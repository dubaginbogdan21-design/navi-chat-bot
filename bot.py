import logging
import os
import asyncio
from collections import defaultdict
import time
from datetime import datetime, timedelta

from openai import AsyncOpenAI
from telegram import Update, ChatMember, ChatPermissions
from telegram.constants import ChatType
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    filters, ContextTypes, ChatMemberHandler
)
from better_profanity import profanity

# Импорт базы данных (файл database.py должен лежать рядом)
from database import Database

# Включаем логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Токены и ключи из переменных окружения
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')   # теперь используется OpenRouter

if not TELEGRAM_TOKEN or not OPENROUTER_API_KEY:
    raise ValueError("Не заданы TELEGRAM_TOKEN или OPENROUTER_API_KEY")

# Инициализация OpenRouter клиента (совместим с OpenAI)
client = AsyncOpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1"
)

# Инициализация базы данных
db = Database()

# Настройка профанного фильтра с русскими словами
profanity.load_censor_words()  # загружает английские по умолчанию
# Добавим русские слова (можно расширить)
russian_bad_words = [ # Нецензурная лексика (мат)
    'сик', 'сикти', 'сиккен', 'сиктир', 'сикип', 'сикишти', 'сиктим', 'сикпей',  # производные от "сик" (половой акт)
    'ам', 'амга', 'амды', 'амың', 'амыңды',  # женский половой орган
    'көт', 'көткө', 'көттү', 'көтүң', 'көтүңө', 'көтүндө',  # задний проход
    'жыныс', 'жыныстык', 'жыныс катыш',  # половой, половой акт (в грубом контексте)
    'ойнош', 'ойношуу', 'ойношкон',  # любовник/любовница, совокупляться (грубо)
    'сак', 'сакчы', 'сак бол',  # может использоваться как ругательство в некоторых регионах
    # Оскорбительные слова
    'ит', 'иттин баласы', 'иттин уулу', 'иттин кызы',  # собака, сын собаки (сильное оскорбление)
    'кош', 'кошун', 'кошпой',  # может использоваться как пренебрежительное
    'жансыз', 'жансыздар',  # бездушный, ничтожество
    'акмак', 'акмактар', 'акмаксың',  # дурак, глупец
    'жалмауз', 'жалмаустар',  # обжора, ненасытный (оскорбительно)
    'сор', 'сорду', 'соруп',  # вор, негодяй (в некоторых диалектах)
    'бака', 'бакалар',  # лягушка (пренебрежительно о человеке)
    'кой', 'койлор',  # овца (тупой, глупый)
    'эшек', 'эшектер',  # осёл (тупой, упрямый)
    'төө', 'төөлөр',  # верблюд (о неуклюжем человеке)
    'чочко', 'чочколор',  # свинья (оскорбление)
    'жалкоо', 'жалкоолор',  # ленивый, лентяй
    'керс', 'керс эт',  # бздун (вульгарно)
    'сидик', 'сидиктен',  # моча (оскорбительно)
    # Политические/националистические оскорбления (опционально)
    'казак', 'казактар',  # может использоваться как уничижительное (в зависимости от контекста)
    'өзбек', 'өзбектер',  # аналогично
    'оруc', 'орустар',  # русский (в негативном контексте)
    # Добавьте свои слова по необходимости
    'хуй', 'хуя', 'хуе', 'хую', 'хуйня', 'хуёвый', 'нахуй', 'похуй', 'охуеть',
    'пизда', 'пизды', 'пизде', 'пизду', 'пиздой', 'пиздец', 'пиздос', 'распиздяй', 'пиздить',
    'блядь', 'бляди', 'блядство', 'блядский', 'бля', 'блять',
    'ебать', 'ебу', 'ебёт', 'ебал', 'ебаный', 'ёбаный', 'заебать', 'наебать', 'выебать',
    'ебануть', 'ёбануть', 'ебанутый', 'ёбанутый', 'разъебай', 'подъеб', 'объебос',
    'мудак', 'мудаки', 'мудацкий', 'мудила', 'мудозвон',
    'гандон', 'гондон',
    'пидор', 'пидорас', 'пидоры', 'пидорасы',
    'шлюха', 'шлюхи', 'шлюхой',
    'проститутка', 'проститутки',
    'долбоеб', 'долбоёб', 'долбоебы', 'долбоёбы',
    'чмо', 'чмошник',
    'ублюдок', 'ублюдки',
    'сука', 'суки', 'сучка', 'сучонок',
    'тварь', 'твари',
    'гад', 'гады',
    'мразь', 'мрази',
    'козёл', 'козлы', 'козлина',
    'петух', 'петухи', 'петушара',
    'залупа', 'залупы', 'залупой',
    'манда', 'манды',
    'срать', 'сру', 'срёт', 'нассал', 'посрать',
    'говно', 'говна', 'говнюк',
    'дерьмо', 'дерьма',
    'фашист', 'фашисты', 'нацист', 'нацисты',  # можно добавить политические оскорбления
]
profanity.add_censor_words(russian_bad_words)

# Хранилище для антиспама (временное, в памяти)
user_last_message = defaultdict(lambda: {"text": "", "time": 0})
warn_count = defaultdict(int)  # chat_id_user_id -> количество предупреждений

# Вспомогательные функции
def is_admin(member):
    return member.status in (ChatMember.ADMINISTRATOR, ChatMember.OWNER)

async def check_bot_rights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет, есть ли у бота права администратора в чате"""
    chat = update.effective_chat
    bot_member = await chat.get_member(context.bot.id)
    return bot_member.status == ChatMember.ADMINISTRATOR and bot_member.can_delete_messages

async def punish_user(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id, reason, settings):
    """Применяет наказание согласно настройкам чата"""
    chat = update.effective_chat
    message = update.effective_message
    action = settings['spam_action']

    try:
        # Сначала удаляем сообщение
        await message.delete()
    except Exception as e:
        logging.error(f"Не удалось удалить сообщение: {e}")

    if action == 'delete':
        # Только удалили
        return

    # Отправляем предупреждение в чат
    warn_text = f"⚠️ {message.from_user.first_name}, ваше сообщение удалено из-за: {reason}."
    if action == 'warn':
        # Увеличиваем счётчик предупреждений для этого пользователя в данном чате
        key = f"{chat.id}_{user_id}"
        warn_count[key] += 1
        warns = warn_count[key]
        limit = settings['warn_limit']
        if warns >= limit:
            # Превышен лимит - мут
            await chat.restrict_member(
                user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=datetime.now() + timedelta(minutes=settings['mute_duration'])
            )
            await context.bot.send_message(
                chat.id,
                f"🔇 Пользователь {message.from_user.first_name} получил мут на {settings['mute_duration']} минут за превышение лимита предупреждений."
            )
            warn_count[key] = 0  # сброс
        else:
            await context.bot.send_message(chat.id, warn_text + f" Предупреждение {warns}/{limit}.")
    elif action == 'mute':
        await chat.restrict_member(
            user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=datetime.now() + timedelta(minutes=settings['mute_duration'])
        )
        await context.bot.send_message(
            chat.id,
            f"🔇 Пользователь {message.from_user.first_name} получил мут на {settings['mute_duration']} минут за {reason}."
        )
    elif action == 'ban':
        await chat.ban_member(user_id)
        await context.bot.send_message(
            chat.id,
            f"⛔ Пользователь {message.from_user.first_name} забанен за {reason}."
        )

# Обработчики команд
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text(
            '👋 Привет! Я Navi Chat — ваш интеллектуальный помощник.\n'
            'Задавайте любые вопросы, а в группах я могу быть администратором и фильтровать спам/мат.'
        )
    else:
        # В группе просто отвечаем
        await update.message.reply_text('Я здесь, чтобы помогать администрировать чат. Используйте /settings для настройки.')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text(
            '🤖 Я использую OpenRouter для ответов (бесплатные модели).\n'
            'Просто напишите мне сообщение.\n\n'
            'Если добавить меня в группу как администратора, я смогу фильтровать мат и спам.\n'
            'В группе используйте /settings для настройки.'
        )
    else:
        await update.message.reply_text(
            'Команды для администраторов группы:\n'
            '/settings — показать текущие настройки\n'
            '/set_filter_profanity on/off — вкл/выкл фильтр мата\n'
            '/set_filter_spam on/off — вкл/выкл фильтр спама\n'
            '/set_spam_action delete/warn/mute/ban — действие при нарушении\n'
            '/set_mute_duration <минуты> — длительность мута\n'
            '/set_warn_limit <число> — лимит предупреждений до мута'
        )

# Настройки (доступны только администраторам группы)
async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type == ChatType.PRIVATE:
        await update.message.reply_text("Эта команда работает только в группах.")
        return

    member = await chat.get_member(user.id)
    if not is_admin(member):
        await update.message.reply_text("❌ Только администраторы могут просматривать настройки.")
        return

    sett = db.get_settings(chat.id)
    text = (
        f"⚙️ **Настройки чата**\n"
        f"Фильтр мата: {'✅' if sett['filter_profanity'] else '❌'}\n"
        f"Фильтр спама: {'✅' if sett['filter_spam'] else '❌'}\n"
        f"Действие при нарушении: {sett['spam_action']}\n"
        f"Длительность мута: {sett['mute_duration']} мин\n"
        f"Лимит предупреждений: {sett['warn_limit']}\n"
        f"Разрешить ссылки (в разработке): {'✅' if sett['whitelist_links'] else '❌'}"
    )
    await update.message.reply_text(text)

async def set_filter_profanity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_bool_setting(update, context, 'filter_profanity')

async def set_filter_spam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_bool_setting(update, context, 'filter_spam')

async def set_bool_setting(update: Update, context: ContextTypes.DEFAULT_TYPE, setting):
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE:
        return
    user = update.effective_user
    member = await chat.get_member(user.id)
    if not is_admin(member):
        await update.message.reply_text("❌ Только администраторы могут менять настройки.")
        return
    if not context.args or context.args[0].lower() not in ['on', 'off']:
        await update.message.reply_text("Использование: /set_filter_profanity on|off")
        return
    value = context.args[0].lower() == 'on'
    db.update_settings(chat.id, **{setting: value})
    await update.message.reply_text(f"✅ Фильтр {'включен' if value else 'выключен'}.")

async def set_spam_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE:
        return
    user = update.effective_user
    member = await chat.get_member(user.id)
    if not is_admin(member):
        await update.message.reply_text("❌ Только администраторы могут менять настройки.")
        return
    if not context.args or context.args[0].lower() not in ['delete', 'warn', 'mute', 'ban']:
        await update.message.reply_text("Использование: /set_spam_action delete|warn|mute|ban")
        return
    action = context.args[0].lower()
    db.update_settings(chat.id, spam_action=action)
    await update.message.reply_text(f"✅ Действие при нарушении: {action}.")

async def set_mute_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_int_setting(update, context, 'mute_duration', min_val=1, max_val=1440)

async def set_warn_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_int_setting(update, context, 'warn_limit', min_val=1, max_val=10)

async def set_int_setting(update: Update, context: ContextTypes.DEFAULT_TYPE, setting, min_val, max_val):
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE:
        return
    user = update.effective_user
    member = await chat.get_member(user.id)
    if not is_admin(member):
        await update.message.reply_text("❌ Только администраторы могут менять настройки.")
        return
    if not context.args:
        await update.message.reply_text(f"Укажите числовое значение от {min_val} до {max_val}.")
        return
    try:
        val = int(context.args[0])
        if val < min_val or val > max_val:
            raise ValueError
    except:
        await update.message.reply_text(f"Неверное значение. Должно быть целое число от {min_val} до {max_val}.")
        return
    db.update_settings(chat.id, **{setting: val})
    await update.message.reply_text(f"✅ {setting} установлено в {val}.")

# Обработчик новых сообщений (групповых и личных)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if not message.text:
        return  # игнорируем не текстовые сообщения
    text = message.text

    # Личные сообщения — отвечаем через OpenRouter
    if chat.type == ChatType.PRIVATE:
        await context.bot.send_chat_action(chat_id=chat.id, action="typing")
        try:
            response = await client.chat.completions.create(
                model="openrouter/free",  # умный роутер
                messages=[
                    {"role": "system", "content": "Ты полезный ассистент по имени Navi Chat. Отвечай дружелюбно и по существу."},
                    {"role": "user", "content": text}
                ],
                temperature=0.7,
                max_tokens=2000,
                timeout=30,
                extra_headers={
                    "HTTP-Referer": "https://github.com/dubaginbogdan21-design/navi-chat-bot",  # ваш репозиторий
                    "X-Title": "Navi Chat Bot"  # название вашего бота
                }
            )
            ai_response = response.choices[0].message.content
            # разбивка длинных сообщений
            if len(ai_response) > 4096:
                for i in range(0, len(ai_response), 4096):
                    await message.reply_text(ai_response[i:i+4096])
            else:
                await message.reply_text(ai_response)
        except Exception as e:
            logging.error(f"OpenRouter API error: {e}")
            await message.reply_text("😔 Ошибка при обращении к AI. Возможно, временные проблемы с сервисом.")
        return

    # Групповые сообщения — применяем фильтры
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    # Проверяем, есть ли у бота права администратора
    if not await check_bot_rights(update, context):
        # Если нет прав, просто игнорируем
        return

    # Получаем настройки чата
    sett = db.get_settings(chat.id)

    # Фильтр мата
    if sett['filter_profanity'] and profanity.contains_profanity(text):
        await punish_user(update, context, user.id, "нецензурная лексика", sett)
        return

    # Фильтр спама (простой)
    if sett['filter_spam']:
        # Проверка на ссылки (если ссылки не разрешены)
        if not sett['whitelist_links'] and ('http://' in text or 'https://' in text or 'www.' in text):
            await punish_user(update, context, user.id, "ссылка в сообщении", sett)
            return

        # Проверка на повтор сообщений
        now = time.time()
        key = f"{chat.id}_{user.id}"
        last = user_last_message[key]
        if last['text'] == text and (now - last['time']) < 30:  # одинаковое сообщение за последние 30 сек
            await punish_user(update, context, user.id, "повтор сообщения (спам)", sett)
            return
        # Обновляем последнее сообщение
        user_last_message[key] = {"text": text, "time": now}

# Обработчик изменения статуса бота (добавление в группу, изменение прав)
async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверяем, касается ли это нашего бота
    if update.my_chat_member:
        new_member = update.my_chat_member.new_chat_member
        if new_member.status == ChatMember.ADMINISTRATOR:
            # Бот стал администратором
            chat = update.effective_chat
            logging.info(f"Бот добавлен как администратор в чат {chat.id}")
            # Отправляем приветственное сообщение
            await context.bot.send_message(
                chat.id,
                "✅ Спасибо, что сделали меня администратором! Теперь я могу фильтровать спам и мат.\n"
                "Используйте /settings для настройки."
            )

# Обработчик ошибок
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Ошибка: {context.error}")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Обработчики команд
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('settings', settings))

    # Команды для групп (доступны админам)
    app.add_handler(CommandHandler('set_filter_profanity', set_filter_profanity))
    app.add_handler(CommandHandler('set_filter_spam', set_filter_spam))
    app.add_handler(CommandHandler('set_spam_action', set_spam_action))
    app.add_handler(CommandHandler('set_mute_duration', set_mute_duration))
    app.add_handler(CommandHandler('set_warn_limit', set_warn_limit))

    # Обработчик текстовых сообщений
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Обработчик обновлений участников (для отслеживания прав бота)
    app.add_handler(ChatMemberHandler(chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))

    # Обработчик ошибок
    app.add_error_handler(error_handler)

    print("Бот Navi Chat (OpenRouter) запущен...")
    app.run_polling()

if __name__ == '__main__':
    main()
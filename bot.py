import logging
import os
import asyncio
from collections import defaultdict
import time
from datetime import datetime, timedelta

from aiohttp import web
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
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')

if not TELEGRAM_TOKEN or not OPENROUTER_API_KEY:
    raise ValueError("Не заданы TELEGRAM_TOKEN или OPENROUTER_API_KEY")

# Инициализация OpenRouter клиента
client = AsyncOpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1"
)

# Инициализация базы данных
db = Database()

# Настройка профанного фильтра с русскими и кыргызскими словами
profanity.load_censor_words()

# Расширенный список русских матов
russian_bad_words = [
    'хуй', 'хуя', 'хуе', 'хую', 'хуйня', 'хуёвый', 'нахуй', 'похуй', 'охуеть',
    'пизда', 'пизды', 'пиздец', 'пиздить', 'пиздюк',
    'блядь', 'бля', 'блять', 'блд',
    'ебать', 'ебу', 'ебал', 'ебаный', 'заебать', 'наебать', 'отъебать',
    'долбоеб', 'мудоёб', 'пиздобол',
    'мудак', 'мудила', 'гандон', 'пидор', 'пидорас', 'шлюха', 'чмо',
    'ублюдок', 'сука', 'тварь', 'гад', 'мразь', 'козёл', 'петух',
    'залупа', 'манда', 'срать', 'говно', 'дерьмо', 'ссать',
]
profanity.add_censor_words(russian_bad_words)

# Расширенный список кыргызских матов
kyrgyz_bad_words = [
    'сик', 'сикти', 'сиккен', 'сиктир', 'сикип',
    'ам', 'амга', 'амды',
    'көт', 'көткө', 'көтүң',
    'ит', 'иттин баласы', 'иттин уулу',
    'акмак', 'жалмауз', 'сорду', 'бака', 'кой', 'эшек', 'төө', 'чочко',
    'жалкоо', 'керс', 'сидик',
]
profanity.add_censor_words(kyrgyz_bad_words)

# Хранилище для антиспама (временное, в памяти)
user_last_message = defaultdict(lambda: {"text": "", "time": 0})
warn_count = defaultdict(int)

# Вспомогательные функции
def is_admin(member):
    return member.status in (ChatMember.ADMINISTRATOR, ChatMember.OWNER)

async def check_bot_rights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    bot_member = await chat.get_member(context.bot.id)
    return bot_member.status == ChatMember.ADMINISTRATOR and bot_member.can_delete_messages

async def punish_user(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id, reason, settings):
    chat = update.effective_chat
    message = update.effective_message
    action = settings['spam_action']

    try:
        await message.delete()
    except Exception as e:
        logging.error(f"Не удалось удалить сообщение: {e}")

    if action == 'delete':
        return

    warn_text = f"⚠️ {message.from_user.first_name}, ваше сообщение удалено из-за: {reason}."
    if action == 'warn':
        key = f"{chat.id}_{user_id}"
        warn_count[key] += 1
        warns = warn_count[key]
        limit = settings['warn_limit']
        if warns >= limit:
            await chat.restrict_member(
                user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=datetime.now() + timedelta(minutes=settings['mute_duration'])
            )
            await context.bot.send_message(
                chat.id,
                f"🔇 Пользователь {message.from_user.first_name} получил мут на {settings['mute_duration']} мин."
            )
            warn_count[key] = 0
        else:
            await context.bot.send_message(chat.id, warn_text + f" Предупреждение {warns}/{limit}.")
    elif action == 'mute':
        await chat.restrict_member(
            user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=datetime.now() + timedelta(minutes=settings['mute_duration'])
        )
        await context.bot.send_message(chat.id, f"🔇 Пользователь {message.from_user.first_name} получил мут.")
    elif action == 'ban':
        await chat.ban_member(user_id)
        await context.bot.send_message(chat.id, f"⛔ Пользователь {message.from_user.first_name} забанен.")

# Обработчики команд
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text(
            '👋 Привет! Я Navi Chat — ваш интеллектуальный помощник.\n'
            'Задавайте любые вопросы, а в группах я могу быть администратором и фильтровать спам/мат.'
        )
    else:
        await update.message.reply_text('Я здесь, чтобы помогать администрировать чат. Используйте /settings.')

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
            'Команды для администраторов:\n'
            '/settings — показать настройки\n'
            '/set_filter_profanity on/off — фильтр мата\n'
            '/set_filter_spam on/off — фильтр спама\n'
            '/set_spam_action delete/warn/mute/ban — действие\n'
            '/set_mute_duration <минуты> — длительность мута\n'
            '/set_warn_limit <число> — лимит предупреждений'
        )

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
        f"Разрешить ссылки: {'✅' if sett['whitelist_links'] else '❌'}"
    )
    await update.message.reply_text(text)

# Другие команды (set_filter_profanity, set_filter_spam и т.д.) остаются без изменений
async def set_filter_profanity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_bool_setting(update, context, 'filter_profanity')
async def set_filter_spam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_bool_setting(update, context, 'filter_spam')
async def set_bool_setting(update: Update, context: ContextTypes.DEFAULT_TYPE, setting):
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE: return
    user = update.effective_user
    member = await chat.get_member(user.id)
    if not is_admin(member):
        await update.message.reply_text("❌ Только администраторы могут менять настройки.")
        return
    if not context.args or context.args[0].lower() not in ['on', 'off']:
        await update.message.reply_text("Использование: on|off")
        return
    value = context.args[0].lower() == 'on'
    db.update_settings(chat.id, **{setting: value})
    await update.message.reply_text(f"✅ Фильтр {'включен' if value else 'выключен'}.")

async def set_spam_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE: return
    user = update.effective_user
    member = await chat.get_member(user.id)
    if not is_admin(member):
        await update.message.reply_text("❌ Только администраторы могут менять настройки.")
        return
    if not context.args or context.args[0].lower() not in ['delete', 'warn', 'mute', 'ban']:
        await update.message.reply_text("Использование: delete|warn|mute|ban")
        return
    action = context.args[0].lower()
    db.update_settings(chat.id, spam_action=action)
    await update.message.reply_text(f"✅ Действие: {action}.")

async def set_mute_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_int_setting(update, context, 'mute_duration', 1, 1440)
async def set_warn_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_int_setting(update, context, 'warn_limit', 1, 10)
async def set_int_setting(update: Update, context: ContextTypes.DEFAULT_TYPE, setting, min_val, max_val):
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE: return
    user = update.effective_user
    member = await chat.get_member(user.id)
    if not is_admin(member):
        await update.message.reply_text("❌ Только администраторы могут менять настройки.")
        return
    if not context.args:
        await update.message.reply_text(f"Укажите число от {min_val} до {max_val}.")
        return
    try:
        val = int(context.args[0])
        if val < min_val or val > max_val: raise ValueError
    except:
        await update.message.reply_text(f"Неверное значение. Должно быть целое число от {min_val} до {max_val}.")
        return
    db.update_settings(chat.id, **{setting: val})
    await update.message.reply_text(f"✅ {setting} = {val}.")

# Обработчик текстовых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if not message.text:
        return
    text = message.text

    if chat.type == ChatType.PRIVATE:
        await context.bot.send_chat_action(chat_id=chat.id, action="typing")
        try:
            response = await client.chat.completions.create(
                model="openrouter/free",
                messages=[
                    {"role": "system", "content": "Ты полезный ассистент по имени Navi Chat."},
                    {"role": "user", "content": text}
                ],
                temperature=0.7,
                max_tokens=2000,
                timeout=30,
                extra_headers={
                    "HTTP-Referer": "https://github.com/dubaginbogdan21-design/navi-chat-bot",
                    "X-Title": "Navi Chat Bot"
                }
            )
            ai_response = response.choices[0].message.content
            if len(ai_response) > 4096:
                for i in range(0, len(ai_response), 4096):
                    await message.reply_text(ai_response[i:i+4096])
            else:
                await message.reply_text(ai_response)
        except Exception as e:
            logging.error(f"OpenRouter API error: {e}")
            await message.reply_text("😔 Ошибка при обращении к AI.")
        return

    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    if not await check_bot_rights(update, context):
        return
    sett = db.get_settings(chat.id)
    if sett['filter_profanity'] and profanity.contains_profanity(text):
        await punish_user(update, context, user.id, "нецензурная лексика", sett)
        return
    if sett['filter_spam']:
        if not sett['whitelist_links'] and ('http://' in text or 'https://' in text or 'www.' in text):
            await punish_user(update, context, user.id, "ссылка", sett)
            return
        now = time.time()
        key = f"{chat.id}_{user.id}"
        last = user_last_message[key]
        if last['text'] == text and (now - last['time']) < 30:
            await punish_user(update, context, user.id, "повтор сообщения (спам)", sett)
            return
        user_last_message[key] = {"text": text, "time": now}

# Обработчик изменения статуса бота
async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.my_chat_member:
        new_member = update.my_chat_member.new_chat_member
        if new_member.status == ChatMember.ADMINISTRATOR:
            chat = update.effective_chat
            logging.info(f"Бот стал администратором в чате {chat.id}")
            await context.bot.send_message(
                chat.id,
                "✅ Спасибо, что сделали меня администратором! Теперь я могу фильтровать спам и мат.\n"
                "Используйте /settings для настройки."
            )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Ошибка: {context.error}")

# Функция для запуска веб-сервера и бота
async def run_bot_and_server():
    # Создаём приложение бота
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('settings', settings))
    application.add_handler(CommandHandler('set_filter_profanity', set_filter_profanity))
    application.add_handler(CommandHandler('set_filter_spam', set_filter_spam))
    application.add_handler(CommandHandler('set_spam_action', set_spam_action))
    application.add_handler(CommandHandler('set_mute_duration', set_mute_duration))
    application.add_handler(CommandHandler('set_warn_limit', set_warn_limit))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(ChatMemberHandler(chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_error_handler(error_handler)

    # Запускаем polling в фоновой задаче
    asyncio.create_task(application.run_polling())

    # Создаём минимальный веб-сервер для health check
    app_web = web.Application()
    async def health_check(request):
        return web.Response(text="OK")
    app_web.router.add_get('/', health_check)
    app_web.router.add_get('/health', health_check)

    port = int(os.getenv('PORT', 10000))
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"Health check server started on port {port}")

    # Бесконечное ожидание, чтобы программа не завершилась
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logging.info("Shutting down...")
        await runner.cleanup()
        await application.stop()

if __name__ == '__main__':
    asyncio.run(run_bot_and_server())
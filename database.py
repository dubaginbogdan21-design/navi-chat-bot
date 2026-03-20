import os
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

class Database:
    def __init__(self):
        # Получаем строку подключения из переменной окружения
        self.db_url = os.getenv('DATABASE_URL')
        if not self.db_url:
            raise ValueError("DATABASE_URL environment variable not set")
        
        # Создаём пул соединений (минимум 1, максимум 10)
        self.pool = psycopg2.pool.ThreadedConnectionPool(
            1, 10, self.db_url, sslmode='require'
        )
        self._init_db()

    def _get_conn(self):
        """Получить соединение из пула"""
        return self.pool.getconn()

    def _put_conn(self, conn):
        """Вернуть соединение в пул"""
        self.pool.putconn(conn)

    def _init_db(self):
        """Создание таблицы, если её нет"""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS chat_settings (
                        chat_id BIGINT PRIMARY KEY,
                        filter_profanity BOOLEAN DEFAULT TRUE,
                        filter_spam BOOLEAN DEFAULT TRUE,
                        spam_action TEXT DEFAULT 'delete',
                        mute_duration INTEGER DEFAULT 5,
                        warn_limit INTEGER DEFAULT 3,
                        whitelist_links BOOLEAN DEFAULT FALSE
                    )
                ''')
                conn.commit()
        finally:
            self._put_conn(conn)

    def get_settings(self, chat_id):
        """Получить настройки чата (создать, если нет)"""
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('SELECT * FROM chat_settings WHERE chat_id = %s', (chat_id,))
                row = cur.fetchone()
                if row:
                    return dict(row)
                else:
                    # Вставляем настройки по умолчанию
                    cur.execute('''
                        INSERT INTO chat_settings (chat_id) VALUES (%s)
                    ''', (chat_id,))
                    conn.commit()
                    # Возвращаем только что созданные настройки
                    cur.execute('SELECT * FROM chat_settings WHERE chat_id = %s', (chat_id,))
                    row = cur.fetchone()
                    return dict(row)
        finally:
            self._put_conn(conn)

    def update_settings(self, chat_id, **kwargs):
        """Обновить указанные поля настроек"""
        conn = self._get_conn()
        try:
            allowed = ['filter_profanity', 'filter_spam', 'spam_action', 
                      'mute_duration', 'warn_limit', 'whitelist_links']
            updates = []
            values = []
            for key, value in kwargs.items():
                if key in allowed:
                    updates.append(f"{key} = %s")
                    values.append(value)
            if not updates:
                return
            values.append(chat_id)
            with conn.cursor() as cur:
                cur.execute(f'UPDATE chat_settings SET {", ".join(updates)} WHERE chat_id = %s', values)
                conn.commit()
        finally:
            self._put_conn(conn)
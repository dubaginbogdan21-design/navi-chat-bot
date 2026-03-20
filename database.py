import sqlite3
import threading

class Database:
    def __init__(self, db_name="bot_settings.db"):
        self.db_name = db_name
        self.local = threading.local()
        self._init_db()

    def _get_conn(self):
        if not hasattr(self.local, 'conn'):
            self.local.conn = sqlite3.connect(self.db_name)
        return self.local.conn

    def _init_db(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id INTEGER PRIMARY KEY,
                filter_profanity BOOLEAN DEFAULT 1,
                filter_spam BOOLEAN DEFAULT 1,
                spam_action TEXT DEFAULT 'delete',  -- delete, warn, mute, ban
                mute_duration INTEGER DEFAULT 5,   -- minutes
                warn_limit INTEGER DEFAULT 3,
                whitelist_links BOOLEAN DEFAULT 0
            )
        ''')
        conn.commit()

    def get_settings(self, chat_id):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM chat_settings WHERE chat_id = ?', (chat_id,))
        row = cursor.fetchone()
        if row:
            return {
                'chat_id': row[0],
                'filter_profanity': bool(row[1]),
                'filter_spam': bool(row[2]),
                'spam_action': row[3],
                'mute_duration': row[4],
                'warn_limit': row[5],
                'whitelist_links': bool(row[6])
            }
        else:
            # создать настройки по умолчанию
            cursor.execute('''
                INSERT INTO chat_settings (chat_id) VALUES (?)
            ''', (chat_id,))
            conn.commit()
            return self.get_settings(chat_id)

    def update_settings(self, chat_id, **kwargs):
        conn = self._get_conn()
        cursor = conn.cursor()
        allowed = ['filter_profanity', 'filter_spam', 'spam_action', 'mute_duration', 'warn_limit', 'whitelist_links']
        updates = []
        values = []
        for key, value in kwargs.items():
            if key in allowed:
                updates.append(f"{key} = ?")
                values.append(value)
        if not updates:
            return
        values.append(chat_id)
        cursor.execute(f'UPDATE chat_settings SET {", ".join(updates)} WHERE chat_id = ?', values)
        conn.commit()
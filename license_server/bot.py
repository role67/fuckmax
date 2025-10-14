import os
import random
import string
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import DictCursor
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN is not set in environment variables")

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in environment variables")
ADMIN_IDS = {634552356, 6602937273}

LICENSE_TYPES = {
    'month': {'days': 30, 'name': 'Месяц'},
    'year': {'days': 365, 'name': 'Год'},
    'lifetime': {'days': None, 'name': 'Пожизненно'}
}

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS licenses (
            id SERIAL PRIMARY KEY,
            key_value TEXT UNIQUE NOT NULL,
            license_type TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

async def admin_only(update: Update) -> bool:
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("Нет доступа.")
        return False
    return True

def generate_key():
    chars = string.ascii_uppercase + string.digits
    return f"{''.join(random.choices(chars, k=2))}-" \
           f"{''.join(random.choices(chars, k=6))}-" \
           f"{''.join(random.choices(chars, k=4))}-" \
           f"{''.join(random.choices(chars, k=4))}"

async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update): return
    args = context.args
    if not args or args[0] not in LICENSE_TYPES:
        await update.message.reply_text("Использование: /generate <month|year|lifetime>")
        return
    license_type = args[0]
    key = generate_key()
    created_at = datetime.now()
    days = LICENSE_TYPES[license_type]['days']
    expires_at = None if days is None else created_at + timedelta(days=days)
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO licenses (key_value, license_type, created_at, expires_at, is_active) VALUES (%s, %s, %s, %s, TRUE)",
                    (key, license_type, created_at, expires_at))
        conn.commit()
    conn.close()
    await update.message.reply_text(f"Ключ: {key}\nТип: {LICENSE_TYPES[license_type]['name']}\nСрок: {expires_at.strftime('%d.%m.%Y %H:%M') if expires_at else 'Бессрочно'}")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update): return
    args = context.args
    if not args:
        await update.message.reply_text("Использование: /ban <key>")
        return
    key = args[0]
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE licenses SET is_active = FALSE WHERE key_value = %s", (key,))
        conn.commit()
    conn.close()
    await update.message.reply_text(f"Ключ {key} заблокирован.")

async def list_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update): return
    conn = get_db_connection()
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT key_value, license_type, expires_at, is_active FROM licenses ORDER BY created_at DESC")
        rows = cur.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Нет ключей.")
        return
    text = '\n'.join([
        f"{row['key_value']}: {LICENSE_TYPES[row['license_type']]['name']}, до {row['expires_at'] if row['expires_at'] else 'Бессрочно'}, {'OK' if row['is_active'] else 'BAN'}" for row in rows
    ])
    await update.message.reply_text(text)

async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update): return
    args = context.args
    if not args:
        await update.message.reply_text("Использование: /verify <key>")
        return
    key = args[0]
    conn = get_db_connection()
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT key_value, license_type, expires_at, is_active FROM licenses WHERE key_value = %s", (key,))
        row = cur.fetchone()
    conn.close()
    if not row:
        await update.message.reply_text("Ключ не найден.")
        return
    status = 'OK' if row['is_active'] else 'BAN'
    await update.message.reply_text(f"Ключ: {row['key_value']}\nТип: {LICENSE_TYPES[row['license_type']]['name']}\nСтатус: {status}\nСрок: {row['expires_at'] if row['expires_at'] else 'Бессрочно'}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user.full_name
    username = user.username
    mention = f"@{username}" if username else name
    if user.id in ADMIN_IDS:
        text = (
            f"Здравствуйте, {mention}!\n\n"
            "🛠️ Вам доступны эти команды:\n"
            "🔑 /generate <lictype> — создать новый лицензионный ключ\n"
            "⛔ /ban <key> — заблокировать ключ\n"
            "📋 /list — показать все ключи\n"
            "🔍 /verify <key> — проверить ключ на валидность"
        )
    else:
        text = (
            f"Здравствуйте, {mention}!\n\n"
            "💸 Наш прайс-лист:\n"
            "• 📅 Месяц — 99р\n"
            "• 🗓️ Год — 349р\n"
            "• ♾️ Пожизненно — 849р\n\n"
            "Для покупки обращаться: @role69, @fuckgrazie\n"
            "Оплата: Cryptobot, TG Stars 💳"
        )
    await update.message.reply_text(text)

async def main():
    try:
        init_db()
        app = Application.builder().token(TELEGRAM_TOKEN).build()
        app.add_handler(CommandHandler('start', start))
        app.add_handler(CommandHandler('generate', generate))
        app.add_handler(CommandHandler('ban', ban))
        app.add_handler(CommandHandler('list', list_keys))
        app.add_handler(CommandHandler('verify', verify))
        
        print("[BOT] Starting Telegram bot...")
        await app.initialize()
        await app.start()
        await app.run_polling(allowed_updates=["message", "callback_query"])
    except Exception as e:
        print(f"[BOT ERROR] {e}")
        raise e

if __name__ == "__main__":
    import asyncio
    import nest_asyncio
    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    loop.run_forever()

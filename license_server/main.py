import os
from flask import Flask, request, jsonify
import telegram
from telegram.ext import Dispatcher, CommandHandler, CallbackContext
from telegram import Update
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime, timedelta
import nest_asyncio

nest_asyncio.apply()

# --- Конфиг ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = set(int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit())
LICENSE_TYPES = {
    'month': {'days': 30, 'name': 'Месяц'},
    'year': {'days': 365, 'name': 'Год'},
    'lifetime': {'days': None, 'name': 'Пожизненно'}
}

bot = telegram.Bot(token=TOKEN)
app = Flask(__name__)

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

def generate_key():
    import random, string
    chars = string.ascii_uppercase + string.digits
    return f"{''.join(random.choices(chars, k=2))}-" \
           f"{''.join(random.choices(chars, k=6))}-" \
           f"{''.join(random.choices(chars, k=4))}-" \
           f"{''.join(random.choices(chars, k=4))}"

# --- Flask endpoints ---
@app.route('/api/validate', methods=['POST'])
def api_validate():
    data = request.get_json() or {}
    key = data.get('key', '').strip().upper()
    if not key:
        return jsonify({'valid': False, 'reason': 'Ключ не передан'}), 400
    conn = get_db_connection()
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT key_value, license_type, expires_at, is_active FROM licenses WHERE key_value = %s", (key,))
        row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({'valid': False, 'reason': 'Ключ не найден'}), 404
    banned = not row['is_active']
    expired = row['expires_at'] and row['expires_at'] < datetime.utcnow()
    valid = row['is_active'] and not expired
    return jsonify({
        'valid': valid,
        'banned': banned,
        'expired': expired,
        'type': row['license_type'],
        'expires_at': row['expires_at'].isoformat() if row['expires_at'] else None,
        'reason': None if valid else ('Ключ заблокирован' if banned else 'Срок действия истек' if expired else 'Ошибка')
    })

@app.route('/generate', methods=['POST'])
def generate():
    data = request.get_json() or {}
    lictype = data.get('type')
    if lictype not in LICENSE_TYPES:
        return jsonify({'error': 'invalid license type'}), 400
    key = generate_key()
    created_at = datetime.utcnow()
    days = LICENSE_TYPES[lictype]['days']
    expires_at = None if days is None else created_at + timedelta(days=days)
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO licenses (key_value, license_type, created_at, expires_at, is_active) VALUES (%s, %s, %s, %s, TRUE)",
                    (key, lictype, created_at, expires_at))
        conn.commit()
    conn.close()
    return jsonify({
        'key': key,
        'type': lictype,
        'expires': expires_at.isoformat() + 'Z' if expires_at else None
    })

@app.route('/verify', methods=['POST'])
def verify():
    data = request.get_json() or {}
    key = data.get('key', '').strip().upper()
    if not key:
        return jsonify({'valid': False, 'reason': 'Ключ не передан'}), 400
    conn = get_db_connection()
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT key_value, license_type, expires_at, is_active FROM licenses WHERE key_value = %s", (key,))
        row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({'valid': False, 'reason': 'Ключ не найден'}), 404
    if not row['is_active']:
        return jsonify({'valid': False, 'reason': 'Ключ заблокирован'}), 403
    if row['expires_at'] and row['expires_at'] < datetime.utcnow():
        return jsonify({'valid': False, 'reason': 'Срок действия истек'}), 403
    days_left = None
    if row['expires_at']:
        days_left = (row['expires_at'] - datetime.utcnow()).days
    return jsonify({'valid': True, 'type': row['license_type'], 'days_left': days_left})

@app.route('/ping', methods=['GET'])
def ping():
    return "pong"

@app.route(f"/{TOKEN}", methods=["POST"])
def telegram_webhook():
    dispatcher = Dispatcher(bot, None, workers=0)
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("generate", tg_generate))
    dispatcher.add_handler(CommandHandler("ban", tg_ban))
    dispatcher.add_handler(CommandHandler("list", tg_list_keys))
    dispatcher.add_handler(CommandHandler("verify", tg_verify))
    dispatcher.process_update(update)
    return "ok"

# --- Telegram bot handlers ---
def admin_only(update: Update):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        update.message.reply_text("Нет доступа.")
        return False
    return True

def start(update: Update, context: CallbackContext):
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
    update.message.reply_text(text)

def tg_generate(update: Update, context: CallbackContext):
    if not admin_only(update): return
    args = context.args
    if not args or args[0] not in LICENSE_TYPES:
        update.message.reply_text("Использование: /generate <month|year|lifetime>")
        return
    license_type = args[0]
    key = generate_key()
    created_at = datetime.utcnow()
    days = LICENSE_TYPES[license_type]['days']
    expires_at = None if days is None else created_at + timedelta(days=days)
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO licenses (key_value, license_type, created_at, expires_at, is_active) VALUES (%s, %s, %s, %s, TRUE)",
                    (key, license_type, created_at, expires_at))
        conn.commit()
    conn.close()
    update.message.reply_text(f"Ключ: {key}\nТип: {LICENSE_TYPES[license_type]['name']}\nСрок: {expires_at.strftime('%d.%m.%Y %H:%M') if expires_at else 'Бессрочно'}")

def tg_ban(update: Update, context: CallbackContext):
    if not admin_only(update): return
    args = context.args
    if not args:
        update.message.reply_text("Использование: /ban <key>")
        return
    key = args[0]
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE licenses SET is_active = FALSE WHERE key_value = %s", (key,))
        conn.commit()
    conn.close()
    update.message.reply_text(f"Ключ {key} заблокирован.")

def tg_list_keys(update: Update, context: CallbackContext):
    if not admin_only(update): return
    conn = get_db_connection()
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT key_value, license_type, expires_at, is_active FROM licenses ORDER BY created_at DESC")
        rows = cur.fetchall()
    conn.close()
    if not rows:
        update.message.reply_text("Нет ключей.")
        return
    text = '\n'.join([
        f"{row['key_value']}: {LICENSE_TYPES[row['license_type']]['name']}, до {row['expires_at'] if row['expires_at'] else 'Бессрочно'}, {'OK' if row['is_active'] else 'BAN'}" for row in rows
    ])
    update.message.reply_text(text)

def tg_verify(update: Update, context: CallbackContext):
    if not admin_only(update): return
    args = context.args
    if not args:
        update.message.reply_text("Использование: /verify <key>")
        return
    key = args[0]
    conn = get_db_connection()
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT key_value, license_type, expires_at, is_active FROM licenses WHERE key_value = %s", (key,))
        row = cur.fetchone()
    conn.close()
    if not row:
        update.message.reply_text("Ключ не найден.")
        return
    status = 'OK' if row['is_active'] else 'BAN'
    update.message.reply_text(f"Ключ: {row['key_value']}\nТип: {LICENSE_TYPES[row['license_type']]['name']}\nСтатус: {status}\nСрок: {row['expires_at'] if row['expires_at'] else 'Бессрочно'}")

@app.route('/')
def index():
    return 'License Server & Telegram Bot is running.'

if __name__ == "__main__":
    init_db()
    # Установить webhook (один раз вручную или через код)
    WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"
    bot.set_webhook(url=WEBHOOK_URL)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

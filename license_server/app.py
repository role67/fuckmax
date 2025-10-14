import os
import psycopg2
from psycopg2.extras import DictCursor
from flask import Flask, request, jsonify
from datetime import datetime, timedelta

app = Flask(__name__)

@app.route('/api/validate', methods=['POST'])
def api_validate():
    data = request.get_json() or {}
    key = data.get('key', '').strip().upper()
    if not key:
        return jsonify({
            'valid': False,
            'banned': False,
            'expired': False,
            'type': None,
            'expires_at': None,
            'reason': 'Ключ не передан'
        }), 400
    conn = get_db_connection()
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT key_value, license_type, expires_at, is_active FROM licenses WHERE key_value = %s", (key,))
        row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({
            'valid': False,
            'banned': False,
            'expired': False,
            'type': None,
            'expires_at': None,
            'reason': 'Ключ не найден'
        }), 404
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

@app.route('/push_token', methods=['POST'])
def push_token():
    data = request.get_json() or {}
    device_id = data.get('device_id')
    token = data.get('token')
    if not device_id or not token:
        return jsonify({'ok': False, 'error': 'device_id and token required'}), 400
    conn = get_db_connection()
    with conn.cursor() as cur:
        # Создать таблицу, если не существует (один раз)
        cur.execute('''
            CREATE TABLE IF NOT EXISTS push_tokens (
                id SERIAL PRIMARY KEY,
                device_id TEXT NOT NULL,
                token TEXT NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE(device_id)
            )
        ''')
        # upsert (insert or update)
        cur.execute('''
            INSERT INTO push_tokens (device_id, token, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (device_id) DO UPDATE SET token = EXCLUDED.token, updated_at = NOW()
        ''', (device_id, token))
        conn.commit()
    conn.close()
    print(f"[PUSH_TOKEN] {device_id} -> {token}")
# app = Flask(__name__)  # Already initialized above

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in environment variables")

LICENSE_TYPES = {
    'month': {'days': 30, 'name': 'Месяц'},
    'year': {'days': 365, 'name': 'Год'},
    'lifetime': {'days': None, 'name': 'Пожизненно'}
}

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def generate_license_key():
    import random, string
    chars = string.ascii_uppercase + string.digits
    return f"{''.join(random.choices(chars, k=2))}-" \
           f"{''.join(random.choices(chars, k=6))}-" \
           f"{''.join(random.choices(chars, k=4))}-" \
           f"{''.join(random.choices(chars, k=4))}"

@app.route('/generate', methods=['POST'])
def generate():
    data = request.get_json() or {}
    lictype = data.get('type')
    if lictype not in LICENSE_TYPES:
        return jsonify({'error': 'invalid license type'}), 400
    key = generate_license_key()
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

@app.route('/')
def index():
    return 'License Server is running.'

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)

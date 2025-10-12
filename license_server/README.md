# Production-ready Python license server for Android app

Build Command:
```
pip install -r requirements.txt
```

Start Command:
```
gunicorn app:app
```

POST /check_key
Body: {"key": "abcd1234efgh5678"}

Ключ должен быть 16 символов, только 0-9, a-z.

---

Android-проект и сервер полностью разделены. Сервер деплоится отдельно (например, Render.com), а Android-приложение обращается к нему по HTTP.

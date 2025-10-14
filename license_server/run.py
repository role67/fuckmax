import os
import subprocess
import sys
import signal
import time

def run_services():
    # Запускаем Flask через gunicorn
    web_process = subprocess.Popen(['gunicorn', 'app:app'])
    
    # Даем веб-серверу время на запуск
    time.sleep(2)
    
    # Запускаем телеграм бота
    bot_process = subprocess.Popen([sys.executable, 'bot.py'])
    
    def signal_handler(signum, frame):
        print("Received shutdown signal, stopping processes...")
        web_process.terminate()
        bot_process.terminate()
        web_process.wait()
        bot_process.wait()
        sys.exit(0)
    
    # Регистрируем обработчик сигналов
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        # Ждем завершения процессов
        web_process.wait()
        bot_process.wait()
    except KeyboardInterrupt:
        print("Stopping services...")
        web_process.terminate()
        bot_process.terminate()
        web_process.wait()
        bot_process.wait()

if __name__ == "__main__":
    run_services()
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import random
import os
import time

# Данные из переменных окружения Render
TOKEN = os.getenv("VK_TOKEN")
GROUP_ID = int(os.getenv("VK_GROUP_ID"))

print("=" * 50)
print("🚀 ЗАПУСК БОТА")
print(f"Токен: {TOKEN[:20]}...")
print(f"ID группы: {GROUP_ID}")
print("=" * 50)

# Подключаемся к VK
vk_session = vk_api.VkApi(token=TOKEN)
vk = vk_session.get_api()

# Проверяем, работает ли токен
try:
    vk.groups.getById(group_id=GROUP_ID)
    print("✅ Токен РАБОТАЕТ!")
except Exception as e:
    print(f"❌ Токен НЕ РАБОТАЕТ! Ошибка: {e}")
    exit(1)

# Подключаем LongPoll
longpoll = VkBotLongPoll(vk_session, GROUP_ID)
print("✅ LongPoll подключен!")

print("🤖 Бот запущен и ждет сообщения...")

# Простой веб-сервер для Render
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Bot is running')

def run_web():
    port = int(os.environ.get('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), Handler)
    server.serve_forever()

threading.Thread(target=run_web, daemon=True).start()

# ========== ОСНОВНОЙ ЦИКЛ ==========
while True:
    try:
        for event in longpoll.listen():
            print(f"🔔 Получено событие: {event.type}")
            
            if event.type == VkBotEventType.MESSAGE_NEW:
                print("📩 Это сообщение!")
                
                # Для личных сообщений
                if event.from_user:
                    user_id = event.object.message['from_id']
                    print(f"Личка от {user_id}")
                    try:
                        vk.messages.send(
                            user_id=user_id,
                            message="Я работаю только в беседах!",
                            random_id=random.randint(1, 999999)
                        )
                        print("✅ Ответил в личку")
                    except Exception as e:
                        print(f"❌ Ошибка: {e}")
                
                # Для бесед
                if event.from_chat:
                    peer_id = event.object.message['peer_id']
                    text = event.object.message['text']
                    from_id = event.object.message['from_id']
                    print(f"Беседа {peer_id}, от {from_id}: {text}")
                    
                    try:
                        vk.messages.send(
                            peer_id=peer_id,
                            message=f"✅ Бот работает! Получено: {text}",
                            random_id=random.randint(1, 999999)
                        )
                        print("✅ Ответил в беседу!")
                    except Exception as e:
                        print(f"❌ Ошибка отправки: {e}")
                        
    except Exception as e:
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        print("🔄 Переподключение через 5 секунд...")
        time.sleep(5)

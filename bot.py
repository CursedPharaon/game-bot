import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import random
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================= КОНФИГУРАЦИЯ =================
GROUP_TOKEN = os.getenv("VK_TOKEN")
GROUP_ID = int(os.getenv("VK_GROUP_ID"))
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID"))

print(f"Токен: {GROUP_TOKEN[:20]}...")
print(f"ID группы: {GROUP_ID}")
print(f"Владелец: {BOT_OWNER_ID}")
# ===============================================

# Инициализация
vk_session = vk_api.VkApi(token=GROUP_TOKEN)
vk = vk_session.get_api()
longpoll = VkBotLongPoll(vk_session, GROUP_ID)

def send(peer_id, text):
    try:
        vk.messages.send(
            peer_id=peer_id,
            message=text,
            random_id=random.randint(1, 2**31)
        )
        print(f"✅ Отправлено: {text[:50]}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

# Веб-сервер для Render
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Bot is running')

def run_web():
    port = int(os.environ.get('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    server.serve_forever()

threading.Thread(target=run_web, daemon=True).start()

# ================= ОСНОВНОЙ ЦИКЛ =================
print("=" * 50)
print("🤖 БОТ ЗАПУЩЕН!")
print("Жду сообщений...")
print("=" * 50)

while True:
    try:
        for event in longpoll.listen():
            if event.type == VkBotEventType.MESSAGE_NEW:
                
                # Личные сообщения
                if event.from_user:
                    user_id = event.object.message['from_id']
                    send(user_id, "🤖 Я работаю только в беседах! Добавь меня в чат.")
                    continue
                
                # Сообщения из бесед
                if event.from_chat:
                    peer_id = event.object.message['peer_id']
                    text = event.object.message['text'].strip()
                    from_id = event.object.message['from_id']
                    
                    print(f"📩 {from_id}: {text}")
                    
                    # ОТВЕЧАЕМ НА ЛЮБОЕ СООБЩЕНИЕ
                    send(peer_id, f"✅ Бот работает! Твое сообщение: {text}")
                    
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        print("🔄 Переподключение через 5 секунд...")
        time.sleep(5)

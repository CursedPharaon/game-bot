import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import random
import time
import re
import json
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from collections import defaultdict

# ================= КОНФИГУРАЦИЯ =================
GROUP_TOKEN = os.getenv("VK_TOKEN")
GROUP_ID = int(os.getenv("VK_GROUP_ID"))
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID"))

if not GROUP_TOKEN or not GROUP_ID or not BOT_OWNER_ID:
    print("❌ ОШИБКА: Не все переменные окружения заданы!")
    exit(1)
# ===============================================

# Функция создания сессии
def create_session():
    session = vk_api.VkApi(token=GROUP_TOKEN)
    api = session.get_api()
    longpoll = VkBotLongPoll(session, GROUP_ID)
    return session, api, longpoll

# База данных
DATA_FILE = "bot_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"chats": {}}

def save_data():
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

data = load_data()

# Словарь ролей
ROLES = {
    0: "👤 Пользователь",
    10: "🛡️ Помощник",
    20: "🔧 Модератор",
    30: "⚡ Администратор",
    50: "👑 Главный админ",
    80: "⭐ Руководитель",
    100: "💎 Владелец"
}

# Защита от дублирования
processed = {}
PROCESS_TIMEOUT = 10

def is_processed(msg_id):
    now = time.time()
    if msg_id in processed and now - processed[msg_id] < PROCESS_TIMEOUT:
        return True
    processed[msg_id] = now
    return False

def get_chat(peer_id):
    pid = str(peer_id)
    if pid not in data["chats"]:
        data["chats"][pid] = {
            "users": {},
            "silence_mode": False,
            "muted_users": {},
            "rules": "📜 Правила пока не установлены"
        }
        save_data()
    return data["chats"][pid]

def send(peer_id, text, reply=None):
    try:
        vk.messages.send(
            peer_id=peer_id,
            message=text,
            random_id=random.randint(1, 2**31),
            reply_to=reply
        )
        return True
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")
        return False

def kick_user(chat_id, user_id):
    try:
        vk.messages.removeChatUser(chat_id=chat_id, user_id=user_id)
        return True
    except:
        return False

def is_chat_owner(peer_id, user_id):
    try:
        members = vk.messages.getConversationMembers(peer_id=peer_id)
        for m in members['items']:
            if m['member_id'] == user_id:
                return m.get('is_owner', False)
    except:
        pass
    return False

def is_chat_admin(peer_id, user_id):
    try:
        members = vk.messages.getConversationMembers(peer_id=peer_id)
        for m in members['items']:
            if m['member_id'] == user_id:
                return m.get('is_admin', False) or m.get('is_owner', False)
    except:
        pass
    return False

def get_role(peer_id, user_id):
    if user_id == BOT_OWNER_ID:
        return 100
    if is_chat_owner(peer_id, user_id):
        return 100
    chat = get_chat(peer_id)
    if str(user_id) in chat["users"]:
        return chat["users"][str(user_id)].get("role", 0)
    if is_chat_admin(peer_id, user_id):
        return 50
    return 0

def role_name(role):
    return ROLES.get(role, "👤 Пользователь")

def can_assign(giver, target):
    if target >= giver:
        return False
    if target == 100:
        return False
    if giver < 30:
        return False
    return True

def is_muted(peer_id, user_id):
    chat = get_chat(peer_id)
    key = str(user_id)
    if key in chat["muted_users"]:
        if chat["muted_users"][key] > time.time():
            return True
        else:
            del chat["muted_users"][key]
            save_data()
    return False

def mute_user(peer_id, user_id, minutes):
    chat = get_chat(peer_id)
    chat["muted_users"][str(user_id)] = time.time() + (minutes * 60)
    save_data()

def unmute_user(peer_id, user_id):
    chat = get_chat(peer_id)
    key = str(user_id)
    if key in chat["muted_users"]:
        del chat["muted_users"][key]
        save_data()

def get_target(text, event):
    if event.object.message.get('reply_message'):
        return event.object.message['reply_message']['from_id']
    match = re.search(r'\[id(\d+)\|', text)
    if match:
        return int(match.group(1))
    return None

def get_username(uid):
    try:
        u = vk.users.get(user_ids=uid, fields='screen_name')
        if u and u[0].get('screen_name'):
            return u[0]['screen_name']
    except:
        pass
    return None

def get_link(uid):
    name = get_username(uid)
    if name:
        return f"@{name}"
    return f"[id{uid}|юзер]"

# ========== ИСПРАВЛЕННАЯ ФУНКЦИЯ РАССЫЛКИ ==========
def broadcast_all(text, sender):
    sender_link = get_link(sender)
    msg = f"📢 **РАССЫЛКА ОТ ВЛАДЕЛЬЦА**\n\nОт: {sender_link}\n\n{text}"
    sent = 0
    failed = 0
    
    try:
        # Получаем ВСЕ беседы, где есть бот
        conversations = vk.messages.getConversations(count=200, filter='all')
        
        print(f"📋 Получено {len(conversations.get('items', []))} диалогов")
        
        for item in conversations.get('items', []):
            peer_id = item['conversation']['peer']['id']
            
            # Проверяем, что это беседа (peer_id > 2000000000)
            if peer_id > 2000000000:
                try:
                    vk.messages.send(
                        peer_id=peer_id,
                        message=msg,
                        random_id=random.randint(1, 2**31)
                    )
                    sent += 1
                    print(f"✅ Отправлено в беседу {peer_id}")
                    time.sleep(0.3)
                except Exception as e:
                    failed += 1
                    print(f"❌ Ошибка отправки в {peer_id}: {e}")
        
        print(f"📊 Рассылка завершена: отправлено {sent}, ошибок {failed}")
        
    except Exception as e:
        print(f"❌ Ошибка получения списка бесед: {e}")
    
    return sent, failed

# ================= ВЕБ-СЕРВЕР =================
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
print("✅ Adrenaline Manager ЗАПУЩЕН!")
print(f"👑 Владелец бота: {BOT_OWNER_ID}")
print("📌 Команды пишите через !")
print("=" * 50)

while True:
    try:
        # Создаем сессию
        vk_session, vk, longpoll = create_session()
        print("✅ Сессия создана, жду сообщения...")
        
        for event in longpoll.listen():
            if event.type != VkBotEventType.MESSAGE_NEW:
                continue
            
            msg_id = event.object.message['id']
            if is_processed(msg_id):
                continue
            
            # Личные сообщения
            if event.from_user:
                try:
                    vk.messages.send(
                        user_id=event.object.message['from_id'],
                        message="🤖 Я работаю только в беседах!",
                        random_id=random.randint(1, 2**31)
                    )
                except:
                    pass
                continue
            
            if not event.from_chat:
                continue
            
            peer = event.object.message['peer_id']
            text = event.object.message['text'].strip()
            from_id = event.object.message['from_id']
            chat_id = peer - 2000000000
            
            # ТОЛЬКО КОМАНДЫ С !
            if not text.startswith('!'):
                continue
            
            command_text = text[1:].strip().lower()
            if not command_text:
                continue
            
            command_parts = command_text.split()
            command = command_parts[0]
            args = text[1:].strip()
            
            print(f"📩 [{chat_id}] {from_id}: {text}")
            
            # Проверка мута
            if is_muted(peer, from_id):
                kick_user(chat_id, from_id)
                continue
            
            # Проверка тишины
            chat = get_chat(peer)
            if chat["silence_mode"]:
                if get_role(peer, from_id) < 30:
                    kick_user(chat_id, from_id)
                    continue
            
            role = get_role(peer, from_id)
            
            # ========== КОМАНДЫ ==========
            
            # !помощь
            if command == "помощь":
                help_text = f"""🤖 **Adrenaline Manager**

🔹 **Все могут:**
!помощь - Это меню
!профиль - Ваш профиль
!роли - Список ролей
!стафф - Сотрудники
!правила - Правила беседы

🔹 **Роли 30+ (Администраторы):**
!выдатьроль @user [число]
!снятьроль @user
!мут @user [минуты]
!снятьмут @user
!кик @user
!варн @user
!тишина

🔹 **Владелец беседы (роль 100):**
!+правила текст
!ник @user текст
!удалитьник @user
!списокников

🔹 **Владелец бота:**
!рассылка текст"""
                send(peer, help_text, msg_id)
                continue
            
            # !роли
            if command == "роли":
                txt = "📋 **Список ролей:**\n\n"
                for rn, rname in ROLES.items():
                    txt += f"{rname} — {rn}\n"
                send(peer, txt, msg_id)
                continue
            
            # !правила
            if command == "правила":
                send(peer, chat["rules"], msg_id)
                continue
            
            # !+правила
            if command == "+правила" and role >= 100:
                new_rules = args[8:].strip()
                if not new_rules:
                    send(peer, "❌ Использование: !+правила Текст правил", msg_id)
                else:
                    chat["rules"] = f"📜 **ПРАВИЛА БЕСЕДЫ**\n\n{new_rules}"
                    save_data()
                    send(peer, f"✅ Правила установлены!", msg_id)
                continue
            
            # !рассылка (только владелец бота)
            if command == "рассылка" and from_id == BOT_OWNER_ID:
                broadcast_text = args[8:].strip()
                if not broadcast_text:
                    send(peer, "❌ Использование: !рассылка Текст", msg_id)
                else:
                    send(peer, "⏳ Начинаю рассылку...", msg_id)
                    sent, failed = broadcast_all(broadcast_text, from_id)
                    send(peer, f"✅ **Рассылка завершена!**\n\n📨 Отправлено в {sent} чатов\n❌ Ошибок: {failed}", msg_id)
                continue
            
            # !профиль
            if command == "профиль":
                if str(from_id) not in chat["users"]:
                    chat["users"][str(from_id)] = {"role": 0, "warns": 0}
                    save_data()
                rnum = get_role(peer, from_id)
                rname = role_name(rnum)
                warns = chat["users"][str(from_id)].get("warns", 0)
                muted = "Да" if is_muted(peer, from_id) else "Нет"
                nick = chat["users"][str(from_id)].get("nickname", "")
                nicktxt = f"\n🏷️ Ник: {nick}" if nick else ""
                send(peer, f"📊 **Ваш профиль**\n⭐ Роль: {rname} ({rnum})\n⚠️ Варны: {warns}/3\n🔇 Мут: {muted}{nicktxt}", msg_id)
                continue
            
            # !стафф
            if command == "стафф" and role >= 30:
                staff = []
                for uid, udata in chat["users"].items():
                    if udata.get("role", 0) > 0:
                        staff.append(f"• {get_link(int(uid))} — {role_name(udata['role'])}")
                if is_chat_owner(peer, from_id):
                    staff.insert(0, f"• {get_link(from_id)} — {role_name(100)} (Владелец)")
                if staff:
                    send(peer, "📋 **Стафф беседы:**\n\n" + "\n".join(staff), msg_id)
                else:
                    send(peer, "📋 Нет сотрудников с ролями", msg_id)
                continue
            
            # !выдатьроль
            if command == "выдатьроль" and role >= 30:
                target = get_target(text, event)
                if not target:
                    send(peer, "❌ Укажите пользователя (@ или ответом)", msg_id)
                else:
                    parts = args.split()
                    if len(parts) < 2:
                        send(peer, "❌ Использование: !выдатьроль @user число", msg_id)
                    else:
                        try:
                            newr = int(parts[-1])
                            if newr not in ROLES:
                                send(peer, f"❌ Роль {newr} не существует", msg_id)
                            elif not can_assign(role, newr):
                                send(peer, f"❌ Нельзя выдать роль {newr}", msg_id)
                            else:
                                if str(target) not in chat["users"]:
                                    chat["users"][str(target)] = {"role": 0, "warns": 0}
                                chat["users"][str(target)]["role"] = newr
                                save_data()
                                send(peer, f"✅ {get_link(target)} получил роль: {role_name(newr)}", msg_id)
                        except:
                            send(peer, "❌ Укажите число", msg_id)
                continue
            
            # !снятьроль
            if command == "снятьроль" and role >= 30:
                target = get_target(text, event)
                if not target:
                    send(peer, "❌ Укажите пользователя", msg_id)
                else:
                    if str(target) in chat["users"]:
                        chat["users"][str(target)]["role"] = 0
                        save_data()
                        send(peer, f"✅ Роль {get_link(target)} сброшена", msg_id)
                    else:
                        send(peer, "❌ У пользователя нет роли", msg_id)
                continue
            
            # !ник
            if command == "ник" and role >= 100:
                target = get_target(text, event)
                if not target:
                    send(peer, "❌ Укажите пользователя (@)", msg_id)
                else:
                    parts = args.split(maxsplit=2)
                    if len(parts) < 3:
                        send(peer, "❌ Использование: !ник @user Никнейм", msg_id)
                    else:
                        new_nick = parts[2][:30]
                        if str(target) not in chat["users"]:
                            chat["users"][str(target)] = {"role": 0, "warns": 0}
                        chat["users"][str(target)]["nickname"] = new_nick
                        save_data()
                        send(peer, f"✅ {get_link(target)} → ник: {new_nick}", msg_id)
                continue
            
            # !удалитьник
            if command == "удалитьник" and role >= 100:
                target = get_target(text, event)
                if not target:
                    send(peer, "❌ Укажите пользователя", msg_id)
                else:
                    if str(target) in chat["users"] and "nickname" in chat["users"][str(target)]:
                        del chat["users"][str(target)]["nickname"]
                        save_data()
                        send(peer, f"✅ Ник {get_link(target)} удален", msg_id)
                    else:
                        send(peer, "❌ Нет ника", msg_id)
                continue
            
            # !списокников
            if command == "списокников" and role >= 100:
                nicks = []
                for uid, udata in chat["users"].items():
                    if udata.get("nickname"):
                        nicks.append(f"• {get_link(int(uid))} → {udata['nickname']}")
                if nicks:
                    send(peer, "📝 **Список ников:**\n\n" + "\n".join(nicks), msg_id)
                else:
                    send(peer, "📝 Ников нет", msg_id)
                continue
            
            # !варн
            if command == "варн" and role >= 30:
                target = get_target(text, event)
                if not target:
                    send(peer, "❌ Укажите пользователя", msg_id)
                else:
                    if str(target) not in chat["users"]:
                        chat["users"][str(target)] = {"role": 0, "warns": 0}
                    chat["users"][str(target)]["warns"] = chat["users"][str(target)].get("warns", 0) + 1
                    warns = chat["users"][str(target)]["warns"]
                    if warns >= 3:
                        if kick_user(chat_id, target):
                            send(peer, f"⚠️ {get_link(target)} кикнут за 3 варна!", msg_id)
                            if str(target) in chat["users"]:
                                del chat["users"][str(target)]
                        else:
                            send(peer, "❌ Ошибка кика", msg_id)
                    else:
                        send(peer, f"⚠️ {get_link(target)} варн {warns}/3", msg_id)
                    save_data()
                continue
            
            # !мут
            if command == "мут" and role >= 30:
                target = get_target(text, event)
                if not target:
                    send(peer, "❌ Укажите пользователя", msg_id)
                else:
                    minutes = 5
                    nums = re.findall(r'\d+', text)
                    if nums:
                        minutes = int(nums[0])
                    if minutes <= 0:
                        minutes = 1
                    if minutes > 10080:
                        minutes = 10080
                    mute_user(peer, target, minutes)
                    send(peer, f"🔇 {get_link(target)} замьючен на {minutes} мин!", msg_id)
                continue
            
            # !снятьмут
            if command == "снятьмут" and role >= 30:
                target = get_target(text, event)
                if not target:
                    send(peer, "❌ Укажите пользователя", msg_id)
                else:
                    unmute_user(peer, target)
                    send(peer, f"✅ {get_link(target)} размьючен", msg_id)
                continue
            
            # !кик
            if command == "кик" and role >= 30:
                target = get_target(text, event)
                if not target:
                    send(peer, "❌ Укажите пользователя", msg_id)
                else:
                    if kick_user(chat_id, target):
                        send(peer, f"🚪 {get_link(target)} кикнут!", msg_id)
                    else:
                        send(peer, "❌ Ошибка. Бот админ?", msg_id)
                continue
            
            # !тишина
            if command == "тишина" and role >= 30:
                chat["silence_mode"] = not chat["silence_mode"]
                save_data()
                if chat["silence_mode"]:
                    send(peer, "🔇 **ТИШИНА ВКЛЮЧЕНА!**\nНе-админы будут кикаться.", msg_id)
                else:
                    send(peer, "🔈 **Тишина выключена**", msg_id)
                continue
                
    except Exception as e:
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        print("🔄 Переподключение через 10 секунд...")
        time.sleep(10)
        continue

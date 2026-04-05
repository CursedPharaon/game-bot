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

vk_session = vk_api.VkApi(token=GROUP_TOKEN)
vk = vk_session.get_api()
longpoll = VkBotLongPoll(vk_session, GROUP_ID)

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
processed_messages = {}
PROCESS_TIMEOUT = 10

def is_processed(msg_id):
    current = time.time()
    if msg_id in processed_messages:
        if current - processed_messages[msg_id] < PROCESS_TIMEOUT:
            return True
    processed_messages[msg_id] = current
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
        print(f"✅ Отправлено")
        return True
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False

def kick(chat_id, user_id):
    try:
        vk.messages.removeChatUser(chat_id=chat_id, user_id=user_id)
        return True
    except:
        return False

def is_admin(peer_id, user_id):
    try:
        members = vk.messages.getConversationMembers(peer_id=peer_id)
        for m in members['items']:
            if m['member_id'] == user_id:
                return m.get('is_admin', False) or m.get('is_owner', False)
    except:
        pass
    return False

def is_owner(peer_id, user_id):
    try:
        members = vk.messages.getConversationMembers(peer_id=peer_id)
        for m in members['items']:
            if m['member_id'] == user_id:
                return m.get('is_owner', False)
    except:
        pass
    return False

def get_role(peer_id, user_id):
    if user_id == BOT_OWNER_ID:
        return 100
    if is_owner(peer_id, user_id):
        return 100
    chat = get_chat(peer_id)
    if str(user_id) in chat["users"]:
        return chat["users"][str(user_id)].get("role", 0)
    if is_admin(peer_id, user_id):
        return 50
    return 0

def role_name(role):
    return ROLES.get(role, "👤 Пользователь")

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

def mute(peer_id, user_id, minutes):
    chat = get_chat(peer_id)
    chat["muted_users"][str(user_id)] = time.time() + (minutes * 60)
    save_data()

def unmute(peer_id, user_id):
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

def broadcast_all(text, sender):
    sender_link = get_link(sender)
    msg = f"📢 **РАССЫЛКА**\n\nОт: {sender_link}\n\n{text}"
    sent = 0
    try:
        convs = vk.messages.getConversations(count=200)
        for c in convs.get('items', []):
            pid = c['conversation']['peer']['id']
            if pid > 2000000000:
                if send(pid, msg):
                    sent += 1
                time.sleep(0.3)
    except Exception as e:
        print(f"Ошибка рассылки: {e}")
    return sent

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
print(f"👑 Владелец: {BOT_OWNER_ID}")
print("=" * 50)

while True:
    try:
        for event in longpoll.listen():
            if event.type != VkBotEventType.MESSAGE_NEW:
                continue
            
            msg_id = event.object.message['id']
            if is_processed(msg_id):
                continue
            
            # Личка
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
            low = text.lower()
            from_id = event.object.message['from_id']
            chat_id = peer - 2000000000
            
            print(f"📩 {from_id}: {text[:30]}")
            
            # Проверка мута
            if is_muted(peer, from_id):
                kick(chat_id, from_id)
                continue
            
            # Проверка тишины
            chat = get_chat(peer)
            if chat["silence_mode"]:
                if get_role(peer, from_id) < 30:
                    kick(chat_id, from_id)
                    continue
            
            # Проверка команды
            if not text:
                continue
            prefix = text[0]
            if prefix not in ['!', '.', '/']:
                continue
            
            cmd = low[1:].split()[0] if len(low[1:].split()) > 0 else ""
            args = text[1:].strip()
            
            role = get_role(peer, from_id)
            
            print(f"⚡ Команда: {cmd}, роль: {role}")
            
            # ========== КОМАНДЫ ==========
            
            # !помощь
            if cmd == "помощь":
                send(peer, f"""🤖 **Adrenaline Manager**

🔹 **Все:**
{prefix}помощь - Это меню
{prefix}профиль - Ваш профиль
{prefix}роли - Список ролей
{prefix}стафф - Сотрудники
{prefix}правила - Правила беседы

🔹 **Роли 30+:**
{prefix}выдатьроль @user [число]
{prefix}снятьроль @user
{prefix}мут @user [мин]
{prefix}снятьмут @user
{prefix}кик @user
{prefix}варн @user
{prefix}тишина

🔹 **Владелец беседы:**
{prefix}+правила текст
{prefix}ник @user текст
{prefix}удалитьник @user
{prefix}списокников

🔹 **Владелец бота:**
{prefix}рассылка текст""", msg_id)
                continue
            
            # !роли
            if cmd == "роли":
                txt = "📋 **Роли:**\n\n"
                for rn, rname in ROLES.items():
                    txt += f"{rname} — {rn}\n"
                send(peer, txt, msg_id)
                continue
            
            # !правила
            if cmd == "правила":
                send(peer, chat["rules"], msg_id)
                continue
            
            # !+правила (только владелец беседы)
            if cmd == "+правила" and role >= 100:
                new_rules = args[8:].strip()
                if not new_rules:
                    send(peer, f"❌ {prefix}+правила Текст правил", msg_id)
                else:
                    chat["rules"] = f"📜 **ПРАВИЛА БЕСЕДЫ**\n\n{new_rules}"
                    save_data()
                    send(peer, f"✅ Правила установлены!\n\n{chat['rules']}", msg_id)
                continue
            
            # !рассылка (только владелец бота)
            if cmd == "рассылка" and from_id == BOT_OWNER_ID:
                broadcast_text = args[8:].strip()
                if not broadcast_text:
                    send(peer, f"❌ {prefix}рассылка Текст", msg_id)
                else:
                    send(peer, "⏳ Рассылаю...", msg_id)
                    sent = broadcast_all(broadcast_text, from_id)
                    send(peer, f"✅ Рассылка завершена!\n📨 Отправлено в {sent} чатов", msg_id)
                continue
            
            # !профиль
            if cmd == "профиль":
                chat = get_chat(peer)
                if str(from_id) not in chat["users"]:
                    chat["users"][str(from_id)] = {"role": 0, "warns": 0}
                    save_data()
                rnum = get_role(peer, from_id)
                rname = role_name(rnum)
                warns = chat["users"][str(from_id)].get("warns", 0)
                muted = "Да" if is_muted(peer, from_id) else "Нет"
                nick = chat["users"][str(from_id)].get("nickname", "")
                nicktxt = f"\n🏷️ Ник: {nick}" if nick else ""
                send(peer, f"📊 **Профиль**\n⭐ Роль: {rname} ({rnum})\n⚠️ Варны: {warns}/3\n🔇 Мут: {muted}{nicktxt}", msg_id)
                continue
            
            # !стафф
            if cmd == "стафф" and role >= 30:
                chat = get_chat(peer)
                staff = []
                for uid, udata in chat["users"].items():
                    if udata.get("role", 0) > 0:
                        staff.append(f"• {get_link(int(uid))} — {role_name(udata['role'])}")
                if is_owner(peer, from_id):
                    staff.insert(0, f"• {get_link(from_id)} — {role_name(100)} (Владелец)")
                if staff:
                    send(peer, "📋 **Стафф:**\n\n" + "\n".join(staff), msg_id)
                else:
                    send(peer, "📋 Нет сотрудников", msg_id)
                continue
            
            # !выдатьроль
            if cmd == "выдатьроль" and role >= 30:
                target = get_target(text, event)
                if not target:
                    send(peer, "❌ Укажите пользователя (@)", msg_id)
                else:
                    parts = args.split()
                    if len(parts) < 2:
                        send(peer, f"❌ {prefix}выдатьроль @user число", msg_id)
                    else:
                        try:
                            newr = int(parts[-1])
                            if newr not in ROLES:
                                send(peer, f"❌ Роль {newr} не существует", msg_id)
                            elif newr >= role:
                                send(peer, f"❌ Нельзя выдать роль {newr} (выше вашей)", msg_id)
                            elif newr == 100:
                                send(peer, f"❌ Нельзя выдать роль 100", msg_id)
                            else:
                                chat = get_chat(peer)
                                if str(target) not in chat["users"]:
                                    chat["users"][str(target)] = {"role": 0, "warns": 0}
                                chat["users"][str(target)]["role"] = newr
                                save_data()
                                send(peer, f"✅ {get_link(target)} получил роль: {role_name(newr)}", msg_id)
                        except:
                            send(peer, "❌ Укажите число", msg_id)
                continue
            
            # !снятьроль
            if cmd == "снятьроль" and role >= 30:
                target = get_target(text, event)
                if not target:
                    send(peer, "❌ Укажите пользователя", msg_id)
                else:
                    chat = get_chat(peer)
                    if str(target) in chat["users"]:
                        chat["users"][str(target)]["role"] = 0
                        save_data()
                        send(peer, f"✅ Роль {get_link(target)} сброшена", msg_id)
                    else:
                        send(peer, "❌ Нет роли", msg_id)
                continue
            
            # !ник
            if cmd == "ник" and role >= 100:
                target = get_target(text, event)
                if not target:
                    send(peer, "❌ Укажите пользователя (@)", msg_id)
                else:
                    parts = args.split(maxsplit=2)
                    if len(parts) < 3:
                        send(peer, f"❌ {prefix}ник @user Никнейм", msg_id)
                    else:
                        new_nick = parts[2][:30]
                        chat = get_chat(peer)
                        if str(target) not in chat["users"]:
                            chat["users"][str(target)] = {"role": 0, "warns": 0}
                        chat["users"][str(target)]["nickname"] = new_nick
                        save_data()
                        send(peer, f"✅ {get_link(target)} → ник: {new_nick}", msg_id)
                continue
            
            # !удалитьник
            if cmd == "удалитьник" and role >= 100:
                target = get_target(text, event)
                if not target:
                    send(peer, "❌ Укажите пользователя", msg_id)
                else:
                    chat = get_chat(peer)
                    if str(target) in chat["users"] and "nickname" in chat["users"][str(target)]:
                        del chat["users"][str(target)]["nickname"]
                        save_data()
                        send(peer, f"✅ Ник {get_link(target)} удален", msg_id)
                    else:
                        send(peer, "❌ Нет ника", msg_id)
                continue
            
            # !списокников
            if cmd == "списокников" and role >= 100:
                chat = get_chat(peer)
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
            if cmd == "варн" and role >= 30:
                target = get_target(text, event)
                if not target:
                    send(peer, "❌ Укажите пользователя", msg_id)
                else:
                    chat = get_chat(peer)
                    if str(target) not in chat["users"]:
                        chat["users"][str(target)] = {"role": 0, "warns": 0}
                    chat["users"][str(target)]["warns"] = chat["users"][str(target)].get("warns", 0) + 1
                    warns = chat["users"][str(target)]["warns"]
                    if warns >= 3:
                        if kick(chat_id, target):
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
            if cmd == "мут" and role >= 30:
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
                    mute(peer, target, minutes)
                    send(peer, f"🔇 {get_link(target)} замьючен на {minutes} мин!", msg_id)
                continue
            
            # !снятьмут
            if cmd == "снятьмут" and role >= 30:
                target = get_target(text, event)
                if not target:
                    send(peer, "❌ Укажите пользователя", msg_id)
                else:
                    unmute(peer, target)
                    send(peer, f"✅ {get_link(target)} размьючен", msg_id)
                continue
            
            # !кик
            if cmd == "кик" and role >= 30:
                target = get_target(text, event)
                if not target:
                    send(peer, "❌ Укажите пользователя", msg_id)
                else:
                    if kick(chat_id, target):
                        send(peer, f"🚪 {get_link(target)} кикнут!", msg_id)
                    else:
                        send(peer, "❌ Ошибка. Бот админ?", msg_id)
                continue
            
            # !тишина
            if cmd == "тишина" and role >= 30:
                chat = get_chat(peer)
                chat["silence_mode"] = not chat["silence_mode"]
                save_data()
                if chat["silence_mode"]:
                    send(peer, "🔇 **ТИШИНА ВКЛЮЧЕНА!**\nНе-админы будут кикаться.", msg_id)
                else:
                    send(peer, "🔈 **Тишина выключена**", msg_id)
                continue
                
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        print("🔄 Переподключение...")
        time.sleep(5)
        try:
            vk_session = vk_api.VkApi(token=GROUP_TOKEN)
            vk = vk_session.get_api()
            longpoll = VkBotLongPoll(vk_session, GROUP_ID)
        except:
            pass

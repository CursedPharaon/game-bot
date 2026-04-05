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

# Глобальные переменные
vk_session = None
vk = None
longpoll = None

def init_vk():
    global vk_session, vk, longpoll
    vk_session = vk_api.VkApi(token=GROUP_TOKEN)
    vk = vk_session.get_api()
    longpoll = VkBotLongPoll(vk_session, GROUP_ID)
    print("✅ VK сессия инициализирована")

init_vk()

# База данных - НОВАЯ СТРУКТУРА: все привязано к peer_id (беседе)
DATA_FILE = "bot_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    # Новая структура: данные по беседам
    return {
        "chats": {}  # chat_id: { "users": {}, "silence_mode": False, "muted_users": {} }
    }

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

# Для защиты от дублирования
processed_messages = defaultdict(float)
PROCESS_TIMEOUT = 10

def is_already_processed(msg_id):
    current_time = time.time()
    if msg_id in processed_messages:
        if current_time - processed_messages[msg_id] < PROCESS_TIMEOUT:
            return True
    processed_messages[msg_id] = current_time
    for mid in list(processed_messages.keys()):
        if current_time - processed_messages[mid] > 60:
            del processed_messages[mid]
    return False

def get_chat_data(peer_id):
    """Получает данные для конкретной беседы"""
    chat_id = str(peer_id)
    if chat_id not in data["chats"]:
        data["chats"][chat_id] = {
            "users": {},
            "silence_mode": False,
            "muted_users": {}
        }
        save_data()
    return data["chats"][chat_id]

def send(peer_id, text, reply_to=None):
    try:
        vk.messages.send(
            peer_id=peer_id,
            message=text,
            random_id=random.randint(1, 2**31),
            reply_to=reply_to
        )
    except Exception as e:
        print(f"Ошибка отправки: {e}")

def kick_user(chat_id, user_id):
    try:
        vk.messages.removeChatUser(chat_id=chat_id, user_id=user_id)
        return True
    except Exception as e:
        print(f"Ошибка кика: {e}")
        return False

def is_chat_admin(peer_id, user_id):
    try:
        members = vk.messages.getConversationMembers(peer_id=peer_id)
        for member in members['items']:
            if member['member_id'] == user_id:
                return member.get('is_admin', False) or member.get('is_owner', False)
    except:
        pass
    return False

def is_chat_owner(peer_id, user_id):
    try:
        members = vk.messages.getConversationMembers(peer_id=peer_id)
        for member in members['items']:
            if member['member_id'] == user_id:
                return member.get('is_owner', False)
    except:
        pass
    return False

def get_access(peer_id, user_id):
    """Получает уровень доступа пользователя в КОНКРЕТНОЙ беседе"""
    # Владелец бота по ID - глобальная роль 100
    if user_id == BOT_OWNER_ID:
        return 100
    # Владелец беседы ВК - роль 100
    if is_chat_owner(peer_id, user_id):
        return 100
    # Роль из БД для этой беседы
    chat_data = get_chat_data(peer_id)
    if str(user_id) in chat_data["users"]:
        return chat_data["users"][str(user_id)].get("role", 0)
    # Админ ВК получает роль 50
    if is_chat_admin(peer_id, user_id):
        return 50
    return 0

def get_role_name(role):
    return ROLES.get(role, "👤 Пользователь")

def can_assign_role(giver_role, target_role):
    if target_role >= giver_role:
        return False
    if target_role == 100:
        return False
    if giver_role < 30:
        return False
    return True

def is_user_muted(peer_id, user_id):
    """Проверяет мут в КОНКРЕТНОЙ беседе"""
    chat_data = get_chat_data(peer_id)
    key = str(user_id)
    if key in chat_data["muted_users"]:
        if chat_data["muted_users"][key] > time.time():
            return True
        else:
            del chat_data["muted_users"][key]
            save_data()
    return False

def mute_user(peer_id, user_id, minutes):
    """Мутит в КОНКРЕТНОЙ беседе"""
    chat_data = get_chat_data(peer_id)
    chat_data["muted_users"][str(user_id)] = time.time() + (minutes * 60)
    save_data()

def unmute_user(peer_id, user_id):
    """Снимает мут в КОНКРЕТНОЙ беседе"""
    chat_data = get_chat_data(peer_id)
    key = str(user_id)
    if key in chat_data["muted_users"]:
        del chat_data["muted_users"][key]
        save_data()

def get_target_user(text, event):
    if event.object.message.get('reply_message'):
        return event.object.message['reply_message']['from_id']
    match = re.search(r'\[id(\d+)\|', text)
    if match:
        return int(match.group(1))
    return None

def get_username(user_id):
    try:
        user = vk.users.get(user_ids=user_id, fields='screen_name')
        if user and user[0].get('screen_name'):
            return user[0]['screen_name']
    except:
        pass
    return None

def get_link(user_id):
    username = get_username(user_id)
    if username:
        return f"@{username}"
    return f"[id{user_id}|юзер]"

# ================= ВЕБ-СЕРВЕР =================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Bot is running')

def run_web():
    port = int(os.environ.get('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_web, daemon=True).start()

# ================= ОСНОВНОЙ ЦИКЛ =================
print("✅ Adrenaline Manager запущен!")
print(f"👑 Владелец бота: {BOT_OWNER_ID}")
print("📌 Все данные (роли, ники, муты) привязаны к каждой беседе отдельно!")

while True:
    try:
        for event in longpoll.listen():
            if event.type != VkBotEventType.MESSAGE_NEW:
                continue
            
            msg_id = event.object.message['id']
            
            if is_already_processed(msg_id):
                print(f"⚠️ Пропущен дубликат: {msg_id}")
                continue
            
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
            
            peer_id = event.object.message['peer_id']
            text = event.object.message['text'].strip()
            text_lower = text.lower()
            from_id = event.object.message['from_id']
            chat_id = peer_id - 2000000000
            
            # Проверка мута (в этой беседе)
            if is_user_muted(peer_id, from_id):
                print(f"🔇 Мут {from_id} в беседе {chat_id} - кикаем")
                kick_user(chat_id, from_id)
                continue
            
            # Проверка тишины (в этой беседе)
            chat_data = get_chat_data(peer_id)
            if chat_data["silence_mode"]:
                user_access = get_access(peer_id, from_id)
                if user_access < 30:
                    print(f"🔇 Тишина в беседе {chat_id}! Кикаем {from_id}")
                    kick_user(chat_id, from_id)
                    continue
            
            # Проверка на команду
            if not (text_lower.startswith('!') or text_lower.startswith('.') or text_lower.startswith('/')):
                continue
            
            prefix = text_lower[0]
            command = text_lower[1:].strip()
            original_command = text[1:].strip()
            
            user_role = get_access(peer_id, from_id)
            
            print(f"⚡ Беседа {chat_id}: {command}, роль: {user_role}")
            
            # ========== КОМАНДЫ ==========
            
            # помощь
            if command == "помощь":
                help_text = f"""🤖 **Adrenaline Manager**

🔹 **Все могут:**
{prefix}помощь - Это сообщение
{prefix}профиль - Ваш профиль
{prefix}роли - Список ролей
{prefix}стафф - Список участников с ролями

🔹 **Команды для ролей 30+:**
{prefix}выдатьроль @user [число] - Выдать роль
{prefix}снятьроль @user - Снять роль
{prefix}мут @user [минуты] - Замутить (кик)
{prefix}снятьмут @user - Снять мут
{prefix}кик @user - Кикнуть
{prefix}варн @user - Варн (3 = кик)
{prefix}тишина - Вкл/выкл тишину (кик)

🔹 **Владельцу беседы (роль 100):**
{prefix}ник @user текст - Сменить ник
{prefix}удалитьник @user - Удалить ник
{prefix}списокников - Список ников"""
                send(peer_id, help_text, msg_id)
                continue
            
            # роли
            if command == "роли":
                roles_text = "📋 **Список ролей:**\n\n"
                for role_num, role_name in ROLES.items():
                    roles_text += f"{role_name} — {role_num}\n"
                send(peer_id, roles_text, msg_id)
                continue
            
            # профиль (данные из этой беседы)
            if command == "профиль":
                chat_data = get_chat_data(peer_id)
                if str(from_id) not in chat_data["users"]:
                    chat_data["users"][str(from_id)] = {"role": 0, "warns": 0}
                    save_data()
                role_num = get_access(peer_id, from_id)
                role_name = get_role_name(role_num)
                warns = chat_data["users"][str(from_id)].get("warns", 0)
                muted = "Да" if is_user_muted(peer_id, from_id) else "Нет"
                nick = chat_data["users"][str(from_id)].get("nickname", "")
                nick_text = f"\n🏷️ Ник: {nick}" if nick else ""
                send(peer_id, f"📊 **Профиль**\n⭐ Роль: {role_name} ({role_num})\n⚠️ Варны: {warns}/3\n🔇 Мут: {muted}{nick_text}", msg_id)
                continue
            
            # стафф (список с ролями в этой беседе)
            if command == "стафф" and user_role >= 30:
                chat_data = get_chat_data(peer_id)
                staff_list = []
                for uid, user_info in chat_data["users"].items():
                    if user_info.get("role", 0) > 0:
                        role_num = user_info.get("role", 0)
                        role_name = get_role_name(role_num)
                        staff_list.append(f"• {get_link(int(uid))} — {role_name} ({role_num})")
                
                if is_chat_owner(peer_id, from_id):
                    staff_list.insert(0, f"• {get_link(from_id)} — {get_role_name(100)} (100) - Владелец")
                
                if staff_list:
                    send(peer_id, "📋 **Стафф этой беседы:**\n\n" + "\n".join(staff_list), msg_id)
                else:
                    send(peer_id, "📋 Нет участников с ролями.", msg_id)
                continue
            
            # выдатьроль (в этой беседе)
            if command.startswith("выдатьроль") and user_role >= 30:
                parts = original_command.split()
                if len(parts) < 3:
                    send(peer_id, f"❌ {prefix}выдатьроль @user [число]", msg_id)
                else:
                    target = get_target_user(text, event)
                    if not target:
                        send(peer_id, "❌ Укажите пользователя (@)", msg_id)
                    else:
                        try:
                            new_role = int(parts[-1])
                            if new_role not in ROLES:
                                send(peer_id, f"❌ Роль {new_role} не существует!", msg_id)
                            elif not can_assign_role(user_role, new_role):
                                send(peer_id, f"❌ Нельзя выдать роль {new_role}", msg_id)
                            else:
                                chat_data = get_chat_data(peer_id)
                                if str(target) not in chat_data["users"]:
                                    chat_data["users"][str(target)] = {"role": 0, "warns": 0}
                                chat_data["users"][str(target)]["role"] = new_role
                                save_data()
                                send(peer_id, f"✅ {get_link(target)} получил роль: {get_role_name(new_role)}", msg_id)
                        except ValueError:
                            send(peer_id, "❌ Укажите число роли", msg_id)
                continue
            
            # снятьроль (в этой беседе)
            if command.startswith("снятьроль") and user_role >= 30:
                target = get_target_user(text, event)
                if not target:
                    send(peer_id, "❌ Укажите пользователя", msg_id)
                else:
                    chat_data = get_chat_data(peer_id)
                    if str(target) in chat_data["users"]:
                        chat_data["users"][str(target)]["role"] = 0
                        save_data()
                        send(peer_id, f"✅ Роль {get_link(target)} сброшена", msg_id)
                    else:
                        send(peer_id, "❌ У пользователя нет роли", msg_id)
                continue
            
            # ник (в этой беседе)
            if command.startswith("ник") and user_role >= 100:
                parts = original_command.split(maxsplit=2)
                if len(parts) < 3:
                    send(peer_id, f"❌ {prefix}ник @user Никнейм", msg_id)
                else:
                    target = get_target_user(text, event)
                    if not target:
                        send(peer_id, "❌ Укажите пользователя (@)", msg_id)
                    else:
                        new_nick = parts[2][:30]
                        chat_data = get_chat_data(peer_id)
                        if str(target) not in chat_data["users"]:
                            chat_data["users"][str(target)] = {"role": 0, "warns": 0}
                        chat_data["users"][str(target)]["nickname"] = new_nick
                        save_data()
                        send(peer_id, f"✅ {get_link(target)} → ник: {new_nick}", msg_id)
                continue
            
            # удалитьник (в этой беседе)
            if command.startswith("удалитьник") and user_role >= 100:
                target = get_target_user(text, event)
                if not target:
                    send(peer_id, "❌ Укажите пользователя", msg_id)
                else:
                    chat_data = get_chat_data(peer_id)
                    if str(target) in chat_data["users"] and "nickname" in chat_data["users"][str(target)]:
                        del chat_data["users"][str(target)]["nickname"]
                        save_data()
                        send(peer_id, f"✅ Ник {get_link(target)} удален", msg_id)
                    else:
                        send(peer_id, "❌ Нет ника", msg_id)
                continue
            
            # списокников (в этой беседе)
            if command == "списокников" and user_role >= 100:
                chat_data = get_chat_data(peer_id)
                nicks = []
                for uid, user_info in chat_data["users"].items():
                    if user_info.get("nickname"):
                        nicks.append(f"• {get_link(int(uid))} → {user_info['nickname']}")
                if nicks:
                    send(peer_id, "📝 **Список ников в этой беседе:**\n\n" + "\n".join(nicks), msg_id)
                else:
                    send(peer_id, "📝 Ников нет", msg_id)
                continue
            
            # варн (в этой беседе)
            if command.startswith("варн") and user_role >= 30:
                target = get_target_user(text, event)
                if not target:
                    send(peer_id, "❌ Укажите пользователя", msg_id)
                else:
                    chat_data = get_chat_data(peer_id)
                    if str(target) not in chat_data["users"]:
                        chat_data["users"][str(target)] = {"role": 0, "warns": 0}
                    chat_data["users"][str(target)]["warns"] = chat_data["users"][str(target)].get("warns", 0) + 1
                    warns = chat_data["users"][str(target)]["warns"]
                    if warns >= 3:
                        if kick_user(chat_id, target):
                            send(peer_id, f"⚠️ {get_link(target)} кикнут за 3 варна!", msg_id)
                            if str(target) in chat_data["users"]:
                                del chat_data["users"][str(target)]
                        else:
                            send(peer_id, "❌ Ошибка кика", msg_id)
                    else:
                        send(peer_id, f"⚠️ {get_link(target)} варн {warns}/3", msg_id)
                    save_data()
                continue
            
            # мут (в этой беседе)
            if command.startswith("мут") and user_role >= 30:
                target = get_target_user(text, event)
                if not target:
                    send(peer_id, "❌ Укажите пользователя", msg_id)
                else:
                    minutes = 5
                    numbers = re.findall(r'\d+', text)
                    if numbers:
                        minutes = int(numbers[0])
                    if minutes <= 0:
                        minutes = 1
                    if minutes > 10080:
                        minutes = 10080
                    mute_user(peer_id, target, minutes)
                    send(peer_id, f"🔇 {get_link(target)} замьючен в ЭТОЙ беседе на {minutes} мин!", msg_id)
                continue
            
            # снятьмут (в этой беседе)
            if command.startswith("снятьмут") and user_role >= 30:
                target = get_target_user(text, event)
                if not target:
                    send(peer_id, "❌ Укажите пользователя", msg_id)
                else:
                    unmute_user(peer_id, target)
                    send(peer_id, f"✅ {get_link(target)} размьючен в ЭТОЙ беседе", msg_id)
                continue
            
            # кик
            if command.startswith("кик") and user_role >= 30:
                target = get_target_user(text, event)
                if not target:
                    send(peer_id, "❌ Укажите пользователя", msg_id)
                else:
                    if kick_user(chat_id, target):
                        send(peer_id, f"🚪 {get_link(target)} кикнут!", msg_id)
                    else:
                        send(peer_id, "❌ Ошибка. Бот админ?", msg_id)
                continue
            
            # тишина (в этой беседе)
            if command == "тишина" and user_role >= 30:
                chat_data = get_chat_data(peer_id)
                chat_data["silence_mode"] = not chat_data["silence_mode"]
                save_data()
                if chat_data["silence_mode"]:
                    send(peer_id, f"🔇 **ТИШИНА ВКЛЮЧЕНА в ЭТОЙ беседе!**", msg_id)
                else:
                    send(peer_id, f"🔈 **Тишина выключена в ЭТОЙ беседе**", msg_id)
                continue
                
    except Exception as e:
        print(f"❌ ОШИБКА: {e}")
        print("🔄 Переподключение через 5 секунд...")
        time.sleep(5)
        try:
            init_vk()
        except:
            print("❌ Не удалось переподключиться")

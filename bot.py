import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import random
import json
import sqlite3
from datetime import datetime, timedelta
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from flask import Flask
import threading
import os
import sys

# ===== НАСТРОЙКИ =====
GROUP_TOKEN = "vk1.a.QnYAWDAZ34tWzrWd4r5oHt5X0xQRf5WnQXO1C2-aJEP_pvrqVFIHIbd312NKSbtOkYCGhocqUm2EPXicYc4avsd6_IBswOJlgCZ1ltEnXKc2CkHv_rM1Mx2nGYokq0A7NglvG87Yyn7HT5asGIvyDjRluqgwyGqxiP_sktNAM0wc8azGqcRuDmMQfOUCcKUzxCE2Bx72cYjbJeHXsRSAjw"
GROUP_ID = 237386759

# ===== БАЗА ДАННЫХ =====
conn = sqlite3.connect('game.db', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 500,
    daily_last TEXT,
    total_wins INTEGER DEFAULT 0,
    total_spins INTEGER DEFAULT 0
)
''')
conn.commit()

def get_user(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    if not user:
        cursor.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (user_id, 500))
        conn.commit()
        return (user_id, 500, None, 0, 0)
    return user

def update_balance(user_id, amount):
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()

def can_take_daily(user_id):
    cursor.execute("SELECT daily_last FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if not result or not result[0]:
        return True
    last = datetime.fromisoformat(result[0])
    return datetime.now() - last > timedelta(days=1)

def set_daily_taken(user_id):
    cursor.execute("UPDATE users SET daily_last = ? WHERE user_id = ?", (datetime.now().isoformat(), user_id))
    conn.commit()

def format_number(n):
    if n >= 1000:
        return f"{n//1000}.{n%1000//100}K"
    return str(n)

# ===== КЛАВИАТУРЫ =====
def get_main_keyboard():
    keyboard = VkKeyboard(inline=True)
    keyboard.add_callback_button("🎰 Слоты", color=VkKeyboardColor.PRIMARY, payload={"type": "slots"})
    keyboard.add_callback_button("🎲 Кости", color=VkKeyboardColor.PRIMARY, payload={"type": "dice"})
    keyboard.add_line()
    keyboard.add_callback_button("💰 Баланс", color=VkKeyboardColor.SECONDARY, payload={"type": "balance"})
    keyboard.add_callback_button("📅 Бонус", color=VkKeyboardColor.SECONDARY, payload={"type": "daily"})
    keyboard.add_line()
    keyboard.add_callback_button("🏆 Топ игроков", color=VkKeyboardColor.SECONDARY, payload={"type": "top"})
    return keyboard

def get_slots_keyboard():
    keyboard = VkKeyboard(inline=True)
    keyboard.add_callback_button("🎰 Крутить (10💰)", color=VkKeyboardColor.PRIMARY, payload={"type": "spin", "bet": 10})
    keyboard.add_callback_button("🎰 Крутить (50💰)", color=VkKeyboardColor.PRIMARY, payload={"type": "spin", "bet": 50})
    keyboard.add_line()
    keyboard.add_callback_button("🎰 Крутить (100💰)", color=VkKeyboardColor.PRIMARY, payload={"type": "spin", "bet": 100})
    keyboard.add_line()
    keyboard.add_callback_button("🔙 Назад", color=VkKeyboardColor.NEGATIVE, payload={"type": "menu"})
    return keyboard

def get_dice_keyboard():
    keyboard = VkKeyboard(inline=True)
    keyboard.add_callback_button("🎲 Кости (5💰)", color=VkKeyboardColor.PRIMARY, payload={"type": "dice_roll", "bet": 5})
    keyboard.add_callback_button("🎲 Кости (25💰)", color=VkKeyboardColor.PRIMARY, payload={"type": "dice_roll", "bet": 25})
    keyboard.add_line()
    keyboard.add_callback_button("🔙 Назад", color=VkKeyboardColor.NEGATIVE, payload={"type": "menu"})
    return keyboard

# ===== ИГРОВАЯ ЛОГИКА =====
def play_slots(bet):
    symbols = ["🍒", "🍋", "🍊", "🍉", "⭐", "💎"]
    result = [random.choice(symbols) for _ in range(3)]
    
    if result[0] == result[1] == result[2]:
        if result[0] == "💎":
            win = bet * 5
        elif result[0] == "⭐":
            win = bet * 3
        else:
            win = bet * 2
        return result, win, True
    else:
        return result, -bet, False

def play_dice(bet):
    roll = random.randint(1, 6)
    parity = "чет" if roll % 2 == 0 else "нечет"
    return roll, parity

# ===== ОБРАБОТЧИКИ =====
def handle_start(user_id):
    get_user(user_id)
    return f"🎮 Добро пожаловать!\n💰 Баланс: {format_number(get_user(user_id)[1])} монет", get_main_keyboard()

def handle_balance(user_id):
    user = get_user(user_id)
    return f"💰 Баланс: {format_number(user[1])} монет\n🏆 Побед: {user[3]}\n🎰 Спинов: {user[4]}", get_main_keyboard()

def handle_daily(user_id):
    if can_take_daily(user_id):
        bonus = random.randint(100, 300)
        update_balance(user_id, bonus)
        set_daily_taken(user_id)
        return f"📅 Бонус! +{bonus} монет\n💰 Баланс: {format_number(get_user(user_id)[1])}", get_main_keyboard()
    return "⚠️ Бонус уже получен сегодня! Завтра будет новый.", get_main_keyboard()

def handle_top(user_id):
    top = cursor.execute("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10").fetchall()
    message = "🏆 ТОП-10 БОГАТЕЙШИХ 🏆\n\n"
    
    vk_session = vk_api.VkApi(token=GROUP_TOKEN)
    vk = vk_session.get_api()
    
    for i, (uid, bal) in enumerate(top, 1):
        try:
            user_info = vk.users.get(user_ids=uid)[0]
            name = f"{user_info['first_name']} {user_info['last_name']}"
        except:
            name = f"User_{uid}"
        message += f"{i}. {name} — {format_number(bal)} монет\n"
    return message, get_main_keyboard()

def handle_slots(user_id):
    return "🎰 Выбери ставку:", get_slots_keyboard()

def handle_spin(user_id, bet):
    user = get_user(user_id)
    if user[1] < bet:
        return f"❌ Не хватает! Нужно {bet}, есть {format_number(user[1])}", get_slots_keyboard()
    
    update_balance(user_id, -bet)
    result, win, is_win = play_slots(bet)
    
    if is_win:
        update_balance(user_id, win)
        return f"🎰 {result[0]} | {result[1]} | {result[2]} 🎰\n\n✨ ПОБЕДА! +{win} монет\n💰 Баланс: {format_number(get_user(user_id)[1])}", get_slots_keyboard()
    else:
        return f"🎰 {result[0]} | {result[1]} | {result[2]} 🎰\n\n❌ Проигрыш! -{bet} монет\n💰 Баланс: {format_number(get_user(user_id)[1])}", get_slots_keyboard()

def handle_dice_menu(user_id):
    return "🎲 Выбери ставку:", get_dice_keyboard()

def handle_dice_roll(user_id, bet):
    user = get_user(user_id)
    if user[1] < bet:
        return f"❌ Не хватает! Нужно {bet}", get_dice_keyboard()
    
    roll, parity = play_dice(bet)
    user_choice = random.choice(["чет", "нечет"])
    update_balance(user_id, -bet)
    
    if user_choice == parity:
        win = bet * 2
        update_balance(user_id, win)
        return f"🎲 Выпало: {roll} ({parity})\nТвой выбор: {user_choice}\n\n✨ ПОБЕДА! +{win} монет\n💰 Баланс: {format_number(get_user(user_id)[1])}", get_dice_keyboard()
    else:
        return f"🎲 Выпало: {roll} ({parity})\nТвой выбор: {user_choice}\n\n❌ Проигрыш! -{bet} монет\n💰 Баланс: {format_number(get_user(user_id)[1])}", get_dice_keyboard()

# ===== FLASK ДЛЯ RENDER HEALTHCHECK =====
app = Flask(__name__)

@app.route('/')
@app.route('/healthcheck')
def healthcheck():
    return "OK", 200

# ===== ЗАПУСК БОТА В ПОТОКЕ =====
def run_vk_bot():
    try:
        vk_session = vk_api.VkApi(token=GROUP_TOKEN)
        vk = vk_session.get_api()
        longpoll = VkBotLongPoll(vk_session, GROUP_ID)
        
        print("🤖 ВК БОТ ЗАПУЩЕН!", flush=True)
        print(f"Группа ID: {GROUP_ID}", flush=True)
        sys.stdout.flush()
        
        for event in longpoll.listen():
            try:
                if event.type == VkBotEventType.MESSAGE_NEW:
                    user_id = event.obj.message['from_id']
                    text = event.obj.message.get('text', '').lower()
                    
                    if text == '/start' or text == 'начать':
                        msg, kb = handle_start(user_id)
                        vk.messages.send(user_id=user_id, message=msg, random_id=random.randint(1, 999999), keyboard=kb.get_keyboard())
                    else:
                        msg, kb = handle_start(user_id)
                        vk.messages.send(user_id=user_id, message=msg, random_id=random.randint(1, 999999), keyboard=kb.get_keyboard())
                
                elif event.type == VkBotEventType.MESSAGE_EVENT:
                    user_id = event.obj.user_id
                    payload = json.loads(event.obj.payload)
                    event_id = event.obj.event_id
                    action = payload.get("type")
                    
                    if action == "menu":
                        msg, kb = handle_start(user_id)
                    elif action == "balance":
                        msg, kb = handle_balance(user_id)
                    elif action == "daily":
                        msg, kb = handle_daily(user_id)
                    elif action == "top":
                        msg, kb = handle_top(user_id)
                    elif action == "slots":
                        msg, kb = handle_slots(user_id)
                    elif action == "dice":
                        msg, kb = handle_dice_menu(user_id)
                    elif action == "spin":
                        bet = payload.get("bet", 10)
                        msg, kb = handle_spin(user_id, bet)
                    elif action == "dice_roll":
                        bet = payload.get("bet", 5)
                        msg, kb = handle_dice_roll(user_id, bet)
                    else:
                        msg, kb = "❌ Неизвестная команда", get_main_keyboard()
                    
                    vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=user_id, event_data=json.dumps({"type": "show_snackbar", "text": "✅"}))
                    vk.messages.send(user_id=user_id, message=msg, random_id=random.randint(1, 999999), keyboard=kb.get_keyboard())
            except Exception as e:
                print(f"Ошибка в событии: {e}", flush=True)
                continue
                
    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: {e}", flush=True)
        sys.stdout.flush()

if __name__ == "__main__":
    # Запускаем ВК бота в отдельном потоке
    bot_thread = threading.Thread(target=run_vk_bot, daemon=True)
    bot_thread.start()
    
    # Запускаем Flask для healthcheck
    port = int(os.environ.get("PORT", 10000))
    print(f"Flask сервер запущен на порту {port}", flush=True)
    app.run(host="0.0.0.0", port=port)

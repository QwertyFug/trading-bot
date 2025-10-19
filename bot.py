import telebot
from telebot import types
import sqlite3
import random
import time
import os
import requests
import hashlib
import hmac
from flask import Flask, request, jsonify
from threading import Thread

# ===== НАСТРОЙКИ =====
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8217857626:AAFePmaExR-7Zr50GtJKZ-1B7ZQ9hVLNYoQ')
CHANNEL_USERNAME = "@SKOLix_group"
SUPPORT_USERNAME = "@Noinbro"
ADMIN_ID = int(os.environ.get('ADMIN_ID', '6313032412'))
BOT_USERNAME = "TradingProiabot"
POCKET_OPTION_AFFILIATE_URL = "https://u3.shortink.io/register?utm_campaign=829188&utm_source=affiliate&utm_medium=sr&a=ln3hvKaiGy3DGT&ac=trading2&code=WELCOME50"
POSTBACK_SECRET = os.environ.get('POSTBACK_SECRET', 'swill_secret_2025')

# ===== ИНИЦИАЛИЗАЦИЯ =====
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

print("🤖 Бот инициализирован на Railway...")

# ===== POSTBACK 2.0 HANDLER =====
@app.route('/pocket-webhook', methods=['GET', 'POST'])
def pocket_webhook():
    try:
        print("🔄 Получен Postback 2.0 запрос")
        
        if request.method == 'GET':
            data = request.args
        else:
            data = request.json or request.form
        
        print(f"📨 Данные: {dict(data)}")
        
        # Проверка подписи
        signature = data.get('signature')
        if not verify_signature(data, signature):
            return jsonify({"status": "error", "message": "Invalid signature"}), 403
        
        user_id = data.get('sub1')
        deposit_amount = data.get('deposit') or data.get('sum')
        
        if not user_id or not deposit_amount:
            return jsonify({"status": "error", "message": "Missing data"}), 400
        
        try:
            user_id = int(user_id)
            deposit_amount = float(deposit_amount)
        except (ValueError, TypeError):
            return jsonify({"status": "error", "message": "Invalid data"}), 400
        
        if deposit_amount < 5.5:
            return jsonify({"status": "success", "message": "Deposit too small"}), 200
        
        # Верификация пользователя
        conn = sqlite3.connect('/tmp/bot_users.db', check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE users 
            SET verified_at = CURRENT_TIMESTAMP, 
                deposit_amount = ?,
                pocket_uid = ?
            WHERE user_id = ?
        ''', (deposit_amount, f"pocket_{user_id}", user_id))
        
        if cursor.rowcount > 0:
            print(f"✅ Пользователь {user_id} верифицирован")
            
            try:
                bot.send_message(
                    user_id, 
                    f"🎉 ВАШ АККАУНТ ВЕРИФИЦИРОВАН!\n\n"
                    f"✅ Депозит: ${deposit_amount}\n"
                    f"🚀 Теперь вам доступны все сигналы!"
                )
            except Exception as e:
                print(f"⚠️ Не удалось уведомить пользователя: {e}")
            
            update_referral_system(user_id)
        
        conn.commit()
        conn.close()
        
        return jsonify({"status": "success", "message": "User verified"}), 200
        
    except Exception as e:
        print(f"❌ Ошибка postback: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def verify_signature(data, signature):
    """Проверка подписи Postback 2.0"""
    try:
        sorted_params = sorted([(k, v) for k, v in data.items() if k != 'signature'])
        message = ''.join([f"{k}{v}" for k, v in sorted_params])
        
        expected_signature = hmac.new(
            POSTBACK_SECRET.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected_signature, signature)
    except Exception as e:
        print(f"❌ Ошибка проверки подписи: {e}")
        return False

def run_flask():
    """Запуск Flask сервера"""
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Запускаю Flask на порту {port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# Запускаем Flask в отдельном потоке
flask_thread = Thread(target=run_flask, daemon=True)
flask_thread.start()

# ===== БАЗА ДАННЫХ =====
def init_db():
    try:
        # Используем /tmp для Railway
        conn = sqlite3.connect('/tmp/bot_users.db', check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                subscribed INTEGER DEFAULT 0,
                signals_count INTEGER DEFAULT 0,
                reg_date TEXT DEFAULT CURRENT_TIMESTAMP,
                last_currency TEXT DEFAULT 'EUR/USD',
                rank TEXT DEFAULT '🥚 Новичок',
                referrer_id INTEGER DEFAULT 0,
                referrals_count INTEGER DEFAULT 0,
                coins INTEGER DEFAULT 0,
                pocket_uid TEXT,
                verified_at TEXT,
                deposit_amount REAL DEFAULT 0,
                is_admin INTEGER DEFAULT 0,
                welcome_shown INTEGER DEFAULT 0,
                last_active TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Добавляем админа
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (ADMIN_ID,))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO users (user_id, username, first_name, is_admin, verified_at, subscribed, welcome_shown, last_active)
                VALUES (?, 'admin', 'Администратор', 1, CURRENT_TIMESTAMP, 1, 1, CURRENT_TIMESTAMP)
            ''', (ADMIN_ID,))
        
        conn.commit()
        conn.close()
        print("✅ База данных инициализирована")
    except Exception as e:
        print(f"❌ Ошибка БД: {e}")

init_db()

# ===== СИСТЕМА РАНГОВ =====
RANKS = {
    0: {"name": "🥚 Новичок", "min_trades": 0},
    5: {"name": "🐣 Ученик", "min_trades": 5},
    10: {"name": "🐥 Опытный", "min_trades": 10},
    20: {"name": "🐓 Эксперт", "min_trades": 20},
    30: {"name": "🦅 Мастер", "min_trades": 30}
}

def get_user_rank(signals_count):
    for min_trades, rank_info in sorted(RANKS.items(), reverse=True):
        if signals_count >= min_trades:
            return rank_info["name"]
    return "🥚 Новичок"

# ===== ВАЛЮТНЫЕ ПАРЫ =====
CURRENCY_PAIRS = {
    "EUR/USD": "🇪🇺🇺🇸 EUR/USD OTC",
    "GBP/USD": "🇬🇧🇺🇸 GBP/USD OTC", 
    "USD/JPY": "🇺🇸🇯🇵 USD/JPY OTC",
    "AUD/USD": "🇦🇺🇺🇸 AUD/USD OTC",
    "USD/CAD": "🇺🇸🇨🇦 USD/CAD OTC",
    "USD/CHF": "🇺🇸🇨🇭 USD/CHF OTC",
    "EUR/GBP": "🇪🇺🇬🇧 EUR/GBP OTC",
    "GBP/JPY": "🇬🇧🇯🇵 GBP/JPY OTC"
}

TIMEFRAMES = {
    "10s": "⚡ 10 секунд",
    "30s": "🎯 30 секунд", 
    "60s": "⏰ 1 минута"
}

# ===== ПРОВЕРКА ПОДПИСКИ =====
def check_subscription(user_id):
    try:
        chat_member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        is_subscribed = chat_member.status in ['member', 'administrator', 'creator']
        
        conn = sqlite3.connect('/tmp/bot_users.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET subscribed = ? WHERE user_id = ?', (1 if is_subscribed else 0, user_id))
        conn.commit()
        conn.close()
        
        return is_subscribed
    except Exception as e:
        print(f"⚠️ Ошибка проверки подписки: {e}")
        return False

# ===== ПРОВЕРКА ВЕРИФИКАЦИИ =====
def check_pocket_verification(user_id):
    if user_id == ADMIN_ID:
        return True
        
    conn = sqlite3.connect('/tmp/bot_users.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT verified_at, deposit_amount FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    return result and result[0] and result[1] >= 5.5

# ===== ДЕКОРАТОР ДОСТУПА =====
def require_verification(func):
    def wrapper(*args, **kwargs):
        try:
            user_id = None
            if isinstance(args[0], types.CallbackQuery):
                user_id = args[0].from_user.id
            elif isinstance(args[0], types.Message):
                user_id = args[0].from_user.id
            
            if not user_id:
                return
                
            if user_id == ADMIN_ID:
                return func(*args, **kwargs)
            
            if not check_subscription(user_id):
                if isinstance(args[0], types.CallbackQuery):
                    bot.answer_callback_query(args[0].id, "❌ Сначала подпишитесь на канал!")
                    show_subscription_request(args[0].message)
                else:
                    show_subscription_request(args[0])
                return
            
            if not check_pocket_verification(user_id):
                if isinstance(args[0], types.CallbackQuery):
                    bot.answer_callback_query(args[0].id, "❌ Завершите регистрацию в Pocket Option!")
                    show_verification_instructions(args[0].message, user_id)
                else:
                    show_verification_instructions(args[0], user_id)
                return
            
            return func(*args, **kwargs)
        except Exception as e:
            print(f"Ошибка в декораторе: {e}")
    return wrapper

# ===== МЕНЮ =====
def main_menu(user_id=None):
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    show_welcome = False
    if user_id and user_id != ADMIN_ID:
        conn = sqlite3.connect('/tmp/bot_users.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT welcome_shown FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        if result and not result[0]:
            show_welcome = True
            cursor.execute('UPDATE users SET welcome_shown = 1 WHERE user_id = ?', (user_id,))
            conn.commit()
        conn.close()
    
    channel_link = f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}"
    support_link = f"https://t.me/{SUPPORT_USERNAME.replace('@', '')}"
    
    buttons = [
        types.InlineKeyboardButton("🎯 Получить сигнал", callback_data="get_signal"),
        types.InlineKeyboardButton("📊 Моя статистика", callback_data="show_stats"),
        types.InlineKeyboardButton("👥 Реферальная программа", callback_data="referral_program"),
        types.InlineKeyboardButton("📋 Инструкция", callback_data="show_instructions"),
        types.InlineKeyboardButton("📢 Наш канал", url=channel_link),
        types.InlineKeyboardButton("🆘 Поддержка", url=support_link)
    ]
    
    markup.add(buttons[0], buttons[1])
    markup.add(buttons[2], buttons[3])
    markup.add(buttons[4], buttons[5])
    
    if user_id == ADMIN_ID:
        markup.add(types.InlineKeyboardButton("👑 Панель админа", callback_data="admin_panel"))
    
    return markup, show_welcome

# ===== ГЕНЕРАТОР СИГНАЛОВ =====
def generate_signal(currency, timeframe):
    direction = random.choice(["BUY", "SELL"])
    confidence = random.randint(68, 87)
    
    if direction == "BUY":
        signal_emoji = "🟢"
        direction_text = "ВВЕРХ"
    else:
        signal_emoji = "🔴" 
        direction_text = "ВНИЗ"
    
    return f"""
{signal_emoji} СИГНАЛ {signal_emoji}

📊 Пара: {CURRENCY_PAIRS[currency]}
⏰ Время: {TIMEFRAMES[timeframe]}
🎯 Точность: {confidence}%
📈 Направление: {direction_text} {signal_emoji}

🚀 Удачи в торговле!
"""

# ===== ИНСТРУКЦИЯ РЕГИСТРАЦИИ =====
def show_verification_instructions(message, user_id):
    affiliate_url = f"{POCKET_OPTION_AFFILIATE_URL}&sub1={user_id}"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🌐 Зарегистрироваться в Pocket Option", url=affiliate_url))
    
    instruction_text = f"""
📋 ДЛЯ ПОЛУЧЕНИЯ ДОСТУПА К СИГНАЛАМ:

1. Нажмите кнопку «Зарегистрироваться в Pocket Option»
2. Создайте НОВЫЙ аккаунт по нашей ссылке
3. Пополните счет на 500 рублей (≈$5.5) или более
4. Доступ откроется АВТОМАТИЧЕСКИ через 1-2 минуты

🎯 Ваш ID для отслеживания: {user_id}
"""
    bot.send_message(message.chat.id, instruction_text, reply_markup=markup)

def show_subscription_request(message):
    markup = types.InlineKeyboardMarkup()
    channel_link = f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}"
    markup.add(types.InlineKeyboardButton("📢 ПОДПИСАТЬСЯ НА КАНАЛ", url=channel_link))
    markup.add(types.InlineKeyboardButton("✅ Я ПОДПИСАЛСЯ", callback_data="check_subscription"))
    
    bot.send_message(message.chat.id, 
                   f"❌ ДОСТУП ЗАКРЫТ\n\nДля использования бота необходимо подпишись на наш канал:\n{CHANNEL_USERNAME}", 
                   reply_markup=markup)

def update_referral_system(user_id):
    try:
        conn = sqlite3.connect('/tmp/bot_users.db', check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute('SELECT verified_at FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        
        if result and result[0]:
            cursor.execute('SELECT referrer_id FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            
            if result and result[0]:
                referrer_id = result[0]
                cursor.execute('UPDATE users SET referrals_count = referrals_count + 1, coins = coins + 10 WHERE user_id = ?', (referrer_id,))
                
                try:
                    cursor.execute('SELECT coins FROM users WHERE user_id = ?', (referrer_id,))
                    coins_result = cursor.fetchone()
                    coins_balance = coins_result[0] if coins_result else 0
                    
                    bot.send_message(referrer_id, 
                                   f"🎉 Ваш реферал успешно верифицирован!\n"
                                   f"💰 Вы получили +10 монет!\n"
                                   f"📊 Ваш баланс: {coins_balance} монет")
                except Exception as e:
                    print(f"⚠️ Не удалось уведомить реферера: {e}")
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Ошибка реферальной системы: {e}")

# ===== КОМАНДА /start =====
@bot.message_handler(commands=['start'])
def start_cmd(message):
    try:
        user_id = message.from_user.id
        name = message.from_user.first_name
        
        print(f"🆕 Новый пользователь: {name} (ID: {user_id})")
        
        referrer_id = None
        if len(message.text.split()) > 1:
            ref_code = message.text.split()[1]
            if ref_code.isdigit():
                referrer_id = int(ref_code)
        
        conn = sqlite3.connect('/tmp/bot_users.db', check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        existing_user = cursor.fetchone()
        
        if not existing_user:
            cursor.execute('''
                INSERT INTO users (user_id, username, first_name, reg_date, referrer_id, last_active) 
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, CURRENT_TIMESTAMP)
            ''', (user_id, message.from_user.username, name, referrer_id))
        
        conn.commit()
        conn.close()
        
        if user_id == ADMIN_ID:
            markup, show_welcome = main_menu(user_id)
            bot.send_message(message.chat.id, "👑 Добро пожаловать, Администратор!", reply_markup=markup)
            return
        
        if not check_subscription(user_id):
            show_subscription_request(message)
            return
        
        if not check_pocket_verification(user_id):
            show_verification_instructions(message, user_id)
            return
        
        markup, show_welcome = main_menu(user_id)
        
        if show_welcome:
            welcome_text = f"🎉 ДОБРО ПОЖАЛОВАТЬ, {name}!"
            bot.send_message(message.chat.id, welcome_text, reply_markup=markup)
        else:
            bot.send_message(message.chat.id, "🏠 Главное меню", reply_markup=markup)
            
    except Exception as e:
        print(f"Ошибка в start: {e}")

# ===== ОСНОВНЫЕ ОБРАБОТЧИКИ =====
@bot.callback_query_handler(func=lambda call: call.data == "check_subscription")
def check_subscription_callback(call):
    try:
        user_id = call.from_user.id
        
        if check_subscription(user_id):
            bot.answer_callback_query(call.id, "✅ Подписка подтверждена!")
            show_verification_instructions(call.message, user_id)
        else:
            bot.answer_callback_query(call.id, "❌ Вы еще не подписались!")
            
    except Exception as e:
        print(f"Ошибка проверки подписки: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "get_signal")
@require_verification
def get_signal_callback(call):
    try:
        markup = types.InlineKeyboardMarkup(row_width=2)
        buttons = [
            types.InlineKeyboardButton("🇪🇺🇺🇸 EUR/USD", callback_data="currency_EUR/USD"),
            types.InlineKeyboardButton("🇬🇧🇺🇸 GBP/USD", callback_data="currency_GBP/USD"),
            types.InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
        ]
        markup.add(buttons[0], buttons[1])
        markup.add(buttons[2])
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="💱 Выберите валютную пару:",
            reply_markup=markup
        )
    except Exception as e:
        print(f"Ошибка получения сигнала: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("currency_"))
@require_verification
def currency_selected(call):
    try:
        currency = call.data.replace("currency_", "")
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        buttons = [
            types.InlineKeyboardButton("⚡ 10 секунд", callback_data=f"timeframe_{currency}_10s"),
            types.InlineKeyboardButton("🎯 30 секунд", callback_data=f"timeframe_{currency}_30s"),
            types.InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
        ]
        markup.add(buttons[0], buttons[1])
        markup.add(buttons[2])
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"🎯 Выбрана пара: {CURRENCY_PAIRS[currency]}\n\n⏰ Выберите таймфрейм:",
            reply_markup=markup
        )
    except Exception as e:
        print(f"Ошибка выбора валюты: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("timeframe_"))
@require_verification
def timeframe_selected(call):
    try:
        data_parts = call.data.replace("timeframe_", "").split("_")
        currency = data_parts[0]
        timeframe = data_parts[1]
        
        signal = generate_signal(currency, timeframe)
        
        user_id = call.from_user.id
        conn = sqlite3.connect('/tmp/bot_users.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET signals_count = signals_count + 1 WHERE user_id = ?', (user_id,))
        
        cursor.execute('SELECT signals_count FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        if result:
            signals_count = result[0]
            new_rank = get_user_rank(signals_count)
            cursor.execute('UPDATE users SET rank = ? WHERE user_id = ?', (new_rank, user_id))
        
        conn.commit()
        conn.close()
        
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, signal)
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📈 Еще сигнал", callback_data="get_signal"))
        markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu"))
        
        bot.send_message(call.message.chat.id, "🔄 Выберите действие:", reply_markup=markup)
        
    except Exception as e:
        print(f"Ошибка выбора таймфрейма: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "main_menu")
@require_verification
def main_menu_callback(call):
    try:
        markup, show_welcome = main_menu(call.from_user.id)
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="🏠 Главное меню",
            reply_markup=markup
        )
    except Exception as e:
        print(f"Ошибка главного меню: {e}")

# ===== ЗАПУСК БОТА =====
if __name__ == "__main__":
    print("🚀 Запускаю бота на Railway...")
    print(f"🔧 Порт: {os.environ.get('PORT', '5000')}")
    print(f"👑 Админ ID: {ADMIN_ID}")
    
    # Даем время Flask запуститься
    time.sleep(2)
    
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except Exception as e:
        print(f"❌ Ошибка бота: {e}")
        print("🔄 Перезапуск через 5 секунд...")
        time.sleep(5)

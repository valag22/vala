import os
import sqlite3
import time
import uuid
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup

# ================= CONFIG =================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
PANEL_BASE = os.environ.get("PANEL_BASE", "https://little-waterfall-27fa.berbrtokamma.workers.dev")
PANEL_API_ROUTE = os.environ.get("PANEL_API_ROUTE", "sync")
PANEL_API_KEY = os.environ.get("PANEL_API_KEY", "")
PANEL_MASTER_KEY_FALLBACK = os.environ.get("PANEL_MASTER_KEY", "")

# شناسه عددی ادمین اصلی
ADMIN_ID = int(os.environ.get("ADMIN_ID", "6059940165"))

bot = telebot.TeleBot(BOT_TOKEN)
DB_PATH = "bot.db"

# ================= DATABASE =================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        # جدول کاربران
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0,
            config TEXT,
            trial_used INTEGER DEFAULT 0
        )
        """)
        # جدول تنظیمات سیستم (تنظیمات پویا)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)
        # جدول پلن‌ها
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            plan_key TEXT PRIMARY KEY,
            title TEXT,
            price INTEGER,
            profiles INTEGER,
            days INTEGER,
            conn_limit INTEGER,
            active INTEGER DEFAULT 1
        )
        """)
        
        # مقداردهی اولیه تنظیمات پیش‌فرض در صورت عدم وجود
        defaults = {
            "card_number": "8673 2559 1411 6362",
            "card_holder": "امیر والا شریف نسب",
            "force_join_enabled": "1",
            "force_join_channel": "@configfarazamin"
        }
        for k, v in defaults.items():
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
            
        # پلن‌های پیش‌فرض
        default_plans = [
            ("single", "یک کاربره", 60000, 1, 30, 1, 1),
            ("double", "دو کاربره", 70000, 1, 30, 2, 1),
            ("unlimited", "نامحدود", 90000, 1, 30, None, 1)
        ]
        for p in default_plans:
            cursor.execute("INSERT OR IGNORE INTO plans VALUES (?,?,?,?,?,?,?)", p)
            
        conn.commit()

init_db()

# ================= DYNAMIC SETTINGS HELPERS =================

def get_setting(key, default=""):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else default

def set_setting(key, value):
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()

def get_all_plans():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM plans WHERE active=1")
        return cursor.fetchall()

# ================= TRIAL CONFIG =================

TRIAL_TRAFFIC_GB = 0.05
TRIAL_DAYS = 1
REQ_PER_GB = 6000

# ================= KEYBOARD =================

reply_keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
reply_keyboard.add(
    "خرید کانفیگ🛒",
    "تست رایگان🕧",
    "کارت به کارت💲",
    "اطلاعات من✨",
    "پشتیبانی👇"
)

# ================= HELPERS =================

def is_member(user_id):
    enabled = get_setting("force_join_enabled", "1") == "1"
    channel = get_setting("force_join_channel", "@configfarazamin")
    if not enabled:
        return True
    try:
        member = bot.get_chat_member(channel, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False

def send_join_prompt(chat_id):
    channel = get_setting("force_join_channel", "@configfarazamin")
    keyboard = InlineKeyboardMarkup()
    channel_url = f"https://t.me/{channel.lstrip('@')}"
    keyboard.add(InlineKeyboardButton("📢 عضویت در کانال", url=channel_url))
    keyboard.add(InlineKeyboardButton("✅ عضو شدم", callback_data="check_join"))
    bot.send_message(
        chat_id,
        "برای استفاده از بات، ابتدا باید عضو کانال ما بشید. بعد از عضویت روی «عضو شدم» بزنید.",
        reply_markup=keyboard
    )

def require_join(message):
    if is_member(message.from_user.id):
        return True
    send_join_prompt(message.chat.id)
    return False

@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join_callback(call):
    if is_member(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ عضویت شما تایید شد")
        bot.edit_message_text(
            "✅ عضویت شما تایید شد. حالا می‌تونید از منو استفاده کنید.",
            call.message.chat.id,
            call.message.message_id
        )
    else:
        bot.answer_callback_query(call.id, "❌ هنوز عضو کانال نشدید", show_alert=True)

# ================= PANEL API =================

class PanelError(Exception):
    pass

def panel_auth():
    url = f"{PANEL_BASE}/{PANEL_API_ROUTE}/api/auth"
    attempts = []
    keys_to_try = []
    
    if PANEL_API_KEY:
        keys_to_try.append(("Panel API Key", PANEL_API_KEY))
    if PANEL_MASTER_KEY_FALLBACK:
        keys_to_try.append(("Master Key", PANEL_MASTER_KEY_FALLBACK))

    for label, key in keys_to_try:
        try:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {key}"},
                json={"key": key},
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    return data["config"], key
                attempts.append(f"{label}: پاسخ success=False")
            else:
                attempts.append(f"{label}: HTTP {resp.status_code}")
        except Exception as e:
            attempts.append(f"{label}: {e}")

    raise PanelError("اتصال به پنل با هیچ‌کدوم از کلیدها موفق نبود:\n" + "\n".join(attempts))

def panel_sync(config, key):
    url = f"{PANEL_BASE}/{PANEL_API_ROUTE}/api/sync"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}"},
        json={"key": key, "config": config},
        timeout=15
    )
    if resp.status_code != 200 or not resp.json().get("success"):
        raise PanelError(f"ذخیره کانفیگ روی پنل ناموفق بود - HTTP {resp.status_code}")
    return resp.json().get("newRoute", config.get("apiRoute", PANEL_API_ROUTE))

def panel_create_profiles(name_prefix, count, days, traffic_gb=None, conn_limit=None):
    config, working_key = panel_auth()

    if config.get("users") is None:
        config["users"] = []

    expiry_ms = int((time.time() + days * 86400) * 1000)
    created_at = int(time.time() * 1000)

    new_names = []
    for i in range(count):
        name = f"{name_prefix}_{i+1}" if count > 1 else name_prefix
        user_obj = {
            "id": str(uuid.uuid4()),
            "name": name,
            "expiryMs": expiry_ms,
            "createdAt": created_at,
        }
        if traffic_gb is not None:
            user_obj["limitTotalReq"] = round(traffic_gb * REQ_PER_GB)
        if conn_limit is not None:
            user_obj["connLimit"] = conn_limit

        config["users"].append(user_obj)
        new_names.append(name)

    new_route = panel_sync(config, working_key)
    return [f"{PANEL_BASE}/{new_route}?sub={name}" for name in new_names]

# ================= USER HANDLERS =================

@bot.message_handler(commands=['start'])
def start(message):
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users(user_id, username) VALUES (?,?)",
            (message.from_user.id, message.from_user.username)
        )
        conn.commit()

    bot.reply_to(message, "به بات کانفیگ فرا زمین خوش آمدید", reply_markup=reply_keyboard)

    if not is_member(message.from_user.id):
        send_join_prompt(message.chat.id)

@bot.message_handler(func=lambda m: m.text == "خرید کانفیگ🛒")
def buy_menu(message):
    if not require_join(message):
        return

    plans = get_all_plans()
    if not plans:
        bot.reply_to(message, "❌ در حال حاضر هیچ پلنی برای فروش فعال نیست.")
        return

    keyboard = InlineKeyboardMarkup()
    for plan in plans:
        keyboard.add(
            InlineKeyboardButton(
                f"{plan['title']} - {plan['price']:,} تومان",
                callback_data=f"buy_{plan['plan_key']}"
            )
        )

    bot.reply_to(message, "پلن مورد نظر را انتخاب کنید، حجم همه کانفیگ‌ها نامحدود هست", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def buy_config(call):
    user_id = call.from_user.id
    if not is_member(user_id):
        bot.answer_callback_query(call.id, "ابتدا باید عضو کانال بشید", show_alert=True)
        send_join_prompt(call.message.chat.id)
        return

    plan_key = call.data.split("_", 1)[1]
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM plans WHERE plan_key=? AND active=1", (plan_key,))
        plan = cursor.fetchone()

    if not plan:
        bot.answer_callback_query(call.id, "پلن نامعتبر یا غیرفعال است")
        return

    price = plan["price"]

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        user = cursor.fetchone()

        if not user:
            bot.reply_to(call.message, "حساب شما پیدا نشد")
            return

        balance = user["balance"]

        if balance < price:
            bot.reply_to(
                call.message,
                f"❌ موجودی کافی نیست\n\nقیمت:\n{price:,} تومان\n\nموجودی شما:\n{balance:,} تومان"
            )
            return

        processing_msg = bot.reply_to(call.message, "⏳ در حال ساخت کانفیگ...")

        try:
            name_prefix = f"u{user_id}_{int(time.time())}"
            links = panel_create_profiles(
                name_prefix=name_prefix,
                count=plan["profiles"],
                days=plan["days"],
                conn_limit=plan["conn_limit"]
            )
        except Exception as e:
            bot.edit_message_text(
                f"❌ خطا در ساخت کانفیگ از پنل.\n\nجزئیات خطا: {e}",
                call.message.chat.id,
                processing_msg.message_id
            )
            return

        config_text = "\n".join(links)
        cursor.execute("UPDATE users SET balance = balance - ?, config = ? WHERE user_id=?", (price, config_text, user_id))
        conn.commit()

    bot.edit_message_text(
        f"✅ خرید موفق بود\n\n💰 مبلغ:\n{price:,} تومان\n\n🔑 لینک(های) اشتراک شما:\n{config_text}",
        call.message.chat.id,
        processing_msg.message_id
    )

@bot.message_handler(func=lambda m: m.text == "تست رایگان🕧")
def free_trial(message):
    if not require_join(message):
        return

    user_id = message.from_user.id

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT trial_used FROM users WHERE user_id=?", (user_id,))
        row = cursor.fetchone()

        if not row:
            conn.execute("INSERT OR IGNORE INTO users(user_id, username) VALUES (?,?)", (user_id, message.from_user.username))
            trial_used = 0
        else:
            trial_used = row["trial_used"]

        if trial_used:
            bot.reply_to(message, "❌ شما قبلاً از تست رایگان استفاده کرده‌اید.")
            return

        processing_msg = bot.reply_to(message, "⏳ در حال ساخت کانفیگ تست...")

        try:
            name_prefix = f"trial_{user_id}_{int(time.time())}"
            links = panel_create_profiles(
                name_prefix=name_prefix,
                count=1,
                days=TRIAL_DAYS,
                traffic_gb=TRIAL_TRAFFIC_GB
            )
        except Exception as e:
            bot.edit_message_text(
                f"❌ خطا در ساخت کانفیگ تست.\n\nجزئیات خطا: {e}",
                message.chat.id,
                processing_msg.message_id
            )
            return

        cursor.execute("UPDATE users SET trial_used = 1 WHERE user_id = ?", (user_id,))
        conn.commit()

    config_text = "\n".join(links)
    bot.edit_message_text(
        f"✅ کانفیگ تست شما ساخته شد\n\n🔑 لینک اشتراک:\n{config_text}",
        message.chat.id,
        processing_msg.message_id
    )

@bot.message_handler(func=lambda m: m.text == "پشتیبانی👇")
def support(message):
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("💬 ارتباط با پشتیبانی", url="https://t.me/valaorp"))
    bot.reply_to(message, "برای ارتباط با پشتیبانی روی دکمه زیر بزنید:", reply_markup=keyboard)

@bot.message_handler(func=lambda m: m.text == "کارت به کارت💲")
def card(message):
    if not require_join(message):
        return
    
    card_num = get_setting("card_number")
    card_holder = get_setting("card_holder")

    bot.reply_to(
        message,
        f"مبلغ را به شماره کارت زیر واریز کنید:\n\n`{card_num}`\n**{card_holder}**\n\nبعد از پرداخت، عکس رسید را ارسال کنید.",
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda m: m.text == "اطلاعات من✨")
def my_info(message):
    if not require_join(message):
        return

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (message.from_user.id,))
        row = cursor.fetchone()
        balance = row["balance"] if row else 0

    bot.send_message(
        message.chat.id,
        f"👤 اطلاعات حساب شما\n\n🆔 شناسه: `{message.from_user.id}`\n💰 موجودی: {balance:,} تومان",
        parse_mode="Markdown"
    )

@bot.message_handler(content_types=['photo'])
def receipt(message):
    bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
    bot.send_message(
        ADMIN_ID,
        f"📥 **رسید جدید دریافت شد:**\n"
        f"👤 نام: {message.from_user.first_name}\n"
        f"🆔 آیدی عددی: `{message.from_user.id}`\n\n"
        f"⚡️ جهت شارژ سریع:\n`/charge {message.from_user.id} 60000`",
        parse_mode="Markdown"
    )
    bot.reply_to(message, "✅ رسید ارسال شد، پس از تایید ادمین موجودی شما شارژ می‌شود.")

# ================= ULTRA-ADVANCED ADMIN PANEL =================

def get_admin_main_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📊 آمار مالی و سیستم", callback_data="adm_stats"),
        InlineKeyboardButton("🔎 مدیریت کاربران", callback_data="adm_user_menu")
    )
    keyboard.add(
        InlineKeyboardButton("💎 مدیریت پلن‌های فروش", callback_data="adm_plan_menu"),
        InlineKeyboardButton("💳 مدیریت شماره کارت", callback_data="adm_card_menu")
    )
    keyboard.add(
        InlineKeyboardButton("🔒 تنظیمات قفل کانال", callback_data="adm_lock_menu"),
        InlineKeyboardButton("📢 پیام همگانی (رسانه‌ای)", callback_data="adm_broadcast_menu")
    )
    keyboard.add(
        InlineKeyboardButton("🌐 تست سلامت پنل", callback_data="adm_test_panel"),
        InlineKeyboardButton("💾 دریافت بکاپ دیتابیس", callback_data="adm_get_backup")
    )
    return keyboard

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        return
    bot.send_message(
        message.chat.id,
        "👑 **پنل مدیریت ارشد (Ultra Admin Panel)**\nکنترل کامل سیستم در اختیار شماست:",
        reply_markup=get_admin_main_keyboard(),
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("adm_"))
def admin_callbacks(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔️ دسترسی غیرمجاز", show_alert=True)
        return

    action = call.data
    bot.answer_callback_query(call.id)

    # --- آمار و آمار مالی ---
    if action == "adm_stats":
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*), COALESCE(SUM(balance),0) FROM users")
            total_users, total_balance = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) FROM users WHERE trial_used=1")
            trial_count = cursor.fetchone()[0]

        text = f"📊 **گزارش کامل سیستم:**\n\n" \
               f"👥 **تعداد کل کاربران:** {total_users:,} نفر\n" \
               f"🧪 **تست‌های گرفته شده:** {trial_count:,} عدد\n" \
               f"💰 **مجموع موجودی کیف‌پول‌ها:** {total_balance:,} تومان\n"
        bot.send_message(call.message.chat.id, text, parse_mode="Markdown")

    # --- منوی کاربران ---
    elif action == "adm_user_menu":
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("🔍 جستجوی کاربر", callback_data="adm_search_u"),
            InlineKeyboardButton("➕ شارژ حساب", callback_data="adm_charge_u"),
            InlineKeyboardButton("➖ کسر موجودی", callback_data="adm_deduct_u"),
            InlineKeyboardButton("✉️ ارسال پیام", callback_data="adm_send_u")
        )
        bot.send_message(call.message.chat.id, "👤 **مدیریت کاربران:**", reply_markup=kb, parse_mode="Markdown")

    elif action == "adm_search_u":
        msg = bot.send_message(call.message.chat.id, "🆔 آیدی عددی کاربر را وارد کنید:")
        bot.register_next_step_handler(msg, process_admin_search)

    elif action == "adm_charge_u":
        msg = bot.send_message(call.message.chat.id, "➕ اطلاعات را وارد کنید:\nفرمت: `آیدی مبلغ`\nمثال: `6059940165 50000`", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_admin_charge)

    elif action == "adm_deduct_u":
        msg = bot.send_message(call.message.chat.id, "➖ اطلاعات را وارد کنید:\nفرمت: `آیدی مبلغ`\nمثال: `6059940165 20000`", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_admin_deduct)

    elif action == "adm_send_u":
        msg = bot.send_message(call.message.chat.id, "✉️ پیام شخصی:\nفرمت: `آیدی متن_پیام`", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_direct_message)

    # --- مدیریت کارت بانکی ---
    elif action == "adm_card_menu":
        card_num = get_setting("card_number")
        card_holder = get_setting("card_holder")
        
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("✏️ تغییر شماره کارت و نام", callback_data="adm_edit_card"))
        
        bot.send_message(
            call.message.chat.id,
            f"💳 **اطلاعات فعلی کارت:**\n\nشماره کارت: `{card_num}`\nصاحب حساب: **{card_holder}**",
            reply_markup=kb,
            parse_mode="Markdown"
        )

    elif action == "adm_edit_card":
        msg = bot.send_message(
            call.message.chat.id,
            "✏️ شماره کارت و نام صاحب حساب را بفرستید:\nفرمت: `شماره_کارت | نام_صاحب_حساب`\nمثال:\n`6037997512345678 | علی محمدی`",
            parse_mode="Markdown"
        )
        bot.register_next_step_handler(msg, process_edit_card)

    # --- مدیریت قفل کانال ---
    elif action == "adm_lock_menu":
        enabled = get_setting("force_join_enabled", "1") == "1"
        channel = get_setting("force_join_channel", "@configfarazamin")
        
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("🟢 فعال" if enabled else "🔴 غیرفعال", callback_data="adm_toggle_lock"),
            InlineKeyboardButton("✏️ تغییر آیدی کانال", callback_data="adm_change_channel")
        )
        bot.send_message(
            call.message.chat.id,
            f"🔒 **وضعیت قفل کانال اجباری:**\n\nوضعیت: {'فعال ✅' if enabled else 'غیرفعال ❌'}\nکانال: `{channel}`",
            reply_markup=kb,
            parse_mode="Markdown"
        )

    elif action == "adm_toggle_lock":
        curr = get_setting("force_join_enabled", "1")
        new_val = "0" if curr == "1" else "1"
        set_setting("force_join_enabled", new_val)
        bot.send_message(call.message.chat.id, f"✅ وضعیت قفل به {'فعال' if new_val == '1' else 'غیرفعال'} تغییر یافت.")

    elif action == "adm_change_channel":
        msg = bot.send_message(call.message.chat.id, "✏️ یوزرنیم جدید کانال را بفرستید (به همراه @):\nمثال: `@mychannel`")
        bot.register_next_step_handler(msg, process_change_channel)

    # --- مدیریت پلن‌ها ---
    elif action == "adm_plan_menu":
        plans = get_all_plans()
        text = "💎 **لیست پلن‌های موجود:**\n\n"
        kb = InlineKeyboardMarkup()
        for p in plans:
            text += f"▪️ **{p['title']}** (`{p['plan_key']}`): {p['price']:,} تومان\n"
            kb.add(InlineKeyboardButton(f"✏️ تغییر قیمت {p['title']}", callback_data=f"adm_p_price_{p['plan_key']}"))
        
        bot.send_message(call.message.chat.id, text, reply_markup=kb, parse_mode="Markdown")

    elif action.startswith("adm_p_price_"):
        plan_key = action.replace("adm_p_price_", "")
        msg = bot.send_message(call.message.chat.id, f"قیمت جدید برای پلن `{plan_key}` را به تومان وارد کنید:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, lambda m: process_change_plan_price(m, plan_key))

    # --- پیام همگانی پیشرفته ---
    elif action == "adm_broadcast_menu":
        msg = bot.send_message(call.message.chat.id, "📢 **پست همگانی خود را بفرستید:**\n(می‌تواند شامل متن، عکس، ویدیو، فایل یا هر رسانه‌ای باشد)")
        bot.register_next_step_handler(msg, process_advanced_broadcast)

    # --- تست پنل ---
    elif action == "adm_test_panel":
        bot.send_message(call.message.chat.id, "⏳ در حال بررسی ارتباط با API...")
        try:
            _, key_used = panel_auth()
            bot.send_message(call.message.chat.id, f"✅ **اتصال برقرار است.**\nKey: `{key_used}`", parse_mode="Markdown")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ **خطا:** {e}")

    # --- دانلود بکاپ ---
    elif action == "adm_get_backup":
        if os.path.exists(DB_PATH):
            with open(DB_PATH, 'rb') as doc:
                bot.send_document(call.message.chat.id, doc, caption="💾 **بکاپ دیتابیس ربات**")
        else:
            bot.send_message(call.message.chat.id, "❌ دیتابیس یافت نشد.")

# ================= ADMIN PROCESSORS =================

def process_edit_card(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.split("|")
        card_num = parts[0].strip()
        card_holder = parts[1].strip()
        set_setting("card_number", card_num)
        set_setting("card_holder", card_holder)
        bot.reply_to(message, "✅ شماره کارت و نام صاحب حساب به‌روزرسانی شد.")
    except Exception:
        bot.reply_to(message, "❌ فرمت ورودی اشتباه است. باید با کاراکتر `|` جدا کنید.")

def process_change_channel(message):
    if message.from_user.id != ADMIN_ID: return
    channel = message.text.strip()
    if not channel.startswith("@"):
        channel = "@" + channel
    set_setting("force_join_channel", channel)
    bot.reply_to(message, f"✅ کانال اجباری به `{channel}` تغییر یافت.", parse_mode="Markdown")

def process_change_plan_price(message, plan_key):
    if message.from_user.id != ADMIN_ID: return
    try:
        new_price = int(message.text.strip())
        with get_db() as conn:
            conn.execute("UPDATE plans SET price=? WHERE plan_key=?", (new_price, plan_key))
            conn.commit()
        bot.reply_to(message, f"✅ قیمت پلن `{plan_key}` به {new_price:,} تومان تغییر یافت.", parse_mode="Markdown")
    except ValueError:
        bot.reply_to(message, "❌ قیمت باید یک عدد معتبر باشد.")

def process_advanced_broadcast(message):
    if message.from_user.id != ADMIN_ID: return
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        all_ids = [row["user_id"] for row in cursor.fetchall()]

    sent, failed = 0, 0
    bot.send_message(message.chat.id, f"⏳ ارسال به {len(all_ids)} کاربر شروع شد...")

    for uid in all_ids:
        try:
            bot.copy_message(chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id)
            sent += 1
        except Exception:
            failed += 1
        time.sleep(0.04)

    bot.send_message(message.chat.id, f"✅ **ارسال کامل شد.**\n🟢 موفق: {sent}\n🔴 ناموفق: {failed}", parse_mode="Markdown")

def process_admin_search(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        target_id = int(message.text.strip())
    except ValueError:
        bot.reply_to(message, "❌ آیدی باید عدد باشد.")
        return

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, balance, trial_used, config FROM users WHERE user_id=?", (target_id,))
        row = cursor.fetchone()

    if not row:
        bot.reply_to(message, "❌ کاربر یافت نشد.")
        return

    text = f"👤 **اطلاعات کاربر:**\n\n" \
           f"🆔 **آیدی:** `{row['user_id']}`\n" \
           f"👤 **یوزرنیم:** @{row['username'] if row['username'] else '-'}\n" \
           f"💰 **موجودی:** {row['balance']:,} تومان\n" \
           f"🧪 **تست رایگان:** {'استفاده شده' if row['trial_used'] else 'استفاده نشده'}\n\n" \
           f"🔑 **آخرین لینک:**\n`{row['config'] if row['config'] else '-'}`"
    bot.reply_to(message, text, parse_mode="Markdown")

def process_admin_charge(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.split()
        target_id, amount = int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        bot.reply_to(message, "❌ فرمت نادرست است.", parse_mode="Markdown")
        return

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (target_id,))
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_id))
        conn.commit()
        cursor.execute("SELECT balance FROM users WHERE user_id=?", (target_id,))
        new_balance = cursor.fetchone()["balance"]

    bot.reply_to(message, f"✅ حساب کاربر `{target_id}` به مبلغ {amount:,} تومان شارژ شد.\nموجودی جدید: {new_balance:,} تومان", parse_mode="Markdown")
    try:
        bot.send_message(target_id, f"✅ حساب شما به مبلغ {amount:,} تومان شارژ شد.\n💰 موجودی جدید: {new_balance:,} تومان")
    except Exception:
        pass

def process_admin_deduct(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.split()
        target_id, amount = int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        bot.reply_to(message, "❌ فرمت نادرست است.", parse_mode="Markdown")
        return

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = MAX(0, balance - ?) WHERE user_id = ?", (amount, target_id))
        conn.commit()
        cursor.execute("SELECT balance FROM users WHERE user_id=?", (target_id,))
        row = cursor.fetchone()
        new_balance = row["balance"] if row else 0

    bot.reply_to(message, f"🔻 مبلغ {amount:,} تومان کسر شد.\nموجودی جدید: {new_balance:,} تومان", parse_mode="Markdown")

def process_direct_message(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.split(maxsplit=1)
        target_id = int(parts[0])
        msg_text = parts[1]
    except (IndexError, ValueError):
        bot.reply_to(message, "❌ فرمت نادرست است.", parse_mode="Markdown")
        return

    try:
        bot.send_message(target_id, f"📩 **پیام مدیریت:**\n\n{msg_text}", parse_mode="Markdown")
        bot.reply_to(message, f"✅ ارسال شد.", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ خطا: {e}")

# ================= RUN BOT =================

if __name__ == "__main__":
    bot.infinity_polling(skip_pending=True)

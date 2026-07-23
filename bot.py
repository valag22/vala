import telebot
import sqlite3
import requests
import uuid
import time
import os

from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup
)

# ================= CONFIG =================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "BJJIBA0BJURXDHCKSSSLRNGMLXJOZLHSQLPXSYXIQGYUPXALTENYFDPAFEOFDHNR")
PANEL_BASE = os.environ.get("PANEL_BASE", "https://little-waterfall-27fa.berbrtokamma.workers.dev")
PANEL_API_ROUTE = os.environ.get("PANEL_API_ROUTE", "sync")
PANEL_API_KEY = os.environ.get("PANEL_API_KEY", "nahan_mrlmsp7c_7lg9rlf0")
PANEL_MASTER_KEY_FALLBACK = os.environ.get("PANEL_MASTER_KEY", "vala1392")
PANEL_AUTH_HEADERS = {"Authorization": f"Bearer {PANEL_API_KEY}"}

ADMIN_ID = 6059940165

bot = telebot.TeleBot(BOT_TOKEN)

# ================= DATABASE =================
conn = sqlite3.connect("bot.db", check_same_thread=False)
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

# جدول تنظیمات عام (کانال اجباری، وضعیت ربات، قیمت پلن‌ها و...)
cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")
conn.commit()

try:
    cursor.execute("ALTER TABLE users ADD COLUMN trial_used INTEGER DEFAULT 0")
    conn.commit()
except sqlite3.OperationalError:
    pass

# حافظه موقت برای مدیریت مراحل ادمین
user_steps = {}

# ================= HELPER FUNCTIONS =================
def get_setting(key, default=None):
    cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cursor.fetchone()
    return row[0] if row else default

def set_setting(key, value):
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()

def get_plan_price(plan_key, default_price):
    val = get_setting(f"price_{plan_key}")
    return int(val) if val else default_price

# ================= PLANS =================
# قیمت‌های پیش‌فرض در صورت ست نشدن در دیتابیس
DEFAULT_PLANS = {
    "single": {"title": "یک کاربره", "default_price": 60000, "profiles": 1, "days": 30, "conn_limit": 1},
    "double": {"title": "دو کاربره", "default_price": 70000, "profiles": 1, "days": 30, "conn_limit": 2},
    "unlimited": {"title": "نامحدود", "default_price": 90000, "profiles": 1, "days": 30, "conn_limit": None},
}

def get_current_plans():
    plans = {}
    for k, v in DEFAULT_PLANS.items():
        plans[k] = v.copy()
        plans[k]["price"] = get_plan_price(k, v["default_price"])
    return plans

# ================= TRIAL =================
TRIAL_TRAFFIC_GB = 0.05   # 50 مگابایت
TRIAL_DAYS = 1            # 1 روز
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

# ================= CHECK BOT & JOIN STATUS =================
def is_bot_active():
    return get_setting("bot_status", "active") == "active"

def is_user_joined(user_id):
    if user_id == ADMIN_ID:
        return True
        
    channel_id = get_setting("force_channel_id")
    if not channel_id or channel_id == "NONE":
        return True
        
    try:
        member = bot.get_chat_member(channel_id, user_id)
        if member.status in ['creator', 'administrator', 'member']:
            return True
        return False
    except Exception:
        return True

def send_force_join_message(chat_id):
    channel_link = get_setting("force_channel_link", "https://t.me/telegram")
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📢 عضویت در کانال", url=channel_link))
    markup.add(InlineKeyboardButton("عضو شدم 🔄", callback_data="check_join"))
    
    bot.send_message(
        chat_id,
        "⚠️ **جهت استفاده از خدمات ربات، باید ابتدا در کانال ما عضو شوید:**\n\nپس از عضویت روی دکمه «عضو شدم 🔄» کلیک کنید.",
        reply_markup=markup,
        parse_mode="Markdown"
    )

def main_guard(func):
    """بررسی خاموش نبودن ربات و عضویت اجباری کاربر"""
    def wrapper(message, *args, **kwargs):
        if message.from_user.id != ADMIN_ID and not is_bot_active():
            bot.reply_to(message, "🛠 **ربات در حال حاضر جهت بهینه‌سازی در دست تعمیر است.**\nلطفاً بعداً مراجعه کنید.")
            return
        if not is_user_joined(message.from_user.id):
            send_force_join_message(message.chat.id)
            return
        return func(message, *args, **kwargs)
    return wrapper

# ================= PANEL API =================
class PanelError(Exception):
    pass

def panel_auth():
    url = f"{PANEL_BASE}/{PANEL_API_ROUTE}/api/auth"
    attempts = []
    keys_to_try = [("Panel API Key", PANEL_API_KEY)]
    if PANEL_MASTER_KEY_FALLBACK:
        keys_to_try.append(("Master Key", PANEL_MASTER_KEY_FALLBACK))

    for label, key in keys_to_try:
        try:
            resp = requests.post(url, headers={"Authorization": f"Bearer {key}"}, json={"key": key}, timeout=15)
        except Exception as e:
            attempts.append(f"{label}: خطای شبکه - {e}")
            continue

        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception:
                attempts.append(f"{label}: پاسخ 200 ولی JSON نامعتبر - {resp.text[:200]}")
                continue

            if data.get("success"):
                return data["config"], key
            else:
                attempts.append(f"{label}: پاسخ 200 ولی success=False - {resp.text[:200]}")
        else:
            attempts.append(f"{label}: HTTP {resp.status_code} - {resp.text[:200]}")

    raise PanelError("اتصال به پنل با هیچ‌کدوم از کلیدها موفق نبود:\n" + "\n".join(attempts))

def panel_sync(config, key):
    url = f"{PANEL_BASE}/{PANEL_API_ROUTE}/api/sync"
    resp = requests.post(url, headers={"Authorization": f"Bearer {key}"}, json={"key": key, "config": config}, timeout=15)

    if resp.status_code != 200:
        raise PanelError(f"ذخیره کانفیگ روی پنل ناموفق بود - HTTP {resp.status_code} - {resp.text[:200]}")

    data = resp.json()
    if not data.get("success"):
        raise PanelError(f"ذخیره کانفیگ روی پنل ناموفق بود - {resp.text[:200]}")
    return data.get("newRoute", config.get("apiRoute", PANEL_API_ROUTE))

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

    links = []
    for name in new_names:
        links.append(f"{PANEL_BASE}/{new_route}?sub={name}")

    return links

# ================= CALLBACK FORCED JOIN CHECK =================
@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join_callback(call):
    if is_user_joined(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ عضویت شما تایید شد!", show_alert=True)
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "به بات کانفیگ فرا زمین خوش آمدید", reply_markup=reply_keyboard)
    else:
        bot.answer_callback_query(call.id, "❌ شما هنوز در کانال عضو نشده‌اید!", show_alert=True)

# ================= START =================
@bot.message_handler(commands=['start'])
@main_guard
def start(message):
    cursor.execute("INSERT OR IGNORE INTO users(user_id, username) VALUES (?,?)",
                   (message.from_user.id, message.from_user.username))
    conn.commit()

    bot.reply_to(message, "به بات کانفیگ فرا زمین خوش آمدید", reply_markup=reply_keyboard)

# ================= ADVANCED ADMIN PANEL =================
def get_admin_keyboard():
    status_icon = "🟢 روشن" if is_bot_active() else "🔴 خاموش (تعمیرات)"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📊 آمار جامع", callback_data="admin_stats"),
        InlineKeyboardButton(f"وضعیت ربات: {status_icon}", callback_data="admin_toggle_status"),
        InlineKeyboardButton("👤 مدیریت کاربر", callback_data="admin_manage_user"),
        InlineKeyboardButton("📢 تنظیم جوین اجباری", callback_data="admin_set_channel"),
        InlineKeyboardButton("🏷 تغییر قیمت پلن‌ها", callback_data="admin_change_prices"),
        InlineKeyboardButton("➕ شارژ سریع", callback_data="admin_charge_user"),
        InlineKeyboardButton("✉️ ارسال همگانی", callback_data="admin_broadcast"),
        InlineKeyboardButton("💾 پشتیبان‌گیری دیتابیس", callback_data="admin_backup_db"),
        InlineKeyboardButton("❌ بستن پنل", callback_data="admin_close")
    )
    return markup

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        return
    bot.reply_to(
        message,
        "⚙️ **پنل مدیریت پیشرفته ربات**\nیک گزینه را انتخاب کنید:",
        reply_markup=get_admin_keyboard(),
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_") and call.from_user.id == ADMIN_ID)
def admin_callbacks(call):
    action = call.data

    if action == "admin_close":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id, "پنل بسته شد")
        return

    elif action == "admin_toggle_status":
        curr = is_bot_active()
        set_setting("bot_status", "off" if curr else "active")
        bot.answer_callback_query(call.id, "وضعیت ربات تغییر کرد", show_alert=True)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_admin_keyboard())

    elif action == "admin_stats":
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        cursor.execute("SELECT SUM(balance) FROM users")
        total_balance = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COUNT(*) FROM users WHERE trial_used = 1")
        total_trials = cursor.fetchone()[0]

        msg = f"""📊 **آمار جامع سیستم:**

👥 تعداد کاربران: `{total_users}` نفر
🎁 تست‌های گرفته‌شده: `{total_trials}` عدد
💰 کل موجودی کیف‌پول‌ها: `{total_balance:,}` تومان
📢 کانال قفل: `{get_setting('force_channel_id', 'ست نشده')}`"""
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, msg, parse_mode="Markdown")

    elif action == "admin_manage_user":
        bot.send_message(call.message.chat.id, "🔍 لطفاً **آیدی عددی** کاربر مورد نظر را بفرستید:")
        user_steps[ADMIN_ID] = "awaiting_search_user"

    elif action == "admin_set_channel":
        msg = bot.send_message(
            call.message.chat.id,
            "📢 **تنظیم کانال جوین اجباری:**\n\n"
            "فرمت ارسال:\n`@channel_username https://t.me/channel_link`\n\n"
            "💡 برای غیرفعال‌سازی عدد `0` را بفرستید.",
            parse_mode="Markdown"
        )
        user_steps[ADMIN_ID] = "awaiting_channel_info"

    elif action == "admin_change_prices":
        plans = get_current_plans()
        msg = "🏷 **تغییر قیمت پلن‌ها:**\n\nقیمت‌های فعلی:\n"
        for k, v in plans.items():
            msg += f"• {v['title']} (`{k}`): {v['price']:,} تومان\n"
        msg += "\nلطفاً کلید پلن و قیمت جدید را بفرستید.\nمثال: `single 65000`"
        bot.send_message(call.message.chat.id, msg, parse_mode="Markdown")
        user_steps[ADMIN_ID] = "awaiting_price_change"

    elif action == "admin_charge_user":
        bot.send_message(call.message.chat.id, "➕ **شارژ حساب کاربر:**\nفرمت: `آیدی_عددی مبلغ` (مثال: `123456 50000`)", parse_mode="Markdown")
        user_steps[ADMIN_ID] = "awaiting_charge_info"

    elif action == "admin_broadcast":
        bot.send_message(call.message.chat.id, "✉️ متن پیام همگانی خود را ارسال کنید:")
        user_steps[ADMIN_ID] = "awaiting_broadcast_msg"

    elif action == "admin_backup_db":
        try:
            with open("bot.db", "rb") as doc:
                bot.send_document(call.message.chat.id, doc, caption="💾 فایل دیتابیس پشتیبان")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ خطا در ساخت پشتیبان: {e}")

# ================= ADMIN STEPS HANDLER =================
@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and ADMIN_ID in user_steps)
def handle_admin_steps(message):
    step = user_steps.get(ADMIN_ID)

    if step == "awaiting_search_user":
        try:
            uid = int(message.text.strip())
            cursor.execute("SELECT user_id, username, balance, trial_used, config FROM users WHERE user_id=?", (uid,))
            user = cursor.fetchone()
            if not user:
                bot.reply_to(message, "❌ کاربری با این آیدی پیدا نشد.")
            else:
                msg = f"""👤 **اطلاعات کاربر:**
🆔 آیدی عددی: `{user[0]}`
نام کاربری: @{user[1] or 'ندارد'}
💰 موجودی: `{user[2]:,}` تومان
🎁 تست رایگان: {'استفاده شده' if user[3] else 'استفاده نشده'}
🔑 آخرین لینک کانفیگ:\n`{user[4] or 'هیچ'}`"""
                bot.reply_to(message, msg, parse_mode="Markdown")
        except ValueError:
            bot.reply_to(message, "❌ آیدی باید عدد باشد.")
        del user_steps[ADMIN_ID]

    elif step == "awaiting_price_change":
        try:
            parts = message.text.split()
            key = parts[0].strip()
            new_p = int(parts[1].strip())
            if key in DEFAULT_PLANS:
                set_setting(f"price_{key}", new_p)
                bot.reply_to(message, f"✅ قیمت پلن `{key}` به {new_p:,} تومان تغییر کرد.", parse_mode="Markdown")
            else:
                bot.reply_to(message, "❌ کلید پلن نامعتبر است! (کلیدهای معتبر: `single`, `double`, `unlimited`)")
        except Exception:
            bot.reply_to(message, "❌ فرمت نادرست! مثال: `single 65000`", parse_mode="Markdown")
        del user_steps[ADMIN_ID]

    elif step == "awaiting_channel_info":
        if message.text.strip() == "0":
            set_setting("force_channel_id", "NONE")
            bot.reply_to(message, "✅ جوین اجباری با موفقیت غیرفعال شد.")
        else:
            try:
                parts = message.text.split()
                ch_id = parts[0].strip()
                ch_link = parts[1].strip() if len(parts) > 1 else f"https://t.me/{ch_id.replace('@','')}"
                set_setting("force_channel_id", ch_id)
                set_setting("force_channel_link", ch_link)
                bot.reply_to(message, f"✅ کانال ست شد:\n🆔: {ch_id}\n🔗: {ch_link}")
            except Exception:
                bot.reply_to(message, "❌ فرمت اشتباه است!")
        del user_steps[ADMIN_ID]

    elif step == "awaiting_charge_info":
        try:
            target_id, amount = map(int, message.text.split())
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_id))
            conn.commit()
            bot.reply_to(message, f"✅ حساب {target_id} به مبلغ {amount:,} شارژ شد.")
            try: bot.send_message(target_id, f"✅ حساب شما مبلغ {amount:,} تومان شارژ شد.")
            except: pass
        except Exception:
            bot.reply_to(message, "❌ فرمت ورودی اشتباه است!")
        del user_steps[ADMIN_ID]

    elif step == "awaiting_broadcast_msg":
        cursor.execute("SELECT user_id FROM users")
        users = cursor.fetchall()
        success, failed = 0, 0
        bot.reply_to(message, "⏳ در حال ارسال همگانی...")
        for u in users:
            try:
                bot.send_message(u[0], message.text)
                success += 1
                time.sleep(0.04)
            except:
                failed += 1
        bot.send_message(ADMIN_ID, f"📢 ارسال انجام شد.\n✅ موفق: {success}\n❌ ناموفق: {failed}")
        del user_steps[ADMIN_ID]

# ================= BUY MENU =================
@bot.message_handler(func=lambda m: m.text == "خرید کانفیگ🛒")
@main_guard
def buy_menu(message):
    keyboard = InlineKeyboardMarkup()
    plans = get_current_plans()
    for key, plan in plans.items():
        keyboard.add(
            InlineKeyboardButton(
                f"{plan['title']} - {plan['price']:,} تومان",
                callback_data=f"buy_{key}"
            )
        )
    bot.reply_to(message, "پلن مورد نظر را انتخاب کنید (حجم تمامی کانفیگ‌ها نامحدود است):", reply_markup=keyboard)

@bot.message_handler(func=lambda m: m.text == "پشتیبانی👇")
@main_guard
def support(message):
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("💬 ارتباط با پشتیبانی", url="https://t.me/valaorp"))
    bot.reply_to(message, "برای ارتباط با پشتیبانی روی دکمه زیر بزنید:", reply_markup=keyboard)

# ================= BUY CHECK =================
@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def buy_config(call):
    user_id = call.from_user.id
    
    if not is_user_joined(user_id):
        bot.answer_callback_query(call.id, "❌ ابتدا باید در کانال ما عضو شوید!", show_alert=True)
        send_force_join_message(call.message.chat.id)
        return

    plan_key = call.data.split("_", 1)[1]
    plans = get_current_plans()
    plan = plans.get(plan_key)
    
    if plan is None:
        bot.answer_callback_query(call.id, "پلن نامعتبر است")
        return

    price = plan["price"]

    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    user = cursor.fetchone()

    if user is None:
        bot.reply_to(call.message, "حساب شما پیدا نشد")
        return

    balance = user[0]

    if balance < price:
        bot.reply_to(
            call.message,
            f"❌ موجودی کافی نیست\n\nقیمت: {price:,} تومان\nموجودی شما: {balance:,} تومان"
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
            f"❌ خطا در ساخت کانفیگ از پنل. مبلغی کم نشد.\n\nخطا: {e}",
            call.message.chat.id,
            processing_msg.message_id
        )
        return

    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (price, user_id))
    conn.commit()

    config_text = "\n".join(links)
    cursor.execute("UPDATE users SET config = ? WHERE user_id = ?", (config_text, user_id))
    conn.commit()

    bot.edit_message_text(
        f"✅ خرید موفق بود\n\n💰 مبلغ: {price:,} تومان\n\n🔑 لینک اشتراک شما:\n{config_text}",
        call.message.chat.id,
        processing_msg.message_id
    )

# ================= FREE TRIAL =================
@bot.message_handler(func=lambda m: m.text == "تست رایگان🕧")
@main_guard
def free_trial(message):
    user_id = message.from_user.id
    cursor.execute("SELECT trial_used FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()

    if row is None:
        cursor.execute("INSERT OR IGNORE INTO users(user_id, username) VALUES (?,?)", (user_id, message.from_user.username))
        conn.commit()
        trial_used = 0
    else:
        trial_used = row[0]

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
            f"❌ خطا در ساخت کانفیگ تست.\n\nخطا: {e}",
            message.chat.id,
            processing_msg.message_id
        )
        return

    cursor.execute("UPDATE users SET trial_used = 1 WHERE user_id = ?", (user_id,))
    conn.commit()

    config_text = "\n".join(links)
    bot.edit_message_text(
        f"✅ کانفیگ تست ساخته شد\n\n📦 حجم: {int(TRIAL_TRAFFIC_GB * 1000)} مگابایت\n🔑 لینک:\n{config_text}",
        message.chat.id,
        processing_msg.message_id
    )

# ================= CARD TO CARD & MY INFO =================
@bot.message_handler(func=lambda m: m.text == "کارت به کارت💲")
@main_guard
def card(message):
    bot.reply_to(
        message,
        "مبلغ را به شماره کارت زیر واریز کنید:\n\n8673 2559 1411 6362\nامیر والا شریف نسب\n\nبعد از پرداخت رسید را ارسال کنید."
    )

@bot.message_handler(func=lambda message: message.text == "اطلاعات من✨")
@main_guard
def my_info(message):
    user_id = message.from_user.id
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    balance = result[0] if result else 0

    bot.send_message(
        message.chat.id,
        f"👤 اطلاعات حساب شما\n\n🆔 شناسه: {user_id}\n💰 موجودی: {balance:,} تومان"
    )

# ================= ADMIN RECEIPT =================
@bot.message_handler(content_types=['photo'])
@main_guard
def receipt(message):
    bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
    bot.send_message(
        ADMIN_ID,
        f"رسید جدید از کاربر `{message.from_user.id}`:\nدستور شارژ سریع:\n`/charge {message.from_user.id} 60000`",
        parse_mode="Markdown"
    )
    bot.reply_to(message, "✅ رسید ارسال شد، پس از تایید ادمین موجودی شما شارژ می‌شود.")

# ================= QUICK ADMIN CHARGE COMMAND =================
@bot.message_handler(func=lambda m: m.text and m.text.startswith("/charge") and m.from_user.id == ADMIN_ID)
def admin_charge(message):
    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "فرمت: /charge <user_id> <amount>")
        return

    try:
        target_id, amount = int(parts[1]), int(parts[2])
    except ValueError:
        bot.reply_to(message, "مقادیر باید عدد باشند.")
        return

    cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (target_id,))
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_id))
    conn.commit()

    bot.reply_to(message, f"✅ حساب {target_id} به‌مبلغ {amount:,} شارژ شد.")
    try: bot.send_message(target_id, f"✅ حساب شما مبلغ {amount:,} تومان شارژ شد.")
    except Exception: pass

if __name__ == "__main__":
    bot.infinity_polling()

import telebot
import sqlite3
import requests
import uuid
import time
import os
import csv
import io

from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup
)


# ================= CONFIG =================
# ⚠️ توجه امنیتی: توکن و کلیدها رو فقط از env بخونید، مقدار پیش‌فرض hardcoded نذارید.
# اگه این کد جایی public شده، همین الان توکن بات و کلیدهای پنل رو عوض کنید.

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8921489424:AAFCrTyaD6S-Zd2sFav_7-WBH9KQDfB7Cmk")

PANEL_BASE = os.environ.get("PANEL_BASE", "https://little-waterfall-27fa.berbrtokamma.workers.dev")
PANEL_API_ROUTE = os.environ.get("PANEL_API_ROUTE", "sync")

PANEL_API_KEY = os.environ.get("PANEL_API_KEY", "nahan_mrlmsp7c_7lg9rlf0")
PANEL_MASTER_KEY_FALLBACK = os.environ.get("PANEL_MASTER_KEY", "vala1392")

PANEL_AUTH_HEADERS = {"Authorization": f"Bearer {PANEL_API_KEY}"}

ADMIN_ID = 6059940165

# ================= FORCE JOIN =================
FORCE_JOIN_ENABLED = True
FORCE_JOIN_CHANNEL = os.environ.get("FORCE_JOIN_CHANNEL", "@configfarazamin")

bot = telebot.TeleBot(BOT_TOKEN)


# ================= DATABASE =================

conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    balance INTEGER DEFAULT 0,
    config TEXT,
    trial_used INTEGER DEFAULT 0
)
""")
conn.commit()

try:
    cursor.execute("ALTER TABLE users ADD COLUMN trial_used INTEGER DEFAULT 0")
    conn.commit()
except sqlite3.OperationalError:
    pass

# --- جدول جدید: تاریخچه‌ی کانفیگ‌های گرفته‌شده توسط هر کاربر ---
cursor.execute("""
CREATE TABLE IF NOT EXISTS configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    plan_title TEXT,
    links TEXT,
    price INTEGER DEFAULT 0,
    created_at INTEGER
)
""")
conn.commit()


def save_config_history(user_id, plan_title, links, price=0):
    """هر بار که کانفیگی (خرید یا تست) ساخته میشه، یه رکورد توی تاریخچه ذخیره میشه."""
    cursor.execute(
        "INSERT INTO configs (user_id, plan_title, links, price, created_at) VALUES (?,?,?,?,?)",
        (user_id, plan_title, links, price, int(time.time()))
    )
    conn.commit()


# --- ستون مسدودسازی کاربر ---
try:
    cursor.execute("ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0")
    conn.commit()
except sqlite3.OperationalError:
    pass

# --- زمان عضویت (برای آمار کاربر جدید) ---
try:
    cursor.execute("ALTER TABLE users ADD COLUMN joined_at INTEGER")
    conn.commit()
except sqlite3.OperationalError:
    pass


def is_banned(user_id):
    cursor.execute("SELECT banned FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return bool(row and row[0])


def set_banned(user_id, value):
    cursor.execute("UPDATE users SET banned=? WHERE user_id=?", (1 if value else 0, user_id))
    conn.commit()


# ================= PLANS =================

PLANS = {
    "single": {"title": "یک کاربره", "price": 60000, "profiles": 1, "days": 30, "conn_limit": 1},
    "double": {"title": "دو کاربره", "price": 70000, "profiles": 1, "days": 30, "conn_limit": 2},
    "unlimited": {"title": "نامحدود", "price": 90000, "profiles": 1, "days": 30, "conn_limit": None},
}

# ================= TRIAL =================

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
    "📜 کانفیگ‌های من",
    "پشتیبانی👇"
)


# ================= FORCE JOIN HELPERS =================

def is_member(user_id):
    if not FORCE_JOIN_ENABLED:
        return True
    try:
        member = bot.get_chat_member(FORCE_JOIN_CHANNEL, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False


def send_join_prompt(chat_id):
    keyboard = InlineKeyboardMarkup()
    channel_url = f"https://t.me/{FORCE_JOIN_CHANNEL.lstrip('@')}"
    keyboard.add(InlineKeyboardButton("📢 عضویت در کانال", url=channel_url))
    keyboard.add(InlineKeyboardButton("✅ عضو شدم", callback_data="check_join"))
    bot.send_message(
        chat_id,
        "برای استفاده از بات، ابتدا باید عضو کانال ما بشید. بعد از عضویت روی «عضو شدم» بزنید.",
        reply_markup=keyboard
    )


def require_join(message):
    """چک ترکیبی: اگه کاربر مسدود باشه یا عضو کانال نباشه، ادامه‌ی کار متوقف میشه."""
    user_id = message.from_user.id

    if is_banned(user_id):
        bot.reply_to(message, "⛔️ حساب شما توسط ادمین مسدود شده است. برای پیگیری با پشتیبانی تماس بگیرید.")
        return False

    if is_member(user_id):
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
    keys_to_try = [("Panel API Key", PANEL_API_KEY)]
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

    raise PanelError(
        "اتصال به پنل با هیچ‌کدوم از کلیدها موفق نبود:\n" + "\n".join(attempts)
    )


def panel_sync(config, key):
    url = f"{PANEL_BASE}/{PANEL_API_ROUTE}/api/sync"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}"},
        json={"key": key, "config": config},
        timeout=15
    )

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


# ================= START =================

@bot.message_handler(commands=['start'])
def start(message):

    cursor.execute(
        "INSERT OR IGNORE INTO users(user_id, username) VALUES (?,?)",
        (message.from_user.id, message.from_user.username)
    )
    conn.commit()

    cursor.execute(
        "UPDATE users SET joined_at = COALESCE(joined_at, ?), username = ? WHERE user_id = ?",
        (int(time.time()), message.from_user.username, message.from_user.id)
    )
    conn.commit()

    if is_banned(message.from_user.id):
        bot.reply_to(message, "⛔️ حساب شما توسط ادمین مسدود شده است. برای پیگیری با پشتیبانی تماس بگیرید.")
        return

    bot.reply_to(
        message,
        "به بات کانفیگ فرا زمین خوش آمدید",
        reply_markup=reply_keyboard
    )

    if not is_member(message.from_user.id):
        send_join_prompt(message.chat.id)


# ================= BUY MENU =================

@bot.message_handler(func=lambda m: m.text == "خرید کانفیگ🛒")
def buy_menu(message):

    if not require_join(message):
        return

    keyboard = InlineKeyboardMarkup()
    for key, plan in PLANS.items():
        keyboard.add(
            InlineKeyboardButton(
                f"{plan['title']} - {plan['price']:,} تومان",
                callback_data=f"buy_{key}"
            )
        )

    bot.reply_to(
        message,
        "پلن مورد نظر را انتخاب کنید، حجم همه کانفیگ‌ها نامحدود هست",
        reply_markup=keyboard
    )


@bot.message_handler(func=lambda m: m.text == "پشتیبانی👇")
def support(message):
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("💬 ارتباط با پشتیبانی", url="https://t.me/valaorp"))
    bot.reply_to(message, "برای ارتباط با پشتیبانی روی دکمه زیر بزنید:", reply_markup=keyboard)


# ================= BUY CHECK =================

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def buy_config(call):

    user_id = call.from_user.id

    if not is_member(user_id):
        bot.answer_callback_query(call.id, "ابتدا باید عضو کانال بشید", show_alert=True)
        send_join_prompt(call.message.chat.id)
        return

    plan_key = call.data.split("_", 1)[1]
    plan = PLANS.get(plan_key)
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
            f"❌ خطا در ساخت کانفیگ از پنل. مبلغی از حساب شما کم نشد.\n\nجزئیات خطا: {e}",
            call.message.chat.id,
            processing_msg.message_id
        )
        return

    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (price, user_id))
    conn.commit()

    config_text = "\n".join(links)

    cursor.execute("UPDATE users SET config = ? WHERE user_id = ?", (config_text, user_id))
    conn.commit()

    # ذخیره در تاریخچه
    save_config_history(user_id, plan["title"], config_text, price)

    bot.edit_message_text(
        f"""✅ خرید موفق بود

💰 مبلغ:
{price:,} تومان

🔑 لینک(های) اشتراک شما:
{config_text}

این لینک رو داخل اپلیکیشن کلاینت (v2rayN, Hiddify, Shadowrocket, Nekoray و ...) به‌عنوان Subscription وارد کن.""",
        call.message.chat.id,
        processing_msg.message_id
    )


# ================= FREE TRIAL =================

@bot.message_handler(func=lambda m: m.text == "تست رایگان🕧")
def free_trial(message):

    if not require_join(message):
        return

    user_id = message.from_user.id

    cursor.execute("SELECT trial_used FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()

    if row is None:
        cursor.execute(
            "INSERT OR IGNORE INTO users(user_id, username) VALUES (?,?)",
            (user_id, message.from_user.username)
        )
        conn.commit()
        trial_used = 0
    else:
        trial_used = row[0]

    if trial_used:
        bot.reply_to(message, "❌ شما قبلاً از تست رایگان استفاده کرده‌اید. برای خرید از منوی «خرید کانفیگ» استفاده کنید.")
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

    # ذخیره در تاریخچه
    save_config_history(user_id, "تست رایگان", config_text, 0)

    bot.edit_message_text(
        f"""✅ کانفیگ تست شما ساخته شد

📦 حجم: {int(TRIAL_TRAFFIC_GB * 1000)} مگابایت
⏳ اعتبار: {TRIAL_DAYS} روز

🔑 لینک اشتراک:
{config_text}

این لینک رو داخل اپلیکیشن کلاینت (v2rayN, Hiddify, Shadowrocket, Nekoray و ...) به‌عنوان Subscription وارد کن.""",
        message.chat.id,
        processing_msg.message_id
    )


# ================= CARD TO CARD =================

@bot.message_handler(func=lambda m: m.text == "کارت به کارت💲")
def card(message):

    bot.reply_to(
        message,
        """
مبلغ را به شماره کارت زیر واریز کنید:

8673 2559 1411 6362

امیر والا شریف نسب

بعد از پرداخت رسید را ارسال کنید. ادمین ما چک میکنه و پول به حساب شما میاد
"""
    )


@bot.message_handler(func=lambda message: message.text == "اطلاعات من✨")
def my_info(message):

    if not require_join(message):
        return

    user_id = message.from_user.id

    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()

    balance = result[0] if result else 0

    bot.send_message(
        message.chat.id,
        f"""👤 اطلاعات حساب شما

🆔 شناسه: {user_id}

💰 موجودی کیف پول: {balance:,} تومان"""
    )


# ================= تاریخچه کانفیگ‌ها (جدید) =================

CONFIGS_PER_PAGE = 5


def build_history_page(user_id, page):
    """صفحه‌ی مشخصی از تاریخچه‌ی کانفیگ‌های کاربر رو برمی‌گردونه: (متن, تعداد کل)."""
    cursor.execute("SELECT COUNT(*) FROM configs WHERE user_id=?", (user_id,))
    total = cursor.fetchone()[0]

    offset = page * CONFIGS_PER_PAGE
    cursor.execute(
        """SELECT plan_title, links, price, created_at
           FROM configs WHERE user_id=?
           ORDER BY created_at DESC
           LIMIT ? OFFSET ?""",
        (user_id, CONFIGS_PER_PAGE, offset)
    )
    rows = cursor.fetchall()

    if not rows:
        return "شما تا الان هیچ کانفیگی دریافت نکردید.", total

    lines = [f"📜 کانفیگ‌های شما (صفحه {page+1}):\n"]
    for plan_title, links, price, created_at in rows:
        date_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(created_at))
        price_str = f"{price:,} تومان" if price else "رایگان"
        lines.append(
            f"🔹 پلن: {plan_title}\n"
            f"🗓 تاریخ: {date_str}\n"
            f"💰 مبلغ: {price_str}\n"
            f"🔑 لینک:\n{links}\n"
        )

    return "\n".join(lines), total


def history_keyboard(user_id, page, total):
    keyboard = InlineKeyboardMarkup(row_width=2)
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"hist_{page-1}"))
    if (page + 1) * CONFIGS_PER_PAGE < total:
        buttons.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"hist_{page+1}"))
    if buttons:
        keyboard.add(*buttons)
    return keyboard


@bot.message_handler(func=lambda m: m.text == "📜 کانفیگ‌های من")
def config_history(message):

    if not require_join(message):
        return

    user_id = message.from_user.id
    text, total = build_history_page(user_id, page=0)
    keyboard = history_keyboard(user_id, 0, total)

    bot.reply_to(message, text, reply_markup=keyboard if total > CONFIGS_PER_PAGE else None)


@bot.callback_query_handler(func=lambda call: call.data.startswith("hist_"))
def config_history_page(call):
    user_id = call.from_user.id
    page = int(call.data.split("_", 1)[1])

    text, total = build_history_page(user_id, page)
    keyboard = history_keyboard(user_id, page, total)

    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard if total > CONFIGS_PER_PAGE else None
    )


# ================= ADMIN RECEIPT =================

@bot.message_handler(content_types=['photo'])
def receipt(message):

    bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)

    uid = message.from_user.id
    quick_amounts = [60000, 70000, 90000]
    keyboard = InlineKeyboardMarkup(row_width=3)
    keyboard.add(*[
        InlineKeyboardButton(f"{amt:,}", callback_data=f"qcharge_{uid}_{amt}")
        for amt in quick_amounts
    ])
    keyboard.add(InlineKeyboardButton("💬 مبلغ دلخواه", callback_data=f"qcharge_custom_{uid}"))

    bot.send_message(
        ADMIN_ID,
        f"""رسید جدید

نام:
{message.from_user.first_name}

آیدی:
{uid}

برای شارژ سریع یکی از دکمه‌های زیر رو بزنید، یا برای مبلغ دلخواه دستور زیر رو بفرستید:
/charge {uid} <مبلغ>""",
        reply_markup=keyboard
    )

    bot.reply_to(message, "✅ رسید ارسال شد، پس از تایید ادمین موجودی شما شارژ می‌شود.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("qcharge_"))
def quick_charge_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔️ دسترسی ندارید", show_alert=True)
        return

    parts = call.data.split("_")

    if parts[1] == "custom":
        target_id = int(parts[2])
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, f"مبلغ شارژ برای کاربر {target_id} رو وارد کنید:")
        bot.register_next_step_handler(msg, lambda m: _process_custom_charge(m, target_id))
        return

    target_id = int(parts[1])
    amount = int(parts[2])

    cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (target_id,))
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_id))
    conn.commit()

    cursor.execute("SELECT balance FROM users WHERE user_id=?", (target_id,))
    new_balance = cursor.fetchone()[0]

    bot.answer_callback_query(call.id, "✅ شارژ شد")
    bot.send_message(
        call.message.chat.id,
        f"✅ حساب {target_id} به مبلغ {amount:,} تومان شارژ شد.\nموجودی جدید: {new_balance:,} تومان"
    )

    try:
        bot.send_message(target_id, f"✅ حساب شما به مبلغ {amount:,} تومان شارژ شد.\nموجودی جدید: {new_balance:,} تومان")
    except Exception:
        pass


def _process_custom_charge(message, target_id):
    if message.from_user.id != ADMIN_ID:
        return

    try:
        amount = int(message.text.strip())
    except ValueError:
        bot.reply_to(message, "مبلغ باید عدد باشه")
        return

    cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (target_id,))
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_id))
    conn.commit()

    cursor.execute("SELECT balance FROM users WHERE user_id=?", (target_id,))
    new_balance = cursor.fetchone()[0]

    bot.reply_to(message, f"✅ حساب {target_id} به مبلغ {amount:,} تومان شارژ شد.\nموجودی جدید: {new_balance:,} تومان")

    try:
        bot.send_message(target_id, f"✅ حساب شما به مبلغ {amount:,} تومان شارژ شد.\nموجودی جدید: {new_balance:,} تومان")
    except Exception:
        pass


# ================= ADMIN CHARGE COMMAND =================

@bot.message_handler(func=lambda m: m.text and m.text.startswith("/charge") and m.from_user.id == ADMIN_ID)
def admin_charge(message):

    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "فرمت درست: /charge <user_id> <amount>")
        return

    try:
        target_id = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        bot.reply_to(message, "user_id و amount باید عدد باشند")
        return

    cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (target_id,))
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_id))
    conn.commit()

    cursor.execute("SELECT balance FROM users WHERE user_id=?", (target_id,))
    new_balance = cursor.fetchone()[0]

    bot.reply_to(message, f"✅ حساب {target_id} به مبلغ {amount:,} تومان شارژ شد.\nموجودی جدید: {new_balance:,} تومان")

    try:
        bot.send_message(target_id, f"✅ حساب شما به مبلغ {amount:,} تومان شارژ شد.\nموجودی جدید: {new_balance:,} تومان")
    except Exception:
        pass


# ================= ADMIN PANEL DIAGNOSTIC =================

@bot.message_handler(func=lambda m: m.text and m.text.startswith("/testpanel") and m.from_user.id == ADMIN_ID)
def admin_test_panel(message):

    bot.reply_to(message, "⏳ در حال تست اتصال به پنل...")

    url = f"{PANEL_BASE}/{PANEL_API_ROUTE}/api/auth"

    test_cases = [
        ("Panel API Key - فقط هدر", PANEL_API_KEY, True, False),
        ("Panel API Key - فقط بدنه", PANEL_API_KEY, False, True),
        ("Panel API Key - هر دو", PANEL_API_KEY, True, True),
    ]

    if PANEL_MASTER_KEY_FALLBACK:
        test_cases += [
            ("Master Key - فقط هدر", PANEL_MASTER_KEY_FALLBACK, True, False),
            ("Master Key - فقط بدنه", PANEL_MASTER_KEY_FALLBACK, False, True),
            ("Master Key - هر دو", PANEL_MASTER_KEY_FALLBACK, True, True),
        ]

    report_lines = [f"🔍 نتیجه تست اتصال به پنل\nURL: {url}\n"]

    for label, key, use_header, use_body in test_cases:
        headers = {}
        body = {}
        if use_header:
            headers["Authorization"] = f"Bearer {key}"
        if use_body:
            body["key"] = key

        try:
            resp = requests.post(url, headers=headers, json=body, timeout=15)
            status = resp.status_code
            snippet = resp.text[:200].replace("\n", " ")
            if status == 200:
                try:
                    data = resp.json()
                    mark = "✅" if data.get("success", False) else "⚠️"
                except Exception:
                    mark = "⚠️"
            else:
                mark = "❌"
            report_lines.append(f"{mark} {label}\nStatus: {status}\nPasokh: {snippet}\n")
        except Exception as e:
            report_lines.append(f"❌ {label}\nError: {e}\n")

    full_report = "\n".join(report_lines)
    for i in range(0, len(full_report), 3500):
        bot.send_message(message.chat.id, full_report[i:i+3500])


# ================= ADMIN: DUMP USER JSON =================

@bot.message_handler(func=lambda m: m.text and m.text.startswith("/dumpuser") and m.from_user.id == ADMIN_ID)
def admin_dump_user(message):

    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        bot.reply_to(message, "فرمت درست: /dumpuser <اسم دقیق کاربر>")
        return

    target_name = parts[1].strip()
    bot.reply_to(message, "⏳ در حال گرفتن اطلاعات از پنل...")

    try:
        config, _ = panel_auth()
    except Exception as e:
        bot.reply_to(message, f"❌ خطا در اتصال به پنل: {e}")
        return

    users = config.get("users") or []
    matches = [u for u in users if u.get("name") == target_name]

    if not matches:
        names = ", ".join([str(u.get("name")) for u in users][:30])
        bot.reply_to(message, f"❌ کاربری با اسم '{target_name}' پیدا نشد.\n\nاسم‌های موجود (حداکثر ۳۰ تا):\n{names}")
        return

    import json as _json
    dump = _json.dumps(matches[0], ensure_ascii=False, indent=2)

    for i in range(0, len(dump), 3500):
        bot.send_message(message.chat.id, f"```\n{dump[i:i+3500]}\n```", parse_mode="Markdown")


# ================= ADMIN PANEL پیشرفته (مدیریت) =================

ADMIN_USERS_PER_PAGE = 8

# نگهداری موقت پیام‌های در انتظار تأیید برای پیام همگانی: {admin_chat_id: (from_chat_id, message_id)}
_pending_broadcasts = {}


def admin_only(func):
    def wrapper(*args, **kwargs):
        obj = args[0]
        uid = obj.from_user.id
        if uid != ADMIN_ID:
            if hasattr(obj, "id") and hasattr(obj, "message"):  # callback query
                bot.answer_callback_query(obj.id, "⛔️ دسترسی ندارید", show_alert=True)
            return
        return func(*args, **kwargs)
    return wrapper


def main_admin_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📊 آمار پیشرفته", callback_data="admin_stats"),
        InlineKeyboardButton("👥 مدیریت کاربران", callback_data="admin_users_0"),
    )
    keyboard.add(
        InlineKeyboardButton("🔍 جستجوی کاربر", callback_data="admin_search"),
        InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast"),
    )
    keyboard.add(
        InlineKeyboardButton("📤 خروجی CSV", callback_data="admin_export"),
    )
    return keyboard


@bot.message_handler(commands=['admin'])
@admin_only
def admin_panel(message):
    bot.send_message(message.chat.id, "🛠 پنل مدیریت بات", reply_markup=main_admin_keyboard())


# --------- آمار پیشرفته ---------

def build_stats_text():
    now = int(time.time())
    today_start = now - (now % 86400)
    week_start = now - 7 * 86400
    month_start = now - 30 * 86400

    cursor.execute("SELECT COUNT(*), COALESCE(SUM(balance),0) FROM users")
    total_users, total_balance = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) FROM users WHERE trial_used=1")
    trial_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users WHERE banned=1")
    banned_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users WHERE joined_at >= ?", (today_start,))
    new_today = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE joined_at >= ?", (week_start,))
    new_week = cursor.fetchone()[0]

    def revenue_since(ts):
        cursor.execute("SELECT COALESCE(SUM(price),0) FROM configs WHERE created_at >= ? AND price > 0", (ts,))
        return cursor.fetchone()[0]

    rev_today = revenue_since(today_start)
    rev_week = revenue_since(week_start)
    rev_month = revenue_since(month_start)
    cursor.execute("SELECT COALESCE(SUM(price),0) FROM configs WHERE price > 0")
    rev_total = cursor.fetchone()[0]

    cursor.execute(
        "SELECT plan_title, COUNT(*), COALESCE(SUM(price),0) FROM configs GROUP BY plan_title ORDER BY COUNT(*) DESC"
    )
    plan_rows = cursor.fetchall()

    cursor.execute(
        """SELECT user_id, COALESCE(SUM(price),0) AS total_spent FROM configs
           WHERE price > 0 GROUP BY user_id ORDER BY total_spent DESC LIMIT 5"""
    )
    top_buyers = cursor.fetchall()

    lines = ["📊 آمار پیشرفته بات\n"]
    lines.append(f"👥 کل کاربران: {total_users:,}  (جدید امروز: {new_today:,} | جدید این هفته: {new_week:,})")
    lines.append(f"🚫 مسدود شده: {banned_count:,}")
    lines.append(f"🧪 استفاده از تست رایگان: {trial_count:,}")
    lines.append(f"💰 مجموع موجودی کیف پول‌ها: {total_balance:,} تومان\n")
    lines.append("💵 درآمد:")
    lines.append(f"  امروز: {rev_today:,} تومان")
    lines.append(f"  ۷ روز اخیر: {rev_week:,} تومان")
    lines.append(f"  ۳۰ روز اخیر: {rev_month:,} تومان")
    lines.append(f"  کل: {rev_total:,} تومان\n")

    if plan_rows:
        lines.append("📦 تفکیک بر اساس پلن:")
        for title, count, rev in plan_rows:
            lines.append(f"  {title}: {count:,} بار — {rev:,} تومان")
        lines.append("")

    if top_buyers:
        lines.append("🏆 ۵ کاربر پرخرج برتر:")
        for uid, spent in top_buyers:
            lines.append(f"  {uid} — {spent:,} تومان")

    return "\n".join(lines)


# --------- مدیریت کاربران (لیست + جزئیات) ---------

def build_users_list(page):
    cursor.execute("SELECT COUNT(*) FROM users")
    total = cursor.fetchone()[0]

    offset = page * ADMIN_USERS_PER_PAGE
    cursor.execute(
        "SELECT user_id, username, balance, banned FROM users ORDER BY user_id DESC LIMIT ? OFFSET ?",
        (ADMIN_USERS_PER_PAGE, offset)
    )
    rows = cursor.fetchall()
    return rows, total


def users_list_keyboard(rows, page, total):
    keyboard = InlineKeyboardMarkup(row_width=1)
    for uid, username, balance, banned in rows:
        label = f"{'🚫 ' if banned else ''}{uid} — @{username if username else '-'} — {balance:,} ت"
        keyboard.add(InlineKeyboardButton(label, callback_data=f"admin_user_{uid}"))

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"admin_users_{page-1}"))
    if (page + 1) * ADMIN_USERS_PER_PAGE < total:
        nav.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"admin_users_{page+1}"))
    if nav:
        keyboard.row(*nav)

    keyboard.add(InlineKeyboardButton("🔙 بازگشت به منو", callback_data="admin_back"))
    return keyboard


def build_user_detail(target_id):
    cursor.execute(
        "SELECT username, balance, trial_used, banned, joined_at FROM users WHERE user_id=?",
        (target_id,)
    )
    row = cursor.fetchone()
    if not row:
        return None, None

    username, balance, trial_used, banned, joined_at = row

    cursor.execute(
        "SELECT COUNT(*), COALESCE(SUM(price),0) FROM configs WHERE user_id=? AND price>0",
        (target_id,)
    )
    purchase_count, total_spent = cursor.fetchone()

    cursor.execute(
        "SELECT plan_title, created_at FROM configs WHERE user_id=? ORDER BY created_at DESC LIMIT 3",
        (target_id,)
    )
    recent = cursor.fetchall()

    joined_str = time.strftime("%Y-%m-%d", time.localtime(joined_at)) if joined_at else "-"

    lines = [
        f"👤 کاربر {target_id}",
        f"یوزرنیم: @{username if username else '-'}",
        f"وضعیت: {'🚫 مسدود' if banned else '✅ فعال'}",
        f"تاریخ عضویت: {joined_str}",
        f"موجودی: {balance:,} تومان",
        f"تست رایگان استفاده شده: {'بله' if trial_used else 'خیر'}",
        f"تعداد خرید: {purchase_count:,} — مجموع: {total_spent:,} تومان",
    ]

    if recent:
        lines.append("\nآخرین کانفیگ‌ها:")
        for plan_title, created_at in recent:
            date_str = time.strftime("%Y-%m-%d", time.localtime(created_at))
            lines.append(f"  {plan_title} — {date_str}")

    return "\n".join(lines), banned


def user_detail_keyboard(target_id, banned):
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("➕ شارژ", callback_data=f"admin_user_addbal_{target_id}"),
        InlineKeyboardButton("➖ کسر", callback_data=f"admin_user_subbal_{target_id}"),
    )
    if banned:
        keyboard.add(InlineKeyboardButton("✅ رفع مسدودی", callback_data=f"admin_user_unban_{target_id}"))
    else:
        keyboard.add(InlineKeyboardButton("🚫 مسدود کردن", callback_data=f"admin_user_ban_{target_id}"))
    keyboard.add(InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="admin_users_0"))
    return keyboard


@bot.callback_query_handler(func=lambda call: call.data == "admin_back")
@admin_only
def admin_back(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text("🛠 پنل مدیریت بات", call.message.chat.id, call.message.message_id, reply_markup=main_admin_keyboard())


@bot.callback_query_handler(func=lambda call: call.data == "admin_stats")
@admin_only
def admin_stats_callback(call):
    bot.answer_callback_query(call.id)
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("🔙 بازگشت به منو", callback_data="admin_back"))
    bot.edit_message_text(build_stats_text(), call.message.chat.id, call.message.message_id, reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_users_"))
@admin_only
def admin_users_list_callback(call):
    page = int(call.data.split("_")[-1])
    rows, total = build_users_list(page)
    bot.answer_callback_query(call.id)

    if not rows:
        bot.edit_message_text("کاربری وجود نداره", call.message.chat.id, call.message.message_id)
        return

    text = f"👥 لیست کاربران (صفحه {page+1} از {(total - 1)//ADMIN_USERS_PER_PAGE + 1})\nروی هرکدوم بزنید تا جزئیات و امکانات مدیریتی رو ببینید:"
    bot.edit_message_text(
        text, call.message.chat.id, call.message.message_id,
        reply_markup=users_list_keyboard(rows, page, total)
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_user_") and call.data.split("_")[2].isdigit())
@admin_only
def admin_user_detail_callback(call):
    target_id = int(call.data.split("_")[2])
    text, banned = build_user_detail(target_id)
    bot.answer_callback_query(call.id)

    if text is None:
        bot.edit_message_text("کاربری با این آیدی پیدا نشد", call.message.chat.id, call.message.message_id)
        return

    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=user_detail_keyboard(target_id, banned))


@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_user_ban_"))
@admin_only
def admin_user_ban_callback(call):
    target_id = int(call.data.rsplit("_", 1)[1])
    set_banned(target_id, True)
    bot.answer_callback_query(call.id, "🚫 کاربر مسدود شد")
    text, banned = build_user_detail(target_id)
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=user_detail_keyboard(target_id, banned))
    try:
        bot.send_message(target_id, "⛔️ حساب شما توسط ادمین مسدود شد.")
    except Exception:
        pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_user_unban_"))
@admin_only
def admin_user_unban_callback(call):
    target_id = int(call.data.rsplit("_", 1)[1])
    set_banned(target_id, False)
    bot.answer_callback_query(call.id, "✅ رفع مسدودی شد")
    text, banned = build_user_detail(target_id)
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=user_detail_keyboard(target_id, banned))
    try:
        bot.send_message(target_id, "✅ حساب شما رفع مسدودی شد و می‌تونید دوباره از بات استفاده کنید.")
    except Exception:
        pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_user_addbal_"))
@admin_only
def admin_user_addbal_callback(call):
    target_id = int(call.data.rsplit("_", 1)[1])
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, f"مبلغ شارژ برای کاربر {target_id} رو وارد کنید:")
    bot.register_next_step_handler(msg, lambda m: _process_balance_change(m, target_id, sign=1))


@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_user_subbal_"))
@admin_only
def admin_user_subbal_callback(call):
    target_id = int(call.data.rsplit("_", 1)[1])
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, f"مبلغ کسر از حساب کاربر {target_id} رو وارد کنید:")
    bot.register_next_step_handler(msg, lambda m: _process_balance_change(m, target_id, sign=-1))


def _process_balance_change(message, target_id, sign):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        amount = int(message.text.strip())
    except ValueError:
        bot.reply_to(message, "مبلغ باید عدد باشه")
        return

    cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (target_id,))
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (sign * amount, target_id))
    conn.commit()

    cursor.execute("SELECT balance FROM users WHERE user_id=?", (target_id,))
    new_balance = cursor.fetchone()[0]

    action_word = "شارژ" if sign > 0 else "کسر"
    bot.reply_to(message, f"✅ {action_word} انجام شد.\nموجودی جدید کاربر {target_id}: {new_balance:,} تومان")

    try:
        bot.send_message(target_id, f"💰 موجودی حساب شما به‌روزرسانی شد.\nموجودی جدید: {new_balance:,} تومان")
    except Exception:
        pass


# --------- جستجوی کاربر ---------

@bot.callback_query_handler(func=lambda call: call.data == "admin_search")
@admin_only
def admin_search_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "آیدی عددی یا یوزرنیم کاربر مورد نظر رو بفرست:")
    bot.register_next_step_handler(msg, process_search)


def process_search(message):
    if message.from_user.id != ADMIN_ID:
        return

    query = message.text.strip()

    if query.isdigit():
        cursor.execute("SELECT user_id FROM users WHERE user_id=?", (int(query),))
    else:
        cursor.execute("SELECT user_id FROM users WHERE username=?", (query.lstrip("@"),))

    row = cursor.fetchone()
    if not row:
        bot.reply_to(message, "کاربری با این مشخصات پیدا نشد")
        return

    target_id = row[0]
    text, banned = build_user_detail(target_id)
    bot.send_message(message.chat.id, text, reply_markup=user_detail_keyboard(target_id, banned))


# --------- پیام همگانی پیشرفته (با پیش‌نمایش و تأیید) ---------

@bot.callback_query_handler(func=lambda call: call.data == "admin_broadcast")
@admin_only
def admin_broadcast_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(
        call.message.chat.id,
        "پیامی که می‌خوای برای همه کاربران ارسال بشه رو بفرست (متن، عکس، فایل و ... همه پشتیبانی میشه):"
    )
    bot.register_next_step_handler(msg, process_broadcast_preview)


def process_broadcast_preview(message):
    if message.from_user.id != ADMIN_ID:
        return

    _pending_broadcasts[message.chat.id] = (message.chat.id, message.message_id)

    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("✅ ارسال به همه", callback_data="bc_confirm"),
        InlineKeyboardButton("❌ لغو", callback_data="bc_cancel"),
    )
    bot.copy_message(message.chat.id, message.chat.id, message.message_id)
    bot.send_message(message.chat.id, "☝️ پیش‌نمایش پیام بالا. آیا مطمئنید می‌خواید این پیام برای همه‌ی کاربران ارسال بشه؟", reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: call.data in ("bc_confirm", "bc_cancel"))
@admin_only
def broadcast_confirm_callback(call):
    admin_chat_id = call.message.chat.id
    pending = _pending_broadcasts.pop(admin_chat_id, None)

    if call.data == "bc_cancel" or pending is None:
        bot.answer_callback_query(call.id, "لغو شد")
        bot.edit_message_reply_markup(admin_chat_id, call.message.message_id, reply_markup=None)
        return

    bot.answer_callback_query(call.id, "در حال ارسال...")
    bot.edit_message_reply_markup(admin_chat_id, call.message.message_id, reply_markup=None)

    from_chat_id, message_id = pending
    cursor.execute("SELECT user_id FROM users")
    all_ids = [row[0] for row in cursor.fetchall()]

    sent = 0
    failed = 0
    for uid in all_ids:
        try:
            bot.copy_message(uid, from_chat_id, message_id)
            sent += 1
        except Exception:
            failed += 1
        time.sleep(0.05)

    bot.send_message(admin_chat_id, f"✅ پیام همگانی ارسال شد.\nموفق: {sent:,}\nناموفق: {failed:,}")


# --------- خروجی CSV ---------

@bot.callback_query_handler(func=lambda call: call.data == "admin_export")
@admin_only
def admin_export_callback(call):
    bot.answer_callback_query(call.id, "در حال ساخت فایل...")

    # --- CSV کاربران ---
    users_buf = io.StringIO()
    writer = csv.writer(users_buf)
    writer.writerow(["user_id", "username", "balance", "trial_used", "banned", "joined_at"])
    cursor.execute("SELECT user_id, username, balance, trial_used, banned, joined_at FROM users")
    for row in cursor.fetchall():
        writer.writerow(row)
    users_bytes = io.BytesIO(users_buf.getvalue().encode("utf-8-sig"))
    users_bytes.name = "users.csv"

    # --- CSV تاریخچه‌ی کانفیگ‌ها ---
    configs_buf = io.StringIO()
    writer2 = csv.writer(configs_buf)
    writer2.writerow(["id", "user_id", "plan_title", "price", "created_at", "links"])
    cursor.execute("SELECT id, user_id, plan_title, price, created_at, links FROM configs")
    for row in cursor.fetchall():
        writer2.writerow(row)
    configs_bytes = io.BytesIO(configs_buf.getvalue().encode("utf-8-sig"))
    configs_bytes.name = "configs_history.csv"

    bot.send_document(call.message.chat.id, users_bytes, caption="📤 خروجی کاربران")
    bot.send_document(call.message.chat.id, configs_bytes, caption="📤 خروجی تاریخچه‌ی کانفیگ‌ها")


if __name__ == "__main__":
    bot.infinity_polling()

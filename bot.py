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

# چند ادمین: با کاما جدا کن، مثال: "6059940165,111111111"
ADMIN_ID = 6059940165  # ادمین اصلی (برای سازگاری با کد قبلی)
ADMIN_IDS = set()
for _piece in os.environ.get("ADMIN_IDS", str(ADMIN_ID)).split(","):
    _piece = _piece.strip()
    if _piece.isdigit():
        ADMIN_IDS.add(int(_piece))
ADMIN_IDS.add(ADMIN_ID)


def is_admin(user_id):
    return user_id in ADMIN_IDS


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

for _ddl in [
    "ALTER TABLE users ADD COLUMN trial_used INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN joined_at INTEGER",
]:
    try:
        cursor.execute(_ddl)
        conn.commit()
    except sqlite3.OperationalError:
        pass

# --- جدول تاریخچه‌ی کانفیگ‌های گرفته‌شده توسط هر کاربر ---
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


def upsert_user(user_id, username=None):
    cursor.execute(
        "INSERT OR IGNORE INTO users(user_id, username, joined_at) VALUES (?,?,?)",
        (user_id, username, int(time.time()))
    )
    if username:
        cursor.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
    conn.commit()


def is_banned(user_id):
    cursor.execute("SELECT banned FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return bool(row and row[0])


def block_if_banned(message):
    if is_banned(message.from_user.id):
        bot.reply_to(message, "⛔️ شما توسط ادمین مسدود شده‌اید و امکان استفاده از بات را ندارید.")
        return True
    return False


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


def panel_delete_profile(name):
    """یک کاربر رو با نام دقیقش از روی پنل حذف می‌کنه."""
    config, key = panel_auth()
    users = config.get("users") or []
    new_users = [u for u in users if u.get("name") != name]

    if len(new_users) == len(users):
        raise PanelError("کاربری با این نام روی پنل پیدا نشد.")

    config["users"] = new_users
    panel_sync(config, key)


# ================= START =================

@bot.message_handler(commands=['start'])
def start(message):

    upsert_user(message.from_user.id, message.from_user.username)

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
    if block_if_banned(message):
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

    if is_banned(user_id):
        bot.answer_callback_query(call.id, "⛔️ شما مسدود شده‌اید", show_alert=True)
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
    if block_if_banned(message):
        return

    user_id = message.from_user.id

    cursor.execute("SELECT trial_used FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()

    if row is None:
        upsert_user(user_id, message.from_user.username)
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

    if block_if_banned(message):
        return

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
    if block_if_banned(message):
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


# ================= تاریخچه کانفیگ‌ها =================

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
    if block_if_banned(message):
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

    if is_admin(message.from_user.id):
        return

    for admin_id in ADMIN_IDS:
        try:
            bot.forward_message(admin_id, message.chat.id, message.message_id)
            bot.send_message(
                admin_id,
                f"""رسید جدید

نام:
{message.from_user.first_name}

آیدی:
{message.from_user.id}

برای شارژ حساب این کاربر دستور زیر رو بفرست:
/charge {message.from_user.id} <مبلغ>
مثال: /charge {message.from_user.id} 60000"""
            )
        except Exception:
            pass

    bot.reply_to(message, "✅ رسید ارسال شد، پس از تایید ادمین موجودی شما شارژ می‌شود.")


# ================= ADMIN CHARGE COMMAND =================

@bot.message_handler(func=lambda m: m.text and m.text.startswith("/charge") and is_admin(m.from_user.id))
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

@bot.message_handler(func=lambda m: m.text and m.text.startswith("/testpanel") and is_admin(m.from_user.id))
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

@bot.message_handler(func=lambda m: m.text and m.text.startswith("/dumpuser") and is_admin(m.from_user.id))
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


# ================= ADMIN PANEL (مدیریت) =================

def admin_main_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📊 آمار", callback_data="admin_stats"),
        InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast"),
    )
    keyboard.add(
        InlineKeyboardButton("👥 کاربران برتر", callback_data="admin_userlist"),
        InlineKeyboardButton("🔍 جستجوی کاربر", callback_data="admin_search"),
    )
    keyboard.add(
        InlineKeyboardButton("💳 ویرایش موجودی", callback_data="admin_balance"),
        InlineKeyboardButton("🚫 مسدود/رفع مسدودیت", callback_data="admin_ban"),
    )
    keyboard.add(
        InlineKeyboardButton("📤 خروجی کاربران (CSV)", callback_data="admin_export"),
        InlineKeyboardButton("🗑 حذف کانفیگ از پنل", callback_data="admin_delete_config"),
    )
    return keyboard


@bot.message_handler(commands=['admin'])
def admin_panel(message):

    if not is_admin(message.from_user.id):
        return

    bot.send_message(message.chat.id, "🛠 پنل مدیریت بات", reply_markup=admin_main_keyboard())


@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
def admin_callbacks(call):

    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔️ دسترسی ندارید", show_alert=True)
        return

    action = call.data
    bot.answer_callback_query(call.id)

    if action == "admin_stats":
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

        cursor.execute("SELECT COALESCE(SUM(price),0), COUNT(*) FROM configs WHERE price > 0")
        revenue_total, sales_total = cursor.fetchone()

        cursor.execute("SELECT COALESCE(SUM(price),0), COUNT(*) FROM configs WHERE price > 0 AND created_at >= ?", (today_start,))
        revenue_today, sales_today = cursor.fetchone()

        cursor.execute("SELECT COALESCE(SUM(price),0), COUNT(*) FROM configs WHERE price > 0 AND created_at >= ?", (week_start,))
        revenue_week, sales_week = cursor.fetchone()

        cursor.execute("SELECT COALESCE(SUM(price),0), COUNT(*) FROM configs WHERE price > 0 AND created_at >= ?", (month_start,))
        revenue_month, sales_month = cursor.fetchone()

        text = f"""📊 آمار بات

👥 تعداد کل کاربران: {total_users:,}
🆕 کاربر جدید امروز: {new_today:,}
🚫 کاربران مسدود: {banned_count:,}
🧪 استفاده از تست رایگان: {trial_count:,}
💰 مجموع موجودی کیف پول‌ها: {total_balance:,} تومان

💵 فروش امروز: {sales_today} عدد — {revenue_today:,} تومان
💵 فروش هفته اخیر: {sales_week} عدد — {revenue_week:,} تومان
💵 فروش ماه اخیر: {sales_month} عدد — {revenue_month:,} تومان
💵 فروش کل: {sales_total} عدد — {revenue_total:,} تومان"""
        bot.send_message(call.message.chat.id, text)

    elif action == "admin_broadcast":
        msg = bot.send_message(call.message.chat.id, "پیامی که می‌خوای برای همه کاربران ارسال بشه رو بفرست:")
        bot.register_next_step_handler(msg, process_broadcast_draft)

    elif action == "admin_userlist":
        cursor.execute("SELECT user_id, balance, banned FROM users ORDER BY balance DESC LIMIT 30")
        rows = cursor.fetchall()
        if not rows:
            bot.send_message(call.message.chat.id, "کاربری وجود نداره")
            return
        lines = []
        for uid, bal, banned in rows:
            mark = "🚫" if banned else "•"
            lines.append(f"{mark} {uid} — {bal:,} تومان")
        bot.send_message(call.message.chat.id, "👥 ۳۰ کاربر برتر (بر اساس موجودی):\n\n" + "\n".join(lines))

    elif action == "admin_search":
        msg = bot.send_message(call.message.chat.id, "آیدی عددی یا یوزرنیم (با یا بدون @) کاربر مورد نظر رو بفرست:")
        bot.register_next_step_handler(msg, process_search)

    elif action == "admin_balance":
        msg = bot.send_message(
            call.message.chat.id,
            "آیدی کاربر و موجودی جدید رو به این شکل بفرست (موجودی قبلی جایگزین میشه، نه اضافه):\n\n<user_id> <مبلغ>\nمثال: 123456789 50000"
        )
        bot.register_next_step_handler(msg, process_set_balance)

    elif action == "admin_ban":
        msg = bot.send_message(call.message.chat.id, "آیدی عددی کاربری که می‌خوای مسدود/رفع مسدودیت بشه رو بفرست:")
        bot.register_next_step_handler(msg, process_toggle_ban)

    elif action == "admin_export":
        send_users_csv(call.message.chat.id)

    elif action == "admin_delete_config":
        msg = bot.send_message(
            call.message.chat.id,
            "اسم دقیق کانفیگ روی پنل رو بفرست (همون بخش بعد از ?sub= توی لینک اشتراک کاربر):"
        )
        bot.register_next_step_handler(msg, process_delete_config)


def process_broadcast_draft(message):
    if not is_admin(message.from_user.id):
        return

    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton("✅ ارسال به همه", callback_data="bc_confirm"),
        InlineKeyboardButton("❌ لغو", callback_data="bc_cancel"),
    )
    bot.send_message(
        message.chat.id,
        f"این پیام برای همه کاربران ارسال بشه؟\n\n---\n{message.text}\n---",
        reply_markup=keyboard
    )
    _broadcast_drafts[message.from_user.id] = message.text


_broadcast_drafts = {}


@bot.callback_query_handler(func=lambda call: call.data in ("bc_confirm", "bc_cancel"))
def broadcast_confirm(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔️ دسترسی ندارید", show_alert=True)
        return

    bot.answer_callback_query(call.id)

    if call.data == "bc_cancel":
        _broadcast_drafts.pop(call.from_user.id, None)
        bot.edit_message_text("❌ ارسال همگانی لغو شد.", call.message.chat.id, call.message.message_id)
        return

    text = _broadcast_drafts.pop(call.from_user.id, None)
    if not text:
        bot.edit_message_text("❌ متنی برای ارسال پیدا نشد، دوباره تلاش کن.", call.message.chat.id, call.message.message_id)
        return

    bot.edit_message_text("⏳ در حال ارسال پیام همگانی...", call.message.chat.id, call.message.message_id)

    cursor.execute("SELECT user_id FROM users WHERE banned=0 OR banned IS NULL")
    all_ids = [row[0] for row in cursor.fetchall()]

    sent = 0
    failed = 0
    for uid in all_ids:
        try:
            bot.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1
        time.sleep(0.05)

    bot.send_message(call.message.chat.id, f"✅ پیام همگانی ارسال شد.\nموفق: {sent}\nناموفق: {failed}")


def process_search(message):
    if not is_admin(message.from_user.id):
        return

    query = message.text.strip()

    if query.lstrip("-").isdigit():
        cursor.execute(
            "SELECT user_id, username, balance, trial_used, banned, config FROM users WHERE user_id=?",
            (int(query),)
        )
        rows = cursor.fetchall()
    else:
        uname = query.lstrip("@")
        cursor.execute(
            "SELECT user_id, username, balance, trial_used, banned, config FROM users WHERE username=?",
            (uname,)
        )
        rows = cursor.fetchall()

    if not rows:
        bot.reply_to(message, "کاربری با این مشخصات پیدا نشد")
        return

    for uid, username, balance, trial_used, banned, config in rows:
        text = f"""👤 اطلاعات کاربر

🆔 آیدی: {uid}
👤 یوزرنیم: @{username if username else '-'}
💰 موجودی: {balance:,} تومان
🧪 تست رایگان استفاده شده: {'بله' if trial_used else 'خیر'}
🚫 وضعیت مسدودی: {'مسدود' if banned else 'آزاد'}
🔑 آخرین کانفیگ:
{config if config else '-'}"""
        bot.reply_to(message, text)


def process_set_balance(message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "فرمت درست: <user_id> <مبلغ>")
        return

    try:
        target_id = int(parts[0])
        amount = int(parts[1])
    except ValueError:
        bot.reply_to(message, "user_id و مبلغ باید عدد باشند")
        return

    cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (target_id,))
    cursor.execute("UPDATE users SET balance=? WHERE user_id=?", (amount, target_id))
    conn.commit()

    bot.reply_to(message, f"✅ موجودی کاربر {target_id} برابر شد با: {amount:,} تومان")

    try:
        bot.send_message(target_id, f"💳 موجودی حساب شما توسط ادمین به {amount:,} تومان تغییر یافت.")
    except Exception:
        pass


def process_toggle_ban(message):
    if not is_admin(message.from_user.id):
        return

    try:
        target_id = int(message.text.strip())
    except ValueError:
        bot.reply_to(message, "آیدی باید عدد باشه")
        return

    cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (target_id,))
    cursor.execute("SELECT banned FROM users WHERE user_id=?", (target_id,))
    current = cursor.fetchone()[0] or 0
    new_status = 0 if current else 1

    cursor.execute("UPDATE users SET banned=? WHERE user_id=?", (new_status, target_id))
    conn.commit()

    if new_status:
        bot.reply_to(message, f"🚫 کاربر {target_id} مسدود شد.")
        try:
            bot.send_message(target_id, "⛔️ حساب شما توسط ادمین مسدود شد.")
        except Exception:
            pass
    else:
        bot.reply_to(message, f"✅ مسدودیت کاربر {target_id} برداشته شد.")
        try:
            bot.send_message(target_id, "✅ مسدودیت حساب شما برداشته شد.")
        except Exception:
            pass


def process_delete_config(message):
    if not is_admin(message.from_user.id):
        return

    name = message.text.strip()
    processing_msg = bot.reply_to(message, "⏳ در حال حذف از پنل...")

    try:
        panel_delete_profile(name)
    except Exception as e:
        bot.edit_message_text(f"❌ حذف انجام نشد: {e}", message.chat.id, processing_msg.message_id)
        return

    bot.edit_message_text(f"✅ کانفیگ '{name}' از پنل حذف شد.", message.chat.id, processing_msg.message_id)


def send_users_csv(chat_id):
    cursor.execute("SELECT user_id, username, balance, trial_used, banned, joined_at FROM users")
    rows = cursor.fetchall()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["user_id", "username", "balance", "trial_used", "banned", "joined_at"])
    for row in rows:
        writer.writerow(row)

    buffer.seek(0)
    data = buffer.getvalue().encode("utf-8-sig")

    bot.send_document(
        chat_id,
        (f"users_{int(time.time())}.csv", data),
        caption=f"📤 خروجی کاربران — {len(rows)} رکورد"
    )


if __name__ == "__main__":
    bot.infinity_polling()

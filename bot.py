import telebot
import sqlite3
import requests
import uuid
import time
import json
import os

from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup
)


# ================= CONFIG =================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8921489424:AAFCrTyaD6S-Zd2sFav_7-WBH9KQDfB7Cmk")

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

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    balance INTEGER DEFAULT 0,
    config TEXT,
    trial_used INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
""")

conn.commit()

# WAL mode برای دسترسی همزمان با پنل ادمین
conn.execute("PRAGMA journal_mode=WAL")

# اگه دیتابیس از قبل بدون ستون trial_used ساخته شده، اضافه‌ش کن
try:
    cursor.execute("ALTER TABLE users ADD COLUMN trial_used INTEGER DEFAULT 0")
    conn.commit()
except sqlite3.OperationalError:
    pass


# ================= SETTINGS =================

def get_settings():
    cursor.execute("SELECT value FROM settings WHERE key='bot_settings'")
    row = cursor.fetchone()
    if row:
        return json.loads(row[0])
    return {
        "forceSubChannels": [],
        "forceSubEnabled": False,
        "plans": {}
    }

def save_settings(data):
    cursor.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('bot_settings', ?)",
        (json.dumps(data, ensure_ascii=False),)
    )
    conn.commit()


# ================= PLANS =================

PLANS = {
    "single":   {"title": "یک کاربره", "price": 60000, "profiles": 1, "days": 30, "conn_limit": 1},
    "double":   {"title": "دو کاربره", "price": 70000, "profiles": 1, "days": 30, "conn_limit": 2},
    "unlimited":{"title": "نامحدود",   "price": 90000, "profiles": 1, "days": 30, "conn_limit": None},
}

# ================= TRIAL =================

TRIAL_TRAFFIC_GB = 0.05
TRIAL_DAYS       = 1
REQ_PER_GB       = 6000


# ================= FORCE SUBSCRIPTION =================

def get_force_sub_channels():
    settings = get_settings()
    if not settings.get("forceSubEnabled", False):
        return []
    return settings.get("forceSubChannels", [])


def check_membership(user_id):
    channels = get_force_sub_channels()
    if not channels:
        return True, []

    not_joined = []
    for ch in channels:
        channel_id = ch.get("id", "")
        try:
            member = bot.get_chat_member(channel_id, user_id)
            if member.status in ("left", "kicked", "restricted"):
                not_joined.append(ch)
        except Exception:
            pass

    if not_joined:
        return False, not_joined
    return True, []


def send_force_sub_message(message, not_joined_channels):
    keyboard = InlineKeyboardMarkup()
    for ch in not_joined_channels:
        keyboard.add(
            InlineKeyboardButton(
                f"📢 عضویت در {ch.get('title', 'کانال')}",
                url=ch.get("url", "https://t.me")
            )
        )
    keyboard.add(
        InlineKeyboardButton("✅ عضو شدم", callback_data="check_membership")
    )
    bot.send_message(
        message.chat.id,
        "🔒 برای استفاده از ربات ابتدا باید در کانال‌های زیر عضو بشید:\n\n"
        "بعد از عضویت روی دکمه «عضو شدم» بزنید.",
        reply_markup=keyboard
    )


def require_membership(func):
    """دکوراتور برای چک عضویت قبل از اجرای هر هندلر"""
    def wrapper(message):
        if message.from_user.id == ADMIN_ID:
            return func(message)
        is_member, not_joined = check_membership(message.from_user.id)
        if not is_member:
            send_force_sub_message(message, not_joined)
            return
        return func(message)
    return wrapper


# ================= KEYBOARD =================

reply_keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
reply_keyboard.add(
    "خرید کانفیگ🛒",
    "تست رایگان🕧",
    "کارت به کارت💲",
    "اطلاعات من✨",
    "پشتیبانی👇"
)


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

    raise PanelError("اتصال به پنل با هیچ‌کدوم از کلیدها موفق نبود:\n" + "\n".join(attempts))


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

    expiry_ms  = int((time.time() + days * 86400) * 1000)
    created_at = int(time.time() * 1000)

    new_names = []
    for i in range(count):
        name = f"{name_prefix}_{i+1}" if count > 1 else name_prefix
        user_obj = {
            "id":        str(uuid.uuid4()),
            "name":      name,
            "expiryMs":  expiry_ms,
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


# ================= START =================

@bot.message_handler(commands=['start'])
def start(message):
    cursor.execute(
        "INSERT OR IGNORE INTO users(user_id, username) VALUES (?,?)",
        (message.from_user.id, message.from_user.username)
    )
    conn.commit()

    if message.from_user.id != ADMIN_ID:
        is_member, not_joined = check_membership(message.from_user.id)
        if not is_member:
            send_force_sub_message(message, not_joined)
            return

    bot.reply_to(message, "به بات کانفیگ فرا زمین خوش آمدید", reply_markup=reply_keyboard)


# ================= CHECK MEMBERSHIP CALLBACK =================

@bot.callback_query_handler(func=lambda call: call.data == "check_membership")
def recheck_membership(call):
    is_member, not_joined = check_membership(call.from_user.id)
    if is_member:
        bot.answer_callback_query(call.id, "✅ عضویت تایید شد!")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(
            call.message.chat.id,
            "✅ عضویت شما تایید شد. خوش آمدید!",
            reply_markup=reply_keyboard
        )
    else:
        names = " و ".join([ch.get("title", "کانال") for ch in not_joined])
        bot.answer_callback_query(call.id, f"❌ هنوز در {names} عضو نشدید!", show_alert=True)


# ================= BUY MENU =================

@bot.message_handler(func=lambda m: m.text == "خرید کانفیگ🛒")
@require_membership
def buy_menu(message):
    keyboard = InlineKeyboardMarkup()
    for key, plan in PLANS.items():
        keyboard.add(
            InlineKeyboardButton(
                f"{plan['title']} - {plan['price']:,} تومان",
                callback_data=f"buy_{key}"
            )
        )
    bot.reply_to(message, "پلن مورد نظر را انتخاب کنید:\nحجم همه کانفیگ ها نامحدود هست", reply_markup=keyboard)


@bot.message_handler(func=lambda m: m.text == "پشتیبانی👇")
@require_membership
def support(message):
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("💬 ارتباط با پشتیبانی", url="https://t.me/valaorp"))
    bot.reply_to(message, "برای ارتباط با پشتیبانی روی دکمه زیر بزنید:", reply_markup=keyboard)


# ================= BUY CHECK =================

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def buy_config(call):
    user_id = call.from_user.id

    if user_id != ADMIN_ID:
        is_member, not_joined = check_membership(user_id)
        if not is_member:
            bot.answer_callback_query(call.id, "ابتدا باید در کانال‌ها عضو بشید!", show_alert=True)
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

    bot.edit_message_text(
        f"✅ خرید موفق بود\n\n💰 مبلغ:\n{price:,} تومان\n\n🔑 لینک(های) اشتراک شما:\n{config_text}\n\n"
        f"این لینک رو داخل اپلیکیشن کلاینت (v2rayN, Hiddify, Shadowrocket, Nekoray و ...) به‌عنوان Subscription وارد کن.",
        call.message.chat.id,
        processing_msg.message_id
    )


# ================= FREE TRIAL =================

@bot.message_handler(func=lambda m: m.text == "تست رایگان🕧")
@require_membership
def free_trial(message):
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
        bot.reply_to(
            message,
            "❌ شما قبلاً از تست رایگان استفاده کرده‌اید. برای خرید از منوی «خرید کانفیگ» استفاده کنید."
        )
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
        f"✅ کانفیگ تست شما ساخته شد\n\n📦 حجم: {int(TRIAL_TRAFFIC_GB * 1000)} مگابایت\n"
        f"⏳ اعتبار: {TRIAL_DAYS} روز\n\n🔑 لینک اشتراک:\n{config_text}\n\n"
        f"این لینک رو داخل اپلیکیشن کلاینت (v2rayN, Hiddify, Shadowrocket, Nekoray و ...) به‌عنوان Subscription وارد کن.",
        message.chat.id,
        processing_msg.message_id
    )


# ================= CARD TO CARD =================

@bot.message_handler(func=lambda m: m.text == "کارت به کارت💲")
@require_membership
def card(message):
    bot.reply_to(
        message,
        "مبلغ را به شماره کارت زیر واریز کنید:\n\n"
        "8673 2559 1411 6362\n\n"
        "امیر والا شریف نسب\n\n"
        "بعد از پرداخت رسید را ارسال کنید. ادمین ما چک میکنه و پول به حساب شما میاد"
    )


@bot.message_handler(func=lambda m: m.text == "اطلاعات من✨")
@require_membership
def my_info(message):
    user_id = message.from_user.id
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    balance = result[0] if result else 0
    bot.send_message(
        message.chat.id,
        f"👤 اطلاعات حساب شما\n\n🆔 شناسه: {user_id}\n\n💰 موجودی کیف پول: {balance:,} تومان"
    )


# ================= ADMIN RECEIPT =================

@bot.message_handler(content_types=['photo'])
def receipt(message):
    if message.from_user.id == ADMIN_ID:
        return

    bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
    bot.send_message(
        ADMIN_ID,
        f"رسید جدید\n\nنام:\n{message.from_user.first_name}\n\nآیدی:\n{message.from_user.id}\n\n"
        f"برای شارژ حساب این کاربر دستور زیر رو بفرست:\n"
        f"/charge {message.from_user.id} <مبلغ>\n"
        f"مثال: /charge {message.from_user.id} 60000"
    )
    bot.reply_to(message, "✅ رسید ارسال شد، پس از تایید ادمین موجودی شما شارژ می‌شود.")


# ================= ADMIN: CHARGE =================

@bot.message_handler(func=lambda m: m.text and m.text.startswith("/charge") and m.from_user.id == ADMIN_ID)
def admin_charge(message):
    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "فرمت درست: /charge <user_id> <amount>")
        return
    try:
        target_id = int(parts[1])
        amount    = int(parts[2])
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


# ================= ADMIN: FORCE SUB =================

@bot.message_handler(func=lambda m: m.text and m.text.startswith("/addchannel") and m.from_user.id == ADMIN_ID)
def admin_add_channel(message):
    parts = message.text.split(maxsplit=3)
    if len(parts) < 4:
        bot.reply_to(message, "فرمت: /addchannel @channel_id عنوان https://t.me/channel")
        return

    channel_id, title, url = parts[1], parts[2], parts[3]
    settings = get_settings()
    channels = settings.get("forceSubChannels", [])

    if any(ch["id"] == channel_id for ch in channels):
        bot.reply_to(message, f"❌ کانال {channel_id} قبلاً اضافه شده.")
        return

    channels.append({"id": channel_id, "title": title, "url": url})
    settings["forceSubChannels"] = channels
    save_settings(settings)
    bot.reply_to(message, f"✅ کانال {title} ({channel_id}) اضافه شد.\nتعداد کانال‌های اجباری: {len(channels)}")


@bot.message_handler(func=lambda m: m.text and m.text.startswith("/removechannel") and m.from_user.id == ADMIN_ID)
def admin_remove_channel(message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "فرمت: /removechannel @channel_id")
        return

    channel_id = parts[1].strip()
    settings   = get_settings()
    channels   = settings.get("forceSubChannels", [])
    new_channels = [ch for ch in channels if ch["id"] != channel_id]

    if len(new_channels) == len(channels):
        bot.reply_to(message, f"❌ کانال {channel_id} پیدا نشد.")
        return

    settings["forceSubChannels"] = new_channels
    save_settings(settings)
    bot.reply_to(message, f"✅ کانال {channel_id} حذف شد.\nتعداد کانال‌های اجباری: {len(new_channels)}")


@bot.message_handler(func=lambda m: m.text and m.text.startswith("/listchannels") and m.from_user.id == ADMIN_ID)
def admin_list_channels(message):
    settings = get_settings()
    channels = settings.get("forceSubChannels", [])
    enabled  = settings.get("forceSubEnabled", False)

    if not channels:
        bot.reply_to(message, "هیچ کانال اجباری تعریف نشده.")
        return

    status = "✅ فعال" if enabled else "❌ غیرفعال"
    lines  = [f"وضعیت عضویت اجباری: {status}\n"]
    for i, ch in enumerate(channels, 1):
        lines.append(f"{i}. {ch['title']} ({ch['id']})\n   {ch['url']}")

    bot.reply_to(message, "\n".join(lines))


@bot.message_handler(func=lambda m: m.text and m.text.startswith("/forcesub") and m.from_user.id == ADMIN_ID)
def admin_toggle_forcesub(message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or parts[1].strip() not in ("on", "off"):
        bot.reply_to(message, "فرمت: /forcesub on یا /forcesub off")
        return

    enabled  = parts[1].strip() == "on"
    settings = get_settings()
    settings["forceSubEnabled"] = enabled
    save_settings(settings)
    bot.reply_to(message, f"عضویت اجباری {'✅ فعال شد' if enabled else '❌ غیرفعال شد'}.")


# ================= ADMIN: DIAGNOSTICS =================

@bot.message_handler(func=lambda m: m.text and m.text.startswith("/testpanel") and m.from_user.id == ADMIN_ID)
def admin_test_panel(message):
    bot.reply_to(message, "⏳ در حال تست اتصال به پنل...")
    url = f"{PANEL_BASE}/{PANEL_API_ROUTE}/api/auth"

    test_cases = [
        ("Panel API Key - فقط هدر", PANEL_API_KEY, True,  False),
        ("Panel API Key - فقط بدنه", PANEL_API_KEY, False, True),
        ("Panel API Key - هر دو",    PANEL_API_KEY, True,  True),
    ]
    if PANEL_MASTER_KEY_FALLBACK:
        test_cases += [
            ("Master Key - فقط هدر", PANEL_MASTER_KEY_FALLBACK, True,  False),
            ("Master Key - فقط بدنه",PANEL_MASTER_KEY_FALLBACK, False, True),
            ("Master Key - هر دو",   PANEL_MASTER_KEY_FALLBACK, True,  True),
        ]

    report_lines = [f"🔍 نتیجه تست اتصال به پنل\nURL: {url}\n"]
    for label, key, use_header, use_body in test_cases:
        headers = {"Authorization": f"Bearer {key}"} if use_header else {}
        body    = {"key": key} if use_body else {}
        try:
            resp    = requests.post(url, headers=headers, json=body, timeout=15)
            snippet = resp.text[:200].replace("\n", " ")
            if resp.status_code == 200:
                try:
                    mark = "✅" if resp.json().get("success") else "⚠️"
                except Exception:
                    mark = "⚠️"
            else:
                mark = "❌"
            report_lines.append(f"{mark} {label}\nStatus: {resp.status_code}\nPasokh: {snippet}\n")
        except Exception as e:
            report_lines.append(f"❌ {label}\nError: {e}\n")

    full_report = "\n".join(report_lines)
    for i in range(0, len(full_report), 3500):
        bot.send_message(message.chat.id, full_report[i:i+3500])


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

    users   = config.get("users") or []
    matches = [u for u in users if u.get("name") == target_name]
    if not matches:
        names = ", ".join([str(u.get("name")) for u in users][:30])
        bot.reply_to(message, f"❌ کاربری با اسم '{target_name}' پیدا نشد.\n\nاسم‌های موجود:\n{names}")
        return

    import json as _json
    dump = _json.dumps(matches[0], ensure_ascii=False, indent=2)
    for i in range(0, len(dump), 3500):
        bot.send_message(message.chat.id, f"```\n{dump[i:i+3500]}\n```", parse_mode="Markdown")


# ================= ADMIN: HELP =================

@bot.message_handler(func=lambda m: m.text == "/adminhelp" and m.from_user.id == ADMIN_ID)
def admin_help(message):
    bot.reply_to(
        message,
        "📋 دستورات ادمین:\n\n"
        "💰 مالی:\n"
        "/charge <user_id> <amount> — شارژ حساب\n\n"
        "📢 عضویت اجباری:\n"
        "/addchannel @id عنوان https://t.me/... — اضافه کردن\n"
        "/removechannel @id — حذف کانال\n"
        "/listchannels — لیست کانال‌ها\n"
        "/forcesub on/off — فعال/غیرفعال\n\n"
        "🔧 تشخیص:\n"
        "/testpanel — تست اتصال به پنل\n"
        "/dumpuser <نام> — اطلاعات کاربر پنل"
    )


if __name__ == "__main__":
    bot.infinity_polling()

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
# بهتره این‌ها رو به‌جای این‌که مستقیم این‌جا بنویسی، از متغیرهای محیطی (Environment Variables) بخونی.
# فعلاً برای راحتی همینجا گذاشتم ولی توصیه می‌کنم بعداً جابه‌جا کنی.

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8921489424:AAGn6Bawl-fkwTHg00ZYDmpYKvARXf6OCXo")

PANEL_BASE = os.environ.get("PANEL_BASE", "https://little-waterfall-27fa.berbrtokamma.workers.dev")
PANEL_API_ROUTE = os.environ.get("PANEL_API_ROUTE", "sync")   # همون بخش اول آدرس (مثلا .../sync/dash)

# ترجیحاً از Panel API Key استفاده کن (نه Master Key) - دسترسی محدودتر و قابل ابطال جداگانه‌ست.
PANEL_API_KEY = os.environ.get("PANEL_API_KEY", "nahan_mrlmsp7c_7lg9rlf0")

# فقط برای عیب‌یابی/فال‌بک - رمز قبلی لو رفته بود، پس خالی گذاشتیمش.
# اگه لازم شد، مقدار Master Key جدید رو فقط به‌صورت Environment Variable ست کن، نه اینجا داخل کد.
PANEL_MASTER_KEY_FALLBACK = os.environ.get("PANEL_MASTER_KEY", "admin")

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

conn.commit()

# اگه دیتابیس از قبل بدون ستون trial_used ساخته شده، اضافه‌ش کن
try:
    cursor.execute("ALTER TABLE users ADD COLUMN trial_used INTEGER DEFAULT 0")
    conn.commit()
except sqlite3.OperationalError:
    pass  # ستون از قبل وجود داره


# ================= PLANS =================
# key: callback_data suffix, value: (عنوان فارسی, قیمت, تعداد کانفیگ, روز اعتبار)

PLANS = {
    "single": {"title": "یک کاربره", "price": 60000, "profiles": 1, "days": 30},
    "double": {"title": "دو کاربره", "price": 70000, "profiles": 2, "days": 30},
    "unlimited": {"title": "نامحدود", "price": 90000, "profiles": 1, "days": 30},
}

# ================= TRIAL =================

TRIAL_TRAFFIC_GB = 0.05   # 50 مگابایت
TRIAL_DAYS = 1            # اعتبار کانفیگ تست

# ✅ تایید شده از داشبورد خود پنل: فیلد واقعی "limitTotalReq"ه، نه یه فیلد GB مستقیم.
# پنل خودش GB رو به تعداد درخواست تبدیل می‌کنه. با یه کاربر نمونه که ادمین دستی با
# "Traffic (GB) Limit" = 1 ساخت، مقدار limitTotalReq برابر 3000 بود.
# پس نسبت تبدیل: هر 1 گیگابایت = 3000 درخواست
REQ_PER_GB = 6000


# ================= KEYBOARD =================

reply_keyboard = ReplyKeyboardMarkup(
    resize_keyboard=True, row_width=2
)

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
    """
    با پنل تلاش می‌کنه وصل بشه. چون مطمئن نیستیم دقیقاً پنل کلید رو با چه روشی
    قبول می‌کنه، چند حالت رو خودکار امتحان می‌کنیم:
    1) Panel API Key
    2) Master Key (fallback، فقط اگه ست شده باشه)
    اگه همه شکست خوردن، خطای کامل (همه‌ی تلاش‌ها) رو برمی‌گردونه.

    خروجی: (config, working_key) - working_key همونیه که موفق بود، برای استفاده در panel_sync.
    """
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
    """کانفیگ جدید رو با همون کلیدی که در panel_auth کار کرد، روی پنل ذخیره می‌کنه."""
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


def panel_create_profiles(name_prefix, count, days, traffic_gb=None):
    """
    یک یا چند پروفایل (کاربر) جدید روی پنل نهان می‌سازه و
    لینک‌های اشتراک (Subscription) رو برمی‌گردونه.

    traffic_gb: اگه مقدار بدی، سقف مصرف (بر حسب گیگابایت) هم روی کاربر ست میشه.
    """
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
        """
        INSERT OR IGNORE INTO users(user_id, username)
        VALUES (?,?)
        """,
        (
            message.from_user.id,
            message.from_user.username
        )
    )

    conn.commit()

    bot.reply_to(
        message,
        "به بات کانفیگ فرا زمین خوش آمدید",
        reply_markup=reply_keyboard
    )


# ================= BUY MENU =================

@bot.message_handler(func=lambda m: m.text == "خرید کانفیگ🛒")
def buy_menu(message):

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
        "پلن مورد نظر را انتخاب کنید:,حجم همه کانفیگ ها نامحدود هست",
        reply_markup=keyboard
    )


# ================= BUY CHECK =================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("buy_")
)
def buy_config(call):

    user_id = call.from_user.id
    plan_key = call.data.split("_", 1)[1]

    plan = PLANS.get(plan_key)
    if plan is None:
        bot.answer_callback_query(call.id, "پلن نامعتبر است")
        return

    price = plan["price"]

    cursor.execute(
        "SELECT balance FROM users WHERE user_id=?",
        (user_id,)
    )
    user = cursor.fetchone()

    if user is None:
        bot.reply_to(call.message, "حساب شما پیدا نشد")
        return

    balance = user[0]

    if balance < price:
        bot.reply_to(
            call.message,
            f"""
❌ موجودی کافی نیست

قیمت:
{price:,} تومان

موجودی شما:
{balance:,} تومان
"""
        )
        return

    # اول بهش اطلاع بده داره پردازش میشه (ساخت کانفیگ ممکنه چند ثانیه طول بکشه)
    processing_msg = bot.reply_to(call.message, "⏳ در حال ساخت کانفیگ...")

    try:
        name_prefix = f"u{user_id}_{int(time.time())}"
        links = panel_create_profiles(
            name_prefix=name_prefix,
            count=plan["profiles"],
            days=plan["days"]
        )
    except Exception as e:
        bot.edit_message_text(
            f"❌ خطا در ساخت کانفیگ از پنل. مبلغی از حساب شما کم نشد.\n\nجزئیات خطا: {e}",
            call.message.chat.id,
            processing_msg.message_id
        )
        return

    # فقط اگه ساخت کانفیگ موفق بود، از موجودی کم کن
    cursor.execute(
        """
        UPDATE users
        SET balance = balance - ?
        WHERE user_id=?
        """,
        (price, user_id)
    )
    conn.commit()

    config_text = "\n".join(links)

    cursor.execute(
        "UPDATE users SET config = ? WHERE user_id = ?",
        (config_text, user_id)
    )
    conn.commit()

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

    user_id = message.from_user.id

    cursor.execute(
        "SELECT trial_used FROM users WHERE user_id=?",
        (user_id,)
    )
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

    cursor.execute(
        "UPDATE users SET trial_used = 1 WHERE user_id = ?",
        (user_id,)
    )
    conn.commit()

    config_text = "\n".join(links)

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

`8673 2559 1411 6362`

امیر والا شریف نسب

بعد از پرداخت رسید را ارسال کنید. ادمین ما چک میکنه و پول به حساب شما میاد
""",
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda message: message.text == "اطلاعات من✨")
def my_info(message):
    user_id = message.from_user.id

    cursor.execute(
        "SELECT balance FROM users WHERE user_id = ?",
        (user_id,)
    )
    result = cursor.fetchone()

    balance = result[0] if result else 0

    bot.send_message(
        message.chat.id,
        f"""👤 اطلاعات حساب شما

🆔 شناسه: {user_id}

💰 موجودی کیف پول: {balance:,} تومان"""
    )

@bot.message_handler(func=lambda m: m.text == "پشتیبانی👇")
def support(message):
    bot.reply_to(message, "id admin = @valaorp")
# ================= ADMIN RECEIPT =================

@bot.message_handler(content_types=['photo'])
def receipt(message):

    bot.forward_message(
        ADMIN_ID,
        message.chat.id,
        message.message_id
    )

    bot.send_message(
        ADMIN_ID,
        f"""رسید جدید

نام:
{message.from_user.first_name}

آیدی:
{message.from_user.id}

برای شارژ حساب این کاربر دستور زیر رو بفرست:
/charge {message.from_user.id} <مبلغ>
مثال: /charge {message.from_user.id} 60000"""
    )

    bot.reply_to(
        message,
        "✅ رسید ارسال شد، پس از تایید ادمین موجودی شما شارژ می‌شود."
    )


# ================= ADMIN CHARGE COMMAND =================

@bot.message_handler(
    func=lambda m: m.text and m.text.startswith("/charge") and m.from_user.id == ADMIN_ID
)
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

    cursor.execute(
        "INSERT OR IGNORE INTO users(user_id) VALUES (?)",
        (target_id,)
    )
    cursor.execute(
        "UPDATE users SET balance = balance + ? WHERE user_id = ?",
        (amount, target_id)
    )
    conn.commit()

    cursor.execute("SELECT balance FROM users WHERE user_id=?", (target_id,))
    new_balance = cursor.fetchone()[0]

    bot.reply_to(message, f"✅ حساب {target_id} به مبلغ {amount:,} تومان شارژ شد.\nموجودی جدید: {new_balance:,} تومان")

    try:
        bot.send_message(target_id, f"✅ حساب شما به مبلغ {amount:,} تومان شارژ شد.\nموجودی جدید: {new_balance:,} تومان")
    except Exception:
        pass


# ================= ADMIN PANEL DIAGNOSTIC =================

@bot.message_handler(
    func=lambda m: m.text and m.text.startswith("/testpanel") and m.from_user.id == ADMIN_ID
)
def admin_test_panel(message):

    bot.reply_to(message, "⏳ در حال تست اتصال به پنل (۶ حالت)...")

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
                    ok = data.get("success", False)
                    mark = "✅" if ok else "⚠️"
                except Exception:
                    mark = "⚠️"
            else:
                mark = "❌"

            report_lines.append(
                f"{mark} {label}\nStatus: {status}\nPasokh: {snippet}\n"
            )

        except Exception as e:
            report_lines.append(f"❌ {label}\nError: {e}\n")

    full_report = "\n".join(report_lines)

    # تلگرام محدودیت طول پیام داره، اگه طولانی بود تیکه‌تیکه بفرست
    for i in range(0, len(full_report), 3500):
        bot.send_message(message.chat.id, full_report[i:i+3500])


# ================= ADMIN: DUMP USER JSON (برای پیدا کردن اسم فیلد سقف مصرف) =================

@bot.message_handler(
    func=lambda m: m.text and m.text.startswith("/dumpuser") and m.from_user.id == ADMIN_ID
)
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
        bot.reply_to(
            message,
            f"❌ کاربری با اسم '{target_name}' پیدا نشد.\n\nاسم‌های موجود (حداکثر ۳۰ تا):\n{names}"
        )
        return

    import json as _json
    dump = _json.dumps(matches[0], ensure_ascii=False, indent=2)

    for i in range(0, len(dump), 3500):
        bot.send_message(message.chat.id, f"```\n{dump[i:i+3500]}\n```", parse_mode="Markdown")


if __name__ == "__main__":
    bot.infinity_polling()

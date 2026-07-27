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

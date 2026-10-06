import os
import asyncio
import threading
import re

from flask import request, jsonify

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)

from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)

from api import app
from database import (
    init_db,
    create_or_update_user,
    update_deposit_status,
    update_exchange_status,
    update_withdrawal_status,
    update_premium_membership_status,
    get_dashboard_stats,
)


# ============================================================
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

WEB_APP_URL = "https://sharm363.github.io/TaskCoin/"

PORT = int(os.getenv("PORT", "10000"))

RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()

# Optional: if this bot also receives admin callback buttons,
# configure ADMIN_TELEGRAM_IDS as comma-separated Telegram IDs.
ADMIN_TELEGRAM_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",")
    if x.strip().isdigit()
}


# ============================================================
# USER / MAIN BOT
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Register the Telegram user and securely capture a referral deep-link."""

    telegram_user = update.effective_user

    # Telegram sends /start <payload> in context.args.
    # TaskCoin referral links use: https://t.me/TaskCoinEarnBot?start=<referrer_id>
    # The referral is saved server-side here, so it does not depend on
    # Telegram Mini App start_param being present in the WebView.
    referrer_id = None
    if context.args:
        raw_referrer = str(context.args[0] or "").strip()
        raw_referrer = re.sub(r"^ref_", "", raw_referrer, flags=re.IGNORECASE)
        if raw_referrer.isdigit():
            try:
                candidate = int(raw_referrer)
                if telegram_user and candidate != int(telegram_user.id):
                    referrer_id = candidate
            except (TypeError, ValueError):
                referrer_id = None

    if telegram_user:
        try:
            create_or_update_user(
                telegram_id=telegram_user.id,
                username=telegram_user.username,
                first_name=telegram_user.first_name,
                referrer_id=referrer_id,
            )
            if referrer_id:
                print(
                    f"User saved with referral: {telegram_user.id} "
                    f"<- {referrer_id}"
                )
            else:
                print(f"User saved: {telegram_user.id}")
        except Exception as exc:
            print(f"User save error: {exc}")

    keyboard = [[
        InlineKeyboardButton(
            "🚀 Open TaskCoin",
            web_app=WebAppInfo(url=WEB_APP_URL),
        )
    ]]

    await update.message.reply_text(
        "👋 Welcome to TaskCoin!\n\n"
        "🎯 Complete available tasks\n"
        "🪙 Earn TaskCoins\n"
        "💰 Manage your rewards\n\n"
        "Tap the button below to open TaskCoin.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ============================================================
# OPTIONAL ADMIN CALLBACK SUPPORT
# ============================================================

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process approve/reject callbacks when they belong to this bot.

    The normal TaskCoin Admin Bot may live in telegram_admin_bot.py.
    This handler is kept here so that, if the same bot token receives
    admin buttons, VIP/Deposit/Exchange/Withdrawal callbacks do not
    fall through to an 'Unknown request type' response.
    """

    query = update.callback_query
    if not query:
        return

    user = query.from_user
    if not user or user.id not in ADMIN_TELEGRAM_IDS:
        await query.answer("Not authorized.", show_alert=True)
        return

    data = query.data or ""

    try:
        parts = data.split(":")

        if len(parts) != 3 or parts[0] not in ("approve", "reject"):
            await query.answer("Unknown request type.", show_alert=True)
            return

        action, request_type, raw_id = parts
        request_id = int(raw_id)

        approved = action == "approve"

        if request_type == "deposit":
            status = "approved" if approved else "rejected"
            result = update_deposit_status(request_id, status)
            label = "Deposit"

        elif request_type == "exchange":
            status = "approved" if approved else "rejected"
            result = update_exchange_status(request_id, status)
            label = "Exchange"

        elif request_type == "withdrawal":
            status = "approved" if approved else "rejected"
            result = update_withdrawal_status(request_id, status)
            label = "Withdrawal"

        elif request_type == "premium":
            # Database uses 'active' for an approved Premium membership.
            status = "active" if approved else "rejected"
            result = update_premium_membership_status(request_id, status)
            label = "VIP / Premium"

        else:
            await query.answer("Unknown request type.", show_alert=True)
            return

        if not result or not result.get("success"):
            message = (result or {}).get("message", "Request processing failed.")
            await query.answer(message[:190], show_alert=True)
            return

        await query.answer(
            "Approved successfully." if approved else "Rejected successfully."
        )

        # Remove the action buttons after successful processing.
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

        if request_type == "premium":
            if approved:
                admin_text = (
                    f"✅ <b>{label} #{request_id} approved.</b>\n"
                    "The Premium membership is now active."
                )
            else:
                admin_text = (
                    f"❌ <b>{label} #{request_id} rejected.</b>\n"
                    "The reserved Deposit Balance has been refunded by the database."
                )
        else:
            admin_text = (
                f"{'✅' if approved else '❌'} <b>{label} #{request_id} "
                f"{'approved' if approved else 'rejected'} successfully.</b>"
            )

        await query.message.reply_text(admin_text)

    except Exception as exc:
        print(f"Admin callback error: {exc}")
        await query.answer("Processing error.", show_alert=True)


# ============================================================
# TELEGRAM WEBHOOK
# ============================================================

async def setup_bot(application: Application):
    await application.initialize()
    await application.start()

    webhook_url = f"{RENDER_EXTERNAL_URL}/telegram"

    await application.bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=False,
    )

    print(f"TaskCoin Bot webhook is ready: {webhook_url}")

    # Keep the async application alive while Flask serves the webhook.
    await asyncio.Event().wait()


def run_flask():
    print(f"TaskCoin API is starting on port {PORT}...")

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
    )


def main():
    # Initialize database.
    init_db()
    print("TaskCoin database initialized successfully.")

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is missing.")

    if not RENDER_EXTERNAL_URL:
        raise RuntimeError("RENDER_EXTERNAL_URL environment variable is missing.")

    if not WEBHOOK_SECRET:
        raise RuntimeError("WEBHOOK_SECRET environment variable is missing.")

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Main user command.
    application.add_handler(CommandHandler("start", start))

    # Support callback buttons if this bot receives them.
    application.add_handler(
        CallbackQueryHandler(
            admin_callback,
            pattern=r"^(approve|reject):(deposit|exchange|withdrawal|premium):\d+$",
        )
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    @app.route("/telegram", methods=["POST"])
    def telegram():
        # Telegram webhook secret validation.
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")

        if secret != WEBHOOK_SECRET:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), 403

        update_data = request.get_json(silent=True)
        if not update_data:
            return jsonify({
                "success": False,
                "message": "Invalid Telegram update",
            }), 400

        try:
            update = Update.de_json(
                update_data,
                application.bot,
            )

            asyncio.run_coroutine_threadsafe(
                application.update_queue.put(update),
                loop,
            )

            return jsonify({"success": True})

        except Exception as exc:
            print(f"Telegram webhook error: {exc}")
            return jsonify({
                "success": False,
                "message": "Webhook processing failed",
            }), 500

    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True,
    )
    flask_thread.start()

    print("TaskCoin Bot + API is starting...")

    loop.run_until_complete(setup_bot(application))


if __name__ == "__main__":
    main()

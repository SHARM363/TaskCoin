import os
import asyncio
import threading

from flask import request, jsonify

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo
)

from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)

from api import app
from database import init_db


BOT_TOKEN = os.getenv("BOT_TOKEN")

WEB_APP_URL = "https://sharm363.github.io/TaskCoin/"

PORT = int(os.getenv("PORT", "10000"))

RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    keyboard = [
        [
            InlineKeyboardButton(
                "🚀 Open TaskCoin",
                web_app=WebAppInfo(
                    url=WEB_APP_URL
                )
            )
        ]
    ]

    reply_markup = InlineKeyboardMarkup(
        keyboard
    )

    await update.message.reply_text(
        "👋 Welcome to TaskCoin!\n\n"
        "🎯 Complete available tasks\n"
        "🪙 Earn TaskCoins\n"
        "💰 Manage your rewards\n\n"
        "Tap the button below to open TaskCoin.",
        reply_markup=reply_markup
    )


async def setup_bot(application):

    await application.initialize()

    await application.start()

    await application.bot.set_webhook(
        url=f"{RENDER_EXTERNAL_URL}/telegram",
        secret_token=WEBHOOK_SECRET
    )

    print("TaskCoin Bot webhook is ready.")

    await asyncio.Event().wait()


def run_flask():

    print(
        f"TaskCoin API is starting on port {PORT}..."
    )

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False
    )


def main():

    init_db()

    print(
        "TaskCoin database initialized successfully."
    )

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    if not RENDER_EXTERNAL_URL:
        raise RuntimeError(
            "RENDER_EXTERNAL_URL environment variable is missing."
        )

    if not WEBHOOK_SECRET:
        raise RuntimeError(
            "WEBHOOK_SECRET environment variable is missing."
        )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    loop = asyncio.new_event_loop()

    asyncio.set_event_loop(loop)

    @app.route(
        "/telegram",
        methods=["POST"]
    )
    def telegram():

        secret = request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token"
        )

        if secret != WEBHOOK_SECRET:

            return jsonify({
                "success": False,
                "message": "Unauthorized"
            }), 403

        update_data = request.get_json(
            force=True
        )

        update = Update.de_json(
            update_data,
            application.bot
        )

        asyncio.run_coroutine_threadsafe(
            application.update_queue.put(update),
            loop
        )

        return jsonify({
            "success": True
        })

    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()

    print(
        "TaskCoin Bot + API is starting..."
    )

    loop.run_until_complete(
        setup_bot(application)
    )


if __name__ == "__main__":

    main()

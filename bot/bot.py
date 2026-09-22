import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes


BOT_TOKEN = os.getenv("BOT_TOKEN")

WEB_APP_URL = "https://sharm363.github.io/TaskCoin/"

PORT = int(os.getenv("PORT", "10000"))

RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [
            InlineKeyboardButton(
                "🚀 Open TaskCoin",
                web_app=WebAppInfo(url=WEB_APP_URL)
            )
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "👋 Welcome to TaskCoin!\n\n"
        "🎯 Complete available tasks\n"
        "🪙 Earn TaskCoins\n"
        "💰 Manage your rewards\n\n"
        "Tap the button below to open TaskCoin.",
        reply_markup=reply_markup
    )


def main():

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

    application.add_handler(
        CommandHandler("start", start)
    )

    print("TaskCoin Bot is starting with webhook...")

    application.run_webhook(
    listen="0.0.0.0",
    port=PORT,
    url_path="telegram",
    webhook_url=f"{RENDER_EXTERNAL_URL}/telegram",
    secret_token=WEBHOOK_SECRET
)


if __name__ == "__main__":
    main()

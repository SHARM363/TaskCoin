import os
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes


BOT_TOKEN = os.getenv("BOT_TOKEN")

WEB_APP_URL = "https://sharm363.github.io/TaskCoin/"


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


async def main():

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is missing.")

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    print("TaskCoin Bot is running...")

    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    try:
        await asyncio.Event().wait()
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

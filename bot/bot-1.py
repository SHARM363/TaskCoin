import os
import json
import time
import threading
from urllib import request as urlrequest
from urllib import parse as urlparse

from database import (
    init_db,
    get_all_deposits,
    get_all_exchanges,
    get_all_withdrawals,
    update_deposit_status,
    update_exchange_status,
    update_withdrawal_status,
    update_premium_membership_status,
    get_user,
    get_dashboard_stats,
)

BOT_TOKEN = os.getenv("TELEGRAM_ADMIN_BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(x.strip()) for x in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",")
    if x.strip().isdigit()
}

API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
_stop = False


def _telegram(method, payload=None):
    if not API:
        return {"ok": False, "description": "TELEGRAM_ADMIN_BOT_TOKEN is missing"}
    data = urlparse.urlencode(payload or {}).encode()
    req = urlrequest.Request(f"{API}/{method}", data=data, method="POST")
    try:
        with urlrequest.urlopen(req, timeout=35) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        print(f"Telegram API error: {method}: {exc}")
        return {"ok": False, "description": str(exc)}


def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": str(chat_id), "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    return _telegram("sendMessage", payload)


def answer_callback(callback_id, text=""):
    return _telegram("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def notify_admins(text, reply_markup=None):
    for admin_id in ADMIN_IDS:
        send_message(admin_id, text, reply_markup)


def _money(v):
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return str(v)


def main_menu():
    return {
        "inline_keyboard": [
            [{"text": "💰 Deposit Requests", "callback_data": "list:deposit"}],
            [{"text": "🔄 Exchange Requests", "callback_data": "list:exchange"}],
            [{"text": "💸 Withdrawal Requests", "callback_data": "list:withdrawal"}],
            [{"text": "📊 Statistics", "callback_data": "stats"}],
        ]
    }


def is_admin(user_id):
    return user_id in ADMIN_IDS


def pending_items(kind):
    if kind == "deposit":
        return [x for x in get_all_deposits() if str(x.get("status")) == "pending"][:20]
    if kind == "exchange":
        return [x for x in get_all_exchanges() if str(x.get("status")) == "pending"][:20]
    return [x for x in get_all_withdrawals() if str(x.get("status")) == "pending"][:20]


def format_item(kind, row):
    user_id = row.get("telegram_id")
    if kind == "deposit":
        return (
            f"💰 <b>Deposit #{row['id']}</b>\n"
            f"User: <code>{user_id}</code>\n"
            f"Method: {row.get('method')}\n"
            f"Amount: <b>{_money(row.get('amount'))}</b>\n"
            f"TXID: <code>{row.get('transaction_id')}</code>\n"
            f"Status: {row.get('status')}"
        )
    if kind == "exchange":
        return (
            f"🔄 <b>Exchange #{row['id']}</b>\n"
            f"User: <code>{user_id}</code>\n"
            f"Coins: <b>{_money(row.get('coin_amount'))}</b>\n"
            f"Cash: <b>{_money(row.get('cash_amount'))} BDT</b>\n"
            f"Status: {row.get('status')}"
        )
    return (
        f"💸 <b>Withdrawal #{row['id']}</b>\n"
        f"User: <code>{user_id}</code>\n"
        f"Source: <b>{row.get('source', 'task')}</b>\n"
        f"Method: {row.get('method')}\n"
        f"Account: <code>{row.get('account_number')}</code>\n"
        f"Amount: <b>{_money(row.get('amount'))}</b>\n"
        f"Status: {row.get('status')}"
    )


def send_list(chat_id, kind):
    items = pending_items(kind)
    title = {"deposit": "💰 Pending Deposits", "exchange": "🔄 Pending Exchanges", "withdrawal": "💸 Pending Withdrawals"}[kind]
    if not items:
        send_message(chat_id, f"{title}\n\nNo pending requests.", main_menu())
        return
    for row in items:
        if kind == "deposit":
            cb = f"deposit:{row['id']}"
        elif kind == "exchange":
            cb = f"exchange:{row['id']}"
        else:
            cb = f"withdrawal:{row['id']}"
        send_message(chat_id, format_item(kind, row), {
            "inline_keyboard": [[
                {"text": "✅ Approve", "callback_data": f"approve:{cb}"},
                {"text": "❌ Reject", "callback_data": f"reject:{cb}"},
            ]]
        })
    send_message(chat_id, "Select another section:", main_menu())


def handle_callback(cb):
    data = cb.get("data", "")
    chat_id = cb.get("message", {}).get("chat", {}).get("id")
    user_id = cb.get("from", {}).get("id")
    callback_id = cb.get("id")
    if not is_admin(user_id):
        answer_callback(callback_id, "Not authorized.")
        return
    try:
        if data.startswith("list:"):
            answer_callback(callback_id)
            send_list(chat_id, data.split(":", 1)[1])
            return
        if data == "stats":
            stats = get_dashboard_stats()
            answer_callback(callback_id)
            send_message(chat_id, "📊 <b>TaskCoin Statistics</b>\n\n" + "\n".join(
                f"{k}: <b>{v}</b>" for k, v in dict(stats).items()
            ), main_menu())
            return
        action, kind, raw_id = data.split(":")
        item_id = int(raw_id)
        status = "approved" if action == "approve" else "rejected"
        if kind == "deposit":
            result = update_deposit_status(item_id, status)
        elif kind == "exchange":
            result = update_exchange_status(item_id, status)
        elif kind == "withdrawal":
            result = update_withdrawal_status(item_id, status)
        elif kind == "premium":
            # Premium request callbacks use approve:premium:<membership_id>
            # and reject:premium:<membership_id>. On rejection the database
            # function automatically refunds the reserved Deposit Balance.
            premium_status = "active" if action == "approve" else "rejected"
            result = update_premium_membership_status(item_id, premium_status)
        else:
            result = {"success": False, "message": "Unknown request type."}
        if not result.get("success"):
            answer_callback(callback_id, result.get("message", "Failed"))
            return
        answer_callback(callback_id, f"{status.title()} successfully")
        send_message(chat_id, f"✅ {kind.title()} #{item_id} <b>{status}</b> successfully.", main_menu())
        # Notify the user when a request is processed.
        row = result.get(kind) or result.get("withdrawal") or result.get("exchange") or result.get("deposit") or result.get("membership")
        if row and row.get("telegram_id"):
            if kind == "deposit":
                text = f"💰 Deposit #{item_id} has been <b>{status}</b>."
            elif kind == "exchange":
                text = f"🔄 Exchange #{item_id} has been <b>{status}</b>."
            elif kind == "withdrawal":
                text = f"💸 Withdrawal #{item_id} has been <b>{status}</b>."
            elif kind == "premium":
                if status == "approved":
                    text = f"💎 Premium request #{item_id} has been <b>approved</b>. Your VIP membership is now active."
                else:
                    text = f"💎 Premium request #{item_id} has been <b>rejected</b>. Your Deposit Balance has been refunded."
            else:
                text = f"Request #{item_id} has been <b>{status}</b>."
            send_message(row["telegram_id"], text)
    except Exception as exc:
        answer_callback(callback_id, "Processing error.")
        print("callback error:", exc)


def handle_message(message):
    chat = message.get("chat", {})
    user = message.get("from", {})
    chat_id = chat.get("id")
    user_id = user.get("id")
    text = (message.get("text") or "").strip()
    if text == "/id":
        send_message(chat_id, f"Your Telegram ID: <code>{user_id}</code>")
        return
    if not is_admin(user_id):
        send_message(chat_id, "⛔ Access denied. This bot is for the configured admin only.")
        return
    if text in ("/start", "/menu", "🏠 Menu"):
        send_message(chat_id, "🤖 <b>TaskCoin Admin Bot</b>\nChoose an action:", main_menu())
    elif text == "/deposits":
        send_list(chat_id, "deposit")
    elif text == "/exchanges":
        send_list(chat_id, "exchange")
    elif text == "/withdrawals":
        send_list(chat_id, "withdrawal")
    elif text == "/stats":
        stats = get_dashboard_stats()
        send_message(chat_id, "📊 <b>Statistics</b>\n\n" + "\n".join(f"{k}: <b>{v}</b>" for k, v in dict(stats).items()), main_menu())
    else:
        send_message(chat_id, "Use /start to open the admin menu.", main_menu())


def poll():
    global _stop
    offset = None
    while not _stop:
        try:
            payload = {"timeout": 25, "allowed_updates": json.dumps(["message", "callback_query"])}
            if offset is not None:
                payload["offset"] = offset
            result = _telegram("getUpdates", payload)
            for update in result.get("result", []) if result.get("ok") else []:
                offset = update["update_id"] + 1
                if update.get("callback_query"):
                    handle_callback(update["callback_query"])
                elif update.get("message"):
                    handle_message(update["message"])
        except Exception as exc:
            print("Telegram polling error:", exc)
            time.sleep(5)


def start_bot():
    if not BOT_TOKEN:
        print("Telegram Admin Bot disabled: TELEGRAM_ADMIN_BOT_TOKEN is not set.")
        return None
    if not ADMIN_IDS:
        print("Telegram Admin Bot disabled: ADMIN_TELEGRAM_IDS is not set.")
        return None
    init_db()
    thread = threading.Thread(target=poll, name="telegram-admin-bot", daemon=True)
    thread.start()
    print("Telegram Admin Bot started.")
    return thread


if __name__ == "__main__":
    start_bot()
    while True:
        time.sleep(3600)

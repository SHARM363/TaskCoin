import os
import json
import time
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
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
    get_user,
    get_dashboard_stats,
    get_premium_membership_requests,
    update_premium_membership_status,
)

BOT_TOKEN = os.getenv("TELEGRAM_ADMIN_BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",")
    if x.strip().isdigit()
}

API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""

# Public channel used for transparent, anonymized withdrawal payment proofs.
# The admin bot must be an administrator of this public channel with
# permission to post/manage messages.
PAYMENT_PROOF_CHANNEL = os.getenv(
    "PAYMENT_PROOF_CHANNEL",
    "@TaskCoinPaymentProof",
).strip()

DHAKA_TZ = ZoneInfo("Asia/Dhaka")
_stop = False


def _telegram(method, payload=None):
    if not API:
        return {
            "ok": False,
            "description": "TELEGRAM_ADMIN_BOT_TOKEN is missing",
        }

    data = urlparse.urlencode(payload or {}).encode()
    req = urlrequest.Request(
        f"{API}/{method}",
        data=data,
        method="POST",
    )

    try:
        with urlrequest.urlopen(req, timeout=35) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"Telegram API error: {method}: {exc}")
        return {"ok": False, "description": str(exc)}


def send_message(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": str(chat_id),
        "text": text,
        "parse_mode": "HTML",
    }

    if reply_markup:
        payload["reply_markup"] = json.dumps(
            reply_markup,
            ensure_ascii=False,
        )

    return _telegram("sendMessage", payload)


def answer_callback(callback_id, text=""):
    return _telegram(
        "answerCallbackQuery",
        {
            "callback_query_id": callback_id,
            "text": text,
        },
    )


def notify_admins(text, reply_markup=None):
    for admin_id in ADMIN_IDS:
        send_message(admin_id, text, reply_markup)


def _mask_account(value):
    """Hide the user payment account from the public channel."""
    raw = str(value or "").strip()
    if not raw:
        return "Hidden"
    if len(raw) <= 4:
        return "****"
    return "*" * max(4, len(raw) - 4) + raw[-4:]


def _publish_withdrawal_proof(row):
    """Publish one anonymized successful withdrawal to the public proof channel.

    This is deliberately called only after the database has successfully
    changed the withdrawal to ``approved``. A channel-post failure must not
    undo the financial database transaction; it is reported to the admin.
    """
    if not PAYMENT_PROOF_CHANNEL:
        return {
            "ok": False,
            "description": "PAYMENT_PROOF_CHANNEL is empty",
        }

    method = str(row.get("method") or "Payment").strip()
    amount = _money(row.get("amount"))
    withdrawal_id = row.get("id")
    account = _mask_account(row.get("account_number"))
    source = str(row.get("source") or "task").strip()
    date_text = datetime.now(DHAKA_TZ).strftime("%d %B %Y")

    text = (
        "✅ <b>TaskCoin Payment Successful</b>\n\n"
        f"🧾 Withdrawal: <b>#{withdrawal_id}</b>\n"
        f"💰 Amount: <b>৳{amount}</b>\n"
        f"💳 Method: <b>{method}</b>\n"
        f"🔐 Account: <code>{account}</code>\n"
        f"📅 Date: <b>{date_text}</b>\n"
        f"📌 Type: <b>{source.title()} Balance</b>\n"
        "\n"
        "🎉 <b>Payment has been successfully processed.</b>\n"
        "\n"
        "ℹ️ Personal Telegram ID and full payment account details are hidden for privacy."
    )

    return send_message(PAYMENT_PROOF_CHANNEL, text)


def _money(value):
    try:
        return f"{float(value):,.2f}"
    except Exception:
        return str(value)


def main_menu():
    return {
        "inline_keyboard": [
            [
                {
                    "text": "💰 Deposit Requests",
                    "callback_data": "list:deposit",
                }
            ],
            [
                {
                    "text": "💎 VIP / Premium Requests",
                    "callback_data": "list:premium",
                }
            ],
            [
                {
                    "text": "🔄 Exchange Requests",
                    "callback_data": "list:exchange",
                }
            ],
            [
                {
                    "text": "💸 Withdrawal Requests",
                    "callback_data": "list:withdrawal",
                }
            ],
            [
                {
                    "text": "📊 Statistics",
                    "callback_data": "stats",
                }
            ],
        ]
    }


def is_admin(user_id):
    return user_id in ADMIN_IDS


def pending_items(kind):
    if kind == "deposit":
        return [
            item
            for item in get_all_deposits()
            if str(item.get("status")) == "pending"
        ][:20]

    if kind == "exchange":
        return [
            item
            for item in get_all_exchanges()
            if str(item.get("status")) == "pending"
        ][:20]

    if kind == "withdrawal":
        return [
            item
            for item in get_all_withdrawals()
            if str(item.get("status")) == "pending"
        ][:20]

    if kind == "premium":
        return list(
            get_premium_membership_requests("pending")
        )[:20]

    return []


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

    if kind == "withdrawal":
        return (
            f"💸 <b>Withdrawal #{row['id']}</b>\n"
            f"User: <code>{user_id}</code>\n"
            f"Source: <b>{row.get('source', 'task')}</b>\n"
            f"Method: {row.get('method')}\n"
            f"Account: <code>{row.get('account_number')}</code>\n"
            f"Amount: <b>{_money(row.get('amount'))}</b>\n"
            f"Status: {row.get('status')}"
        )

    if kind == "premium":
        price = row.get("price_paid")
        if price is None:
            price = row.get("price")

        return (
            f"💎 <b>VIP / Premium Request #{row['id']}</b>\n"
            f"User: <code>{user_id}</code>\n"
            f"VIP Level: <b>{row.get('level')}</b>\n"
            f"Price: <b>৳{_money(price)}</b>\n"
            f"Duration: <b>{row.get('duration_days')} days</b>\n"
            f"Bonus Website Tasks: "
            f"<b>{row.get('bonus_website_tasks', 0)}</b>\n"
            f"Status: {row.get('status')}"
        )

    return f"Unknown request type: {kind}"


def send_list(chat_id, kind):
    allowed = {
        "deposit",
        "premium",
        "exchange",
        "withdrawal",
    }

    if kind not in allowed:
        send_message(
            chat_id,
            "❌ Unknown request type.",
            main_menu(),
        )
        return

    items = pending_items(kind)

    title = {
        "deposit": "💰 Pending Deposits",
        "premium": "💎 Pending VIP / Premium Requests",
        "exchange": "🔄 Pending Exchanges",
        "withdrawal": "💸 Pending Withdrawals",
    }[kind]

    if not items:
        send_message(
            chat_id,
            f"{title}\n\nNo pending requests.",
            main_menu(),
        )
        return

    for row in items:
        callback_data = f"{kind}:{row['id']}"

        send_message(
            chat_id,
            format_item(kind, row),
            {
                "inline_keyboard": [
                    [
                        {
                            "text": (
                                "✅ Approve / Paid"
                                if kind == "withdrawal"
                                else "✅ Approve"
                            ),
                            "callback_data": f"approve:{callback_data}",
                        },
                        {
                            "text": "❌ Reject",
                            "callback_data": f"reject:{callback_data}",
                        },
                    ]
                ],
            },
        )

    send_message(
        chat_id,
        "Select another section:",
        main_menu(),
    )


def handle_premium_action(
    callback_id,
    chat_id,
    action,
    item_id,
):
    if action == "approve":
        new_status = "active"
    else:
        new_status = "rejected"

    try:
        result = update_premium_membership_status(
            item_id,
            new_status,
            reason=(
                "Rejected by admin."
                if action == "reject"
                else None
            ),
        )
    except TypeError:
        # Compatibility with an older database.py signature.
        result = update_premium_membership_status(
            item_id,
            new_status,
        )

    if not result.get("success"):
        answer_callback(
            callback_id,
            result.get("message", "Failed"),
        )
        return

    membership = result.get("membership") or {}

    telegram_id = membership.get("telegram_id")
    if telegram_id is None:
        telegram_id = result.get("telegram_id")

    if action == "approve":
        answer_callback(
            callback_id,
            "VIP approved successfully",
        )

        send_message(
            chat_id,
            (
                f"💎 VIP / Premium #{item_id} "
                f"<b>approved successfully.</b>\n\n"
                f"VIP Level: <b>{membership.get('level', '')}</b>\n"
                f"Duration: <b>{membership.get('duration_days', '')} days</b>"
            ),
            main_menu(),
        )

        if telegram_id:
            send_message(
                telegram_id,
                (
                    "🎉 <b>Your VIP / Premium membership "
                    "has been approved!</b>\n\n"
                    f"💎 VIP Level: "
                    f"<b>{membership.get('level', '')}</b>\n"
                    f"📅 Duration: "
                    f"<b>{membership.get('duration_days', '')} days</b>\n"
                    f"⏳ Expires: "
                    f"<b>{membership.get('expires_at', '')}</b>"
                ),
            )

    else:
        answer_callback(
            callback_id,
            "VIP rejected and refunded",
        )

        send_message(
            chat_id,
            (
                f"❌ VIP / Premium #{item_id} "
                f"<b>rejected.</b>\n\n"
                "💰 Purchase amount has been refunded "
                "to the user's Deposit Balance."
            ),
            main_menu(),
        )

        if telegram_id:
            send_message(
                telegram_id,
                (
                    "❌ <b>Your VIP / Premium request "
                    "was rejected.</b>\n\n"
                    "💰 The purchase amount has been "
                    "refunded to your Deposit Balance."
                ),
            )


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
            kind = data.split(":", 1)[1]

            if kind not in {
                "deposit",
                "premium",
                "exchange",
                "withdrawal",
            }:
                answer_callback(
                    callback_id,
                    "Unknown request type.",
                )
                return

            answer_callback(callback_id)
            send_list(chat_id, kind)
            return

        if data == "stats":
            stats = get_dashboard_stats()

            answer_callback(callback_id)

            send_message(
                chat_id,
                "📊 <b>TaskCoin Statistics</b>\n\n"
                + "\n".join(
                    f"{key}: <b>{value}</b>"
                    for key, value in dict(stats).items()
                ),
                main_menu(),
            )
            return

        parts = data.split(":")

        if len(parts) != 3:
            answer_callback(
                callback_id,
                "Invalid request action.",
            )
            return

        action, kind, raw_id = parts

        if action not in {"approve", "reject"}:
            answer_callback(
                callback_id,
                "Invalid action.",
            )
            return

        item_id = int(raw_id)

        # VIP / Premium requests are handled separately.
        # The request callback is:
        # approve:premium:<membership_id>
        # reject:premium:<membership_id>
        if kind == "premium":
            handle_premium_action(
                callback_id,
                chat_id,
                action,
                item_id,
            )
            return

        status = (
            "approved"
            if action == "approve"
            else "rejected"
        )

        if kind == "deposit":
            result = update_deposit_status(
                item_id,
                status,
            )

        elif kind == "exchange":
            result = update_exchange_status(
                item_id,
                status,
            )

        elif kind == "withdrawal":
            result = update_withdrawal_status(
                item_id,
                status,
            )

        else:
            answer_callback(
                callback_id,
                "Unknown request type.",
            )
            return

        if not result.get("success"):
            answer_callback(
                callback_id,
                result.get("message", "Failed"),
            )
            return

        answer_callback(
            callback_id,
            f"{status.title()} successfully",
        )

        send_message(
            chat_id,
            (
                f"✅ {kind.title()} #{item_id} "
                f"<b>{status}</b> successfully."
            ),
            main_menu(),
        )

        row = (
            result.get(kind)
            or result.get("withdrawal")
            or result.get("exchange")
            or result.get("deposit")
        )

        if row and row.get("telegram_id"):
            if kind == "deposit":
                text = (
                    f"💰 Deposit #{item_id} has been "
                    f"<b>{status}</b>."
                )
            elif kind == "exchange":
                text = (
                    f"🔄 Exchange #{item_id} has been "
                    f"<b>{status}</b>."
                )
            else:
                text = (
                    f"💸 Withdrawal #{item_id} has been "
                    f"<b>{status}</b>."
                )

            send_message(
                row["telegram_id"],
                text,
            )

        # A withdrawal marked approved is treated as paid. Publish an
        # anonymized proof only for successful withdrawal approvals.
        if kind == "withdrawal" and status == "approved" and row:
            proof_result = _publish_withdrawal_proof(row)
            if proof_result.get("ok"):
                send_message(
                    chat_id,
                    (
                        f"📢 <b>Payment proof published.</b>\n"
                        f"Withdrawal #{item_id} is now visible in "
                        f"{PAYMENT_PROOF_CHANNEL}."
                    ),
                    main_menu(),
                )
            else:
                error_text = proof_result.get(
                    "description",
                    "Unknown Telegram error",
                )
                send_message(
                    chat_id,
                    (
                        f"⚠️ <b>Withdrawal #{item_id} was approved, "
                        "but the public payment proof could not be posted.</b>\n\n"
                        f"Channel: <code>{PAYMENT_PROOF_CHANNEL}</code>\n"
                        f"Reason: <code>{error_text}</code>"
                    ),
                    main_menu(),
                )

    except ValueError:
        answer_callback(
            callback_id,
            "Invalid request ID.",
        )

    except Exception as exc:
        answer_callback(
            callback_id,
            "Processing error.",
        )
        print("callback error:", exc)


def handle_message(message):
    chat = message.get("chat", {})
    user = message.get("from", {})
    chat_id = chat.get("id")
    user_id = user.get("id")
    text = (message.get("text") or "").strip()

    if text == "/id":
        send_message(
            chat_id,
            f"Your Telegram ID: <code>{user_id}</code>",
        )
        return

    if not is_admin(user_id):
        send_message(
            chat_id,
            (
                "⛔ Access denied. "
                "This bot is for the configured admin only."
            ),
        )
        return

    if text in ("/start", "/menu", "🏠 Menu"):
        send_message(
            chat_id,
            "🤖 <b>TaskCoin Admin Bot</b>\nChoose an action:",
            main_menu(),
        )

    elif text == "/deposits":
        send_list(chat_id, "deposit")

    elif text in ("/premium", "/vip"):
        send_list(chat_id, "premium")

    elif text == "/exchanges":
        send_list(chat_id, "exchange")

    elif text == "/withdrawals":
        send_list(chat_id, "withdrawal")

    elif text == "/stats":
        stats = get_dashboard_stats()

        send_message(
            chat_id,
            "📊 <b>Statistics</b>\n\n"
            + "\n".join(
                f"{key}: <b>{value}</b>"
                for key, value in dict(stats).items()
            ),
            main_menu(),
        )

    else:
        send_message(
            chat_id,
            "Use /start to open the admin menu.",
            main_menu(),
        )


def poll():
    global _stop
    offset = None

    while not _stop:
        try:
            payload = {
                "timeout": 25,
                "allowed_updates": json.dumps(
                    [
                        "message",
                        "callback_query",
                    ]
                ),
            }

            if offset is not None:
                payload["offset"] = offset

            result = _telegram(
                "getUpdates",
                payload,
            )

            for update in (
                result.get("result", [])
                if result.get("ok")
                else []
            ):
                offset = update["update_id"] + 1

                if update.get("callback_query"):
                    handle_callback(
                        update["callback_query"]
                    )

                elif update.get("message"):
                    handle_message(
                        update["message"]
                    )

        except Exception as exc:
            print(
                "Telegram polling error:",
                exc,
            )
            time.sleep(5)


def start_bot():
    if not BOT_TOKEN:
        print(
            "Telegram Admin Bot disabled: "
            "TELEGRAM_ADMIN_BOT_TOKEN is not set."
        )
        return None

    if not ADMIN_IDS:
        print(
            "Telegram Admin Bot disabled: "
            "ADMIN_TELEGRAM_IDS is not set."
        )
        return None

    init_db()

    thread = threading.Thread(
        target=poll,
        name="telegram-admin-bot",
        daemon=True,
    )

    thread.start()

    print(
        "Telegram Admin Bot started."
    )

    return thread


if __name__ == "__main__":
    start_bot()

    while True:
        time.sleep(3600)

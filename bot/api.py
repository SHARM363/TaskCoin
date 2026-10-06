WITHDRAW_MIN = 500
WITHDRAW_MAX = 25000
EXCHANGE_FEE_PERCENT = 3
import os
import hmac

from flask import Flask, jsonify, request
from flask_cors import CORS

from telegram_admin_bot import start_bot, notify_admins
from database import (

    get_user,
    get_all_users,
    create_or_update_user,
    create_deposit,
    get_user_deposits,
    get_all_deposits,
    update_deposit_status,
    get_deposit_payment_settings,
    update_deposit_payment_setting,
    start_task,
    process_adgem_conversion,
    process_monetag_postback,
    process_cpagrip_postback,

    get_active_tasks,
    get_active_tasks_for_user,
    get_all_tasks,
    create_task,
    update_task,
    delete_task,
    claim_task_reward,

    create_withdrawal,
    create_exchange_request,
    get_user_exchanges,
    get_all_exchanges,
    update_exchange_status,
    get_user_withdrawals,
    get_all_withdrawals,
    update_withdrawal_status,
    get_public_withdrawal_proofs,
    get_public_withdrawal_stats,

    get_user_referrals,
    get_referral_requests,
    process_referral_request,
    admin_give_referral_bonus,
    transfer_taskcoins,

    # VIP / Premium Membership
    get_premium_plans,
    get_premium_plan,
    get_active_premium,
    get_user_premium_memberships,
    purchase_premium,
    get_premium_membership_requests,
    update_premium_membership_status,
    get_premium_daily_status,
    get_daily_task_limits,
    get_connection,

    get_lucky_spin_config,
    lucky_spin,
    update_lucky_spin_prize,

    get_admin_by_username,
    create_admin_session,
    get_admin_by_token,
    delete_admin_session,
    update_admin_last_login,
    get_dashboard_stats,
    init_db
)

app = Flask(__name__)

# TaskCoin Characters / Character Marketplace
try:
    from character_api import character_bp
    app.register_blueprint(character_bp)
except Exception as exc:
    print("Character API registration failed:", exc)

# Start the private Telegram Admin Bot in the same Render service.
# Configure TELEGRAM_ADMIN_BOT_TOKEN and ADMIN_TELEGRAM_IDS in Render.
try:
    init_db()
except Exception as exc:
    print("Database initialization failed:", exc)
try:
    start_bot()
except Exception as exc:
    print("Telegram Admin Bot startup failed:", exc)
CORS(
    app,
    resources={
        r"/api/*": {
            "origins": [
                "https://sharm363.github.io"
            ]
        }
    }
)

# ============================================================
# BASIC API
# ============================================================


@app.route("/api/exchange/quote", methods=["GET"])
def exchange_quote():
    """Quote main-balance BDT exchange with a fixed 3% fee."""
    try:
        amount = float(request.args.get("amount", "0"))
        if amount <= 0:
            return jsonify({"success": False, "message": "Invalid amount"}), 400
        fee = round(amount * 0.03, 2)
        net = round(amount - fee, 2)
        return jsonify({
            "success": True,
            "gross": amount,
            "fee_percent": 3,
            "fee": fee,
            "net_bdt": net,
            "currency": "BDT",
            "balance_source": "main"
        })
    except Exception:
        return jsonify({"success": False, "message": "Invalid amount"}), 400

@app.route("/")
def home():

    return jsonify({
        "success": True,
        "message": "TaskCoin API is working"
    })


@app.route("/api/test")
def api_test():

    return jsonify({
        "success": True,
        "message": "TaskCoin API test successful"
    })


# ============================================================
# USER API
# ============================================================

@app.route("/api/user")
def api_user():

    telegram_id = request.args.get(
        "telegram_id"
    )

    if not telegram_id:

        return jsonify({
            "success": False,
            "message":
                "telegram_id is required"
        }), 400

    try:

        telegram_id = int(
            telegram_id
        )

    except (ValueError, TypeError):

        return jsonify({
            "success": False,
            "message":
                "Invalid telegram_id"
        }), 400

    user = get_user(
        telegram_id
    )

    if not user:

        return jsonify({
            "success": False,
            "message":
                "User not found"
        }), 404

    return jsonify({
        "success": True,
        "user": dict(user)
    })


@app.route(
    "/api/user/create",
    methods=["POST"]
)
def create_user():

    data = request.get_json(
        silent=True
    ) or {}

    telegram_id = data.get(
        "telegram_id"
    )

    username = data.get(
        "username"
    )

    first_name = data.get(
        "first_name"
    )

    referrer_id = data.get("referrer_id")

    if not telegram_id:

        return jsonify({
            "success": False,
            "message":
                "telegram_id is required"
        }), 400

    try:

        telegram_id = int(
            telegram_id
        )

    except (ValueError, TypeError):

        return jsonify({
            "success": False,
            "message":
                "Invalid telegram_id"
        }), 400

    try:

        user = create_or_update_user(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            referrer_id=referrer_id,
            signup_ip=(request.headers.get("X-Forwarded-For", request.remote_addr) or "").split(",")[0].strip()
        )

        if referrer_id and int(referrer_id) != telegram_id:
            try:
                pending = get_referral_requests("pending")
                req = next((dict(x) for x in pending if int(x.get("referred_id")) == telegram_id), None)
                if req:
                    notify_admins(
                        "👥 <b>New Referral Approval Request</b>\n"
                        f"Referrer: <code>{req.get('referrer_id')}</code>\n"
                        f"Referred User: <code>{req.get('referred_id')}</code>\n"
                        f"Bonus: <b>{float(req.get('reward') or 500):,.2f} TaskCoins</b>\n\n"
                        "Open Admin Panel → 🎁 Referral Bonus to approve or reject."
                    )
            except Exception:
                app.logger.exception("Failed to notify admins about referral request")

        return jsonify({
            "success": True,
            "message": "User created/updated successfully",
            "user": dict(user)
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "message":
                "Database error",
            "error": str(e)
        }), 500


@app.route("/api/tasks/start", methods=["POST"])
def api_start_task():
    data=request.get_json(silent=True) or {}
    try:
        telegram_id=int(data.get("telegram_id")); task_id=int(data.get("task_id"))
    except (TypeError,ValueError):
        return jsonify({"success":False,"message":"Invalid task start data."}),400
    try: return jsonify(start_task(telegram_id,task_id))
    except Exception as e: return jsonify({"success":False,"message":"Failed to start task.","error":str(e)}),500


# ============================================================
# TASK API
# ============================================================

@app.route("/api/tasks")
def api_tasks():

    try:
        telegram_id = int(request.args.get("telegram_id"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "telegram_id is required."}), 400

    try:

        tasks = get_active_tasks_for_user(telegram_id)

        return jsonify({
            "success": True,
            "tasks": [
                dict(task)
                for task in tasks
            ]
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "message":
                "Failed to load tasks",
            "error": str(e)
        }), 500


# ============================================================
# CLAIM TASK
# ============================================================

@app.route(
    "/api/tasks/claim",
    methods=["POST"]
)
def api_claim_task():

    data = request.get_json(
        silent=True
    ) or {}

    telegram_id = data.get(
        "telegram_id"
    )

    task_id = data.get(
        "task_id"
    )

    if not telegram_id or not task_id:

        return jsonify({
            "success": False,
            "message":
                "telegram_id and task_id are required"
        }), 400

    try:

        telegram_id = int(
            telegram_id
        )

        task_id = int(
            task_id
        )

    except (ValueError, TypeError):

        return jsonify({
            "success": False,
            "message":
                "Invalid telegram_id or task_id"
        }), 400

    try:

        result = claim_task_reward(
            telegram_id,
            task_id
        )

        return jsonify(result)

    except Exception as e:

        return jsonify({
            "success": False,
            "message":
                "Failed to claim task",
            "error": str(e)
        }), 500
# ============================================================
# ADMIN AUTHENTICATION
# ============================================================

def get_admin_from_request():

    token = request.headers.get(
        "Authorization"
    )

    if not token:

        token = request.headers.get(
            "X-Admin-Token"
        )

    if not token:

        return None

    if token.startswith("Bearer "):

        token = token[7:].strip()

    return get_admin_by_token(token)


def require_admin():

    admin = get_admin_from_request()

    if not admin:

        return None, (
            jsonify({
                "success": False,
                "message":
                    "Unauthorized. Admin login required."
            }),
            401
        )

    return admin, None


# ============================================================
# ADMIN LOGIN
# ============================================================

@app.route(
    "/api/admin/login",
    methods=["POST"]
)
def admin_login():

    data = request.get_json(
        silent=True
    ) or {}

    username = data.get(
        "username"
    )

    password = data.get(
        "password"
    )

    if not username or not password:

        return jsonify({
            "success": False,
            "message":
                "Username and password are required."
        }), 400

    try:

        admin = get_admin_by_username(
            username
        )

        if not admin:

            return jsonify({
                "success": False,
                "message":
                    "Invalid admin username or password."
            }), 401

        from database import verify_admin_password

        if not verify_admin_password(
            password,
            admin["password_hash"]
        ):

            return jsonify({
                "success": False,
                "message":
                    "Invalid admin username or password."
            }), 401

        token, session = create_admin_session(
            admin["id"],
            hours=24
        )

        update_admin_last_login(
            admin["id"]
        )

        return jsonify({
            "success": True,
            "message":
                "Admin login successful.",
            "token": token,
            "admin": {
                "id": admin["id"],
                "username": admin["username"]
            },
            "expires_at":
                session["expires_at"]
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "message":
                "Admin login failed.",
            "error": str(e)
        }), 500


# ============================================================
# ADMIN LOGOUT
# ============================================================

@app.route(
    "/api/admin/logout",
    methods=["POST"]
)
def admin_logout():

    token = request.headers.get(
        "Authorization"
    )

    if token and token.startswith(
        "Bearer "
    ):

        token = token[7:].strip()

    if not token:

        token = request.headers.get(
            "X-Admin-Token"
        )

    if not token:

        return jsonify({
            "success": True,
            "message":
                "Already logged out."
        })

    try:

        delete_admin_session(
            token
        )

        return jsonify({
            "success": True,
            "message":
                "Admin logged out successfully."
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "message":
                "Logout failed.",
            "error": str(e)
        }), 500


# ============================================================
# ADMIN PROFILE / AUTH CHECK
# ============================================================

@app.route(
    "/api/admin/me",
    methods=["GET"]
)
def admin_me():

    admin, error = require_admin()

    if error:

        return error

    return jsonify({
        "success": True,
        "admin": dict(admin)
    })


# ============================================================
# ADMIN DASHBOARD
# ============================================================

@app.route(
    "/api/admin/dashboard",
    methods=["GET"]
)
def admin_dashboard():

    admin, error = require_admin()

    if error:

        return error

    try:

        stats = get_dashboard_stats()

        return jsonify({
            "success": True,
            "stats": dict(stats)
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "message":
                "Failed to load dashboard.",
            "error": str(e)
        }), 500
# ============================================================
# ADMIN TASK MANAGEMENT
# ============================================================

@app.route(
    "/api/admin/tasks",
    methods=["GET"]
)
def admin_get_tasks():

    admin, error = require_admin()

    if error:

        return error

    try:

        tasks = get_all_tasks()

        return jsonify({
            "success": True,
            "tasks": [
                dict(task)
                for task in tasks
            ]
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "message":
                "Failed to load tasks.",
            "error": str(e)
        }), 500


@app.route(
    "/api/admin/tasks",
    methods=["POST"]
)
def admin_create_task():

    admin, error = require_admin()

    if error:

        return error

    data = request.get_json(
        silent=True
    ) or {}

    title = data.get(
        "title"
    )

    description = data.get(
        "description",
        ""
    )

    icon = data.get(
        "icon",
        "🎯"
    )

    platform = data.get(
        "platform",
        "Other"
    )

    task_url = data.get(
        "task_url",
        ""
    )

    reward = data.get(
        "reward",
        0
    )

    duration = data.get(
        "duration",
        20
    )

    is_active = data.get(
        "is_active",
        True
    )

    target_vip_level = data.get("target_vip_level")
    if target_vip_level in ("", None):
        target_vip_level = None
    else:
        try:
            target_vip_level = int(target_vip_level)
        except (ValueError, TypeError):
            return jsonify({"success": False, "message": "Invalid VIP task audience."}), 400
        if target_vip_level < 0 or target_vip_level > 10:
            return jsonify({"success": False, "message": "VIP level must be 0 to 10."}), 400

    if not title:

        return jsonify({
            "success": False,
            "message":
                "Task title is required."
        }), 400

    try:

        reward = float(
            reward
        )

        duration = int(
            duration
        )

    except (ValueError, TypeError):

        return jsonify({
            "success": False,
            "message":
                "Invalid reward or duration."
        }), 400

    if reward < 0:

        return jsonify({
            "success": False,
            "message":
                "Reward cannot be negative."
        }), 400

    if duration < 1:

        duration = 20

    try:

        task = create_task(
            title=title,
            description=description,
            icon=icon,
            platform=platform,
            task_url=task_url,
            reward=reward,
            duration=duration,
            is_active=bool(is_active),
            target_vip_level=target_vip_level
        )

        return jsonify({
            "success": True,
            "message":
                "Task created successfully.",
            "task": dict(task)
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "message":
                "Failed to create task.",
            "error": str(e)
        }), 500


@app.route(
    "/api/admin/tasks/<int:task_id>",
    methods=["PUT"]
)
def admin_update_task(
    task_id
):

    admin, error = require_admin()

    if error:

        return error

    data = request.get_json(
        silent=True
    ) or {}

    title = data.get(
        "title"
    )

    description = data.get(
        "description"
    )

    icon = data.get(
        "icon"
    )

    platform = data.get(
        "platform"
    )

    task_url = data.get(
        "task_url"
    )

    reward = data.get(
        "reward"
    )

    duration = data.get(
        "duration"
    )

    is_active = data.get(
        "is_active"
    )

    target_vip_level = data.get("target_vip_level")
    if target_vip_level == "":
        target_vip_level = None
    elif target_vip_level is not None:
        try:
            target_vip_level = int(target_vip_level)
        except (ValueError, TypeError):
            return jsonify({"success": False, "message": "Invalid VIP task audience."}), 400
        if target_vip_level < 0 or target_vip_level > 10:
            return jsonify({"success": False, "message": "VIP level must be 0 to 10."}), 400

    try:

        if reward is not None:

            reward = float(
                reward
            )

            if reward < 0:

                return jsonify({
                    "success": False,
                    "message":
                        "Reward cannot be negative."
                }), 400

        if duration is not None:

            duration = int(
                duration
            )

            if duration < 1:

                duration = 20

        task = update_task(
            task_id=task_id,
            title=title,
            description=description,
            icon=icon,
            platform=platform,
            task_url=task_url,
            reward=reward,
            duration=duration,
            is_active=is_active,
            target_vip_level=target_vip_level
        )

        if not task:

            return jsonify({
                "success": False,
                "message":
                    "Task not found."
            }), 404

        return jsonify({
            "success": True,
            "message":
                "Task updated successfully.",
            "task": dict(task)
        })

    except (ValueError, TypeError):

        return jsonify({
            "success": False,
            "message":
                "Invalid task data."
        }), 400

    except Exception as e:

        return jsonify({
            "success": False,
            "message":
                "Failed to update task.",
            "error": str(e)
        }), 500


@app.route(
    "/api/admin/tasks/<int:task_id>",
    methods=["DELETE"]
)
def admin_delete_task(
    task_id
):

    admin, error = require_admin()

    if error:

        return error

    try:

        deleted = delete_task(
            task_id
        )

        if not deleted:

            return jsonify({
                "success": False,
                "message":
                    "Task not found."
            }), 404

        return jsonify({
            "success": True,
            "message":
                "Task deleted successfully."
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "message":
                "Failed to delete task.",
            "error": str(e)
        }), 500


# ============================================================
# ADMIN USER MANAGEMENT
# ============================================================

@app.route(
    "/api/admin/users",
    methods=["GET"]
)
def admin_get_users():

    admin, error = require_admin()

    if error:

        return error

    try:

        users = get_all_users()

        return jsonify({
            "success": True,
            "users": [
                dict(user)
                for user in users
            ]
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "message":
                "Failed to load users.",
            "error": str(e)
        }), 500
@app.route("/api/deposit/settings", methods=["GET"])
def api_deposit_settings():
    try:
        return jsonify({"success":True,"settings":[dict(x) for x in get_deposit_payment_settings(active_only=True)]})
    except Exception as e:
        return jsonify({"success":False,"message":"Failed to load deposit settings.","error":str(e)}),500

@app.route("/api/admin/deposit/settings", methods=["GET"])
def admin_get_deposit_settings():
    admin,error=require_admin()
    if error: return error
    try:
        return jsonify({"success":True,"settings":[dict(x) for x in get_deposit_payment_settings(active_only=False)]})
    except Exception as e:
        return jsonify({"success":False,"message":"Failed to load deposit settings.","error":str(e)}),500

@app.route("/api/admin/deposit/settings/<method>", methods=["PUT"])
def admin_update_deposit_setting(method):
    admin,error=require_admin()
    if error: return error
    data=request.get_json(silent=True) or {}
    try:
        result=update_deposit_payment_setting(method,data.get('wallet_address'),data.get('instruction_type'),data.get('network'),data.get('is_active',True))
        return jsonify(result),(400 if not result.get('success') else 200)
    except Exception as e:
        return jsonify({"success":False,"message":"Failed to update deposit setting.","error":str(e)}),500

@app.route("/api/admin/deposits", methods=["GET"])
def admin_get_deposits():
    admin,error=require_admin()
    if error: return error
    try: return jsonify({"success":True,"deposits":[dict(x) for x in get_all_deposits()]})
    except Exception as e: return jsonify({"success":False,"message":"Failed to load deposits.","error":str(e)}),500

@app.route("/api/admin/deposits/<int:deposit_id>", methods=["PUT"])
def admin_update_deposit(deposit_id):
    admin,error=require_admin()
    if error: return error
    status=(request.get_json(silent=True) or {}).get("status")
    try:
        result=update_deposit_status(deposit_id,status); return jsonify(result),(400 if not result.get("success") else 200)
    except Exception as e: return jsonify({"success":False,"message":"Failed to update deposit.","error":str(e)}),500


# ============================================================
# ADMIN WITHDRAWAL MANAGEMENT
# ============================================================

@app.route(
    "/api/admin/withdrawals",
    methods=["GET"]
)
def admin_get_withdrawals():

    admin, error = require_admin()

    if error:

        return error

    try:

        withdrawals = get_all_withdrawals()

        return jsonify({
            "success": True,
            "withdrawals": [
                dict(item)
                for item in withdrawals
            ]
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "message":
                "Failed to load withdrawals.",
            "error": str(e)
        }), 500


@app.route(
    "/api/admin/withdrawals/<int:withdrawal_id>",
    methods=["PUT"]
)
def admin_update_withdrawal(
    withdrawal_id
):

    admin, error = require_admin()

    if error:

        return error

    data = request.get_json(
        silent=True
    ) or {}

    status = data.get(
        "status"
    )

    if status not in (
        "approved",
        "rejected"
    ):

        return jsonify({
            "success": False,
            "message":
                "Status must be approved or rejected."
        }), 400

    try:

        result = update_withdrawal_status(
            withdrawal_id,
            status
        )

        if not result.get(
            "success"
        ):

            return jsonify(result), 400

        return jsonify(result)

    except Exception as e:

        return jsonify({
            "success": False,
            "message":
                "Failed to update withdrawal.",
            "error": str(e)
        }), 500


@app.route("/api/deposit", methods=["POST"])
def api_deposit():
    data=request.get_json(silent=True) or {}
    try: telegram_id=int(data.get("telegram_id"))
    except (TypeError,ValueError): return jsonify({"success":False,"message":"Invalid telegram_id."}),400
    result=create_deposit(telegram_id,data.get("method"),data.get("amount"),data.get("transaction_id"),data.get("account_number"))
    if result.get("success"):
        dep=result.get("deposit") or {}
        notify_admins(
            "💰 <b>New Deposit Request</b>\n"
            f"ID: <code>{dep.get('id')}</code>\n"
            f"User: <code>{telegram_id}</code>\n"
            f"Method: {dep.get('method')}\n"
            f"Amount: <b>{dep.get('amount')}</b>\n"
            f"Sender: <code>{dep.get('account_number') or '—'}</code>\n"
            f"TXID: <code>{dep.get('transaction_id')}</code>",
            {"inline_keyboard":[[{"text":"✅ Approve","callback_data":f"approve:deposit:{dep.get('id')}"},{"text":"❌ Reject","callback_data":f"reject:deposit:{dep.get('id')}"}]]}
        )
    return jsonify(result), (400 if not result.get("success") else 200)

@app.route("/api/deposits", methods=["GET"])
def api_user_deposits():
    try: telegram_id=int(request.args.get("telegram_id"))
    except (TypeError,ValueError): return jsonify({"success":False,"message":"Invalid telegram_id."}),400
    try: return jsonify({"success":True,"deposits":[dict(x) for x in get_user_deposits(telegram_id)]})
    except Exception as e: return jsonify({"success":False,"message":"Failed to load deposit history.","error":str(e)}),500


# ============================================================
# ADMIN COIN EXCHANGE API
# ============================================================

@app.route("/api/admin/exchanges", methods=["GET"])
def admin_get_exchanges():
    admin, error = require_admin()
    if error: return error
    try: return jsonify({"success":True,"exchanges":[dict(x) for x in get_all_exchanges()]})
    except Exception as e: return jsonify({"success":False,"message":"Failed to load exchange requests.","error":str(e)}),500

@app.route("/api/admin/exchanges/<int:exchange_id>", methods=["PUT"])
def admin_update_exchange(exchange_id):
    admin, error = require_admin()
    if error: return error
    data=request.get_json(silent=True) or {}
    status=str(data.get("status") or "").lower()
    try: result=update_exchange_status(exchange_id,status)
    except Exception as e: return jsonify({"success":False,"message":"Failed to process exchange.","error":str(e)}),500
    return jsonify(result),(400 if not result.get("success") else 200)

# ============================================================
# USER COIN EXCHANGE API
# ============================================================

@app.route("/api/exchange", methods=["POST"])
def api_exchange():
    data=request.get_json(silent=True) or {}
    try: telegram_id=int(data.get("telegram_id")); coin_amount=float(data.get("coin_amount"))
    except (TypeError,ValueError): return jsonify({"success":False,"message":"Invalid exchange data."}),400
    try: result=create_exchange_request(telegram_id,coin_amount)
    except Exception as e: return jsonify({"success":False,"message":"Exchange request failed.","error":str(e)}),500
    if result.get("success"):
        ex=result.get("exchange") or {}
        notify_admins(
            "🔄 <b>New Coin Exchange Request</b>\n"
            f"ID: <code>{ex.get('id')}</code>\n"
            f"User: <code>{telegram_id}</code>\n"
            f"Coins: <b>{ex.get('coin_amount')}</b>\n"
            f"Cash: <b>{ex.get('cash_amount')} BDT</b>",
            {"inline_keyboard":[[{"text":"✅ Approve","callback_data":f"approve:exchange:{ex.get('id')}"},{"text":"❌ Reject","callback_data":f"reject:exchange:{ex.get('id')}"}]]}
        )
    return jsonify(result),(400 if not result.get("success") else 200)

@app.route("/api/exchanges", methods=["GET"])
def api_user_exchanges():
    try: telegram_id=int(request.args.get("telegram_id"))
    except (TypeError,ValueError): return jsonify({"success":False,"message":"Invalid telegram_id."}),400
    try: return jsonify({"success":True,"exchanges":[dict(x) for x in get_user_exchanges(telegram_id)]})
    except Exception as e: return jsonify({"success":False,"message":"Failed to load exchange history.","error":str(e)}),500

# ============================================================
# USER WITHDRAWAL API
# ============================================================

@app.route(
    "/api/withdraw",
    methods=["POST"]
)
def api_withdraw():

    data = request.get_json(
        silent=True
    ) or {}

    telegram_id = data.get(
        "telegram_id"
    )

    method = data.get(
        "method"
    )

    account_number = data.get(
        "account_number"
    )

    amount = data.get(
        "amount"
    )


    if not telegram_id:

        return jsonify({
            "success": False,
            "message":
                "telegram_id is required."
        }), 400

    if not method:

        return jsonify({
            "success": False,
            "message":
                "Withdrawal method is required."
        }), 400

    if not account_number:

        return jsonify({
            "success": False,
            "message":
                "Account number or wallet address is required."
        }), 400

    if amount is None:

        return jsonify({
            "success": False,
            "message":
                "Withdrawal amount is required."
        }), 400

    try:

        telegram_id = int(
            telegram_id
        )

        amount = float(
            amount
        )

    except (ValueError, TypeError):

        return jsonify({
            "success": False,
            "message":
                "Invalid withdrawal data."
        }), 400

    # --------------------------------------------------------
    # USDT TRC20 VALIDATION
    # --------------------------------------------------------

    if method.lower() == "usdt":

        if not (
            account_number.startswith("T")
            and len(account_number) == 34
        ):

            return jsonify({
                "success": False,
                "message":
                    "Invalid USDT TRC20 wallet address."
            }), 400

    try:

        result = create_withdrawal(
            telegram_id=telegram_id,
            method=method,
            account_number=account_number,
            amount=amount,
            source="main"
        )
        if result.get("success"):
            wd=result.get("withdrawal") or {}
            notify_admins(
                "💸 <b>New Withdrawal Request</b>\n"
                f"ID: <code>{wd.get('id')}</code>\n"
                f"User: <code>{telegram_id}</code>\n"
                f"Method: {wd.get('method')}\n"
                f"Account: <code>{wd.get('account_number')}</code>\n"
                f"Amount: <b>{wd.get('amount')}</b>",
                {"inline_keyboard":[[{"text":"✅ Approve","callback_data":f"approve:withdrawal:{wd.get('id')}"},{"text":"❌ Reject","callback_data":f"reject:withdrawal:{wd.get('id')}"}]]}
            )

        return jsonify(result)

    except Exception as e:

        return jsonify({
            "success": False,
            "message":
                "Withdrawal failed.",
            "error": str(e)
        }), 500


# ============================================================
# USER WITHDRAWAL HISTORY
# ============================================================

@app.route(
    "/api/withdrawals",
    methods=["GET"]
)
def user_withdrawals():

    telegram_id = request.args.get(
        "telegram_id"
    )

    if not telegram_id:

        return jsonify({
            "success": False,
            "message":
                "telegram_id is required."
        }), 400

    try:

        telegram_id = int(
            telegram_id
        )

        withdrawals = get_user_withdrawals(
            telegram_id
        )

        return jsonify({
            "success": True,
            "withdrawals": [
                dict(item)
                for item in withdrawals
            ]
        })

    except (ValueError, TypeError):

        return jsonify({
            "success": False,
            "message":
                "Invalid telegram_id."
        }), 400

    except Exception as e:

        return jsonify({
            "success": False,
            "message":
                "Failed to load withdrawal history.",
            "error": str(e)
        }), 500



# ============================================================
# PUBLIC WITHDRAWAL PROOF
# ============================================================
@app.route("/api/public/withdrawals", methods=["GET"])
def public_withdrawals():
    """Public, privacy-safe list of successfully processed withdrawals."""
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 100)
    except (TypeError, ValueError):
        limit = 50
    try:
        rows = get_public_withdrawal_proofs(limit)
        total_paid = round(sum(float(x.get("amount") or 0) for x in rows), 2)
        stats = get_public_withdrawal_stats()
        return jsonify({
            "success": True,
            "payments": rows,
            "count": len(rows),
            "total_paid_in_list": total_paid,
            "stats": stats,
            "privacy": "User IDs and full payment account details are not publicly exposed."
        })
    except Exception as e:
        return jsonify({"success": False, "message": "Failed to load public payment proof."}), 500

# ============================================================
# VIP / PREMIUM MEMBERSHIP API
# ============================================================

@app.route("/api/premium", methods=["GET"])
def api_premium():
    """Return every VIP membership plus active/pending status for each level."""
    try:
        telegram_id = int(request.args.get("telegram_id"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Invalid telegram_id."}), 400

    try:
        memberships = [dict(x) for x in get_user_premium_memberships(telegram_id)]
        active = [x for x in memberships if str(x.get("status", "")).lower() == "active"]
        pending = [x for x in memberships if str(x.get("status", "")).lower() == "pending"]
        # Lucky Spin/task logic continues to use the latest active membership.
        current_row = get_active_premium(telegram_id)
        current = dict(current_row) if current_row else None
        limits = get_daily_task_limits(telegram_id)
        return jsonify({
            "success": True,
            "membership": current,
            "memberships": memberships,
            "active_memberships": active,
            "pending_memberships": pending,
            "progress": limits,
            "daily_limits": limits
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "message": "Failed to load Premium membership.",
            "error": str(e)
        }), 500


@app.route("/api/premium/plans", methods=["GET"])
def api_premium_plans():
    try:
        return jsonify({
            "success": True,
            "plans": [dict(item) for item in get_premium_plans(active_only=True)]
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "message": "Failed to load Premium plans.",
            "error": str(e)
        }), 500


@app.route("/api/premium/purchase", methods=["POST"])
def api_premium_purchase():
    data = request.get_json(silent=True) or {}
    try:
        telegram_id = int(data.get("telegram_id"))
        level = int(data.get("level"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Invalid telegram_id or VIP level."}), 400

    try:
        result = purchase_premium(telegram_id, level)
        if not result.get("success"):
            return jsonify(result), 400
        membership = result.get("membership") or {}
        plan = result.get("plan") or {}
        notify_admins(
            "💎 <b>New VIP / Premium Request</b>\n"
            f"ID: <code>{membership.get('id')}</code>\n"
            f"User: <code>{telegram_id}</code>\n"
            f"VIP Level: <b>{plan.get('level')}</b>\n"
            f"Price: <b>৳{float(plan.get('price') or 0):,.2f}</b>\n"
            f"Duration: <b>{plan.get('duration_days')} days</b>",
            {"inline_keyboard": [[
                {"text": "✅ Approve", "callback_data": f"approve:premium:{membership.get('id')}"},
                {"text": "❌ Reject", "callback_data": f"reject:premium:{membership.get('id')}"}
            ]]}
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "message": "Premium purchase request failed.", "error": str(e)}), 500


# ============================================================
# ADMIN REFERRAL MANAGEMENT
# ============================================================

@app.route("/api/admin/referral-requests", methods=["GET"])
def admin_get_referral_requests():
    admin,error=require_admin()
    if error: return error
    try: return jsonify({"success":True,"requests":[dict(x) for x in get_referral_requests(request.args.get("status","pending"))]})
    except Exception as e: return jsonify({"success":False,"message":"Failed to load referral requests.","error":str(e)}),500

@app.route("/api/admin/referral-requests/<int:referral_id>", methods=["PUT"])
def admin_process_referral_request(referral_id):
    admin,error=require_admin()
    if error: return error
    data=request.get_json(silent=True) or {}
    try:
        result=process_referral_request(referral_id,data.get("status"),data.get("amount",500),admin.get("id"))
        return jsonify(result),(200 if result.get("success") else 400)
    except Exception as e:
        app.logger.exception("Referral approval failed")
        return jsonify({"success":False,"message":"Failed to process referral request.","error":str(e)}),500

@app.route("/api/admin/referral-bonus", methods=["POST"])
def admin_referral_bonus():
    admin,error=require_admin()
    if error: return error
    data=request.get_json(silent=True) or {}
    try:
        result=admin_give_referral_bonus(data.get("referrer_id"),data.get("referred_id"),data.get("amount",500),admin.get("id"))
        return jsonify(result),(200 if result.get("success") else 400)
    except Exception as e:
        app.logger.exception("Manual referral bonus failed")
        return jsonify({"success":False,"message":"Failed to give referral bonus.","error":str(e)}),500


# ============================================================
# ADMIN VIP / PREMIUM MANAGEMENT
# ============================================================

@app.route("/api/admin/premium/plans", methods=["GET"])
def admin_get_premium_plans():
    admin, error = require_admin()
    if error:
        return error
    try:
        return jsonify({"success": True, "plans": [dict(x) for x in get_premium_plans(active_only=False)]})
    except Exception as e:
        return jsonify({"success": False, "message": "Failed to load VIP plans.", "error": str(e)}), 500


@app.route("/api/admin/premium/plans/<int:level>", methods=["PUT"])
def admin_update_premium_plan(level):
    admin, error = require_admin()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    conn = None; cur = None
    try:
        conn = get_connection(); cur = conn.cursor()
        cur.execute("SELECT id FROM premium_plans WHERE level=%s FOR UPDATE", (level,))
        if not cur.fetchone():
            conn.rollback(); return jsonify({"success": False, "message": f"VIP Level {level} not found."}), 404
        fields=[]; values=[]
        if "price" in data:
            price=float(data.get("price"));
            if price < 0: raise ValueError("Price cannot be negative.")
            fields.append("price=%s"); values.append(price)
        if "bonus_website_tasks" in data:
            bonus=int(data.get("bonus_website_tasks"));
            if bonus < 0: raise ValueError("Bonus Website Tasks cannot be negative.")
            fields.append("bonus_website_tasks=%s"); values.append(bonus)
        if "is_active" in data:
            fields.append("is_active=%s"); values.append(bool(data.get("is_active")))
        if not fields:
            conn.rollback(); return jsonify({"success": False, "message": "No VIP plan fields were supplied."}), 400
        values.append(level)
        cur.execute(f"UPDATE premium_plans SET {', '.join(fields)}, updated_at=CURRENT_TIMESTAMP WHERE level=%s RETURNING *", tuple(values))
        updated=cur.fetchone(); conn.commit()
        return jsonify({"success": True, "message": f"VIP Level {level} updated successfully.", "plan": dict(updated)})
    except (ValueError, TypeError) as e:
        if conn: conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"success": False, "message": "Failed to update VIP plan.", "error": str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: conn.close()


@app.route("/api/admin/premium/requests", methods=["GET"])
def admin_get_premium_requests():
    admin, error = require_admin()
    if error: return error
    try:
        return jsonify({"success": True, "requests": [dict(x) for x in get_premium_membership_requests("pending")]})
    except Exception as e:
        return jsonify({"success": False, "message": "Failed to load VIP purchase requests.", "error": str(e)}), 500


@app.route("/api/admin/premium/requests/<int:membership_id>", methods=["PUT"])
def admin_update_premium_request(membership_id):
    admin, error = require_admin()
    if error: return error
    data=request.get_json(silent=True) or {}
    status=str(data.get("status") or "").strip().lower()
    if status == "approved": status="active"
    if status not in ("active", "rejected"):
        return jsonify({"success": False, "message": "Status must be approved or rejected."}), 400
    try:
        result=update_premium_membership_status(membership_id, status, data.get("reason"))
        if not result.get("success"): return jsonify(result), 400
        return jsonify({"success": True, "message": "VIP request approved." if status=="active" else "VIP request rejected and Deposit Balance refunded.", "membership": result.get("membership")})
    except Exception as e:
        return jsonify({"success": False, "message": "Failed to update VIP request.", "error": str(e)}), 500


@app.route("/api/admin/premium/members", methods=["GET"])
def admin_get_premium_members():
    admin, error = require_admin()
    if error: return error
    try:
        return jsonify({"success": True, "members": [dict(x) for x in get_premium_membership_requests("active")]})
    except Exception as e:
        return jsonify({"success": False, "message": "Failed to load VIP members.", "error": str(e)}), 500


# ============================================================
# VIP LUCKY SPIN API
# ============================================================

@app.route("/api/lucky-spin", methods=["GET"])
def api_lucky_spin_config():
    try:
        return jsonify({"success": True, "prizes": [dict(x) for x in get_lucky_spin_config()]})
    except Exception as e:
        return jsonify({"success": False, "message": "Failed to load Lucky Spin.", "error": str(e)}), 500


@app.route("/api/lucky-spin/spin", methods=["POST"])
def api_lucky_spin():
    data=request.get_json(silent=True) or {}
    try: telegram_id=int(data.get("telegram_id"))
    except (TypeError,ValueError): return jsonify({"success":False,"message":"Invalid telegram_id."}),400
    try:
        result=lucky_spin(telegram_id)
        return jsonify(result), (200 if result.get("success") else 400)
    except Exception as e:
        app.logger.exception("Lucky Spin failed")
        return jsonify({"success":False,"message":"Lucky Spin failed.","error":str(e)}),500


@app.route("/api/admin/lucky-spin/prizes", methods=["GET"])
def admin_lucky_spin_prizes():
    admin,error=require_admin()
    if error: return error
    try:
        return jsonify({"success":True,"prizes":[dict(x) for x in get_lucky_spin_config()]})
    except Exception as e:
        return jsonify({"success":False,"message":"Failed to load Lucky Spin prizes.","error":str(e)}),500


@app.route("/api/admin/lucky-spin/prizes/<int:prize_id>", methods=["PUT"])
def admin_update_lucky_spin_prize(prize_id):
    admin,error=require_admin()
    if error: return error
    try:
        result=update_lucky_spin_prize(prize_id, request.get_json(silent=True) or {})
        return jsonify(result), (200 if result.get("success") else 400)
    except (ValueError,TypeError) as e:
        return jsonify({"success":False,"message":str(e)}),400
    except Exception as e:
        return jsonify({"success":False,"message":"Failed to update Lucky Spin prize.","error":str(e)}),500

# ============================================================
# TASKCOIN USER-TO-USER TRANSFER API
# ============================================================

@app.route("/api/taskcoin/transfer", methods=["POST"])
def api_taskcoin_transfer():
    """Send TaskCoins from one existing Mini App user to another."""
    data = request.get_json(silent=True) or {}

    try:
        sender_id = int(data.get("sender_id"))
        receiver_id = int(data.get("receiver_id"))
        amount = float(data.get("amount"))
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "message": "Invalid sender, receiver or amount."
        }), 400

    try:
        result = transfer_taskcoins(
            sender_id=sender_id,
            receiver_id=receiver_id,
            amount=amount
        )
        return jsonify(result), (200 if result.get("success") else 400)
    except Exception as e:
        app.logger.exception("TaskCoin transfer failed")
        return jsonify({
            "success": False,
            "message": "TaskCoin transfer failed.",
            "error": str(e)
        }), 500


# ============================================================
# REFERRAL API
# ============================================================

@app.route(
    "/api/referrals",
    methods=["GET"]
)
def api_referrals():

    telegram_id = request.args.get(
        "telegram_id"
    )

    if not telegram_id:

        return jsonify({
            "success": False,
            "message":
                "telegram_id is required."
        }), 400

    try:

        telegram_id = int(
            telegram_id
        )

        referrals = get_user_referrals(
            telegram_id
        )

        return jsonify({
            "success": True,
            "referrals": [
                dict(item)
                for item in referrals
            ]
        })

    except (ValueError, TypeError):

        return jsonify({
            "success": False,
            "message":
                "Invalid telegram_id."
        }), 400

    except Exception as e:

        return jsonify({
            "success": False,
            "message":
                "Failed to load referrals.",
            "error": str(e)
        }), 500
# ============================================================
# CPAGRIP LANDING-PAGE TRACKING BRIDGE
# ============================================================

CPAGRIP_LANDING_URL = os.getenv(
    "CPAGRIP_LANDING_URL",
    "https://sites.google.com/view/taskcoin-offer/home"
).strip()
CPAGRIP_SMART_LINK = os.getenv(
    "CPAGRIP_SMART_LINK",
    "https://tundrafile.com/1917387/"
).strip()


def _valid_cpagrip_tracking_id(value):
    value = str(value or "").strip()
    return bool(__import__("re").fullmatch(r"tc_\d+_\d+_[a-f0-9]{20}", value))


@app.route("/api/cpagrip/prepare", methods=["GET"])
def cpagrip_prepare():
    """
    Store the TaskCoin tracking ID in a short-lived first-party cookie, then
    send the user to the existing Google Sites landing page.

    Google Sites buttons are static, so the cookie is the bridge that lets the
    static button later reach /api/cpagrip/redirect with the correct tracking ID.
    """
    tracking_id = str(request.args.get("tracking_id") or "").strip()
    if not _valid_cpagrip_tracking_id(tracking_id):
        return jsonify({"success": False, "message": "Invalid CPAGrip tracking_id."}), 400

    response = __import__("flask").redirect(CPAGRIP_LANDING_URL, code=302)
    response.set_cookie(
        "taskcoin_cpagrip_tracking_id",
        tracking_id,
        max_age=1800,
        secure=True,
        httponly=True,
        samesite="Lax",
        path="/"
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


@app.route("/api/cpagrip/redirect", methods=["GET"])
def cpagrip_redirect():
    """Read the short-lived tracking cookie and redirect to CPAGrip Smart Link."""
    tracking_id = str(request.cookies.get("taskcoin_cpagrip_tracking_id") or "").strip()
    if not _valid_cpagrip_tracking_id(tracking_id):
        # Direct visits still reach the offer, but are not attributable to a
        # TaskCoin start and therefore cannot unlock a TaskCoin reward.
        return __import__("flask").redirect(CPAGRIP_SMART_LINK, code=302)

    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    parts = urlsplit(CPAGRIP_SMART_LINK)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["tracking_id"] = tracking_id
    target = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    response = __import__("flask").redirect(target, code=302)
    response.delete_cookie("taskcoin_cpagrip_tracking_id", path="/")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


# ============================================================
# CPAGRIP GLOBAL POSTBACK
# ============================================================

@app.route("/api/cpagrip/postback", methods=["GET", "POST"])
def cpagrip_postback():
    """
    Receive CPAGrip's Global Postback and mark the matching task as verified.

    Configure CPAGRIP_POSTBACK_PASSWORD in Render and use the same password
    in CPAGrip Global Postback. The reward is NOT credited here; claim_task_reward
    credits it only after this verification gate is satisfied.
    """
    try:
        data = {}
        data.update(request.args.to_dict(flat=True))
        data.update(request.form.to_dict(flat=True))
        body = request.get_json(silent=True) or {}
        if isinstance(body, dict):
            data.update(body)

        configured_password = str(os.getenv("CPAGRIP_POSTBACK_PASSWORD") or "").strip()
        supplied_password = str(
            data.get("password") or data.get("pass") or data.get("postback_password") or ""
        ).strip()
        if configured_password:
            if not supplied_password or not hmac.compare_digest(supplied_password, configured_password):
                return jsonify({"success": False, "verified": False, "message": "Invalid CPAGrip postback password."}), 403

        tracking_id = (
            data.get("tracking_id") or data.get("subid") or data.get("sub_id")
            or data.get("click_id") or data.get("clickid")
        )
        payout = data.get("payout") or data.get("revenue") or data.get("amount") or data.get("commission") or 0
        transaction_id = (
            data.get("transaction_id") or data.get("transactionid") or data.get("txid")
            or data.get("conversion_id") or data.get("conversionid")
        )
        status = data.get("status") or data.get("conversion_status") or ""
        offer_id = data.get("offer_id") or data.get("offerid") or data.get("campaign_id") or ""
        offer_name = data.get("offer_name") or data.get("offername") or data.get("campaign_name") or ""

        result = process_cpagrip_postback(
            tracking_id=tracking_id, payout=payout, transaction_id=transaction_id,
            status=status, offer_id=offer_id, offer_name=offer_name, raw_payload=data
        )
        code = 200 if result.get("success") else 400
        return jsonify(result), code
    except Exception as e:
        app.logger.exception("CPAGrip postback failed")
        return jsonify({"success": False, "verified": False, "message": "CPAGrip postback processing failed."}), 500


# ============================================================
# ADGEM POSTBACK
# ============================================================

@app.route(
    "/api/adgem/postback",
    methods=["POST"]
)
def adgem_postback():

    data = request.get_json(
        silent=True
    ) or {}

    return jsonify({
        "success": True,
        "message": "AdGem postback received.",
        "data": data
    })
# ============================================================
# MONETAG POSTBACK
# ============================================================

@app.route("/api/monetag/postback", methods=["GET"])
def monetag_postback():
    """Receive Monetag TMA server-side postbacks."""

    ymid = request.args.get("ymid")
    telegram_id = request.args.get("telegram_id")
    zone_id = request.args.get("zone_id")
    sub_zone_id = request.args.get("sub_zone_id")
    event_type = request.args.get("event_type")
    reward_event_type = request.args.get("reward_event_type")
    estimated_price = request.args.get("estimated_price", "0")
    request_var = request.args.get("request_var")

    if not ymid:
        return jsonify({
            "success": False,
            "credited": False,
            "message": "ymid is required."
        }), 400

    if not telegram_id:
        return jsonify({
            "success": False,
            "credited": False,
            "message": "telegram_id is required."
        }), 400

    if zone_id not in (None, "", "11915530"):
        return jsonify({
            "success": False,
            "credited": False,
            "message": "Unknown Monetag zone."
        }), 400

    try:
        result = process_monetag_postback(
            ymid=ymid,
            telegram_id=telegram_id,
            zone_id=zone_id,
            sub_zone_id=sub_zone_id,
            event_type=event_type,
            reward_event_type=reward_event_type,
            estimated_price=estimated_price,
            request_var=request_var,
            reward=50
        )

        if not result.get("success"):
            return jsonify(result), 400

        # Always acknowledge valid/duplicate postbacks with HTTP 200 so
        # Monetag does not keep retrying an already processed event.
        return jsonify(result), 200

    except (ValueError, TypeError):
        return jsonify({
            "success": False,
            "credited": False,
            "message": "Invalid Monetag postback values."
        }), 400

    except Exception as e:
        app.logger.exception("Monetag postback processing failed")
        return jsonify({
            "success": False,
            "credited": False,
            "message": "Monetag postback processing failed.",
            "error": str(e)
        }), 500


# ============================================================
# LEGACY MONETAG REWARD API
# ============================================================

@app.route("/api/monetag/reward", methods=["POST"])
def monetag_reward():
    # Client-side reward crediting is disabled. Monetag postback is authoritative.
    return jsonify({
        "success": False,
        "message": "Use the Monetag server-side postback for rewards."
    }), 410

# ============================================================
# RUN APP
# ============================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )

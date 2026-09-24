import os

from flask import Flask, jsonify, request
from flask_cors import CORS
from database import (
    get_user,
    get_all_users,
    create_or_update_user,

    get_active_tasks,
    get_all_tasks,
    create_task,
    update_task,
    delete_task,
    claim_task_reward,

    create_withdrawal,
    get_user_withdrawals,
    get_all_withdrawals,
    update_withdrawal_status,

    get_user_referrals,

    get_admin_by_username,
    create_admin_session,
    get_admin_by_token,
    delete_admin_session,
    update_admin_last_login,
    get_dashboard_stats
)


app = Flask(__name__)
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
            first_name=first_name
        )

        return jsonify({
            "success": True,
            "message":
                "User created/updated successfully",
            "user": dict(user)
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "message":
                "Database error",
            "error": str(e)
        }), 500


# ============================================================
# TASK API
# ============================================================

@app.route("/api/tasks")
def api_tasks():

    try:

        tasks = get_active_tasks()

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
            is_active=bool(is_active)
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
            is_active=is_active
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
            amount=amount
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

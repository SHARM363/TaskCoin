import os
import hashlib
import secrets
import hmac

from datetime import datetime, timedelta

import psycopg2
from psycopg2.extras import RealDictCursor


DATABASE_URL = os.getenv("DATABASE_URL")


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection():

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL environment variable is missing."
        )

    return psycopg2.connect(
        DATABASE_URL
    )


# ============================================================
# ADMIN PASSWORD FUNCTIONS
# ============================================================

def hash_admin_password(password):

    salt = secrets.token_bytes(16)

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        310000
    )

    return (
        "pbkdf2_sha256$"
        + salt.hex()
        + "$"
        + password_hash.hex()
    )


def verify_admin_password(password, stored_hash):

    try:

        parts = stored_hash.split("$")

        if len(parts) != 3:
            return False

        algorithm = parts[0]

        if algorithm != "pbkdf2_sha256":
            return False

        salt = bytes.fromhex(parts[1])
        original_hash = bytes.fromhex(parts[2])

        new_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            310000
        )

        return hmac.compare_digest(
            new_hash,
            original_hash
        )

    except Exception:

        return False


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_db():

    conn = get_connection()
    cur = conn.cursor()

    try:

        # ----------------------------------------------------
        # USERS
        # ----------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (

                id SERIAL PRIMARY KEY,

                telegram_id BIGINT UNIQUE NOT NULL,

                username TEXT,

                first_name TEXT,

                balance NUMERIC(20, 2)
                    DEFAULT 0,

                total_earned NUMERIC(20, 2)
                    DEFAULT 0,

                total_withdrawn NUMERIC(20, 2)
                    DEFAULT 0,

                referral_code TEXT UNIQUE,

                referred_by BIGINT,

                referral_count INTEGER
                    DEFAULT 0,

                completed_tasks INTEGER
                    DEFAULT 0,

                status TEXT
                    DEFAULT 'active',

                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP,

                last_active TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # ----------------------------------------------------
        # TASKS
        # ----------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS tasks (

                id SERIAL PRIMARY KEY,

                title TEXT NOT NULL,

                description TEXT
                    DEFAULT '',

                icon TEXT
                    DEFAULT '🎯',

                platform TEXT
                    DEFAULT 'Other',

                task_url TEXT
                    DEFAULT '',

                reward NUMERIC(20, 2)
                    DEFAULT 0,

                duration INTEGER
                    DEFAULT 20,

                is_active BOOLEAN
                    DEFAULT TRUE,

                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP,

                updated_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # ----------------------------------------------------
        # TASK COMPLETIONS
        # ----------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS task_completions (

                id SERIAL PRIMARY KEY,

                telegram_id BIGINT NOT NULL,

                task_id INTEGER NOT NULL,

                reward NUMERIC(20, 2)
                    DEFAULT 0,

                completed_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP,

                completed_date DATE
                    DEFAULT CURRENT_DATE,

                UNIQUE (
                    telegram_id,
                    task_id,
                    completed_date
                )
            );
        """)

        # ----------------------------------------------------
        # WITHDRAWALS
        # ----------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (

                id SERIAL PRIMARY KEY,

                telegram_id BIGINT NOT NULL,

                method TEXT NOT NULL,

                account_number TEXT NOT NULL,

                amount NUMERIC(20, 2) NOT NULL,

                status TEXT
                    DEFAULT 'pending',

                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP,

                processed_at TIMESTAMP
            );
        """)

        # ----------------------------------------------------
        # REFERRALS
        # ----------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS referrals (

                id SERIAL PRIMARY KEY,

                referrer_id BIGINT NOT NULL,

                referred_id BIGINT NOT NULL,

                reward NUMERIC(20, 2)
                    DEFAULT 0,

                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP,

                UNIQUE (
                    referrer_id,
                    referred_id
                )
            );
        """)

        # ----------------------------------------------------
        # ADMINS
        # ----------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS admins (

                id SERIAL PRIMARY KEY,

                username TEXT UNIQUE NOT NULL,

                password_hash TEXT NOT NULL,

                is_active BOOLEAN
                    DEFAULT TRUE,

                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP,

                last_login TIMESTAMP
            );
        """)

        # ----------------------------------------------------
        # ADMIN SESSIONS
        # ----------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin_sessions (

                id SERIAL PRIMARY KEY,

                admin_id INTEGER NOT NULL,

                token_hash TEXT UNIQUE NOT NULL,

                expires_at TIMESTAMP NOT NULL,

                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            );
        """)
                # ----------------------------------------------------
        # OLD DATABASE COMPATIBILITY
        # ----------------------------------------------------

        cur.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS
            total_earned NUMERIC(20, 2)
            DEFAULT 0;
        """)

        cur.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS
            total_withdrawn NUMERIC(20, 2)
            DEFAULT 0;
        """)

        cur.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS
            referral_code TEXT;
        """)

        cur.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS
            referred_by BIGINT;
        """)

        cur.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS
            referral_count INTEGER
            DEFAULT 0;
        """)

        cur.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS
            completed_tasks INTEGER
            DEFAULT 0;
        """)

        cur.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS
            status TEXT
            DEFAULT 'active';
        """)

        cur.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS
            description TEXT
            DEFAULT '';
        """)

        cur.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS
            icon TEXT
            DEFAULT '🎯';
        """)

        cur.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS
            platform TEXT
            DEFAULT 'Other';
        """)

        cur.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS
            task_url TEXT
            DEFAULT '';
        """)

        cur.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS
            reward NUMERIC(20, 2)
            DEFAULT 0;
        """)

        cur.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS
            duration INTEGER
            DEFAULT 20;
        """)

        cur.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS
            is_active BOOLEAN
            DEFAULT TRUE;
        """)

        # ----------------------------------------------------
        # INDEXES
        # ----------------------------------------------------

        cur.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_users_telegram_id
            ON users(telegram_id);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_tasks_active
            ON tasks(is_active);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_task_completions_user
            ON task_completions(telegram_id);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_withdrawals_user
            ON withdrawals(telegram_id);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_withdrawals_status
            ON withdrawals(status);
        """)

        # ----------------------------------------------------
        # AUTO CREATE ADMIN
        # ----------------------------------------------------

        admin_username = os.getenv(
            "ADMIN_USERNAME"
        )

        admin_password = os.getenv(
            "ADMIN_PASSWORD"
        )

        if admin_username and admin_password:

            password_hash = hash_admin_password(
                admin_password
            )

            cur.execute("""
                INSERT INTO admins (
                    username,
                    password_hash
                )
                VALUES (
                    %s,
                    %s
                )
                ON CONFLICT (username)
                DO NOTHING;
            """, (
                admin_username,
                password_hash
            ))

        conn.commit()

    except Exception:

        conn.rollback()
        raise

    finally:

        cur.close()
        conn.close()


# ============================================================
# USER FUNCTIONS
# ============================================================

def create_or_update_user(
    telegram_id,
    username=None,
    first_name=None
):

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        referral_code = "TC" + str(telegram_id)

        cur.execute("""
            INSERT INTO users (
                telegram_id,
                username,
                first_name,
                referral_code,
                last_active
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT (telegram_id)
            DO UPDATE SET

                username =
                    EXCLUDED.username,

                first_name =
                    EXCLUDED.first_name,

                last_active =
                    CURRENT_TIMESTAMP

            RETURNING *;
        """, (
            telegram_id,
            username,
            first_name,
            referral_code
        ))

        user = cur.fetchone()

        conn.commit()

        return user

    except Exception:

        conn.rollback()
        raise

    finally:

        cur.close()
        conn.close()


def get_user(telegram_id):

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cur.execute("""
            SELECT *
            FROM users
            WHERE telegram_id = %s;
        """, (
            telegram_id,
        ))

        return cur.fetchone()

    finally:

        cur.close()
        conn.close()


def get_all_users():

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cur.execute("""
            SELECT *
            FROM users
            ORDER BY id DESC;
        """)

        return cur.fetchall()

    finally:

        cur.close()
        conn.close()
   # ============================================================
# TASK FUNCTIONS
# ============================================================

def get_active_tasks():

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cur.execute("""
            SELECT *
            FROM tasks
            WHERE is_active = TRUE
            ORDER BY id DESC;
        """)

        return cur.fetchall()

    finally:

        cur.close()
        conn.close()


def get_all_tasks():

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cur.execute("""
            SELECT *
            FROM tasks
            ORDER BY id DESC;
        """)

        return cur.fetchall()

    finally:

        cur.close()
        conn.close()


def create_task(
    title,
    description="",
    icon="🎯",
    platform="Other",
    task_url="",
    reward=0,
    duration=20,
    is_active=True
):

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cur.execute("""
            INSERT INTO tasks (
                title,
                description,
                icon,
                platform,
                task_url,
                reward,
                duration,
                is_active
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
            RETURNING *;
        """, (
            title,
            description,
            icon,
            platform,
            task_url,
            reward,
            duration,
            is_active
        ))

        task = cur.fetchone()

        conn.commit()

        return task

    except Exception:

        conn.rollback()
        raise

    finally:

        cur.close()
        conn.close()


def update_task(
    task_id,
    title=None,
    description=None,
    icon=None,
    platform=None,
    task_url=None,
    reward=None,
    duration=None,
    is_active=None
):

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cur.execute("""
            UPDATE tasks
            SET

                title =
                    COALESCE(%s, title),

                description =
                    COALESCE(%s, description),

                icon =
                    COALESCE(%s, icon),

                platform =
                    COALESCE(%s, platform),

                task_url =
                    COALESCE(%s, task_url),

                reward =
                    COALESCE(%s, reward),

                duration =
                    COALESCE(%s, duration),

                is_active =
                    COALESCE(%s, is_active),

                updated_at =
                    CURRENT_TIMESTAMP

            WHERE id = %s

            RETURNING *;
        """, (
            title,
            description,
            icon,
            platform,
            task_url,
            reward,
            duration,
            is_active,
            task_id
        ))

        task = cur.fetchone()

        conn.commit()

        return task

    except Exception:

        conn.rollback()
        raise

    finally:

        cur.close()
        conn.close()


def delete_task(task_id):

    conn = get_connection()

    cur = conn.cursor()

    try:

        cur.execute("""
            DELETE FROM tasks
            WHERE id = %s;
        """, (
            task_id,
        ))

        deleted = cur.rowcount > 0

        conn.commit()

        return deleted

    except Exception:

        conn.rollback()
        raise

    finally:

        cur.close()
        conn.close()
# ============================================================
# TASK LIMIT / COMPLETION
# ============================================================

def count_today_tasks(telegram_id):

    conn = get_connection()

    cur = conn.cursor()

    try:

        cur.execute("""
            SELECT COUNT(*)
            FROM task_completions
            WHERE telegram_id = %s
            AND completed_date = CURRENT_DATE;
        """, (
            telegram_id,
        ))

        return cur.fetchone()[0]

    finally:

        cur.close()
        conn.close()


def task_completed_today(
    telegram_id,
    task_id
):

    conn = get_connection()

    cur = conn.cursor()

    try:

        cur.execute("""
            SELECT id
            FROM task_completions
            WHERE telegram_id = %s
            AND task_id = %s
            AND completed_date = CURRENT_DATE
            LIMIT 1;
        """, (
            telegram_id,
            task_id
        ))

        return cur.fetchone() is not None

    finally:

        cur.close()
        conn.close()


def claim_task_reward(
    telegram_id,
    task_id
):

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        # ----------------------------------------------------
        # LOCK USER
        # ----------------------------------------------------

        cur.execute("""
            SELECT *
            FROM users
            WHERE telegram_id = %s
            FOR UPDATE;
        """, (
            telegram_id,
        ))

        user = cur.fetchone()

        if not user:

            conn.rollback()

            return {
                "success": False,
                "message": "User not found."
            }

        # ----------------------------------------------------
        # DAILY LIMIT
        # ----------------------------------------------------

        cur.execute("""
            SELECT COUNT(*) AS total
            FROM task_completions
            WHERE telegram_id = %s
            AND completed_date = CURRENT_DATE;
        """, (
            telegram_id,
        ))

        today_count = cur.fetchone()["total"]

        if today_count >= 10:

            conn.rollback()

            return {
                "success": False,
                "message":
                    "Daily task limit reached."
            }

        # ----------------------------------------------------
        # GET TASK
        # ----------------------------------------------------

        cur.execute("""
            SELECT *
            FROM tasks
            WHERE id = %s
            AND is_active = TRUE
            FOR UPDATE;
        """, (
            task_id,
        ))

        task = cur.fetchone()

        if not task:

            conn.rollback()

            return {
                "success": False,
                "message": "Task not found."
            }

        # ----------------------------------------------------
        # SAME TASK CHECK
        # ----------------------------------------------------

        cur.execute("""
            SELECT id
            FROM task_completions
            WHERE telegram_id = %s
            AND task_id = %s
            AND completed_date = CURRENT_DATE
            LIMIT 1;
        """, (
            telegram_id,
            task_id
        ))

        already_done = cur.fetchone()

        if already_done:

            conn.rollback()

            return {
                "success": False,
                "message":
                    "Task already completed today."
            }

        reward = task["reward"]

        # ----------------------------------------------------
        # INSERT COMPLETION
        # ----------------------------------------------------

        cur.execute("""
            INSERT INTO task_completions (
                telegram_id,
                task_id,
                reward
            )
            VALUES (
                %s,
                %s,
                %s
            );
        """, (
            telegram_id,
            task_id,
            reward
        ))

        # ----------------------------------------------------
        # UPDATE BALANCE
        # ----------------------------------------------------

        cur.execute("""
            UPDATE users
            SET

                balance =
                    balance + %s,

                total_earned =
                    total_earned + %s,

                completed_tasks =
                    completed_tasks + 1,

                last_active =
                    CURRENT_TIMESTAMP

            WHERE telegram_id = %s

            RETURNING *;
        """, (
            reward,
            reward,
            telegram_id
        ))

        updated_user = cur.fetchone()

        conn.commit()

        return {
            "success": True,
            "reward": reward,
            "user": updated_user
        }

    except Exception:

        conn.rollback()
        raise

    finally:

        cur.close()
        conn.close()
    # ============================================================
# WITHDRAWAL FUNCTIONS
# ============================================================

def create_withdrawal(
    telegram_id,
    method,
    account_number,
    amount
):

    try:

        amount = float(amount)

    except (ValueError, TypeError):

        return {
            "success": False,
            "message": "Invalid withdrawal amount."
        }

    if amount < 100:

        return {
            "success": False,
            "message":
                "Minimum withdrawal is 100 TaskCoins."
        }

    allowed_methods = (
        "bKash",
        "Nagad",
        "USDT",
        "usdt",
        "bkash",
        "nagad"
    )

    if method not in allowed_methods:

        return {
            "success": False,
            "message": "Invalid withdrawal method."
        }

    if not account_number:

        return {
            "success": False,
            "message":
                "Account number or wallet address is required."
        }

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cur.execute("""
            SELECT *
            FROM users
            WHERE telegram_id = %s
            FOR UPDATE;
        """, (
            telegram_id,
        ))

        user = cur.fetchone()

        if not user:

            conn.rollback()

            return {
                "success": False,
                "message": "User not found."
            }

        current_balance = float(
            user["balance"]
        )

        if current_balance < amount:

            conn.rollback()

            return {
                "success": False,
                "message": "Insufficient balance."
            }

        cur.execute("""
            UPDATE users
            SET

                balance =
                    balance - %s,

                total_withdrawn =
                    total_withdrawn + %s

            WHERE telegram_id = %s;
        """, (
            amount,
            amount,
            telegram_id
        ))

        cur.execute("""
            INSERT INTO withdrawals (
                telegram_id,
                method,
                account_number,
                amount,
                status
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                'pending'
            )
            RETURNING *;
        """, (
            telegram_id,
            method,
            account_number,
            amount
        ))

        withdrawal = cur.fetchone()

        conn.commit()

        return {
            "success": True,
            "withdrawal": withdrawal
        }

    except Exception:

        conn.rollback()
        raise

    finally:

        cur.close()
        conn.close()


def get_user_withdrawals(
    telegram_id
):

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cur.execute("""
            SELECT *
            FROM withdrawals
            WHERE telegram_id = %s
            ORDER BY id DESC;
        """, (
            telegram_id,
        ))

        return cur.fetchall()

    finally:

        cur.close()
        conn.close()


def get_all_withdrawals():

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cur.execute("""
            SELECT *
            FROM withdrawals
            ORDER BY id DESC;
        """)

        return cur.fetchall()

    finally:

        cur.close()
        conn.close()


def update_withdrawal_status(
    withdrawal_id,
    status
):

    if status not in (
        "pending",
        "approved",
        "rejected"
    ):

        return {
            "success": False,
            "message":
                "Invalid withdrawal status."
        }

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cur.execute("""
            SELECT *
            FROM withdrawals
            WHERE id = %s
            FOR UPDATE;
        """, (
            withdrawal_id,
        ))

        withdrawal = cur.fetchone()

        if not withdrawal:

            conn.rollback()

            return {
                "success": False,
                "message":
                    "Withdrawal not found."
            }

        old_status = withdrawal["status"]

        if old_status in (
            "approved",
            "rejected"
        ):

            conn.rollback()

            return {
                "success": False,
                "message":
                    "Withdrawal already processed."
            }

        if status == "rejected":

            cur.execute("""
                UPDATE users
                SET

                    balance =
                        balance + %s,

                    total_withdrawn =
                        GREATEST(
                            0,
                            total_withdrawn - %s
                        )

                WHERE telegram_id = %s;
            """, (
                withdrawal["amount"],
                withdrawal["amount"],
                withdrawal["telegram_id"]
            ))

        cur.execute("""
            UPDATE withdrawals
            SET

                status = %s,

                processed_at =
                    CURRENT_TIMESTAMP

            WHERE id = %s

            RETURNING *;
        """, (
            status,
            withdrawal_id
        ))

        updated = cur.fetchone()

        conn.commit()

        return {
            "success": True,
            "withdrawal": updated
        }

    except Exception:

        conn.rollback()
        raise

    finally:

        cur.close()
        conn.close()


# ============================================================
# REFERRAL FUNCTIONS
# ============================================================

def create_referral(
    referrer_id,
    referred_id,
    reward=0
):

    if referrer_id == referred_id:

        return {
            "success": False,
            "message":
                "Self referral is not allowed."
        }

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cur.execute("""
            SELECT id
            FROM referrals
            WHERE referrer_id = %s
            AND referred_id = %s
            LIMIT 1;
        """, (
            referrer_id,
            referred_id
        ))

        existing = cur.fetchone()

        if existing:

            conn.rollback()

            return {
                "success": False,
                "message":
                    "Referral already exists."
            }

        cur.execute("""
            INSERT INTO referrals (
                referrer_id,
                referred_id,
                reward
            )
            VALUES (
                %s,
                %s,
                %s
            )
            RETURNING *;
        """, (
            referrer_id,
            referred_id,
            reward
        ))

        referral = cur.fetchone()

        cur.execute("""
            UPDATE users
            SET
                referral_count =
                    referral_count + 1
            WHERE telegram_id = %s;
        """, (
            referrer_id,
        ))

        if reward and float(reward) > 0:

            cur.execute("""
                UPDATE users
                SET

                    balance =
                        balance + %s,

                    total_earned =
                        total_earned + %s

                WHERE telegram_id = %s;
            """, (
                reward,
                reward,
                referrer_id
            ))

        cur.execute("""
            UPDATE users
            SET
                referred_by = %s
            WHERE telegram_id = %s;
        """, (
            referrer_id,
            referred_id
        ))

        conn.commit()

        return {
            "success": True,
            "referral": referral
        }

    except Exception:

        conn.rollback()
        raise

    finally:

        cur.close()
        conn.close()


def get_user_referrals(
    telegram_id
):

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cur.execute("""
            SELECT
                r.*,
                u.username,
                u.first_name
            FROM referrals r
            LEFT JOIN users u
                ON u.telegram_id =
                   r.referred_id
            WHERE r.referrer_id = %s
            ORDER BY r.id DESC;
        """, (
            telegram_id,
        ))

        return cur.fetchall()

    finally:

        cur.close()
        conn.close()
# ============================================================
# ADMIN FUNCTIONS
# ============================================================

def get_admin_by_username(
    username
):

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cur.execute("""
            SELECT *
            FROM admins
            WHERE username = %s
            AND is_active = TRUE
            LIMIT 1;
        """, (
            username,
        ))

        return cur.fetchone()

    finally:

        cur.close()
        conn.close()


def create_admin(
    username,
    password
):

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        password_hash = hash_admin_password(
            password
        )

        cur.execute("""
            INSERT INTO admins (
                username,
                password_hash
            )
            VALUES (
                %s,
                %s
            )
            ON CONFLICT (username)
            DO UPDATE SET
                password_hash =
                    EXCLUDED.password_hash
            RETURNING *;
        """, (
            username,
            password_hash
        ))

        admin = cur.fetchone()

        conn.commit()

        return admin

    except Exception:

        conn.rollback()
        raise

    finally:

        cur.close()
        conn.close()


def create_admin_session(
    admin_id,
    hours=24
):

    token = secrets.token_urlsafe(48)

    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    expires_at = (
        datetime.utcnow()
        + timedelta(hours=hours)
    )

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cur.execute("""
            INSERT INTO admin_sessions (
                admin_id,
                token_hash,
                expires_at
            )
            VALUES (
                %s,
                %s,
                %s
            )
            RETURNING *;
        """, (
            admin_id,
            token_hash,
            expires_at
        ))

        session = cur.fetchone()

        conn.commit()

        return token, session

    except Exception:

        conn.rollback()
        raise

    finally:

        cur.close()
        conn.close()


def get_admin_by_token(
    token
):

    if not token:
        return None

    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cur.execute("""
            SELECT

                admins.id,
                admins.username,
                admins.is_active,
                admins.created_at,
                admins.last_login,

                admin_sessions.expires_at

            FROM admin_sessions

            INNER JOIN admins
                ON admins.id =
                   admin_sessions.admin_id

            WHERE admin_sessions.token_hash = %s

            AND admin_sessions.expires_at >
                CURRENT_TIMESTAMP

            AND admins.is_active = TRUE

            LIMIT 1;
        """, (
            token_hash,
        ))

        return cur.fetchone()

    finally:

        cur.close()
        conn.close()


def delete_admin_session(
    token
):

    if not token:
        return False

    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    conn = get_connection()

    cur = conn.cursor()

    try:

        cur.execute("""
            DELETE FROM admin_sessions
                       WHERE token_hash = %s;
        """, (
            token_hash,
        ))

        deleted = cur.rowcount > 0

        conn.commit()

        return deleted

    except Exception:

        conn.rollback()
        raise

    finally:

        cur.close()
        conn.close()


def update_admin_last_login(
    admin_id
):

    conn = get_connection()

    cur = conn.cursor()

    try:

        cur.execute("""
            UPDATE admins
            SET
                last_login =
                    CURRENT_TIMESTAMP
            WHERE id = %s;
        """, (
            admin_id,
        ))

        conn.commit()

    except Exception:

        conn.rollback()
        raise

    finally:

        cur.close()
        conn.close()


# ============================================================
# ADMIN DASHBOARD STATISTICS
# ============================================================

def get_dashboard_stats():

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cur.execute("""
            SELECT

                COUNT(*) AS total_users,

                COALESCE(
                    SUM(total_earned),
                    0
                ) AS total_earned,

                COALESCE(
                    SUM(total_withdrawn),
                    0
                ) AS total_withdrawn,

                COALESCE(
                    SUM(balance),
                    0
                ) AS total_balance

            FROM users;
        """)

        money = cur.fetchone()

        cur.execute("""
            SELECT COUNT(*) AS active_tasks
            FROM tasks
            WHERE is_active = TRUE;
        """)

        active_tasks = (
            cur.fetchone()["active_tasks"]
        )

        cur.execute("""
            SELECT COUNT(*) AS pending_withdrawals
            FROM withdrawals
            WHERE status = 'pending';
        """)

        pending_withdrawals = (
            cur.fetchone()["pending_withdrawals"]
        )

        return {

            "total_users":
                money["total_users"],

            "active_tasks":
                active_tasks,

            "pending_withdrawals":
                pending_withdrawals,

            "total_earned":
                money["total_earned"],

            "total_withdrawn":
                money["total_withdrawn"],

            "total_balance":
                money["total_balance"]
        }

    finally:

        cur.close()
        conn.close()

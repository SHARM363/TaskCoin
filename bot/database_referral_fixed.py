import os
import hashlib
import secrets
import hmac
import random

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

                task_balance NUMERIC(20, 2)
                    DEFAULT 0,

                deposit_balance NUMERIC(20, 2)
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
        # MONETAG POSTBACKS
        # ----------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS monetag_postbacks (
                id SERIAL PRIMARY KEY,
                ymid TEXT UNIQUE NOT NULL,
                telegram_id BIGINT NOT NULL,
                zone_id INTEGER,
                sub_zone_id INTEGER,
                event_type TEXT NOT NULL,
                reward_event_type TEXT NOT NULL,
                estimated_price NUMERIC(20, 8) DEFAULT 0,
                request_var TEXT,
                credited_reward NUMERIC(20, 2) DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'credited',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_monetag_postbacks_telegram_id
            ON monetag_postbacks(telegram_id);
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

        # Task audience migration:
        # NULL = all users (keeps existing tasks working),
        # 0 = non-VIP users only,
        # 1..10 = exact active VIP level only.
        cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS target_vip_level INTEGER DEFAULT NULL;")
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_target_vip_level
            ON tasks(target_vip_level);
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

                source TEXT NOT NULL DEFAULT 'task',

                status TEXT
                    DEFAULT 'pending',

                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP,

                processed_at TIMESTAMP
            );
        """)

        # ----------------------------------------------------
        # BALANCE SEPARATION MIGRATION (after withdrawals exists)
        # ----------------------------------------------------
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS task_balance NUMERIC(20,2) DEFAULT 0;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS deposit_balance NUMERIC(20,2) DEFAULT 0;")
        cur.execute("ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'task';")
        cur.execute("UPDATE users SET task_balance=COALESCE(balance,0) WHERE task_balance IS NULL OR task_balance=0;")
        cur.execute("UPDATE users SET balance=COALESCE(task_balance,0) WHERE balance IS NULL;")

        # ----------------------------------------------------
        # DEPOSITS
        # ----------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS deposits (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT NOT NULL,
                method TEXT NOT NULL,
                account_number TEXT,
                amount NUMERIC(20, 2) NOT NULL,
                transaction_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_deposits_user
            ON deposits(telegram_id);
        """)
        cur.execute("ALTER TABLE deposits ADD COLUMN IF NOT EXISTS account_number TEXT;")
        # ----------------------------------------------------
        # DEPOSIT PAYMENT SETTINGS (ADMIN CONTROLLED)
        # ----------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS deposit_payment_settings (
                method TEXT PRIMARY KEY,
                wallet_address TEXT NOT NULL DEFAULT '',
                instruction_type TEXT NOT NULL DEFAULT 'Send Money',
                network TEXT NOT NULL DEFAULT '',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            INSERT INTO deposit_payment_settings(method,wallet_address,instruction_type,network,is_active)
            VALUES
                ('bkash','','Send Money','',TRUE),
                ('nagad','','Send Money','',TRUE),
                ('usdt','','Send USDT','TRON (TRC20)',TRUE)
            ON CONFLICT (method) DO NOTHING;
        """)

        # ----------------------------------------------------
        # TASKCOIN -> CASH EXCHANGE
        # 1500 TaskCoins = 100 BDT. Multiples are allowed.
        # Approval credits Deposit Balance and transfers coins to
        # the admin ledger atomically.
        # ----------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS coin_exchanges (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT NOT NULL,
                coin_amount NUMERIC(20,2) NOT NULL,
                cash_amount NUMERIC(20,2) NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin_coin_ledger (
                id SERIAL PRIMARY KEY,
                exchange_id INTEGER NOT NULL UNIQUE,
                telegram_id BIGINT NOT NULL,
                coin_amount NUMERIC(20,2) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_coin_exchanges_user
            ON coin_exchanges(telegram_id);
        """)

        # ----------------------------------------------------
        # TASK STARTS / 10 SECOND COOLDOWN
        # ----------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS task_starts (
                telegram_id BIGINT NOT NULL,
                task_id INTEGER NOT NULL,
                started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (telegram_id, task_id)
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS task_cooldowns (
                telegram_id BIGINT NOT NULL,
                task_id INTEGER NOT NULL,
                available_at TIMESTAMP NOT NULL,
                PRIMARY KEY (telegram_id, task_id)
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

        cur.execute("""ALTER TABLE referrals ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending';""")
        cur.execute("""ALTER TABLE referrals ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP;""")
        cur.execute("""ALTER TABLE referrals ADD COLUMN IF NOT EXISTS approved_by INTEGER;""")
        # Keep pending referrals pending until an admin explicitly approves them.
        # Only normalize missing/blank status values; never auto-approve a referral.
        cur.execute("""
            UPDATE referrals
            SET status='pending'
            WHERE status IS NULL OR status='';
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
        # ADSGRAM REWARDS
        # ----------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS adsgram_rewards (

                id SERIAL PRIMARY KEY,

                telegram_id BIGINT NOT NULL,

                reward NUMERIC(20, 2)
                    NOT NULL DEFAULT 0,

                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_adsgram_rewards_user
            ON adsgram_rewards(telegram_id);
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

        # One account per IP address. This is used to prevent duplicate referral
        # accounts/bonuses from the same network address.
        cur.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS
            signup_ip TEXT;
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_signup_ip_unique
            ON users(signup_ip)
            WHERE signup_ip IS NOT NULL AND signup_ip <> '';
        """)

        # Admin-issued referral bonus ledger. One manual admin award per referral.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin_referral_bonus_awards (
                id SERIAL PRIMARY KEY,
                referral_id INTEGER UNIQUE NOT NULL,
                referrer_id BIGINT NOT NULL,
                referred_id BIGINT NOT NULL,
                amount NUMERIC(20,2) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # TaskCoin user-to-user transfer ledger.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS taskcoin_transfers (
                id BIGSERIAL PRIMARY KEY,
                sender_id BIGINT NOT NULL,
                receiver_id BIGINT NOT NULL,
                amount NUMERIC(20,2) NOT NULL CHECK (amount > 0),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_taskcoin_transfers_sender
            ON taskcoin_transfers(sender_id);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_taskcoin_transfers_receiver
            ON taskcoin_transfers(receiver_id);
        """)

        # Lifetime 5% commission ledger for approved referred-user deposits.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS referral_deposit_commissions (
                id SERIAL PRIMARY KEY,
                deposit_id INTEGER UNIQUE NOT NULL,
                referrer_id BIGINT NOT NULL,
                referred_id BIGINT NOT NULL,
                deposit_amount NUMERIC(20,2) NOT NULL,
                commission_rate NUMERIC(8,4) NOT NULL DEFAULT 5,
                commission_amount NUMERIC(20,2) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
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
        cur.execute("""
    CREATE TABLE IF NOT EXISTS adgem_conversions (
        id SERIAL PRIMARY KEY,

        request_id TEXT UNIQUE NOT NULL,

        conversion_id TEXT UNIQUE,

        player_id TEXT NOT NULL,

        telegram_id BIGINT NOT NULL,

        app_id TEXT,

        campaign_id TEXT,

        offer_id TEXT,

        goal_id TEXT,

        offer_name TEXT,

        goal_name TEXT,

        amount NUMERIC(20, 2) NOT NULL DEFAULT 0,

        payout NUMERIC(20, 6) NOT NULL DEFAULT 0,

        conversion_type TEXT,

        country TEXT,

        status TEXT NOT NULL DEFAULT 'credited',

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
""")

        # ----------------------------------------------------
        # LUCKY SPIN
        # ----------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS lucky_spin_prizes (
                id SERIAL PRIMARY KEY,
                wheel_group TEXT NOT NULL CHECK (wheel_group IN ('vip_1_5','vip_6_10')),
                prize_name TEXT NOT NULL,
                reward_type TEXT NOT NULL CHECK (reward_type IN ('bdt','taskcoin')),
                reward_amount NUMERIC(20,2) NOT NULL DEFAULT 0,
                chance NUMERIC(8,4) NOT NULL DEFAULT 0,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS lucky_spin_records (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT NOT NULL,
                vip_level INTEGER NOT NULL,
                wheel_group TEXT NOT NULL,
                prize_id INTEGER REFERENCES lucky_spin_prizes(id),
                reward_type TEXT NOT NULL,
                reward_amount NUMERIC(20,2) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_lucky_spin_records_user_day ON lucky_spin_records(telegram_id, created_at);")
        # Seed prizes only when the wheel has no prizes; Admin can later change chances/values.
        cur.execute("SELECT COUNT(*) FROM lucky_spin_prizes WHERE wheel_group='vip_1_5';")
        if int(cur.fetchone()[0] or 0) == 0:
            for row in [
                ('vip_1_5','৳300 Real Balance','bdt',300,5),
                ('vip_1_5','5,000 TaskCoins','taskcoin',5000,5),
                ('vip_1_5','2,500 TaskCoins','taskcoin',2500,15),
                ('vip_1_5','1,000 TaskCoins','taskcoin',1000,25),
                ('vip_1_5','200 TaskCoins','taskcoin',200,50),
            ]:
                cur.execute("INSERT INTO lucky_spin_prizes(wheel_group,prize_name,reward_type,reward_amount,chance) VALUES(%s,%s,%s,%s,%s)", row)
        cur.execute("SELECT COUNT(*) FROM lucky_spin_prizes WHERE wheel_group='vip_6_10';")
        if int(cur.fetchone()[0] or 0) == 0:
            for row in [
                ('vip_6_10','৳500 Real Balance','bdt',500,5),
                ('vip_6_10','8,500 TaskCoins','taskcoin',8500,5),
                ('vip_6_10','4,500 TaskCoins','taskcoin',4500,15),
                ('vip_6_10','2,500 TaskCoins','taskcoin',2500,25),
                ('vip_6_10','1,500 TaskCoins','taskcoin',1500,50),
            ]:
                cur.execute("INSERT INTO lucky_spin_prizes(wheel_group,prize_name,reward_type,reward_amount,chance) VALUES(%s,%s,%s,%s,%s)", row)

        # ----------------------------------------------------
        # PREMIUM / VIP MEMBERSHIP
        # ----------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS premium_plans (
                id SERIAL PRIMARY KEY,
                level INTEGER UNIQUE NOT NULL,
                duration_days INTEGER NOT NULL,
                price NUMERIC(20,2) NOT NULL,
                bonus_website_tasks INTEGER NOT NULL DEFAULT 0,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS premium_memberships (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT NOT NULL,
                plan_id INTEGER NOT NULL REFERENCES premium_plans(id),
                status TEXT NOT NULL DEFAULT 'pending',
                price_paid NUMERIC(20,2) NOT NULL DEFAULT 0,
                requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_at TIMESTAMP,
                starts_at TIMESTAMP,
                expires_at TIMESTAMP,
                rejected_at TIMESTAMP,
                rejection_reason TEXT
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_premium_memberships_user
            ON premium_memberships(telegram_id);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_premium_memberships_status
            ON premium_memberships(status);
        """)
        # Seed the fixed VIP catalog. Prices/bonus counts remain editable later from Admin.
        premium_seed = [
            (1, 7, 150, 5),
            (2, 7, 300, 8),
            (3, 7, 600, 12),
            (4, 7, 900, 18),
            (5, 30, 1450, 24),
            (6, 30, 1899, 29),
            (7, 30, 2344, 35),
            (8, 30, 2899, 42),
            (9, 30, 3466, 48),
            (10, 30, 4599, 50),
        ]
        for level, days, price, bonus in premium_seed:
            cur.execute("""
                INSERT INTO premium_plans(level,duration_days,price,bonus_website_tasks)
                VALUES(%s,%s,%s,%s)
                ON CONFLICT(level) DO NOTHING;
            """, (level, days, price, bonus))

        # Correct the two old default bonus values once, but never overwrite
        # a value that the admin has already customized.
        cur.execute("UPDATE premium_plans SET bonus_website_tasks=48 WHERE level=9 AND bonus_website_tasks=57;")
        cur.execute("UPDATE premium_plans SET bonus_website_tasks=50 WHERE level=10 AND bonus_website_tasks=80;")

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

        # Safe legacy referral repair:
        # If an old user's account already contains a trusted `referred_by`
        # value but no referral row exists, create ONLY a pending request.
        # No balance, task balance, referral count, or earnings are changed.
        # Existing referral rows are never modified here.
        cur.execute("""
            INSERT INTO referrals (referrer_id,referred_id,reward,status)
            SELECT
                referred.referred_by,
                referred.telegram_id,
                500,
                'pending'
            FROM users AS referred
            INNER JOIN users AS referrer
                ON referrer.telegram_id = referred.referred_by
            WHERE referred.referred_by IS NOT NULL
              AND referred.referred_by <> referred.telegram_id
              AND NOT EXISTS (
                  SELECT 1
                  FROM referrals AS r
                  WHERE r.referred_id = referred.telegram_id
              );
        """)

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
    first_name=None,
    referrer_id=None,
    signup_ip=None
):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    REFERRAL_REWARD = 500
    try:
        referral_code = "TC" + str(telegram_id)
        cur.execute("SELECT * FROM users WHERE telegram_id = %s FOR UPDATE;", (telegram_id,))
        existing = cur.fetchone()
        if existing:
            cur.execute("""
                UPDATE users
                SET username=%s,
                    first_name=%s,
                    signup_ip=CASE
                        WHEN signup_ip IS NULL OR signup_ip='' THEN %s
                        ELSE signup_ip
                    END,
                    last_active=CURRENT_TIMESTAMP
                WHERE telegram_id=%s
                RETURNING *;
            """, (username, first_name, signup_ip, telegram_id))
            user = cur.fetchone()

            # If an existing account arrives through a valid referral link,
            # restore/create the referral request only when this account has
            # never had a referral relationship before. This does NOT pay
            # any bonus; the Admin must approve the pending request.
            if referrer_id and not user.get("referred_by"):
                try:
                    candidate_referrer = int(referrer_id)
                except (TypeError, ValueError):
                    candidate_referrer = None

                if candidate_referrer and candidate_referrer != int(telegram_id):
                    cur.execute(
                        "SELECT telegram_id FROM users WHERE telegram_id=%s FOR UPDATE;",
                        (candidate_referrer,)
                    )
                    referrer = cur.fetchone()

                    if referrer:
                        cur.execute(
                            "SELECT id FROM referrals WHERE referred_id=%s LIMIT 1 FOR UPDATE;",
                            (telegram_id,)
                        )
                        existing_referral = cur.fetchone()

                        if not existing_referral:
                            cur.execute(
                                """
                                UPDATE users
                                SET referred_by=%s
                                WHERE telegram_id=%s
                                  AND referred_by IS NULL;
                                """,
                                (candidate_referrer, telegram_id)
                            )
                            cur.execute(
                                """
                                INSERT INTO referrals
                                    (referrer_id,referred_id,reward,status)
                                VALUES
                                    (%s,%s,%s,'pending')
                                RETURNING *;
                                """,
                                (candidate_referrer, telegram_id, REFERRAL_REWARD)
                            )
                            user["referred_by"] = candidate_referrer

            conn.commit()
            return user

        if signup_ip:
            cur.execute("SELECT telegram_id FROM users WHERE signup_ip=%s LIMIT 1 FOR UPDATE;", (signup_ip,))
            ip_user = cur.fetchone()
            if ip_user and int(ip_user["telegram_id"]) != int(telegram_id):
                conn.rollback()
                raise ValueError("Only one TaskCoin account is allowed from the same IP address.")

        cur.execute("""
            INSERT INTO users (telegram_id, username, first_name, referral_code, signup_ip, last_active)
            VALUES (%s,%s,%s,%s,%s,CURRENT_TIMESTAMP) RETURNING *;
        """, (telegram_id, username, first_name, referral_code, signup_ip))
        user = cur.fetchone()

        if referrer_id:
            try:
                referrer_id = int(referrer_id)
            except (TypeError, ValueError):
                referrer_id = None

            if referrer_id and referrer_id != telegram_id:
                cur.execute(
                    "SELECT telegram_id FROM users WHERE telegram_id=%s FOR UPDATE;",
                    (referrer_id,)
                )
                referrer = cur.fetchone()

                if referrer:
                    cur.execute(
                        "SELECT id FROM referrals WHERE referred_id=%s LIMIT 1 FOR UPDATE;",
                        (telegram_id,)
                    )
                    existing_referral = cur.fetchone()

                    if not existing_referral:
                        # Save the relationship, but DO NOT credit the bonus yet.
                        # Admin approval will credit the referrer atomically.
                        cur.execute(
                            """
                            UPDATE users
                            SET referred_by=%s
                            WHERE telegram_id=%s
                              AND referred_by IS NULL;
                            """,
                            (referrer_id, telegram_id)
                        )
                        cur.execute(
                            """
                            INSERT INTO referrals (referrer_id,referred_id,reward,status)
                            VALUES (%s,%s,%s,'pending')
                            RETURNING *;
                            """,
                            (referrer_id, telegram_id, REFERRAL_REWARD)
                        )
        conn.commit()
        return user
    except Exception:
        conn.rollback(); raise
    finally:
        cur.close(); conn.close()


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


def get_active_tasks_for_user(telegram_id):
    """Return only tasks the user's current VIP status is allowed to see.

    target_vip_level semantics:
      NULL -> all users (backward-compatible/general task)
      0    -> non-VIP users only
      1-10 -> exact active VIP level only
    """
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT *
            FROM tasks t
            WHERE t.is_active = TRUE
              AND (
                    t.target_vip_level IS NULL
                    OR (t.target_vip_level = 0 AND NOT EXISTS (
                        SELECT 1
                        FROM premium_memberships pm
                        WHERE pm.telegram_id = %s
                          AND pm.status = 'active'
                          AND pm.expires_at > CURRENT_TIMESTAMP
                    ))
                    OR (t.target_vip_level BETWEEN 1 AND 10 AND EXISTS (
                        SELECT 1
                        FROM premium_memberships pm
                        JOIN premium_plans pp ON pp.id = pm.plan_id
                        WHERE pm.telegram_id = %s
                          AND pm.status = 'active'
                          AND pm.expires_at > CURRENT_TIMESTAMP
                          AND pp.level = t.target_vip_level
                    ))
              )
            ORDER BY t.id DESC;
        """, (telegram_id, telegram_id))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def task_allowed_for_user(cur, telegram_id, task):
    """Authoritative server-side task audience check."""
    target = task.get('target_vip_level')
    if target is None:
        return True
    target = int(target)

    cur.execute("""
        SELECT pp.level
        FROM premium_memberships pm
        JOIN premium_plans pp ON pp.id = pm.plan_id
        WHERE pm.telegram_id = %s
          AND pm.status = 'active'
          AND pm.expires_at > CURRENT_TIMESTAMP
        ORDER BY pm.expires_at DESC
        LIMIT 1;
    """, (telegram_id,))
    membership = cur.fetchone()
    active_level = int(membership['level']) if membership else None

    if target == 0:
        return active_level is None
    return active_level == target


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
    is_active=True,
    target_vip_level=None
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
                is_active,
                target_vip_level
            )
            VALUES (
                %s,
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
            is_active,
            target_vip_level
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
    is_active=None,
    target_vip_level=None
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

                target_vip_level =
                    CASE
                        WHEN %s::INTEGER IS NULL THEN target_vip_level
                        ELSE %s::INTEGER
                    END,

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
            target_vip_level,
            target_vip_level,
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
 # ============================================================
# ADSGRAM REWARD
# ============================================================

def add_adsgram_reward(
    telegram_id,
    reward
):
    """
    Credit an AdsGram reward to a user.
    """

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        reward = float(reward)

        if reward <= 0:
            return {
                "success": False,
                "message": "Invalid reward."
            }

        # Lock user row
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

        # Credit balance
        cur.execute("""
            UPDATE users
            SET
                task_balance = COALESCE(task_balance, 0) + %s,
                balance = COALESCE(task_balance, 0) + %s,

                total_earned =
                    COALESCE(total_earned, 0) + %s,

                last_active =
                    CURRENT_TIMESTAMP

            WHERE telegram_id = %s

            RETURNING *;
        """, (
            reward,
            reward,
            reward,
            telegram_id
        ))

        updated_user = cur.fetchone()

        # Save reward record
        cur.execute("""
            INSERT INTO adsgram_rewards (
                telegram_id,
                reward
            )
            VALUES (
                %s,
                %s
            )
            RETURNING *;
        """, (
            telegram_id,
            reward
        ))

        reward_record = cur.fetchone()

        conn.commit()

        return {
            "success": True,
            "reward": reward,
            "user": updated_user,
            "reward_record": reward_record
        }

    except Exception:

        conn.rollback()

        raise

    finally:

        cur.close()
        conn.close()

def claim_task_reward(telegram_id, task_id):
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM users WHERE telegram_id=%s FOR UPDATE;",(telegram_id,)); user=cur.fetchone()
        if not user: conn.rollback(); return {"success":False,"message":"User not found."}
        cur.execute("SELECT * FROM tasks WHERE id=%s AND is_active=TRUE FOR UPDATE;",(task_id,)); task=cur.fetchone()
        if not task: conn.rollback(); return {"success":False,"message":"Task not found or inactive."}
        if not task_allowed_for_user(cur, telegram_id, task):
            target = task.get('target_vip_level')
            if target == 0:
                msg = "This task is available to Non-VIP users only."
            else:
                msg = f"This task is reserved for VIP Level {int(target)}."
            conn.rollback(); return {"success":False,"message":msg}
        platform=str(task.get('platform') or '').strip().lower()
        is_social=platform in PREMIUM_SOCIAL_PLATFORMS
        is_website=platform in ('website','webview','web view','web-view','site')
        is_webview=platform in ('webview','web view','web-view')
        if is_social:
            # Five Social tasks per day: one completion per social platform.
            cur.execute("SELECT 1 FROM task_completions tc JOIN tasks t ON t.id=tc.task_id WHERE tc.telegram_id=%s AND tc.completed_date=CURRENT_DATE AND lower(trim(coalesce(t.platform,'')))=%s LIMIT 1;",(telegram_id,platform))
            if cur.fetchone():
                conn.rollback(); return {"success":False,"message":f'{platform.title()} task limit reached for today.'}
        elif is_website:
            cur.execute("SELECT COUNT(*) AS total FROM task_completions tc JOIN tasks t ON t.id=tc.task_id WHERE tc.telegram_id=%s AND tc.completed_date=CURRENT_DATE AND lower(trim(coalesce(t.platform,''))) IN ('website','webview','web view','web-view','site');",(telegram_id,))
            website_count=int(cur.fetchone()['total'] or 0)
            cur.execute("SELECT 1 FROM premium_memberships pm WHERE pm.telegram_id=%s AND pm.status='active' AND pm.expires_at>CURRENT_TIMESTAMP LIMIT 1;",(telegram_id,))
            pmrow=cur.fetchone()
            website_limit=20 if pmrow else 7
            if website_count >= website_limit:
                conn.rollback(); return {"success":False,"message":f'Website daily limit of {website_limit} tasks reached.'}
        else:
            cur.execute("SELECT 1 FROM task_completions WHERE telegram_id=%s AND task_id=%s AND completed_date=CURRENT_DATE LIMIT 1;",(telegram_id,task_id))
            if cur.fetchone(): conn.rollback(); return {"success":False,"message":"Task already completed today."}
        # A real Start record is required, and duration must elapse.
        cur.execute("SELECT started_at FROM task_starts WHERE telegram_id=%s AND task_id=%s;",(telegram_id,task_id)); st=cur.fetchone()
        if not st: conn.rollback(); return {"success":False,"message":"Start Task first."}
        cur.execute("SELECT EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP-%s)) AS seconds;",(st['started_at'],)); elapsed=float(cur.fetchone()['seconds'] or 0)
        required=max(1,int(task.get('duration') or 20))
        # For rewarded-ad tasks the ad completion is the completion gate; do not
        # reject a valid claim merely because the configured page duration is longer
        # than the ad. Non-ad tasks keep the original duration requirement.
        if not is_webview and elapsed < required:
            conn.rollback(); return {"success":False,"message":f"Please complete the task for at least {required} seconds.","remaining":max(0,required-int(elapsed))}
        cur.execute("SELECT available_at FROM task_cooldowns WHERE telegram_id=%s AND task_id=%s;",(telegram_id,task_id)); cd=cur.fetchone()
        if cd:
            cur.execute("SELECT EXTRACT(EPOCH FROM (%s-CURRENT_TIMESTAMP)) AS seconds;",(cd['available_at'],)); remain=float(cur.fetchone()['seconds'] or 0)
            if remain>0: conn.rollback(); return {"success":False,"message":"Please wait before starting this task again.","cooldown":int(remain)+1}
        reward=float(task['reward'] or 0)
        cur.execute("INSERT INTO task_completions(telegram_id,task_id,reward,completed_date) VALUES(%s,%s,%s,CURRENT_DATE) RETURNING *;",(telegram_id,task_id,reward)); completion=cur.fetchone()
        cur.execute("UPDATE users SET task_balance=COALESCE(task_balance,0)+%s,balance=COALESCE(task_balance,0)+%s,total_earned=COALESCE(total_earned,0)+%s,completed_tasks=COALESCE(completed_tasks,0)+1,last_active=CURRENT_TIMESTAMP WHERE telegram_id=%s RETURNING *;",(reward,reward,reward,telegram_id)); updated=cur.fetchone()
        if not updated: raise RuntimeError('User disappeared while claiming task.')
        # 10-second cooldown after a successful reward.
        cur.execute("INSERT INTO task_cooldowns(telegram_id,task_id,available_at) VALUES(%s,%s,CURRENT_TIMESTAMP+INTERVAL '10 seconds') ON CONFLICT(telegram_id,task_id) DO UPDATE SET available_at=EXCLUDED.available_at;",(telegram_id,task_id))
        cur.execute("DELETE FROM task_starts WHERE telegram_id=%s AND task_id=%s;",(telegram_id,task_id))
        conn.commit(); return {"success":True,"message":"Task completed successfully.","reward":reward,"completion":completion,"user":updated,"cooldown_seconds":10,"webview":is_webview}
    except Exception: conn.rollback(); raise
    finally: cur.close(); conn.close()


# ============================================================
# PREMIUM / VIP MEMBERSHIP FUNCTIONS
# ============================================================

PREMIUM_SOCIAL_PLATFORMS = {'facebook', 'tiktok', 'youtube', 'telegram', 'instagram'}


def get_premium_plans(active_only=True):
    conn = get_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        sql = "SELECT * FROM premium_plans"
        if active_only:
            sql += " WHERE is_active=TRUE"
        sql += " ORDER BY level ASC"
        cur.execute(sql)
        return cur.fetchall()
    finally:
        cur.close(); conn.close()


def get_premium_plan(level):
    conn = get_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM premium_plans WHERE level=%s AND is_active=TRUE", (level,))
        return cur.fetchone()
    finally:
        cur.close(); conn.close()


def get_active_premium(telegram_id):
    conn = get_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            UPDATE premium_memberships
            SET status='expired'
            WHERE telegram_id=%s AND status='active'
              AND expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP;
        """, (telegram_id,))
        conn.commit()
        cur.execute("""
            SELECT pm.*, pp.level, pp.duration_days, pp.price, pp.bonus_website_tasks
            FROM premium_memberships pm
            JOIN premium_plans pp ON pp.id=pm.plan_id
            WHERE pm.telegram_id=%s AND pm.status='active'
              AND pm.expires_at > CURRENT_TIMESTAMP
            ORDER BY pm.expires_at DESC LIMIT 1;
        """, (telegram_id,))
        return cur.fetchone()
    finally:
        cur.close(); conn.close()


def get_user_premium_memberships(telegram_id):
    """Return all non-rejected VIP memberships for the user, expiring old ones first."""
    conn = get_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            UPDATE premium_memberships
            SET status='expired'
            WHERE telegram_id=%s AND status='active'
              AND expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP;
        """, (telegram_id,))
        conn.commit()
        cur.execute("""
            SELECT pm.*, pp.level, pp.duration_days, pp.price, pp.bonus_website_tasks, pp.is_active AS plan_is_active
            FROM premium_memberships pm
            JOIN premium_plans pp ON pp.id=pm.plan_id
            WHERE pm.telegram_id=%s AND pm.status IN ('pending','active','expired')
            ORDER BY pp.level ASC, pm.requested_at DESC;
        """, (telegram_id,))
        return cur.fetchall()
    finally:
        cur.close(); conn.close()


def purchase_premium(telegram_id, level):
    conn = get_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM users WHERE telegram_id=%s FOR UPDATE", (telegram_id,))
        user = cur.fetchone()
        if not user:
            conn.rollback(); return {'success':False,'message':'User not found.'}
        cur.execute("SELECT * FROM premium_plans WHERE level=%s AND is_active=TRUE FOR UPDATE", (level,))
        plan = cur.fetchone()
        if not plan:
            conn.rollback(); return {'success':False,'message':'Premium plan not found or disabled by admin.'}

        # A user may own different VIP levels. Only block another purchase of
        # the same level while that level is pending/active.
        cur.execute("""
            SELECT pm.id FROM premium_memberships pm
            WHERE pm.telegram_id=%s AND pm.plan_id=%s
              AND pm.status IN ('pending','active')
              AND (pm.status='pending' OR pm.expires_at > CURRENT_TIMESTAMP)
            LIMIT 1 FOR UPDATE;
        """, (telegram_id, plan['id']))
        if cur.fetchone():
            conn.rollback(); return {'success':False,'message':f'VIP Level {level} is already pending or active.'}
        price=float(plan['price'] or 0)
        deposit=float(user['deposit_balance'] or 0)
        if deposit < price:
            conn.rollback(); return {'success':False,'message':f'Insufficient Deposit Balance. Need {price:.2f}.'}
        cur.execute("UPDATE users SET deposit_balance=COALESCE(deposit_balance,0)-%s WHERE telegram_id=%s RETURNING *", (price,telegram_id))
        updated=cur.fetchone()
        cur.execute("""
            INSERT INTO premium_memberships(telegram_id,plan_id,status,price_paid)
            VALUES(%s,%s,'pending',%s) RETURNING *;
        """, (telegram_id,plan['id'],price))
        membership=cur.fetchone()
        conn.commit()
        return {'success':True,'message':'Premium request submitted. Waiting for admin approval.','membership':membership,'plan':plan,'user':updated}
    except Exception:
        conn.rollback(); raise
    finally:
        cur.close(); conn.close()


def get_premium_membership_requests(status='pending'):
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT pm.*, u.username, u.first_name, u.deposit_balance,
                   pp.level, pp.duration_days, pp.price, pp.bonus_website_tasks
            FROM premium_memberships pm
            JOIN users u ON u.telegram_id=pm.telegram_id
            JOIN premium_plans pp ON pp.id=pm.plan_id
            WHERE pm.status=%s ORDER BY pm.requested_at ASC;
        """, (status,))
        return cur.fetchall()
    finally:
        cur.close(); conn.close()


def update_premium_membership_status(membership_id, status, reason=None):
    allowed={'active','rejected','expired'}
    if status not in allowed:
        return {'success':False,'message':'Invalid Premium status.'}
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT pm.*, pp.duration_days, pp.price, pp.level, pp.bonus_website_tasks
            FROM premium_memberships pm JOIN premium_plans pp ON pp.id=pm.plan_id
            WHERE pm.id=%s FOR UPDATE;
        """, (membership_id,))
        m=cur.fetchone()
        if not m: conn.rollback(); return {'success':False,'message':'Premium membership not found.'}
        if m['status'] != 'pending':
            conn.rollback(); return {'success':False,'message':'Only pending Premium requests can be approved or rejected.'}
        if status=='active':
            cur.execute("""
                UPDATE premium_memberships
                SET status='active', approved_at=CURRENT_TIMESTAMP,
                    starts_at=CURRENT_TIMESTAMP,
                    expires_at=CURRENT_TIMESTAMP + (%s * INTERVAL '1 day')
                WHERE id=%s RETURNING *;
            """, (int(m['duration_days']), membership_id))
        else:
            # Refund the purchase to Deposit Balance on rejection.
            cur.execute("UPDATE users SET deposit_balance=COALESCE(deposit_balance,0)+%s WHERE telegram_id=%s", (m['price_paid'],m['telegram_id']))
            cur.execute("""
                UPDATE premium_memberships
                SET status='rejected', rejected_at=CURRENT_TIMESTAMP, rejection_reason=%s
                WHERE id=%s RETURNING *;
            """, (reason or 'Rejected by admin.', membership_id))
        result=cur.fetchone()
        conn.commit()
        return {'success':True,'membership':result}
    except Exception:
        conn.rollback(); raise
    finally:
        cur.close(); conn.close()


def get_premium_daily_status(telegram_id):
    membership=get_active_premium(telegram_id)
    if not membership:
        return {'active':False,'level':None,'bonus_website_tasks':0,'expires_at':None}
    return {'active':True,'level':int(membership['level']),'bonus_website_tasks':int(membership['bonus_website_tasks'] or 0),'expires_at':membership['expires_at']}


def _daily_platform_count(cur, telegram_id, platforms):
    cur.execute("""
        SELECT COUNT(*) FROM task_completions tc
        JOIN tasks t ON t.id=tc.task_id
        WHERE tc.telegram_id=%s AND tc.completed_date=CURRENT_DATE
          AND lower(trim(coalesce(t.platform,''))) = ANY(%s);
    """, (telegram_id, list(platforms)))
    return int(cur.fetchone()[0] or 0)


def get_daily_task_limits(telegram_id):
    membership=get_active_premium(telegram_id)
    bonus=int(membership['bonus_website_tasks'] or 0) if membership else 0
    # Website tasks reset automatically at the database's CURRENT_DATE boundary.
    # Exact product rule: VIP = 20 website tasks/day, Non-VIP = 7/day.
    website_limit = 20 if membership else 7
    return {'social':5,'website':website_limit,'premium_bonus_website':bonus,'premium_active':bool(membership),'premium_level':int(membership['level']) if membership else None}

# ============================================================
# WITHDRAWAL FUNCTIONS
# ============================================================

def create_withdrawal(telegram_id, method, account_number, amount, source='task'):
    try: amount=float(amount)
    except (ValueError, TypeError): return {"success":False,"message":"Invalid withdrawal amount."}
    source=str(source or 'task').strip().lower()
    if source not in ('task','deposit'): return {"success":False,"message":"Invalid withdrawal source."}
    # Task/main balance: minimum 1000 TaskCoins. Deposit balance: minimum 1500 BDT.
    minimum = 1000 if source == 'task' else 1500
    if amount < minimum: return {"success":False,"message":f"Minimum withdrawal is {minimum} {'TaskCoins' if source=='task' else 'BDT'}."}
    if amount > 30000: return {"success":False,"message":"Maximum withdrawal is 30000."}
    method_norm=str(method or '').strip()
    allowed={"bkash":"bKash","nagad":"Nagad","usdt":"USDT"}
    method_key=method_norm.lower()
    if method_key not in allowed: return {"success":False,"message":"Invalid withdrawal method."}
    if not account_number: return {"success":False,"message":"Account number or wallet address is required."}
    if method_key == 'usdt' and not (str(account_number).startswith('T') and len(str(account_number))==34): return {"success":False,"message":"Invalid USDT TRC20 wallet address."}
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM users WHERE telegram_id=%s FOR UPDATE;",(telegram_id,)); user=cur.fetchone()
        if not user: conn.rollback(); return {"success":False,"message":"User not found."}
        cur.execute("SELECT 1 FROM withdrawals WHERE telegram_id=%s AND (created_at AT TIME ZONE 'Asia/Dhaka')::date=(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Dhaka')::date LIMIT 1;",(telegram_id,))
        if cur.fetchone(): conn.rollback(); return {"success":False,"message":"You can withdraw only once per day."}
        field = 'task_balance' if source == 'task' else 'deposit_balance'
        current=float(user[field] or 0)
        if current < amount: conn.rollback(); return {"success":False,"message":"Insufficient balance."}
        if source == 'task':
            cur.execute("UPDATE users SET task_balance=COALESCE(task_balance,0)-%s,balance=COALESCE(task_balance,0)-%s,total_withdrawn=total_withdrawn+%s WHERE telegram_id=%s;",(amount,amount,amount,telegram_id))
        else:
            cur.execute("UPDATE users SET deposit_balance=COALESCE(deposit_balance,0)-%s,total_withdrawn=total_withdrawn+%s WHERE telegram_id=%s;",(amount,amount,telegram_id))
        cur.execute("""INSERT INTO withdrawals(telegram_id,method,account_number,amount,status,source) VALUES(%s,%s,%s,%s,'pending',%s) RETURNING *;""",(telegram_id,allowed[method_key],account_number,amount,source))
        withdrawal=cur.fetchone(); conn.commit(); return {"success":True,"withdrawal":withdrawal}
    except Exception: conn.rollback(); raise
    finally: cur.close(); conn.close()


# ============================================================
# TASKCOIN -> CASH EXCHANGE
# ============================================================

def create_exchange_request(telegram_id, coin_amount):
    try: coin_amount=float(coin_amount)
    except (ValueError, TypeError): return {"success":False,"message":"Invalid TaskCoin amount."}
    if coin_amount < 1500: return {"success":False,"message":"Minimum exchange is 1500 TaskCoins."}
    if coin_amount % 1500 != 0: return {"success":False,"message":"TaskCoins must be exchanged in multiples of 1500."}
    cash_amount=coin_amount/15.0
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM users WHERE telegram_id=%s FOR UPDATE;",(telegram_id,)); user=cur.fetchone()
        if not user: conn.rollback(); return {"success":False,"message":"User not found."}
        balance=float(user['task_balance'] or 0)
        if balance < coin_amount: conn.rollback(); return {"success":False,"message":"Insufficient TaskCoin balance."}
        cur.execute("INSERT INTO coin_exchanges(telegram_id,coin_amount,cash_amount,status) VALUES(%s,%s,%s,'pending') RETURNING *;",(telegram_id,coin_amount,cash_amount))
        row=cur.fetchone(); conn.commit(); return {"success":True,"message":"Exchange request sent to admin for approval.","exchange":row}
    except Exception: conn.rollback(); raise
    finally: cur.close(); conn.close()

def get_user_exchanges(telegram_id):
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM coin_exchanges WHERE telegram_id=%s ORDER BY id DESC;",(telegram_id,)); return cur.fetchall()
    finally: cur.close(); conn.close()

def get_all_exchanges():
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM coin_exchanges ORDER BY id DESC;"); return cur.fetchall()
    finally: cur.close(); conn.close()

def update_exchange_status(exchange_id,status):
    if status not in ('approved','rejected'): return {"success":False,"message":"Invalid exchange status."}
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM coin_exchanges WHERE id=%s FOR UPDATE;",(exchange_id,)); ex=cur.fetchone()
        if not ex: conn.rollback(); return {"success":False,"message":"Exchange request not found."}
        if ex['status'] != 'pending': conn.rollback(); return {"success":False,"message":"Exchange request already processed."}
        if status == 'approved':
            cur.execute("SELECT * FROM users WHERE telegram_id=%s FOR UPDATE;",(ex['telegram_id'],)); user=cur.fetchone()
            if not user: conn.rollback(); return {"success":False,"message":"User not found."}
            if float(user['task_balance'] or 0) < float(ex['coin_amount']): conn.rollback(); return {"success":False,"message":"User no longer has enough TaskCoins for this exchange."}
            cur.execute("UPDATE users SET task_balance=task_balance-%s,balance=task_balance-%s,deposit_balance=COALESCE(deposit_balance,0)+%s WHERE telegram_id=%s RETURNING *;",(ex['coin_amount'],ex['coin_amount'],ex['cash_amount'],ex['telegram_id']))
            cur.execute("INSERT INTO admin_coin_ledger(exchange_id,telegram_id,coin_amount) VALUES(%s,%s,%s);",(exchange_id,ex['telegram_id'],ex['coin_amount']))
        cur.execute("UPDATE coin_exchanges SET status=%s,processed_at=CURRENT_TIMESTAMP WHERE id=%s RETURNING *;",(status,exchange_id)); row=cur.fetchone(); conn.commit(); return {"success":True,"exchange":row}
    except Exception: conn.rollback(); raise
    finally: cur.close(); conn.close()

def get_deposit_payment_settings(active_only=True):
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        sql="SELECT * FROM deposit_payment_settings"
        if active_only: sql += " WHERE is_active=TRUE"
        sql += " ORDER BY CASE method WHEN 'bkash' THEN 1 WHEN 'nagad' THEN 2 WHEN 'usdt' THEN 3 ELSE 9 END"
        cur.execute(sql); return cur.fetchall()
    finally: cur.close(); conn.close()

def update_deposit_payment_setting(method, wallet_address, instruction_type='Send Money', network='', is_active=True):
    method=str(method or '').strip().lower()
    if method not in ('bkash','nagad','usdt'): return {'success':False,'message':'Invalid payment method.'}
    wallet_address=str(wallet_address or '').strip()
    if not wallet_address: return {'success':False,'message':'Wallet/account number is required.'}
    instruction_type=str(instruction_type or 'Send Money').strip()[:80]
    network='TRON (TRC20)' if method=='usdt' else ''
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""INSERT INTO deposit_payment_settings(method,wallet_address,instruction_type,network,is_active,updated_at)
                      VALUES(%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)
                      ON CONFLICT(method) DO UPDATE SET wallet_address=EXCLUDED.wallet_address,instruction_type=EXCLUDED.instruction_type,network=EXCLUDED.network,is_active=EXCLUDED.is_active,updated_at=CURRENT_TIMESTAMP
                      RETURNING *;""",(method,wallet_address,instruction_type,network,bool(is_active)))
        row=cur.fetchone(); conn.commit(); return {'success':True,'setting':row}
    except Exception: conn.rollback(); raise
    finally: cur.close(); conn.close()

def create_deposit(telegram_id, method, amount, transaction_id, account_number=None):
    try: amount=float(amount)
    except (ValueError,TypeError): return {"success":False,"message":"Invalid deposit amount."}
    if amount < 500 or amount > 25000: return {"success":False,"message":"Deposit amount must be between 500 and 25000 BDT."}
    method_key=str(method or '').strip().lower()
    methods={"bkash":"bKash","nagad":"Nagad","usdt":"USDT"}
    if method_key not in methods: return {"success":False,"message":"Invalid deposit method."}
    tx=str(transaction_id or '').strip()
    account=str(account_number or '').strip()
    if not account: return {"success":False,"message":"Payment sender number or wallet address is required."}
    if not tx: return {"success":False,"message":"Transaction ID / hash is required."}
    if method_key=='usdt' and not (account.startswith('T') and len(account)==34): return {"success":False,"message":"Enter a valid USDT TRC20 sender wallet address."}
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT wallet_address,is_active FROM deposit_payment_settings WHERE method=%s;",(method_key,)); setting=cur.fetchone()
        if not setting or not setting['is_active'] or not setting['wallet_address']:
            conn.rollback(); return {"success":False,"message":f'{methods[method_key]} deposit is currently unavailable. Admin has not configured the payment wallet.'}
        cur.execute("SELECT 1 FROM deposits WHERE transaction_id=%s LIMIT 1;",(tx,))
        if cur.fetchone(): conn.rollback(); return {"success":False,"message":"This transaction ID has already been submitted."}
        cur.execute("""INSERT INTO deposits(telegram_id,method,account_number,amount,transaction_id,status) VALUES(%s,%s,%s,%s,%s,'pending') RETURNING *;""",(telegram_id,methods[method_key],account,amount,tx))
        row=cur.fetchone(); conn.commit(); return {"success":True,"message":"Deposit submitted. Wait for admin approval.","deposit":row}
    except Exception: conn.rollback(); raise
    finally: cur.close(); conn.close()

def get_user_deposits(telegram_id):
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM deposits WHERE telegram_id=%s ORDER BY id DESC;",(telegram_id,)); return cur.fetchall()
    finally: cur.close(); conn.close()

def get_all_deposits():
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM deposits ORDER BY id DESC;"); return cur.fetchall()
    finally: cur.close(); conn.close()

def update_deposit_status(deposit_id,status):
    if status not in ('approved','rejected'): return {"success":False,"message":"Invalid deposit status."}
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM deposits WHERE id=%s FOR UPDATE;",(deposit_id,)); dep=cur.fetchone()
        if not dep: conn.rollback(); return {"success":False,"message":"Deposit not found."}
        if dep['status'] != 'pending': conn.rollback(); return {"success":False,"message":"Deposit already processed."}
        if status=='approved':
            cur.execute("UPDATE users SET deposit_balance=COALESCE(deposit_balance,0)+%s WHERE telegram_id=%s RETURNING *;",(dep['amount'],dep['telegram_id']))
            if not cur.fetchone(): raise RuntimeError('User not found for deposit approval.')
            # Lifetime 5% referral commission, credited from the approved deposit.
            referrer_id = None
            cur.execute("SELECT referred_by FROM users WHERE telegram_id=%s FOR UPDATE;", (dep['telegram_id'],))
            refrow = cur.fetchone()
            referrer_id = refrow['referred_by'] if refrow else None
            if referrer_id:
                cur.execute("CREATE TABLE IF NOT EXISTS referral_deposit_commissions (id SERIAL PRIMARY KEY, deposit_id INTEGER UNIQUE NOT NULL, referrer_id BIGINT NOT NULL, referred_id BIGINT NOT NULL, deposit_amount NUMERIC(20,2) NOT NULL, commission_rate NUMERIC(8,4) NOT NULL DEFAULT 5, commission_amount NUMERIC(20,2) NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
                cur.execute("SELECT 1 FROM referral_deposit_commissions WHERE deposit_id=%s;", (deposit_id,))
                if not cur.fetchone():
                    commission=round(float(dep['amount'] or 0)*0.05,2)
                    if commission>0:
                        cur.execute("UPDATE users SET deposit_balance=COALESCE(deposit_balance,0)+%s WHERE telegram_id=%s;", (commission,referrer_id))
                        cur.execute("INSERT INTO referral_deposit_commissions(deposit_id,referrer_id,referred_id,deposit_amount,commission_rate,commission_amount) VALUES(%s,%s,%s,%s,5,%s);", (deposit_id,referrer_id,dep['telegram_id'],dep['amount'],commission))
        cur.execute("UPDATE deposits SET status=%s,processed_at=CURRENT_TIMESTAMP WHERE id=%s RETURNING *;",(status,deposit_id)); row=cur.fetchone(); conn.commit(); return {"success":True,"deposit":row}
    except Exception: conn.rollback(); raise
    finally: cur.close(); conn.close()

def start_task(telegram_id,task_id):
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM tasks WHERE id=%s AND is_active=TRUE FOR UPDATE;",(task_id,)); task=cur.fetchone()
        if not task: conn.rollback(); return {"success":False,"message":"Task not found or inactive."}
        if not task_allowed_for_user(cur, telegram_id, task):
            target = task.get('target_vip_level')
            if target == 0:
                msg = "This task is available to Non-VIP users only."
            else:
                msg = f"This task is reserved for VIP Level {int(target)}."
            conn.rollback(); return {"success":False,"message":msg}
        cur.execute("SELECT available_at FROM task_cooldowns WHERE telegram_id=%s AND task_id=%s;",(telegram_id,task_id)); cd=cur.fetchone()
        if cd and cd['available_at'] > __import__('datetime').datetime.now(__import__('datetime').timezone.utc).replace(tzinfo=None):
            conn.rollback(); return {"success":False,"message":"Please wait 10 seconds before starting again.","available_at":cd['available_at'].isoformat()}
        cur.execute("INSERT INTO task_starts(telegram_id,task_id,started_at) VALUES(%s,%s,CURRENT_TIMESTAMP) ON CONFLICT(telegram_id,task_id) DO UPDATE SET started_at=CURRENT_TIMESTAMP RETURNING *;",(telegram_id,task_id)); row=cur.fetchone(); conn.commit(); return {"success":True,"start":row}
    except Exception: conn.rollback(); raise
    finally: cur.close(); conn.close()


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
                    task_balance = CASE WHEN %s = 'task' THEN COALESCE(task_balance,0) + %s ELSE task_balance END,
                    balance = CASE WHEN %s = 'task' THEN COALESCE(task_balance,0) + %s ELSE balance END,
                    deposit_balance = CASE WHEN %s = 'deposit' THEN COALESCE(deposit_balance,0) + %s ELSE deposit_balance END,
                    total_withdrawn = GREATEST(0, total_withdrawn - %s)
                WHERE telegram_id = %s;
            """, (
                withdrawal["source"], withdrawal["amount"],
                withdrawal["source"], withdrawal["amount"],
                withdrawal["source"], withdrawal["amount"],
                withdrawal["amount"], withdrawal["telegram_id"]
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

def create_referral(referrer_id, referred_id, reward=500):
    """Create a pending referral. Bonus is paid only after admin approval."""
    try:
        referrer_id = int(referrer_id)
        referred_id = int(referred_id)
        reward = round(float(reward), 2)
    except (TypeError, ValueError):
        return {"success": False, "message": "Invalid referral IDs or reward."}

    if referrer_id == referred_id:
        return {"success": False, "message": "Self referral is not allowed."}
    if reward <= 0:
        return {"success": False, "message": "Referral reward must be greater than 0."}

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT telegram_id FROM users WHERE telegram_id=%s FOR UPDATE;", (referrer_id,))
        if not cur.fetchone():
            conn.rollback()
            return {"success": False, "message": "Referrer not found."}

        cur.execute("SELECT telegram_id FROM users WHERE telegram_id=%s FOR UPDATE;", (referred_id,))
        if not cur.fetchone():
            conn.rollback()
            return {"success": False, "message": "Referred user not found."}

        cur.execute("SELECT * FROM referrals WHERE referred_id=%s LIMIT 1 FOR UPDATE;", (referred_id,))
        existing = cur.fetchone()
        if existing:
            conn.rollback()
            return {"success": False, "message": "This user has already been referred.", "referral": existing}

        cur.execute(
            "UPDATE users SET referred_by=%s WHERE telegram_id=%s AND referred_by IS NULL;",
            (referrer_id, referred_id)
        )
        cur.execute(
            """INSERT INTO referrals(referrer_id,referred_id,reward,status)
               VALUES(%s,%s,%s,'pending') RETURNING *;""",
            (referrer_id, referred_id, reward)
        )
        referral = cur.fetchone()
        conn.commit()
        return {"success": True, "message": "Referral created and is pending admin approval.", "referral": referral, "reward": reward}
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def admin_give_referral_bonus(referrer_id,referred_id,amount,admin_id=None):
    try: referrer_id=int(referrer_id); referred_id=int(referred_id); amount=float(amount)
    except (TypeError,ValueError): return {'success':False,'message':'Invalid referral IDs or bonus amount.'}
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute('SELECT id FROM referrals WHERE referrer_id=%s AND referred_id=%s FOR UPDATE;',(referrer_id,referred_id)); row=cur.fetchone()
    finally: cur.close(); conn.close()
    if not row: return {'success':False,'message':'Referral relationship not found.'}
    return process_referral_request(row['id'],'approved',amount,admin_id)


def get_lucky_spin_config():
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM lucky_spin_prizes WHERE is_active=TRUE ORDER BY wheel_group,id;")
        rows=cur.fetchall()
        return rows
    finally:
        cur.close(); conn.close()


def lucky_spin(telegram_id):
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""SELECT * FROM premium_memberships pm JOIN premium_plans pp ON pp.id=pm.plan_id
                       WHERE pm.telegram_id=%s AND pm.status='active' AND pm.expires_at>CURRENT_TIMESTAMP
                       ORDER BY pm.expires_at DESC LIMIT 1 FOR UPDATE;""", (telegram_id,))
        membership=cur.fetchone()
        if not membership:
            conn.rollback(); return {'success':False,'message':'VIP Membership required. Please upgrade your VIP.'}
        level=int(membership['level'])
        wheel='vip_1_5' if level<=5 else 'vip_6_10'
        daily_limit=1 if level<=5 else 3
        cur.execute("SELECT COUNT(*) AS c FROM lucky_spin_records WHERE telegram_id=%s AND wheel_group=%s AND created_at::date=CURRENT_DATE;", (telegram_id,wheel))
        used=int(cur.fetchone()['c'] or 0)
        if used>=daily_limit:
            conn.rollback(); return {'success':False,'message':f'Daily Lucky Spin limit reached ({daily_limit}).','used':used,'limit':daily_limit}
        cur.execute("SELECT * FROM lucky_spin_prizes WHERE wheel_group=%s AND is_active=TRUE AND chance>0 ORDER BY id;", (wheel,))
        prizes=cur.fetchall()
        if not prizes:
            conn.rollback(); return {'success':False,'message':'Lucky Spin is not configured yet.'}
        total=sum(float(x['chance']) for x in prizes)
        if total<=0:
            conn.rollback(); return {'success':False,'message':'Lucky Spin chances are invalid.'}
        pick=random.uniform(0,total); acc=0; prize=None
        for x in prizes:
            acc+=float(x['chance'])
            if pick<=acc: prize=x; break
        prize=prize or prizes[-1]
        amount=float(prize['reward_amount'] or 0)
        if amount<=0:
            conn.rollback(); return {'success':False,'message':'Invalid Lucky Spin reward.'}
        if prize['reward_type']=='taskcoin':
            cur.execute("UPDATE users SET task_balance=COALESCE(task_balance,0)+%s,balance=COALESCE(balance,0)+%s,total_earned=COALESCE(total_earned,0)+%s,last_active=CURRENT_TIMESTAMP WHERE telegram_id=%s RETURNING *;",(amount,amount,amount,telegram_id))
        else:
            cur.execute("UPDATE users SET deposit_balance=COALESCE(deposit_balance,0)+%s,last_active=CURRENT_TIMESTAMP WHERE telegram_id=%s RETURNING *;",(amount,telegram_id))
        user=cur.fetchone()
        if not user: raise RuntimeError('User not found while crediting Lucky Spin.')
        cur.execute("INSERT INTO lucky_spin_records(telegram_id,vip_level,wheel_group,prize_id,reward_type,reward_amount) VALUES(%s,%s,%s,%s,%s,%s) RETURNING *;",(telegram_id,level,wheel,prize['id'],prize['reward_type'],amount))
        record=cur.fetchone(); conn.commit()
        return {'success':True,'message':f"You won {prize['prize_name']}!",'prize':dict(prize),'record':record,'user':user,'used':used+1,'limit':daily_limit,'wheel_group':wheel}
    except Exception:
        conn.rollback(); raise
    finally:
        cur.close(); conn.close()


def update_lucky_spin_prize(prize_id, data):
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        fields=[]; vals=[]
        if 'prize_name' in data: fields.append('prize_name=%s'); vals.append(str(data['prize_name']).strip())
        if 'reward_type' in data and data['reward_type'] in ('bdt','taskcoin'): fields.append('reward_type=%s'); vals.append(data['reward_type'])
        if 'reward_amount' in data:
            amount=float(data['reward_amount']);
            if amount<0: raise ValueError('Reward amount cannot be negative.')
            fields.append('reward_amount=%s'); vals.append(amount)
        if 'chance' in data:
            chance=float(data['chance']);
            if chance<0: raise ValueError('Chance cannot be negative.')
            fields.append('chance=%s'); vals.append(chance)
        if 'is_active' in data: fields.append('is_active=%s'); vals.append(bool(data['is_active']))
        if not fields: return {'success':False,'message':'No fields supplied.'}
        vals.append(int(prize_id)); cur.execute(f"UPDATE lucky_spin_prizes SET {', '.join(fields)},updated_at=CURRENT_TIMESTAMP WHERE id=%s RETURNING *;",tuple(vals)); row=cur.fetchone()
        if not row: conn.rollback(); return {'success':False,'message':'Prize not found.'}
        conn.commit(); return {'success':True,'prize':row}
    except Exception:
        conn.rollback(); raise
    finally: cur.close(); conn.close()


def credit_referral_deposit_commission(deposit_id):
    """Credit 5% lifetime commission exactly once when a referred user's deposit is approved."""
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT d.*,u.referred_by FROM deposits d JOIN users u ON u.telegram_id=d.telegram_id WHERE d.id=%s FOR UPDATE;",(deposit_id,))
        dep=cur.fetchone()
        if not dep or not dep.get('referred_by'): return {'success':True,'commission':0}
        cur.execute("""CREATE TABLE IF NOT EXISTS referral_deposit_commissions(
            id SERIAL PRIMARY KEY, deposit_id INTEGER UNIQUE NOT NULL, referrer_id BIGINT NOT NULL,
            referred_id BIGINT NOT NULL, deposit_amount NUMERIC(20,2) NOT NULL,
            commission_rate NUMERIC(8,4) NOT NULL DEFAULT 5, commission_amount NUMERIC(20,2) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);""")
        cur.execute("SELECT 1 FROM referral_deposit_commissions WHERE deposit_id=%s;",(deposit_id,))
        if cur.fetchone(): conn.rollback(); return {'success':True,'commission':0,'duplicate':True}
        commission=round(float(dep['amount'] or 0)*0.05,2)
        if commission<=0: conn.rollback(); return {'success':True,'commission':0}
        cur.execute("UPDATE users SET deposit_balance=COALESCE(deposit_balance,0)+%s,last_active=CURRENT_TIMESTAMP WHERE telegram_id=%s RETURNING *;",(commission,dep['referred_by']))
        referrer=cur.fetchone()
        if not referrer: conn.rollback(); return {'success':False,'message':'Referrer not found.'}
        cur.execute("INSERT INTO referral_deposit_commissions(deposit_id,referrer_id,referred_id,deposit_amount,commission_rate,commission_amount) VALUES(%s,%s,%s,%s,5,%s);",(deposit_id,dep['referred_by'],dep['telegram_id'],dep['amount'],commission))
        conn.commit(); return {'success':True,'commission':commission,'referrer':referrer}
    except Exception:
        conn.rollback(); raise
    finally: cur.close(); conn.close()


def get_user_referrals(telegram_id):
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT r.id,r.referrer_id,r.referred_id,r.reward,COALESCE(NULLIF(TRIM(r.status),''),'pending') AS status,
                   r.created_at,r.approved_at,u.username,u.first_name,
                   COALESCE(a.amount,0) AS bonus_earned,
                   COALESCE(c.lifetime_commission,0) AS lifetime_commission
            FROM referrals r
            LEFT JOIN users u ON u.telegram_id=r.referred_id
            LEFT JOIN admin_referral_bonus_awards a ON a.referral_id=r.id
            LEFT JOIN (
                SELECT referrer_id,referred_id,SUM(commission_amount) AS lifetime_commission
                FROM referral_deposit_commissions GROUP BY referrer_id,referred_id
            ) c ON c.referrer_id=r.referrer_id AND c.referred_id=r.referred_id
            WHERE r.referrer_id=%s ORDER BY r.id DESC;
        """,(telegram_id,))
        return cur.fetchall()
    finally: cur.close(); conn.close()


def get_referral_requests(status='pending'):
    conn=get_connection(); cur=conn.cursor(cursor_factory=RealDictCursor)
    try:
        params=[]; where=''
        if status and status!='all': where="WHERE COALESCE(NULLIF(TRIM(r.status),''),'pending')=%s"; params.append(status)
        cur.execute(f"""
            SELECT r.*,ru.username AS referrer_username,ru.first_name AS referrer_first_name,
                   uu.username AS referred_username,uu.first_name AS referred_first_name,
                   COALESCE(a.amount,0) AS bonus_earned,COALESCE(c.lifetime_commission,0) AS lifetime_commission
            FROM referrals r
            LEFT JOIN users ru ON ru.telegram_id=r.referrer_id
            LEFT JOIN users uu ON uu.telegram_id=r.referred_id
            LEFT JOIN admin_referral_bonus_awards a ON a.referral_id=r.id
            LEFT JOIN (SELECT referrer_id,referred_id,SUM(commission_amount) AS lifetime_commission FROM referral_deposit_commissions GROUP BY referrer_id,referred_id) c
              ON c.referrer_id=r.referrer_id AND c.referred_id=r.referred_id
            {where} ORDER BY r.id DESC;
        """,tuple(params))
        return cur.fetchall()
    finally: cur.close(); conn.close()


def process_referral_request(referral_id, status, amount=500, admin_id=None):
    """Approve/reject a pending referral; approval credits the referrer exactly once."""
    status = str(status or '').strip().lower()
    if status not in ('approved', 'rejected'):
        return {'success': False, 'message': 'Status must be approved or rejected.'}
    try:
        referral_id = int(referral_id)
        amount = round(float(amount), 2)
    except (TypeError, ValueError):
        return {'success': False, 'message': 'Invalid referral request or bonus amount.'}
    if status == 'approved' and amount <= 0:
        return {'success': False, 'message': 'Bonus amount must be greater than 0.'}

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute('SELECT * FROM referrals WHERE id=%s FOR UPDATE;', (referral_id,))
        r = cur.fetchone()
        if not r:
            conn.rollback()
            return {'success': False, 'message': 'Referral request not found.'}

        current = str(r.get('status') or 'pending').lower()
        if current != 'pending':
            conn.rollback()
            return {'success': False, 'message': f'Referral request is already {current}.', 'duplicate': True}

        if status == 'rejected':
            cur.execute(
                "UPDATE referrals SET status='rejected', approved_at=CURRENT_TIMESTAMP, approved_by=%s WHERE id=%s RETURNING *;",
                (admin_id, referral_id)
            )
            row = cur.fetchone()
            conn.commit()
            return {'success': True, 'message': 'Referral request rejected.', 'referral': row}

        # Lock both accounts before changing balances.
        cur.execute('SELECT * FROM users WHERE telegram_id=%s FOR UPDATE;', (r['referrer_id'],))
        referrer = cur.fetchone()
        if not referrer:
            conn.rollback()
            return {'success': False, 'message': 'Referrer user not found.'}

        cur.execute('SELECT * FROM users WHERE telegram_id=%s FOR UPDATE;', (r['referred_id'],))
        referred = cur.fetchone()
        if not referred:
            conn.rollback()
            return {'success': False, 'message': 'Referred user not found.'}

        # The referral relationship is stored on the referred account.
        if referred.get('referred_by') not in (None, r['referrer_id']):
            conn.rollback()
            return {'success': False, 'message': 'Referral owner does not match this account.'}

        # Insert the one-time award record first. The UNIQUE referral_id constraint
        # makes duplicate admin clicks unable to create a second bonus.
        cur.execute(
            """INSERT INTO admin_referral_bonus_awards
               (referral_id,referrer_id,referred_id,amount)
               VALUES(%s,%s,%s,%s)
               ON CONFLICT (referral_id) DO NOTHING
               RETURNING *;""",
            (referral_id, r['referrer_id'], r['referred_id'], amount)
        )
        award = cur.fetchone()
        if not award:
            conn.rollback()
            return {'success': False, 'message': 'Referral bonus has already been awarded.', 'duplicate': True}

        cur.execute(
            """UPDATE users
               SET referral_count=COALESCE(referral_count,0)+1,
                   task_balance=COALESCE(task_balance,0)+%s,
                   balance=COALESCE(balance,0)+%s,
                   total_earned=COALESCE(total_earned,0)+%s,
                   last_active=CURRENT_TIMESTAMP
               WHERE telegram_id=%s RETURNING *;""",
            (amount, amount, amount, r['referrer_id'])
        )
        referrer = cur.fetchone()

        cur.execute(
            """UPDATE referrals
               SET status='approved', approved_at=CURRENT_TIMESTAMP, approved_by=%s, reward=%s
               WHERE id=%s RETURNING *;""",
            (admin_id, amount, referral_id)
        )
        approved = cur.fetchone()

        cur.execute(
            "UPDATE users SET referred_by=%s WHERE telegram_id=%s AND referred_by IS NULL RETURNING *;",
            (r['referrer_id'], r['referred_id'])
        )
        referred = cur.fetchone() or referred

        conn.commit()
        return {
            'success': True,
            'message': f'Referral approved and {amount:,.2f} TaskCoins credited to the referrer.',
            'referral': approved,
            'award': award,
            'referrer': referrer,
            'referred': referred
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def transfer_taskcoins(sender_id, receiver_id, amount):
    """Atomically transfer TaskCoins between two existing users."""
    try:
        sender_id = int(sender_id)
        receiver_id = int(receiver_id)
        amount = round(float(amount), 2)
    except (TypeError, ValueError):
        return {'success': False, 'message': 'Invalid sender, receiver or amount.'}

    if sender_id == receiver_id:
        return {'success': False, 'message': 'You cannot send TaskCoins to yourself.'}
    if amount <= 0:
        return {'success': False, 'message': 'Transfer amount must be greater than 0.'}

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Always lock accounts in numeric order to reduce deadlock risk.
        first_id, second_id = sorted((sender_id, receiver_id))
        cur.execute('SELECT * FROM users WHERE telegram_id=%s FOR UPDATE;', (first_id,))
        first = cur.fetchone()
        cur.execute('SELECT * FROM users WHERE telegram_id=%s FOR UPDATE;', (second_id,))
        second = cur.fetchone()

        if not first or not second:
            conn.rollback()
            return {'success': False, 'message': 'Sender or receiver account was not found.'}

        sender = first if int(first['telegram_id']) == sender_id else second
        receiver = second if int(second['telegram_id']) == receiver_id else first
        sender_balance = float(sender.get('task_balance') or 0)
        if sender_balance < amount:
            conn.rollback()
            return {'success': False, 'message': f'Insufficient TaskCoins. Available: {sender_balance:,.2f}'}

        cur.execute(
            """UPDATE users
               SET task_balance=COALESCE(task_balance,0)-%s,
                   balance=COALESCE(balance,0)-%s,
                   last_active=CURRENT_TIMESTAMP
               WHERE telegram_id=%s AND COALESCE(task_balance,0)>=%s
               RETURNING *;""",
            (amount, amount, sender_id, amount)
        )
        sender = cur.fetchone()
        if not sender:
            conn.rollback()
            return {'success': False, 'message': 'Transfer failed because the sender balance changed. Please try again.'}

        cur.execute(
            """UPDATE users
               SET task_balance=COALESCE(task_balance,0)+%s,
                   balance=COALESCE(balance,0)+%s,
                   last_active=CURRENT_TIMESTAMP
               WHERE telegram_id=%s RETURNING *;""",
            (amount, amount, receiver_id)
        )
        receiver = cur.fetchone()
        if not receiver:
            conn.rollback()
            return {'success': False, 'message': 'Receiver account was not found.'}

        cur.execute(
            """INSERT INTO taskcoin_transfers(sender_id,receiver_id,amount)
               VALUES(%s,%s,%s) RETURNING *;""",
            (sender_id, receiver_id, amount)
        )
        transfer = cur.fetchone()
        conn.commit()
        return {
            'success': True,
            'message': f'{amount:,.2f} TaskCoins sent successfully.',
            'transfer': transfer,
            'sender': sender,
            'receiver': receiver
        }
    except Exception:
        conn.rollback()
        raise
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
def process_adgem_conversion(data):
    """
    Process one AdGem v3 reward postback.

    AdGem player_id:
        tg_<telegram_id>

    Reward:
        data["amount"]

    Revenue:
        data["payout"]
    """

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        request_id = str(
            data.get("request_id") or ""
        ).strip()

        conversion_id = str(
            data.get("conversion_id") or ""
        ).strip()

        player_id = str(
            data.get("player_id") or ""
        ).strip()

        if not request_id:
            return {
                "success": False,
                "message": "Missing request_id"
            }

        if not player_id:
            return {
                "success": False,
                "message": "Missing player_id"
            }

        # --------------------------------------------------
        # GET TELEGRAM ID FROM PLAYER ID
        # --------------------------------------------------

        if not player_id.startswith("tg_"):
            return {
                "success": False,
                "message": "Invalid player_id"
            }

        try:
            telegram_id = int(
                player_id[3:]
            )
        except ValueError:
            return {
                "success": False,
                "message": "Invalid Telegram ID"
            }

        # --------------------------------------------------
        # ONLY REWARD POSTBACKS
        # --------------------------------------------------

        conversion_type = str(
            data.get("conversion_type") or ""
        ).lower()

        if conversion_type != "reward":
            return {
                "success": True,
                "credited": False,
                "message": "Non-reward conversion ignored"
            }

        # --------------------------------------------------
        # REWARD AMOUNT
        # --------------------------------------------------

        try:
            reward = float(
                data.get("amount") or 0
            )
        except (TypeError, ValueError):
            reward = 0

        if reward <= 0:
            return {
                "success": False,
                "message": "Invalid reward amount"
            }

        # --------------------------------------------------
        # LOCK USER
        # --------------------------------------------------

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
                "message": "User not found"
            }

        # --------------------------------------------------
        # DUPLICATE REQUEST CHECK
        # --------------------------------------------------

        cur.execute("""
            SELECT id
            FROM adgem_conversions
            WHERE request_id = %s
            LIMIT 1;
        """, (
            request_id,
        ))

        if cur.fetchone():

            conn.rollback()

            return {
                "success": True,
                "credited": False,
                "duplicate": True,
                "message": "Conversion already processed"
            }

        # --------------------------------------------------
        # DUPLICATE CONVERSION CHECK
        # --------------------------------------------------

        if conversion_id:

            cur.execute("""
                SELECT id
                FROM adgem_conversions
                WHERE conversion_id = %s
                LIMIT 1;
            """, (
                conversion_id,
            ))

            if cur.fetchone():

                conn.rollback()

                return {
                    "success": True,
                    "credited": False,
                    "duplicate": True,
                    "message": "Conversion already processed"
                }

        # --------------------------------------------------
        # INSERT CONVERSION
        # --------------------------------------------------

        cur.execute("""
            INSERT INTO adgem_conversions (
                request_id,
                conversion_id,
                player_id,
                telegram_id,
                app_id,
                campaign_id,
                offer_id,
                goal_id,
                offer_name,
                goal_name,
                amount,
                payout,
                conversion_type,
                country,
                status
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                'credited'
            )
            RETURNING *;
        """, (
            request_id,
            conversion_id or None,
            player_id,
            telegram_id,

            str(data.get("app_id") or ""),
            str(data.get("campaign_id") or ""),
            str(data.get("offer_id") or ""),
            str(data.get("goal_id") or ""),

            str(data.get("offer_name") or ""),
            str(data.get("goal_name") or ""),

            reward,

            float(
                data.get("payout") or 0
            ),

            conversion_type,

            str(
                data.get("country") or ""
            )
        ))

        conversion = cur.fetchone()

        # --------------------------------------------------
        # CREDIT USER
        # --------------------------------------------------

        cur.execute("""
            UPDATE users
            SET
                task_balance = COALESCE(task_balance, 0) + %s,
                balance = COALESCE(task_balance, 0) + %s,

                total_earned =
                    COALESCE(total_earned, 0) + %s,

                last_active =
                    CURRENT_TIMESTAMP

            WHERE telegram_id = %s

            RETURNING *;
        """, (
            reward,
            reward,
            reward,
            telegram_id
        ))

        updated_user = cur.fetchone()

        if not updated_user:
            raise RuntimeError(
                "User disappeared while processing AdGem reward."
            )

        # --------------------------------------------------
        # COMMIT EVERYTHING TOGETHER
        # --------------------------------------------------

        conn.commit()

        return {
            "success": True,
            "credited": True,
            "reward": reward,
            "conversion": conversion,
            "user": updated_user
        }

    except Exception:

        conn.rollback()

        raise

    finally:

        cur.close()
        conn.close()
# ============================================================
# MONETAG REWARD
# ============================================================

def add_monetag_reward(telegram_id, reward):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        reward = float(reward)

        if reward <= 0:
            return {
                "success": False,
                "message": "Invalid reward."
            }

        cur.execute(
            "SELECT * FROM users WHERE telegram_id = %s FOR UPDATE;",
            (telegram_id,)
        )

        user = cur.fetchone()

        if not user:
            conn.rollback()
            return {
                "success": False,
                "message": "User not found."
            }

        sql = (
            "UPDATE users "
            "SET task_balance = COALESCE(task_balance, 0) + %s, "
            "balance = COALESCE(task_balance, 0) + %s, "
            "total_earned = COALESCE(total_earned, 0) + %s, "
            "last_active = CURRENT_TIMESTAMP "
            "WHERE telegram_id = %s "
            "RETURNING *;"
        )

        cur.execute(sql, (reward, reward, reward, telegram_id))

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

def process_monetag_postback(
    ymid, telegram_id, zone_id=None, sub_zone_id=None,
    event_type=None, reward_event_type=None, estimated_price=0,
    request_var=None, reward=50
):
    """Process a Monetag TMA postback atomically and idempotently."""
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        ymid = str(ymid or "").strip()
        if not ymid:
            return {"success": False, "credited": False, "message": "ymid is required."}

        try:
            telegram_id = int(telegram_id)
            reward = float(reward)
            estimated_price = float(estimated_price or 0)
        except (ValueError, TypeError):
            return {"success": False, "credited": False, "message": "Invalid Monetag postback values."}

        event_type = str(event_type or "").strip().lower()
        reward_event_type = str(reward_event_type or "").strip().lower()

        # Monetag dashboard variants may expose paid/unpaid as yes/no.
        if reward_event_type == "yes":
            reward_event_type = "valued"
        elif reward_event_type == "no":
            reward_event_type = "non_valued"

        if event_type not in ("impression", "click"):
            return {"success": False, "credited": False, "message": "Invalid event_type."}
        if reward_event_type not in ("valued", "non_valued"):
            return {"success": False, "credited": False, "message": "Invalid reward_event_type."}
        if reward <= 0:
            return {"success": False, "credited": False, "message": "Invalid reward amount."}

        # Only Monetag-confirmed paid impressions create the 50-coin reward.
        if event_type != "impression" or reward_event_type != "valued":
            conn.rollback()
            return {
                "success": True,
                "credited": False,
                "message": "Postback received but is not a rewardable event."
            }

        cur.execute("SELECT * FROM users WHERE telegram_id = %s FOR UPDATE;", (telegram_id,))
        user = cur.fetchone()
        if not user:
            conn.rollback()
            return {"success": False, "credited": False, "message": "User not found."}

        # Monetag may retry the same postback. ymid is the unique event ID.
        cur.execute("SELECT * FROM monetag_postbacks WHERE ymid = %s;", (ymid,))
        existing = cur.fetchone()
        if existing:
            conn.rollback()
            return {
                "success": True,
                "credited": False,
                "duplicate": True,
                "message": "Postback already processed.",
                "postback": existing
            }

        cur.execute("""
            INSERT INTO monetag_postbacks (
                ymid, telegram_id, zone_id, sub_zone_id, event_type,
                reward_event_type, estimated_price, request_var,
                credited_reward, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'credited')
            RETURNING *;
        """, (
            ymid, telegram_id,
            int(zone_id) if zone_id not in (None, "") else None,
            int(sub_zone_id) if sub_zone_id not in (None, "") else None,
            event_type, reward_event_type, estimated_price,
            str(request_var or ""), reward
        ))
        postback = cur.fetchone()

        cur.execute("""
            UPDATE users
            SET task_balance = COALESCE(task_balance, 0) + %s,
                balance = COALESCE(task_balance, 0) + %s,
                total_earned = COALESCE(total_earned, 0) + %s,
                last_active = CURRENT_TIMESTAMP
            WHERE telegram_id = %s
            RETURNING *;
        """, (reward, reward, reward, telegram_id))
        updated_user = cur.fetchone()

        # Referral reward: credit the referred user's referrer once for this
        # Monetag event. The ymid uniqueness above prevents repeat payouts.
        referral_bonus = 0
        cur.execute("SELECT referred_by FROM users WHERE telegram_id=%s FOR UPDATE;", (telegram_id,))
        refrow = cur.fetchone()
        referrer_id = refrow["referred_by"] if refrow else None
        if referrer_id:
            referral_bonus = reward
            cur.execute("""
                UPDATE users
                SET task_balance=COALESCE(task_balance,0)+%s,
                    balance=COALESCE(balance,0)+%s,
                    total_earned=COALESCE(total_earned,0)+%s,
                    last_active=CURRENT_TIMESTAMP
                WHERE telegram_id=%s
                RETURNING *;
            """, (referral_bonus, referral_bonus, referral_bonus, referrer_id))

        conn.commit()
        return {
            "success": True,
            "credited": True,
            "duplicate": False,
            "reward": reward,
            "referral_bonus": referral_bonus,
            "postback": postback,
            "user": updated_user
        }

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


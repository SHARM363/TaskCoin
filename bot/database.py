import os
import psycopg2
from psycopg2.extras import RealDictCursor


DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL environment variable is missing."
        )

    return psycopg2.connect(DATABASE_URL)


def init_db():

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,

            telegram_id BIGINT UNIQUE NOT NULL,

            username TEXT,
            first_name TEXT,

            balance NUMERIC(20, 2) DEFAULT 0,

            total_earned NUMERIC(20, 2) DEFAULT 0,
            total_withdrawn NUMERIC(20, 2) DEFAULT 0,

            referral_code TEXT UNIQUE,
            referred_by BIGINT,

            referral_count INTEGER DEFAULT 0,
            completed_tasks INTEGER DEFAULT 0,

            status TEXT DEFAULT 'active',

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()

    cur.close()
    conn.close()


def create_or_update_user(
    telegram_id,
    username=None,
    first_name=None
):

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    cur.execute("""
        INSERT INTO users (
            telegram_id,
            username,
            first_name,
            last_active
        )
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP)

        ON CONFLICT (telegram_id)

        DO UPDATE SET
            username = EXCLUDED.username,
            first_name = EXCLUDED.first_name,
            last_active = CURRENT_TIMESTAMP

        RETURNING *;
    """, (
        telegram_id,
        username,
        first_name
    ))

    user = cur.fetchone()

    conn.commit()

    cur.close()
    conn.close()

    return user


def get_user(telegram_id):

    conn = get_connection()

    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    cur.execute("""
        SELECT *
        FROM users
        WHERE telegram_id = %s;
    """, (telegram_id,))

    user = cur.fetchone()

    cur.close()
    conn.close()

    return user

"""
TaskCoin Character Backend API (standalone Blueprint)

Purpose:
- 10 original character slots (TC-001 ... TC-010).
- Backend-only endpoints; no frontend/UI changes.
- Admin controls name, description, ability, boost, rarity, base price,
  supply, active status, trading, and market-pressure settings.
- User can list characters, inspect one, buy, view owned characters, and sell.
- Current price is derived from base price and admin-controlled pressure factors.

Integration (one time, later):
    from character_api import character_bp
    app.register_blueprint(character_bp)

The existing database.py is NOT modified by this file. The character tables
are created automatically in the existing PostgreSQL database on first use.
"""

import hashlib
import os
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps

from flask import Blueprint, jsonify, request

from database import get_connection, get_admin_by_token


character_bp = Blueprint("character_api", __name__, url_prefix="/api/characters")

CHARACTER_COUNT = 10
MIN_PRICE = Decimal("0.00")
MAX_PRICE = Decimal("100000000.00")

DEFAULT_CHARACTERS = [
    (1, "Coin Guardian", "The first TaskCoin guardian.", "Task Reward Boost", "Rare", 500, 5, 10000),
    (2, "Spark Runner", "A fast reward-focused character.", "Task Speed Boost", "Rare", 750, 7, 10000),
    (3, "Vault Keeper", "A premium balance guardian.", "Reward Protection", "Epic", 1200, 10, 5000),
    (4, "Coin Ranger", "Built for active task users.", "Task Bonus", "Epic", 1800, 12, 5000),
    (5, "Golden Pilot", "A high-tier TaskCoin pilot.", "Reward Multiplier", "Epic", 2500, 15, 3000),
    (6, "Diamond Sentinel", "A powerful premium sentinel.", "Premium Boost", "Legendary", 4000, 20, 2000),
    (7, "Nova Miner", "Designed for high activity users.", "Mining Boost", "Legendary", 6000, 25, 1500),
    (8, "Royal Guardian", "An elite TaskCoin guardian.", "Elite Task Boost", "Legendary", 9000, 30, 1000),
    (9, "Cosmic Trader", "A rare market-themed character.", "Trading Boost", "Mythic", 15000, 35, 500),
    (10, "TaskCoin Master", "The top original TaskCoin character.", "Master Boost", "Mythic", 25000, 50, 250),
]


def _money(value):
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def _json_character(row):
    d = dict(row)
    for key in ("base_price", "current_price", "market_multiplier", "seller_pressure", "external_pressure", "upgrade_cost_l2", "upgrade_cost_l3", "upgrade_cost_l4", "upgrade_cost_l5"):
        if key in d and d[key] is not None:
            d[key] = float(d[key])
    return d


def _token_from_request():
    auth = request.headers.get("Authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("X-Admin-Token", "").strip()


def _require_admin():
    token = _token_from_request()
    admin = get_admin_by_token(token) if token else None
    return admin


def require_admin(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        admin = _require_admin()
        if not admin:
            return jsonify({"success": False, "message": "Admin authentication required."}), 401
        return fn(admin, *args, **kwargs)
    return wrapped


def ensure_character_schema():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                ability_name TEXT NOT NULL DEFAULT '',
                ability_description TEXT NOT NULL DEFAULT '',
                benefits TEXT NOT NULL DEFAULT '',
                image_url TEXT NOT NULL DEFAULT '',
                rarity TEXT NOT NULL DEFAULT 'Common',
                base_price NUMERIC(20,2) NOT NULL DEFAULT 0,
                boost_percent NUMERIC(10,2) NOT NULL DEFAULT 5,
                upgrade_cost_l2 NUMERIC(20,2) NOT NULL DEFAULT 1000,
                upgrade_cost_l3 NUMERIC(20,2) NOT NULL DEFAULT 2500,
                upgrade_cost_l4 NUMERIC(20,2) NOT NULL DEFAULT 5000,
                upgrade_cost_l5 NUMERIC(20,2) NOT NULL DEFAULT 10000,
                max_supply INTEGER NOT NULL DEFAULT 0,
                sold_count INTEGER NOT NULL DEFAULT 0,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                trading_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                seller_pressure NUMERIC(10,4) NOT NULL DEFAULT 0,
                external_pressure NUMERIC(10,4) NOT NULL DEFAULT 0,
                market_multiplier NUMERIC(12,6) NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS character_ownerships (
                id BIGSERIAL PRIMARY KEY,
                character_id INTEGER NOT NULL REFERENCES characters(id),
                telegram_id BIGINT NOT NULL,
                purchase_price NUMERIC(20,2) NOT NULL,
                acquired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sold_at TIMESTAMP,
                sale_price NUMERIC(20,2),
                status TEXT NOT NULL DEFAULT 'owned',
                UNIQUE(character_id, telegram_id, status)
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_character_ownership_user
            ON character_ownerships(telegram_id, status);
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS character_trade_history (
                id BIGSERIAL PRIMARY KEY,
                character_id INTEGER NOT NULL REFERENCES characters(id),
                seller_id BIGINT NOT NULL,
                buyer_id BIGINT,
                price NUMERIC(20,2) NOT NULL,
                trade_type TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS character_market_listings (
                id BIGSERIAL PRIMARY KEY,
                ownership_id BIGINT NOT NULL UNIQUE REFERENCES character_ownerships(id),
                character_id INTEGER NOT NULL REFERENCES characters(id),
                seller_id BIGINT NOT NULL,
                asking_price NUMERIC(20,2) NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sold_at TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_character_market_active
            ON character_market_listings(status, created_at DESC);
        """)
        # Safe additive migrations: do not drop or rewrite existing user data.
        for column, definition in [
            ("benefits", "TEXT NOT NULL DEFAULT ''"),
            ("image_url", "TEXT NOT NULL DEFAULT ''"),
            ("upgrade_cost_l2", "NUMERIC(20,2) NOT NULL DEFAULT 1000"),
            ("upgrade_cost_l3", "NUMERIC(20,2) NOT NULL DEFAULT 2500"),
            ("upgrade_cost_l4", "NUMERIC(20,2) NOT NULL DEFAULT 5000"),
            ("upgrade_cost_l5", "NUMERIC(20,2) NOT NULL DEFAULT 10000"),
        ]:
            cur.execute(f"ALTER TABLE characters ADD COLUMN IF NOT EXISTS {column} {definition}")
        cur.execute("ALTER TABLE character_ownerships ADD COLUMN IF NOT EXISTS level INTEGER NOT NULL DEFAULT 1")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS character_daily_rewards (
                id BIGSERIAL PRIMARY KEY,
                telegram_id BIGINT NOT NULL,
                ownership_id BIGINT NOT NULL REFERENCES character_ownerships(id),
                reward_day DATE NOT NULL DEFAULT CURRENT_DATE,
                reward_amount NUMERIC(20,2) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(telegram_id, reward_day)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS character_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL
            )
        """)
        cur.execute("""
            INSERT INTO character_settings(setting_key,setting_value)
            VALUES('weekly_daily_rewards','100,200,350,400,500,650,800')
            ON CONFLICT(setting_key) DO NOTHING
        """)

        for cid, name, description, ability, rarity, price, boost, supply in DEFAULT_CHARACTERS:
            cur.execute("""
                INSERT INTO characters
                    (id, code, name, description, ability_name, ability_description,
                     rarity, base_price, boost_percent, max_supply)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO NOTHING;
            """, (
                cid, f"TC-{cid:03d}", name, description, ability,
                f"Admin-controlled {ability.lower()}.", rarity,
                price, boost, supply,
            ))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def _recalculate_price(cur, character_id):
    cur.execute("""
        SELECT base_price, seller_pressure, external_pressure, market_multiplier
        FROM characters WHERE id=%s FOR UPDATE
    """, (character_id,))
    row = cur.fetchone()
    if not row:
        return None
    base, seller, external, multiplier = map(Decimal, [row[0], row[1], row[2], row[3]])
    # Pressure values are percentages. Seller pressure is allowed to be negative
    # (more selling pressure can reduce price); external pressure is admin-fed.
    factor = (Decimal("1") + seller / Decimal("100") + external / Decimal("100")) * multiplier
    if factor < Decimal("0.01"):
        factor = Decimal("0.01")
    current = (base * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    current = max(MIN_PRICE, min(MAX_PRICE, current))
    cur.execute("UPDATE characters SET updated_at=CURRENT_TIMESTAMP WHERE id=%s", (character_id,))
    return current


@character_bp.before_request
def _character_before_request():
    ensure_character_schema()


@character_bp.get("")
def list_characters():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM characters ORDER BY id")
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        result = []
        for row in rows:
            item = dict(zip(cols, row))
            item["current_price"] = float(_money(item["base_price"]) * Decimal(str(item.get("market_multiplier") or 1)) * (Decimal("1") + Decimal(str(item.get("seller_pressure") or 0))/100 + Decimal(str(item.get("external_pressure") or 0))/100))
            result.append(_json_character(item))
        return jsonify({"success": True, "characters": result})
    finally:
        cur.close(); conn.close()


@character_bp.get("/<int:character_id>")
def get_character(character_id):
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM characters WHERE id=%s", (character_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"success": False, "message": "Character not found."}), 404
        cols = [d[0] for d in cur.description]
        item = dict(zip(cols, row))
        item["current_price"] = float(_money(item["base_price"]) * Decimal(str(item.get("market_multiplier") or 1)) * (Decimal("1") + Decimal(str(item.get("seller_pressure") or 0))/100 + Decimal(str(item.get("external_pressure") or 0))/100))
        return jsonify({"success": True, "character": _json_character(item)})
    finally:
        cur.close(); conn.close()


@character_bp.get("/user/<int:telegram_id>")
def user_characters(telegram_id):
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("""
            SELECT o.*, c.code, c.name, c.rarity, c.boost_percent, c.ability_name
            FROM character_ownerships o
            JOIN characters c ON c.id=o.character_id
            WHERE o.telegram_id=%s AND o.status='owned'
            ORDER BY o.acquired_at DESC
        """, (telegram_id,))
        rows = cur.fetchall(); cols = [d[0] for d in cur.description]
        return jsonify({"success": True, "characters": [dict(zip(cols, r)) for r in rows]})
    finally:
        cur.close(); conn.close()


@character_bp.post("/buy")
def buy_character():
    data = request.get_json(silent=True) or {}
    try:
        telegram_id = int(data.get("telegram_id")); character_id = int(data.get("character_id"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "telegram_id and character_id are required."}), 400

    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT id, balance, deposit_balance FROM users WHERE telegram_id=%s FOR UPDATE", (telegram_id,))
        user = cur.fetchone()
        if not user:
            return jsonify({"success": False, "message": "User not found."}), 404
        cur.execute("SELECT * FROM characters WHERE id=%s FOR UPDATE", (character_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"success": False, "message": "Character not found."}), 404
        cols = [d[0] for d in cur.description]; c = dict(zip(cols, row))
        if not c["is_active"] or not c["trading_enabled"]:
            return jsonify({"success": False, "message": "Character is not available for purchase."}), 400
        if int(c["sold_count"]) >= int(c["max_supply"]):
            return jsonify({"success": False, "message": "Character supply is sold out."}), 400
        cur.execute("SELECT 1 FROM character_ownerships WHERE character_id=%s AND telegram_id=%s AND status='owned' LIMIT 1", (character_id, telegram_id))
        if cur.fetchone():
            return jsonify({"success": False, "message": "You already own this character."}), 400
        # Character Level 1 is purchased at the admin-set BDT price, from deposit_balance only.
        price = _money(c.get("base_price"))
        balance = Decimal(str(user[2] or 0))
        if balance < price:
            return jsonify({"success": False, "message": "Insufficient Deposit Balance.", "required": float(price), "available": float(balance)}), 400
        cur.execute("UPDATE users SET deposit_balance=deposit_balance-%s WHERE telegram_id=%s", (price, telegram_id))
        cur.execute("UPDATE characters SET sold_count=sold_count+1 WHERE id=%s", (character_id,))
        cur.execute("INSERT INTO character_ownerships(character_id,telegram_id,purchase_price) VALUES(%s,%s,%s)", (character_id, telegram_id, price))
        cur.execute("INSERT INTO character_trade_history(character_id,seller_id,buyer_id,price,trade_type) VALUES(%s,0,%s,%s,'primary_sale')", (character_id, telegram_id, price))
        conn.commit()
        return jsonify({"success": True, "message": "Character purchased successfully.", "character_id": character_id, "price": float(price)})
    except Exception as exc:
        conn.rollback(); return jsonify({"success": False, "message": "Character purchase failed.", "error": str(exc)}), 500
    finally:
        cur.close(); conn.close()


@character_bp.post("/sell")
def sell_character():
    data = request.get_json(silent=True) or {}
    try:
        telegram_id = int(data.get("telegram_id")); character_id = int(data.get("character_id")); price = _money(data.get("price"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Invalid sell data."}), 400
    if price <= 0:
        return jsonify({"success": False, "message": "Sell price must be greater than zero."}), 400

    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM characters WHERE id=%s FOR UPDATE", (character_id,))
        row = cur.fetchone()
        if not row: return jsonify({"success": False, "message": "Character not found."}), 404
        cols=[d[0] for d in cur.description]; c=dict(zip(cols,row))
        if not c["trading_enabled"]:
            return jsonify({"success": False, "message": "Character trading is disabled."}), 400
        cur.execute("""
            SELECT id FROM character_ownerships
            WHERE character_id=%s AND telegram_id=%s AND status='owned'
            FOR UPDATE
        """, (character_id, telegram_id))
        ownership = cur.fetchone()
        if not ownership: return jsonify({"success": False, "message": "You do not own this character."}), 403
        cur.execute("UPDATE character_ownerships SET status='sold', sold_at=CURRENT_TIMESTAMP, sale_price=%s WHERE id=%s", (price, ownership[0]))
        # Selling back to the platform credits Main Balance. A later marketplace
        # connection can replace this with buyer-to-seller settlement.
        cur.execute("UPDATE users SET deposit_balance=deposit_balance+%s WHERE telegram_id=%s", (price, telegram_id))
        cur.execute("UPDATE characters SET seller_pressure=seller_pressure-1, updated_at=CURRENT_TIMESTAMP WHERE id=%s", (character_id,))
        cur.execute("INSERT INTO character_trade_history(character_id,seller_id,buyer_id,price,trade_type) VALUES(%s,%s,NULL,%s,'user_sale')", (character_id, telegram_id, price))
        conn.commit()
        return jsonify({"success": True, "message": "Character sold successfully.", "sale_price": float(price)})
    except Exception as exc:
        conn.rollback(); return jsonify({"success": False, "message": "Character sale failed.", "error": str(exc)}), 500
    finally:
        cur.close(); conn.close()


@character_bp.get("/market")
def market_listings():
    conn=get_connection(); cur=conn.cursor()
    try:
        cur.execute("""
            SELECT l.id, l.ownership_id, l.character_id, l.seller_id, l.asking_price,
                   l.status, l.created_at, c.code, c.name, c.rarity, c.boost_percent,
                   c.ability_name
            FROM character_market_listings l
            JOIN characters c ON c.id=l.character_id
            WHERE l.status='active'
            ORDER BY l.created_at DESC
        """)
        rows=cur.fetchall(); cols=[d[0] for d in cur.description]
        listings=[]
        for r in rows:
            item=dict(zip(cols,r)); item['asking_price']=float(item['asking_price']); listings.append(item)
        return jsonify({'success':True,'listings':listings})
    finally: cur.close(); conn.close()


@character_bp.post("/market/list")
def create_market_listing():
    data=request.get_json(silent=True) or {}
    try:
        telegram_id=int(data.get('telegram_id')); ownership_id=int(data.get('ownership_id')); asking_price=_money(data.get('asking_price'))
    except (TypeError,ValueError):
        return jsonify({'success':False,'message':'Invalid listing data.'}),400
    if asking_price <= 0:
        return jsonify({'success':False,'message':'Asking price must be greater than zero.'}),400
    conn=get_connection(); cur=conn.cursor()
    try:
        cur.execute("SELECT * FROM character_ownerships WHERE id=%s FOR UPDATE", (ownership_id,))
        own=cur.fetchone()
        if not own: return jsonify({'success':False,'message':'Character ownership not found.'}),404
        ocols=[d[0] for d in cur.description]; own=dict(zip(ocols,own))
        if int(own['telegram_id']) != telegram_id or own['status'] != 'owned':
            return jsonify({'success':False,'message':'You do not own this character.'}),403
        cur.execute("SELECT trading_enabled FROM characters WHERE id=%s FOR UPDATE", (own['character_id'],))
        c=cur.fetchone()
        if not c or not c[0]: return jsonify({'success':False,'message':'Character trading is disabled.'}),400
        cur.execute("SELECT 1 FROM character_market_listings WHERE ownership_id=%s AND status='active'", (ownership_id,))
        if cur.fetchone(): return jsonify({'success':False,'message':'Character is already listed.'}),400
        cur.execute("""INSERT INTO character_market_listings(ownership_id,character_id,seller_id,asking_price)
                       VALUES(%s,%s,%s,%s) RETURNING id""", (ownership_id,own['character_id'],telegram_id,asking_price))
        listing_id=cur.fetchone()[0]
        conn.commit()
        return jsonify({'success':True,'listing_id':listing_id,'asking_price':float(asking_price)})
    except Exception as exc:
        conn.rollback(); return jsonify({'success':False,'message':'Listing failed.','error':str(exc)}),500
    finally: cur.close(); conn.close()


@character_bp.post("/market/buy")
def buy_market_listing():
    data=request.get_json(silent=True) or {}
    try: buyer_id=int(data.get('telegram_id')); listing_id=int(data.get('listing_id'))
    except (TypeError,ValueError): return jsonify({'success':False,'message':'telegram_id and listing_id are required.'}),400
    conn=get_connection(); cur=conn.cursor()
    try:
        cur.execute("SELECT * FROM character_market_listings WHERE id=%s AND status='active' FOR UPDATE", (listing_id,))
        listing=cur.fetchone()
        if not listing: return jsonify({'success':False,'message':'Listing not found or already sold.'}),404
        lcols=[d[0] for d in cur.description]; l=dict(zip(lcols,listing))
        if int(l['seller_id']) == buyer_id: return jsonify({'success':False,'message':'You cannot buy your own listing.'}),400
        cur.execute("SELECT * FROM users WHERE telegram_id=%s FOR UPDATE", (buyer_id,))
        buyer=cur.fetchone()
        if not buyer: return jsonify({'success':False,'message':'Buyer not found.'}),404
        ucols=[d[0] for d in cur.description]; buyer_row=dict(zip(ucols,buyer))
        price=_money(l['asking_price'])
        if _money(buyer_row.get('deposit_balance')) < price:
            return jsonify({'success':False,'message':'Insufficient Main Balance.','required':float(price),'available':float(buyer_row.get('deposit_balance') or 0)}),400
        cur.execute("SELECT * FROM character_ownerships WHERE id=%s FOR UPDATE", (l['ownership_id'],))
        own=cur.fetchone()
        if not own: return jsonify({'success':False,'message':'Ownership record not found.'}),404
        ocols=[d[0] for d in cur.description]; own=dict(zip(ocols,own))
        if own['status'] != 'owned' or int(own['telegram_id']) != int(l['seller_id']):
            return jsonify({'success':False,'message':'Listing ownership is no longer valid.'}),409
        cur.execute("SELECT 1 FROM character_ownerships WHERE character_id=%s AND telegram_id=%s AND status='owned' LIMIT 1", (l['character_id'],buyer_id))
        if cur.fetchone(): return jsonify({'success':False,'message':'You already own this character.'}),400
        cur.execute("UPDATE users SET deposit_balance=deposit_balance-%s WHERE telegram_id=%s", (price,buyer_id))
        cur.execute("UPDATE users SET deposit_balance=deposit_balance+%s WHERE telegram_id=%s", (price,l['seller_id']))
        cur.execute("UPDATE character_ownerships SET telegram_id=%s, purchase_price=%s, acquired_at=CURRENT_TIMESTAMP, sold_at=NULL, sale_price=NULL WHERE id=%s", (buyer_id,price,l['ownership_id']))
        cur.execute("UPDATE character_market_listings SET status='sold', sold_at=CURRENT_TIMESTAMP WHERE id=%s", (listing_id,))
        cur.execute("INSERT INTO character_trade_history(character_id,seller_id,buyer_id,price,trade_type) VALUES(%s,%s,%s,%s,'secondary_sale')", (l['character_id'],l['seller_id'],buyer_id,price))
        conn.commit()
        return jsonify({'success':True,'message':'Character purchased from marketplace.','listing_id':listing_id,'price':float(price),'character_id':int(l['character_id'])})
    except Exception as exc:
        conn.rollback(); return jsonify({'success':False,'message':'Marketplace purchase failed.','error':str(exc)}),500
    finally: cur.close(); conn.close()


@character_bp.delete("/market/list/<int:listing_id>")
def cancel_market_listing(listing_id):
    data=request.get_json(silent=True) or {}
    try: telegram_id=int(data.get('telegram_id'))
    except (TypeError,ValueError): return jsonify({'success':False,'message':'telegram_id is required.'}),400
    conn=get_connection(); cur=conn.cursor()
    try:
        cur.execute("UPDATE character_market_listings SET status='cancelled' WHERE id=%s AND seller_id=%s AND status='active' RETURNING id", (listing_id,telegram_id))
        row=cur.fetchone()
        if not row: conn.rollback(); return jsonify({'success':False,'message':'Active listing not found.'}),404
        conn.commit(); return jsonify({'success':True,'message':'Listing cancelled.'})
    except Exception as exc:
        conn.rollback(); return jsonify({'success':False,'message':'Listing cancellation failed.','error':str(exc)}),500
    finally: cur.close(); conn.close()


@character_bp.get("/admin/config")
@require_admin
def admin_list_characters(admin):
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM characters ORDER BY id")
        rows=cur.fetchall(); cols=[d[0] for d in cur.description]
        return jsonify({"success":True,"characters":[_json_character(dict(zip(cols,r))) for r in rows]})
    finally: cur.close(); conn.close()


@character_bp.put("/admin/config/<int:character_id>")
@require_admin
def admin_update_character(admin, character_id):
    data=request.get_json(silent=True) or {}
    allowed={
        "name","description","ability_name","ability_description","benefits","image_url","rarity",
        "base_price","boost_percent","upgrade_cost_l2","upgrade_cost_l3","upgrade_cost_l4","upgrade_cost_l5",
        "max_supply","is_active","trading_enabled","seller_pressure","external_pressure","market_multiplier"
    }
    updates={k:data[k] for k in allowed if k in data}
    if "image_url" in updates:
        image_value=str(updates["image_url"] or "")
        if len(image_value)>750000 or (image_value and not (image_value.startswith("data:image/") or image_value.startswith("https://") or image_value.startswith("http://"))):
            return jsonify({"success":False,"message":"Logo must be an image upload or a valid image URL, maximum 512 KB."}),400
        updates["image_url"]=image_value
    if not updates:
        return jsonify({"success":False,"message":"No character fields supplied."}),400
    if "base_price" in updates and not (MIN_PRICE <= _money(updates["base_price"]) <= MAX_PRICE):
        return jsonify({"success":False,"message":"Invalid base price."}),400
    if "max_supply" in updates:
        try:
            updates["max_supply"]=int(updates["max_supply"])
            if updates["max_supply"]<0: raise ValueError
        except (TypeError,ValueError):
            return jsonify({"success":False,"message":"Invalid max supply."}),400
    conn=get_connection(); cur=conn.cursor()
    try:
        sets=[]; vals=[]
        for key,value in updates.items():
            if key in {"base_price","boost_percent","seller_pressure","external_pressure","market_multiplier"}:
                value=_money(value) if key!="market_multiplier" else Decimal(str(value))
            sets.append(f"{key}=%s"); vals.append(value)
        sets.append("updated_at=CURRENT_TIMESTAMP")
        vals.append(character_id)
        cur.execute(f"UPDATE characters SET {', '.join(sets)} WHERE id=%s RETURNING *", vals)
        row=cur.fetchone()
        if not row:
            conn.rollback(); return jsonify({"success":False,"message":"Character not found."}),404
        cols=[d[0] for d in cur.description]
        saved_character = _json_character(dict(zip(cols, row)))
        conn.commit()
        # Re-read the persisted record after commit so the API confirms the
        # value that is actually stored, rather than only the UPDATE RETURNING row.
        cur.execute("SELECT * FROM characters WHERE id=%s", (character_id,))
        persisted_row = cur.fetchone()
        if not persisted_row:
            return jsonify({"success":False,"message":"Character update committed but could not be read back."}),500
        persisted_cols=[d[0] for d in cur.description]
        persisted_character=_json_character(dict(zip(persisted_cols,persisted_row)))
        if "image_url" in updates and str(persisted_character.get("image_url") or "") != str(updates["image_url"] or ""):
            return jsonify({"success":False,"message":"Character details were saved, but logo was not persisted. Check database column/update."}),500
        # Ensure the image field is explicitly present in the JSON response.
        persisted_character["image_url"] = persisted_character.get("image_url") or ""
        return jsonify({"success":True,"character":persisted_character,"logo_saved":bool(persisted_character.get("image_url"))})
    except Exception as exc:
        conn.rollback(); return jsonify({"success":False,"message":"Character update failed.","error":str(exc)}),500
    finally: cur.close(); conn.close()


@character_bp.post("/admin/config/<int:character_id>/market")
@require_admin
def admin_update_market(admin, character_id):
    data=request.get_json(silent=True) or {}
    fields={k:data[k] for k in ("seller_pressure","external_pressure","market_multiplier") if k in data}
    if not fields:
        return jsonify({"success":False,"message":"No market fields supplied."}),400
    conn=get_connection(); cur=conn.cursor()
    try:
        sets=[]; vals=[]
        for k,v in fields.items():
            sets.append(f"{k}=%s"); vals.append(Decimal(str(v)))
        vals.append(character_id)
        cur.execute(f"UPDATE characters SET {', '.join(sets)}, updated_at=CURRENT_TIMESTAMP WHERE id=%s RETURNING *", vals)
        row=cur.fetchone()
        if not row:
            conn.rollback(); return jsonify({"success":False,"message":"Character not found."}),404
        cols=[d[0] for d in cur.description]
        conn.commit()
        return jsonify({"success":True,"character":_json_character(dict(zip(cols,row)))})
    except Exception as exc:
        conn.rollback(); return jsonify({"success":False,"message":"Market settings update failed.","error":str(exc)}),500
    finally: cur.close(); conn.close()


@character_bp.get("/admin/trades")
@require_admin
def admin_trades(admin):
    conn=get_connection(); cur=conn.cursor()
    try:
        cur.execute("""
            SELECT h.*, c.code, c.name
            FROM character_trade_history h
            JOIN characters c ON c.id=h.character_id
            ORDER BY h.created_at DESC LIMIT 500
        """)
        rows=cur.fetchall(); cols=[d[0] for d in cur.description]
        return jsonify({"success":True,"trades":[dict(zip(cols,r)) for r in rows]})
    finally: cur.close(); conn.close()


# Endpoint map (kept in the file for easy frontend connection):
# GET    /api/characters
# GET    /api/characters/<id>
# GET    /api/characters/user/<telegram_id>
# POST   /api/characters/buy
# POST   /api/characters/sell
# GET    /api/characters/market
# POST   /api/characters/market/list
# POST   /api/characters/market/buy
# DELETE /api/characters/market/list/<id>
# GET    /api/characters/admin/config
# PUT    /api/characters/admin/config/<id>
# POST   /api/characters/admin/config/<id>/market
# GET    /api/characters/admin/trades


# Character ownership level upgrades, daily reward, and admin-configurable weekly rewards.
LEVEL_BOOSTS = {1: 5, 2: 7, 3: 10, 4: 15, 5: 20}
WEEKLY_REWARD_DEFAULTS = [100, 200, 350, 400, 500, 650, 800]

@character_bp.get("/user/<int:telegram_id>/daily-status")
def character_daily_status(telegram_id):
    conn=get_connection(); cur=conn.cursor()
    try:
        cur.execute("""SELECT o.id,o.character_id,o.level,c.name,c.image_url
                       FROM character_ownerships o JOIN characters c ON c.id=o.character_id
                       WHERE o.telegram_id=%s AND o.status='owned' ORDER BY o.acquired_at DESC""",(telegram_id,))
        owned=cur.fetchall()
        if not owned:
            return jsonify({"success":True,"owns_character":False,"claimed_today":False,"message":"Daily Reward পেতে Character কিনুন।"})
        cur.execute("SELECT setting_value FROM character_settings WHERE setting_key='weekly_daily_rewards'")
        row=cur.fetchone()
        try: rewards=[max(0,float(x)) for x in (row[0] if row else '').split(',')]
        except Exception: rewards=[]
        if len(rewards)!=7: rewards=WEEKLY_REWARD_DEFAULTS
        cur.execute("SELECT 1 FROM character_daily_rewards WHERE telegram_id=%s AND reward_day=(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Dhaka')::date",(telegram_id,))
        claimed=cur.fetchone() is not None
        cur.execute("SELECT EXTRACT(ISODOW FROM (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Dhaka')::date)::int")
        day=int(cur.fetchone()[0])
        return jsonify({"success":True,"owns_character":True,"claimed_today":claimed,"today_reward":rewards[day-1],"weekday":day,"weekly_rewards":rewards,"owned":[{"ownership_id":r[0],"character_id":r[1],"level":r[2],"name":r[3],"image_url":r[4]} for r in owned]})
    finally: cur.close(); conn.close()

@character_bp.post("/daily-reward/claim")
def claim_character_daily_reward():
    data=request.get_json(silent=True) or {}
    try: telegram_id=int(data.get('telegram_id'))
    except (TypeError,ValueError): return jsonify({"success":False,"message":"telegram_id is required."}),400
    conn=get_connection(); cur=conn.cursor()
    try:
        cur.execute("SELECT id FROM character_ownerships WHERE telegram_id=%s AND status='owned' ORDER BY acquired_at DESC LIMIT 1 FOR UPDATE",(telegram_id,))
        own=cur.fetchone()
        if not own: conn.rollback(); return jsonify({"success":False,"message":"Daily Reward পেতে Character থাকতে হবে।"}),403
        cur.execute("SELECT setting_value FROM character_settings WHERE setting_key='weekly_daily_rewards' FOR SHARE")
        row=cur.fetchone()
        try: rewards=[Decimal(x.strip()) for x in row[0].split(',')] if row else []
        except Exception: rewards=[]
        if len(rewards)!=7 or any(x<0 for x in rewards): rewards=[Decimal(str(x)) for x in WEEKLY_REWARD_DEFAULTS]
        cur.execute("SELECT EXTRACT(ISODOW FROM (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Dhaka')::date)::int")
        day=int(cur.fetchone()[0]); amount=rewards[day-1]
        cur.execute("""INSERT INTO character_daily_rewards(telegram_id,ownership_id,reward_day,reward_amount)
                       VALUES(%s,%s,(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Dhaka')::date,%s) ON CONFLICT(telegram_id,reward_day) DO NOTHING RETURNING id""",(telegram_id,own[0],amount))
        if not cur.fetchone(): conn.rollback(); return jsonify({"success":False,"message":"আজকের Daily Reward ইতিমধ্যে নেওয়া হয়েছে।"}),409
        cur.execute("UPDATE users SET task_balance=COALESCE(task_balance,0)+%s,balance=COALESCE(task_balance,0)+%s,total_earned=COALESCE(total_earned,0)+%s,last_active=CURRENT_TIMESTAMP WHERE telegram_id=%s RETURNING task_balance",(amount,amount,amount,telegram_id))
        updated=cur.fetchone()
        if not updated: conn.rollback(); return jsonify({"success":False,"message":"User not found."}),404
        conn.commit()
        return jsonify({"success":True,"message":"Daily Reward পেয়েছেন!","reward":float(amount),"balance":float(updated[0]),"weekday":day})
    except Exception as exc:
        conn.rollback(); return jsonify({"success":False,"message":"Daily Reward failed.","error":str(exc)}),500
    finally: cur.close(); conn.close()

@character_bp.post("/upgrade")
def upgrade_character_level():
    data=request.get_json(silent=True) or {}
    try: telegram_id=int(data.get('telegram_id')); ownership_id=int(data.get('ownership_id'))
    except (TypeError,ValueError): return jsonify({"success":False,"message":"telegram_id and ownership_id are required."}),400
    conn=get_connection(); cur=conn.cursor()
    try:
        cur.execute("SELECT * FROM character_ownerships WHERE id=%s AND telegram_id=%s AND status='owned' FOR UPDATE",(ownership_id,telegram_id))
        own=cur.fetchone()
        if not own: conn.rollback(); return jsonify({"success":False,"message":"আপনার এই Character নেই।"}),404
        cols=[d[0] for d in cur.description]; own=dict(zip(cols,own)); level=int(own.get('level') or 1)
        if level>=5: conn.rollback(); return jsonify({"success":False,"message":"Character ইতিমধ্যে Level 5।"}),400
        next_level=level+1; cost_col=f'upgrade_cost_l{next_level}'
        cur.execute(f"SELECT {cost_col},name FROM characters WHERE id=%s FOR UPDATE",(own['character_id'],))
        c=cur.fetchone()
        if not c: conn.rollback(); return jsonify({"success":False,"message":"Character not found."}),404
        cost=Decimal(str(c[0] or 0))
        cur.execute("SELECT task_balance FROM users WHERE telegram_id=%s FOR UPDATE",(telegram_id,)); user=cur.fetchone()
        if not user: conn.rollback(); return jsonify({"success":False,"message":"User not found."}),404
        available=Decimal(str(user[0] or 0))
        if cost<0 or available<cost: conn.rollback(); return jsonify({"success":False,"message":"Upgrade-এর জন্য পর্যাপ্ত TaskCoin নেই।","required":float(cost),"available":float(available)}),400
        cur.execute("UPDATE users SET task_balance=COALESCE(task_balance,0)-%s,balance=COALESCE(task_balance,0)-%s WHERE telegram_id=%s",(cost,cost,telegram_id))
        cur.execute("UPDATE character_ownerships SET level=%s WHERE id=%s",(next_level,ownership_id))
        conn.commit()
        return jsonify({"success":True,"message":f"Character Level {next_level} হয়েছে!","level":next_level,"boost_percent":LEVEL_BOOSTS[next_level],"cost":float(cost)})
    except Exception as exc:
        conn.rollback(); return jsonify({"success":False,"message":"Upgrade failed.","error":str(exc)}),500
    finally: cur.close(); conn.close()

@character_bp.put("/admin/daily-rewards")
@require_admin
def admin_update_weekly_rewards(admin):
    data=request.get_json(silent=True) or {}; values=data.get('weekly_rewards')
    if not isinstance(values,list) or len(values)!=7:
        return jsonify({"success":False,"message":"সাত দিনের জন্য ৭টি reward amount দিন।"}),400
    try: rewards=[Decimal(str(v)) for v in values]
    except Exception: return jsonify({"success":False,"message":"Invalid reward values."}),400
    if any(v<0 or v>100000000 for v in rewards): return jsonify({"success":False,"message":"Reward values must be between 0 and 100000000."}),400
    conn=get_connection(); cur=conn.cursor()
    try:
        cur.execute("INSERT INTO character_settings(setting_key,setting_value) VALUES('weekly_daily_rewards',%s) ON CONFLICT(setting_key) DO UPDATE SET setting_value=EXCLUDED.setting_value",(','.join(str(v) for v in rewards),))
        conn.commit(); return jsonify({"success":True,"weekly_rewards":[float(v) for v in rewards]})
    except Exception as exc:
        conn.rollback(); return jsonify({"success":False,"message":"Could not save weekly rewards.","error":str(exc)}),500
    finally: cur.close(); conn.close()


@character_bp.get("/admin/daily-rewards")
@require_admin
def admin_get_weekly_rewards(admin):
    conn=get_connection(); cur=conn.cursor()
    try:
        cur.execute("SELECT setting_value FROM character_settings WHERE setting_key='weekly_daily_rewards'")
        row=cur.fetchone()
        try: values=[float(v.strip()) for v in row[0].split(',')] if row else WEEKLY_REWARD_DEFAULTS
        except Exception: values=WEEKLY_REWARD_DEFAULTS
        if len(values)!=7: values=WEEKLY_REWARD_DEFAULTS
        return jsonify({"success":True,"weekly_rewards":values})
    finally: cur.close(); conn.close()

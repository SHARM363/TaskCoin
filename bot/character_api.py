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
    for key in ("base_price", "current_price", "market_multiplier", "seller_pressure", "external_pressure"):
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
                rarity TEXT NOT NULL DEFAULT 'Common',
                base_price NUMERIC(20,2) NOT NULL DEFAULT 0,
                boost_percent NUMERIC(10,2) NOT NULL DEFAULT 0,
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
        price = _recalculate_price(cur, character_id)
        balance = Decimal(str(user[2] or 0))
        if balance < price:
            return jsonify({"success": False, "message": "Insufficient Main Balance.", "required": float(price), "available": float(balance)}), 400
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
        "name","description","ability_name","ability_description","rarity",
        "base_price","boost_percent","max_supply","is_active","trading_enabled",
        "seller_pressure","external_pressure","market_multiplier"
    }
    updates={k:data[k] for k in allowed if k in data}
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
        conn.commit()
        return jsonify({"success":True,"character":_json_character(dict(zip(cols,row)))})
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

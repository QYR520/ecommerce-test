# -*- coding: utf-8 -*-
"""电商被测系统 —— Flask 后端。

覆盖完整业务域：用户/地址、商品(搜索/筛选)、购物车、优惠券、
下单(金额计算)、支付、订单状态机(取消/退款/发货/收货/完成)、后台管理(越权拦截)。

金额规则（自动化用例硬校验）：
    subtotal = Σ(单价 × 数量)
    运费 freight = 0（subtotal >= 99 包邮）否则 8
    满减 discount = 10（subtotal >= 200）否则 0
    优惠券 coupon = min(券面额, 满足门槛时) —— 与满减叠加
    实付 pay_amount = subtotal + freight - discount - coupon

订单状态机：
    unpaid →(pay)→ paid →(ship)→ shipped →(deliver)→ delivered →(complete)→ completed
    unpaid →(cancel)→ cancelled（回滚库存）
    paid   →(refund)→ refunded（回滚库存 + 退款流水）

缓存一致性（缺陷开关 flaw.stale_cache）：下单/退款回滚若不失效商品缓存，
接口(页面)展示的库存会与数据库不一致，由对账用例抓出。
"""
import os
import time

from flask import Flask, g, jsonify, request, send_from_directory

from . import auth as authmod
from . import db as dbmod
from .cache import Cache


def create_app(config):
    app = Flask(__name__)
    app.config["DB_PATH"] = config["app"]["db_path"]
    app.config["CACHE"] = Cache()
    app.config["CACHE_TTL"] = config["app"].get("cache_ttl", 60)
    app.config["STALE_CACHE"] = bool((config["app"].get("flaw") or {}).get("stale_cache"))
    app.config["TOKEN_TTL"] = config["auth"]["token_ttl"]

    def get_conn():
        if "db" not in g:
            g.db = dbmod.connect(app.config["DB_PATH"])
        return g.db

    @app.teardown_appcontext
    def close(exception):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def current_user():
        """校验 token，返回 users 行；未登录返回 None。"""
        auth = request.headers.get("Authorization", "")
        username = authmod.validate_token(auth.replace("Bearer ", "").strip())
        if not username:
            return None
        return get_conn().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()

    def product_via_cache(conn, pid):
        cache = app.config["CACHE"]
        key = f"product:{pid}"
        hit = cache.get(key)
        if hit is not None:
            return hit, True
        row = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        if row is None:
            return None, False
        data = {"id": row["id"], "name": row["name"], "price": row["price"],
                "stock": row["stock"], "category": row["category"], "status": row["status"]}
        cache.set(key, data, ttl=app.config["CACHE_TTL"])
        return data, False

    def invalidate_products(conn, product_ids):
        if app.config["STALE_CACHE"]:
            return
        for pid in product_ids:
            app.config["CACHE"].delete(f"product:{pid}")

    def restore_stock(conn, order_id):
        """订单取消/退款时回滚库存，并失效对应商品缓存。"""
        items = conn.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,)).fetchall()
        for it in items:
            conn.execute("UPDATE products SET stock = stock + ? WHERE id=?",
                         (it["quantity"], it["product_id"]))
        invalidate_products(conn, [it["product_id"] for it in items])

    def calc_order(conn, items, coupon=None):
        subtotal = 0.0
        rows = []
        for it in items:
            pid = it["product_id"]
            qty = int(it["quantity"])
            row = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
            if row is None:
                raise ValueError(f"商品不存在: {pid}")
            if row["stock"] < qty:
                raise ValueError(f"库存不足: {pid}")
            st = round(row["price"] * qty, 2)
            subtotal += st
            rows.append((row, qty, st))
        subtotal = round(subtotal, 2)
        freight = 0.0 if subtotal >= 99 else 8.0
        discount = 10.0 if subtotal >= 200 else 0.0
        coupon_amount = 0.0
        if coupon is not None:
            if subtotal < coupon["threshold"]:
                raise ValueError(f"未满足优惠券门槛(满{coupon['threshold']}可用)")
            coupon_amount = coupon["amount"]
        pay = round(subtotal + freight - discount - coupon_amount, 2)
        return subtotal, freight, discount, coupon_amount, pay, rows

    # ============ 用户域 ============
    @app.route("/register", methods=["POST"])
    def register():
        body = request.get_json(force=True, silent=True) or {}
        username = body.get("username")
        password = body.get("password")
        if not username or not password:
            return jsonify({"error": "用户名/密码不能为空"}), 400
        conn = get_conn()
        if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            return jsonify({"error": "用户名已存在"}), 400
        conn.execute("INSERT INTO users(username, password, role) VALUES(?,?,?)",
                     (username, password, "user"))
        conn.commit()
        return jsonify({"ok": True}), 201

    @app.route("/login", methods=["POST"])
    def login():
        body = request.get_json(force=True, silent=True) or {}
        conn = get_conn()
        row = conn.execute("SELECT * FROM users WHERE username=? AND password=?",
                           (body.get("username"), body.get("password"))).fetchone()
        if row is None:
            return jsonify({"error": "用户名或密码错误"}), 401
        token = authmod.issue_token(row["username"], app.config["TOKEN_TTL"])
        return jsonify({"token": token, "expires_in": app.config["TOKEN_TTL"]})

    # ============ 地址域 ============
    @app.route("/address", methods=["GET"])
    def list_address():
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        rows = get_conn().execute("SELECT * FROM addresses WHERE user_id=? ORDER BY is_default DESC, id",
                                  (user["id"],)).fetchall()
        return jsonify({"addresses": [dict(r) for r in rows]})

    @app.route("/address", methods=["POST"])
    def add_address():
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        body = request.get_json(force=True, silent=True) or {}
        conn = get_conn()
        if body.get("is_default"):
            conn.execute("UPDATE addresses SET is_default=0 WHERE user_id=?", (user["id"],))
        cur = conn.execute(
            "INSERT INTO addresses(user_id, receiver, phone, province, city, detail, is_default) "
            "VALUES(?,?,?,?,?,?,?)",
            (user["id"], body.get("receiver"), body.get("phone"), body.get("province"),
             body.get("city"), body.get("detail"), 1 if body.get("is_default") else 0))
        conn.commit()
        return jsonify({"id": cur.lastrowid, "ok": True}), 201

    @app.route("/address/<int:aid>", methods=["PUT"])
    def update_address(aid):
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        conn = get_conn()
        addr = conn.execute("SELECT * FROM addresses WHERE id=? AND user_id=?",
                            (aid, user["id"])).fetchone()
        if addr is None:
            return jsonify({"error": "地址不存在"}), 404
        body = request.get_json(force=True, silent=True) or {}
        if body.get("is_default"):
            conn.execute("UPDATE addresses SET is_default=0 WHERE user_id=?", (user["id"],))
        conn.execute(
            "UPDATE addresses SET receiver=?, phone=?, province=?, city=?, detail=?, is_default=? "
            "WHERE id=?",
            (body.get("receiver", addr["receiver"]), body.get("phone", addr["phone"]),
             body.get("province", addr["province"]), body.get("city", addr["city"]),
             body.get("detail", addr["detail"]),
             1 if body.get("is_default") else 0, aid))
        conn.commit()
        return jsonify({"ok": True})

    @app.route("/address/<int:aid>", methods=["DELETE"])
    def delete_address(aid):
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        conn = get_conn()
        cur = conn.execute("DELETE FROM addresses WHERE id=? AND user_id=?", (aid, user["id"]))
        conn.commit()
        return jsonify({"ok": True, "deleted": cur.rowcount})

    # ============ 商品域（搜索/筛选/分页） ============
    @app.route("/products", methods=["GET"])
    def list_products():
        conn = get_conn()
        where = ["status='on_sale'"]
        params = []
        if request.args.get("kw"):
            where.append("name LIKE ?")
            params.append(f"%{request.args['kw']}%")
        if request.args.get("category"):
            where.append("category=?")
            params.append(request.args["category"])
        if request.args.get("min_price") is not None:
            where.append("price>=?")
            params.append(float(request.args["min_price"]))
        if request.args.get("max_price") is not None:
            where.append("price<=?")
            params.append(float(request.args["max_price"]))
        page = max(1, request.args.get("page", 1, type=int))
        size = max(1, request.args.get("size", 10, type=int))
        cond = " AND ".join(where)
        total = conn.execute(f"SELECT COUNT(*) c FROM products WHERE {cond}", params).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM products WHERE {cond} ORDER BY id LIMIT ? OFFSET ?",
            params + [size, (page - 1) * size]).fetchall()
        return jsonify({"total": total, "page": page, "size": size,
                        "products": [dict(r) for r in rows]})

    @app.route("/products/<pid>", methods=["GET"])
    def product(pid):
        conn = get_conn()
        data, hit = product_via_cache(conn, pid)
        if data is None:
            return jsonify({"error": "商品不存在"}), 404
        return jsonify({"product": data, "from_cache": hit})

    @app.route("/products/<pid>", methods=["PUT"])
    def admin_update_product(pid):
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        if user["role"] != "admin":
            return jsonify({"error": "无权限"}), 403
        body = request.get_json(force=True, silent=True) or {}
        conn = get_conn()
        fields, params = [], []
        for col in ("price", "stock", "status"):
            if col in body:
                fields.append(f"{col}=?")
                params.append(body[col])
        if not fields:
            return jsonify({"error": "无可更新字段"}), 400
        conn.execute(f"UPDATE products SET {','.join(fields)} WHERE id=?", params + [pid])
        conn.commit()
        app.config["CACHE"].delete(f"product:{pid}")
        row = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        return jsonify({"product": dict(row)})

    # ============ 购物车域 ============
    @app.route("/cart", methods=["POST"])
    def add_cart():
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        body = request.get_json(force=True, silent=True) or {}
        conn = get_conn()
        cur = conn.execute("INSERT INTO carts(user_id, product_id, quantity) VALUES(?,?,?)",
                           (user["id"], body.get("product_id"), int(body.get("quantity", 1))))
        conn.commit()
        return jsonify({"id": cur.lastrowid, "ok": True})

    @app.route("/cart", methods=["GET"])
    def view_cart():
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        conn = get_conn()
        rows = conn.execute(
            "SELECT c.id, c.quantity, p.id AS product_id, p.name, p.price "
            "FROM carts c JOIN products p ON c.product_id=p.id WHERE c.user_id=?",
            (user["id"],)).fetchall()
        return jsonify({"items": [dict(r) for r in rows]})

    @app.route("/cart/<int:cid>", methods=["PUT"])
    def update_cart(cid):
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        body = request.get_json(force=True, silent=True) or {}
        conn = get_conn()
        cur = conn.execute("UPDATE carts SET quantity=? WHERE id=? AND user_id=?",
                           (int(body.get("quantity", 1)), cid, user["id"]))
        conn.commit()
        return jsonify({"ok": True})

    @app.route("/cart/<int:cid>", methods=["DELETE"])
    def delete_cart(cid):
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        conn = get_conn()
        cur = conn.execute("DELETE FROM carts WHERE id=? AND user_id=?", (cid, user["id"]))
        conn.commit()
        return jsonify({"ok": True, "deleted": cur.rowcount})

    @app.route("/cart", methods=["DELETE"])
    def clear_cart():
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        conn = get_conn()
        cur = conn.execute("DELETE FROM carts WHERE user_id=?", (user["id"],))
        conn.commit()
        return jsonify({"ok": True, "deleted": cur.rowcount})

    # ============ 优惠券域 ============
    @app.route("/coupons", methods=["GET"])
    def list_coupons():
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        conn = get_conn()
        rows = conn.execute(
            "SELECT uc.id, uc.status, c.id AS coupon_id, c.title, c.threshold, c.amount "
            "FROM user_coupons uc JOIN coupons c ON c.id=uc.coupon_id WHERE uc.user_id=?",
            (user["id"],)).fetchall()
        return jsonify({"coupons": [dict(r) for r in rows]})

    @app.route("/coupons/<cid>/claim", methods=["POST"])
    def claim_coupon(cid):
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        conn = get_conn()
        coupon = conn.execute("SELECT * FROM coupons WHERE id=?", (cid,)).fetchone()
        if coupon is None or coupon["stock"] <= 0:
            return jsonify({"error": "优惠券不存在或已领完"}), 400
        conn.execute("UPDATE coupons SET stock=stock-1 WHERE id=?", (cid,))
        conn.execute("INSERT INTO user_coupons(user_id, coupon_id, status) VALUES(?,?,?)",
                     (user["id"], cid, "unused"))
        conn.commit()
        return jsonify({"ok": True})

    # ============ 订单域 ============
    @app.route("/order", methods=["POST"])
    def create_order():
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        body = request.get_json(force=True, silent=True) or {}
        items = body.get("items")
        if not items:
            return jsonify({"error": "订单为空"}), 400

        conn = get_conn()
        coupon = None
        coupon_id = body.get("coupon_id")
        if coupon_id:
            coupon = conn.execute("SELECT * FROM coupons WHERE id=? AND stock>=0",
                                  (coupon_id,)).fetchone()
            if coupon is None:
                return jsonify({"error": "优惠券不存在"}), 400
            uc = conn.execute(
                "SELECT * FROM user_coupons WHERE user_id=? AND coupon_id=? AND status='unused'",
                (user["id"], coupon_id)).fetchone()
            if uc is None:
                return jsonify({"error": "未持有该优惠券"}), 400
        try:
            subtotal, freight, discount, coupon_amount, pay, rows = calc_order(conn, items, coupon)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

        cur = conn.cursor()
        cur.execute(
            "INSERT INTO orders(user_id, subtotal, freight, discount, coupon_amount, pay_amount, "
            "status, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (user["id"], subtotal, freight, discount, coupon_amount, pay, "unpaid", time.time()))
        order_id = cur.lastrowid
        for prod, qty, st in rows:
            cur.execute(
                "INSERT INTO order_items(order_id, product_id, price, quantity, subtotal) "
                "VALUES(?,?,?,?,?)",
                (order_id, prod["id"], prod["price"], qty, st))
            cur.execute("UPDATE products SET stock = stock - ? WHERE id=?", (qty, prod["id"]))
        invalidate_products(conn, [p["id"] for p, _, _ in rows])
        if coupon is not None:
            cur.execute("UPDATE user_coupons SET status='used', used_order_id=? "
                        "WHERE user_id=? AND coupon_id=? AND status='unused'",
                        (order_id, user["id"], coupon_id))
        conn.commit()

        return jsonify({"order_id": order_id, "subtotal": subtotal, "freight": freight,
                        "discount": discount, "coupon_amount": coupon_amount,
                        "pay_amount": pay, "status": "unpaid"})

    @app.route("/orders", methods=["GET"])
    def list_orders():
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        conn = get_conn()
        rows = conn.execute("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC",
                            (user["id"],)).fetchall()
        return jsonify({"orders": [dict(r) for r in rows]})

    @app.route("/order/<int:oid>", methods=["GET"])
    def get_order(oid):
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        conn = get_conn()
        order = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if order is None:
            return jsonify({"error": "订单不存在"}), 404
        items = conn.execute("SELECT * FROM order_items WHERE order_id=?", (oid,)).fetchall()
        payments = conn.execute("SELECT * FROM payments WHERE order_id=?", (oid,)).fetchall()
        return jsonify({"order": dict(order), "items": [dict(i) for i in items],
                        "payments": [dict(p) for p in payments]})

    @app.route("/order/<int:oid>/pay", methods=["POST"])
    def pay(oid):
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        conn = get_conn()
        order = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if order is None:
            return jsonify({"error": "订单不存在"}), 404
        if order["status"] != "unpaid":
            return jsonify({"error": f"订单状态 {order['status']} 不可支付"}), 400
        conn.execute("UPDATE orders SET status='paid' WHERE id=?", (oid,))
        conn.execute("INSERT INTO payments(order_id, type, amount, status, created_at) "
                     "VALUES(?,?,?,?,?)", (oid, "pay", order["pay_amount"], "success", time.time()))
        conn.commit()
        return jsonify({"ok": True, "status": "paid"})

    @app.route("/order/<int:oid>/cancel", methods=["POST"])
    def cancel(oid):
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        conn = get_conn()
        order = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if order is None:
            return jsonify({"error": "订单不存在"}), 404
        if order["status"] != "unpaid":
            return jsonify({"error": f"订单状态 {order['status']} 不可取消"}), 400
        restore_stock(conn, oid)
        conn.execute("UPDATE orders SET status='cancelled' WHERE id=?", (oid,))
        conn.commit()
        return jsonify({"ok": True, "status": "cancelled"})

    @app.route("/order/<int:oid>/refund", methods=["POST"])
    def refund(oid):
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        conn = get_conn()
        order = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if order is None:
            return jsonify({"error": "订单不存在"}), 404
        if order["status"] != "paid":
            return jsonify({"error": f"订单状态 {order['status']} 不可退款"}), 400
        restore_stock(conn, oid)
        conn.execute("UPDATE orders SET status='refunded' WHERE id=?", (oid,))
        conn.execute("INSERT INTO payments(order_id, type, amount, status, created_at) "
                     "VALUES(?,?,?,?,?)", (oid, "refund", -order["pay_amount"], "success", time.time()))
        conn.commit()
        return jsonify({"ok": True, "status": "refunded"})

    # ============ 订单状态机（发货/收货/完成，admin 发货可做越权演示） ============
    @app.route("/order/<int:oid>/ship", methods=["POST"])
    def ship(oid):
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        if user["role"] != "admin":
            return jsonify({"error": "无权限"}), 403
        conn = get_conn()
        order = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if order is None:
            return jsonify({"error": "订单不存在"}), 404
        if order["status"] != "paid":
            return jsonify({"error": f"订单状态 {order['status']} 不可发货"}), 400
        conn.execute("UPDATE orders SET status='shipped' WHERE id=?", (oid,))
        conn.commit()
        return jsonify({"ok": True, "status": "shipped"})

    @app.route("/order/<int:oid>/deliver", methods=["POST"])
    def deliver(oid):
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        conn = get_conn()
        order = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if order is None:
            return jsonify({"error": "订单不存在"}), 404
        if order["status"] != "shipped":
            return jsonify({"error": f"订单状态 {order['status']} 不可收货"}), 400
        conn.execute("UPDATE orders SET status='delivered' WHERE id=?", (oid,))
        conn.commit()
        return jsonify({"ok": True, "status": "delivered"})

    @app.route("/order/<int:oid>/complete", methods=["POST"])
    def complete(oid):
        user = current_user()
        if not user:
            return jsonify({"error": "未登录"}), 401
        conn = get_conn()
        order = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if order is None:
            return jsonify({"error": "订单不存在"}), 404
        if order["status"] != "delivered":
            return jsonify({"error": f"订单状态 {order['status']} 不可完成"}), 400
        conn.execute("UPDATE orders SET status='completed' WHERE id=?", (oid,))
        conn.commit()
        return jsonify({"ok": True, "status": "completed"})

    # ============ 前端页面（供 Playwright UI 自动化用） ============
    TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

    @app.route("/")
    def page_index():
        return send_from_directory(TEMPLATES, "index.html")

    @app.route("/login")
    def page_login():
        return send_from_directory(TEMPLATES, "login.html")

    @app.route("/cart_page")
    def page_cart():
        return send_from_directory(TEMPLATES, "cart.html")

    @app.route("/orders/<int:oid>")
    def page_order(oid):
        return send_from_directory(TEMPLATES, "order.html")

    return app
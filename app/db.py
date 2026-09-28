# -*- coding: utf-8 -*-
"""数据库：SQLite（零配置），表结构等价 MySQL 关系模型，支持多表联查。

表（对应简历「多表联查 + 数据一致性校验」）：
    users / products / carts / orders / order_items / payments
    addresses（收货地址）/ coupons（优惠券）/ user_coupons（领券记录）

金额字段用 REAL（演示用）；生产建议 DECIMAL 存分。
"""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password TEXT,
    role TEXT DEFAULT 'user'
);
CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    name TEXT,
    price REAL,
    stock INTEGER,
    category TEXT,
    status TEXT DEFAULT 'on_sale'
);
CREATE TABLE IF NOT EXISTS carts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    product_id TEXT,
    quantity INTEGER
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    subtotal REAL,
    freight REAL,
    discount REAL,
    coupon_amount REAL,
    pay_amount REAL,
    status TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER,
    product_id TEXT,
    price REAL,
    quantity INTEGER,
    subtotal REAL
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER,
    type TEXT,
    amount REAL,
    status TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS addresses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    receiver TEXT,
    phone TEXT,
    province TEXT,
    city TEXT,
    detail TEXT,
    is_default INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS coupons (
    id TEXT PRIMARY KEY,
    title TEXT,
    threshold REAL,
    amount REAL,
    stock INTEGER
);
CREATE TABLE IF NOT EXISTS user_coupons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    coupon_id TEXT,
    status TEXT DEFAULT 'unused',
    used_order_id INTEGER
);
"""

SEED_USERS = [
    ("test_user", "123456", "user"),
    ("admin", "admin123", "admin"),
]

SEED_PRODUCTS = [
    ("P1", "手机", 1999.0, 100, "数码", "on_sale"),
    ("P2", "蓝牙耳机", 299.0, 50, "数码", "on_sale"),
    ("P3", "手机壳", 59.0, 150, "配件", "on_sale"),
    ("P4", "数据线", 39.0, 200, "配件", "on_sale"),
    ("P5", "充电器", 99.0, 80, "配件", "on_sale"),
    ("P6", "平板电脑", 2999.0, 30, "数码", "on_sale"),
    ("P7", "智能手表", 899.0, 40, "数码", "on_sale"),
    ("P8", "钢化膜", 19.0, 300, "配件", "on_sale"),
]

SEED_COUPONS = [
    ("C1", "满100减20", 100.0, 20.0, 100),
    ("C2", "满50减5", 50.0, 5.0, 100),
]


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path):
    """建表 + 幂等种子数据（仅在空表时插入），可反复调用。"""
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT INTO users(username, password, role) VALUES(?,?,?)", SEED_USERS)
        if conn.execute("SELECT COUNT(*) c FROM products").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT INTO products(id, name, price, stock, category, status) "
                "VALUES(?,?,?,?,?,?)", SEED_PRODUCTS)
        if conn.execute("SELECT COUNT(*) c FROM coupons").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT INTO coupons(id, title, threshold, amount, stock) VALUES(?,?,?,?,?)",
                SEED_COUPONS)
        conn.commit()
    finally:
        conn.close()
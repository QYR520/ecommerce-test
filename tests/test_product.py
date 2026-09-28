# -*- coding: utf-8 -*-
"""商品域：列表分页/搜索/价格筛选/分类筛选 + 后台改库存（越权拦截）。"""


def test_list_products_pagination(client):
    s, base = client
    d = s.get(base + "/products", params={"page": 1, "size": 3}).json()
    assert d["total"] == 8
    assert len(d["products"]) == 3


def test_list_products_search(client):
    s, base = client
    d = s.get(base + "/products", params={"kw": "耳机"}).json()
    assert d["total"] == 1
    assert d["products"][0]["id"] == "P2"


def test_list_products_filter_category(client):
    s, base = client
    d = s.get(base + "/products", params={"category": "配件"}).json()
    assert d["total"] == 4  # P3 P4 P5 P8


def test_list_products_filter_price(client):
    s, base = client
    d = s.get(base + "/products", params={"min_price": 100, "max_price": 1000}).json()
    assert d["total"] == 2  # P2=299, P7=899


def test_product_detail(client):
    s, base = client
    r = s.get(base + "/products/P1")
    assert r.status_code == 200
    assert r.json()["product"]["name"] == "手机"


def test_product_not_found(client):
    s, base = client
    assert s.get(base + "/products/XX").status_code == 404


def test_admin_update_product_stock(db, admin_client):
    s, base = admin_client
    r = s.put(base + "/products/P3", json={"stock": 999})
    assert r.status_code == 200
    stock = db.execute("SELECT stock FROM products WHERE id='P3'").fetchone()["stock"]
    assert stock == 999


def test_normal_user_cannot_update_product(db, auth_client):
    s, base = auth_client
    r = s.put(base + "/products/P3", json={"stock": 999})
    assert r.status_code == 403
    stock = db.execute("SELECT stock FROM products WHERE id='P3'").fetchone()["stock"]
    assert stock == 150  # 未被修改
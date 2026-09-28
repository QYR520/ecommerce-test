# -*- coding: utf-8 -*-
"""购物车域：加购、查看、改数量、删除、鉴权。"""


def test_cart_add_and_view(auth_client):
    s, base = auth_client
    s.post(base + "/cart", json={"product_id": "P3", "quantity": 2})
    items = s.get(base + "/cart").json()["items"]
    assert len(items) == 1
    assert items[0]["quantity"] == 2


def test_cart_update_quantity(auth_client):
    s, base = auth_client
    cid = s.post(base + "/cart", json={"product_id": "P3", "quantity": 1}).json()["id"]
    s.put(base + f"/cart/{cid}", json={"quantity": 5})
    assert s.get(base + "/cart").json()["items"][0]["quantity"] == 5


def test_cart_delete(auth_client):
    s, base = auth_client
    cid = s.post(base + "/cart", json={"product_id": "P3", "quantity": 1}).json()["id"]
    s.delete(base + f"/cart/{cid}")
    assert len(s.get(base + "/cart").json()["items"]) == 0


def test_cart_requires_auth(client):
    s, base = client
    assert s.post(base + "/cart", json={"product_id": "P3"}).status_code == 401
    assert s.get(base + "/cart").status_code == 401
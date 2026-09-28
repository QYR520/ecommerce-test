# -*- coding: utf-8 -*-
"""用户域：注册 + 收货地址增删改查 + 默认地址唯一。"""


def test_register_ok(client):
    s, base = client
    r = s.post(base + "/register", json={"username": "alice", "password": "123"})
    assert r.status_code == 201


def test_register_duplicate(client):
    s, base = client
    r = s.post(base + "/register", json={"username": "test_user", "password": "123"})
    assert r.status_code == 400


def test_register_missing_fields(client):
    s, base = client
    r = s.post(base + "/register", json={"username": "bob"})
    assert r.status_code == 400


def test_address_crud(auth_client):
    s, base = auth_client
    r = s.post(base + "/address", json={"receiver": "张三", "phone": "13800000000",
                                        "province": "广东", "city": "广州",
                                        "detail": "XX路1号", "is_default": True})
    assert r.status_code == 201
    aid = r.json()["id"]

    data = s.get(base + "/address").json()["addresses"]
    assert len(data) == 1
    assert data[0]["is_default"] == 1

    s.put(base + f"/address/{aid}", json={"receiver": "李四"})
    assert s.get(base + "/address").json()["addresses"][0]["receiver"] == "李四"

    s.delete(base + f"/address/{aid}")
    assert len(s.get(base + "/address").json()["addresses"]) == 0


def test_address_default_unique(auth_client):
    s, base = auth_client
    s.post(base + "/address", json={"receiver": "A", "phone": "1", "province": "p",
                                    "city": "c", "detail": "d", "is_default": True})
    s.post(base + "/address", json={"receiver": "B", "phone": "1", "province": "p",
                                    "city": "c", "detail": "d", "is_default": True})
    data = s.get(base + "/address").json()["addresses"]
    defaults = [a for a in data if a["is_default"] == 1]
    assert len(defaults) == 1


def test_address_requires_auth(client):
    s, base = client
    assert s.get(base + "/address").status_code == 401
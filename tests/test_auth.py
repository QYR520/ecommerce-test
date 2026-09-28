# -*- coding: utf-8 -*-
"""鉴权测试：登录、错误密码、无 token 401、token 过期自动重登。"""
from app import auth as authmod


def test_login_ok(client):
    s, base = client
    r = s.post(base + "/login", json={"username": "test_user", "password": "123456"})
    assert r.status_code == 200
    assert r.json()["token"]


def test_login_wrong_password(client):
    s, base = client
    r = s.post(base + "/login", json={"username": "test_user", "password": "wrong"})
    assert r.status_code == 401


def test_protected_requires_token(client):
    s, base = client
    assert s.get(base + "/cart").status_code == 401
    assert s.get(base + "/order/1").status_code == 401


def test_token_expiry_and_relogin(client):
    s, base = client
    r = s.post(base + "/login", json={"username": "test_user", "password": "123456"})
    token = r.json()["token"]
    s.headers["Authorization"] = "Bearer " + token

    authmod.expire_token(token)  # 模拟 token 过期
    assert s.get(base + "/cart").status_code == 401

    # 自动重登：重新登录拿到新 token 后恢复正常
    r = s.post(base + "/login", json={"username": "test_user", "password": "123456"})
    s.headers["Authorization"] = "Bearer " + r.json()["token"]
    assert s.get(base + "/cart").status_code == 200
# -*- coding: utf-8 -*-
"""下单测试：金额计算（YAML 数据驱动）、空订单、商品不存在、库存不足。"""
import pytest


def test_order_amount(auth_client, amount_case):
    s, base = auth_client
    r = s.post(base + "/order", json={"items": amount_case["items"]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["subtotal"] == pytest.approx(amount_case["subtotal"])
    assert data["freight"] == pytest.approx(amount_case["freight"])
    assert data["discount"] == pytest.approx(amount_case["discount"])
    assert data["pay_amount"] == pytest.approx(amount_case["pay"])


def test_order_empty(auth_client):
    s, base = auth_client
    r = s.post(base + "/order", json={"items": []})
    assert r.status_code == 400


def test_order_not_exist_product(auth_client):
    s, base = auth_client
    r = s.post(base + "/order", json={"items": [{"product_id": "XX", "quantity": 1}]})
    assert r.status_code == 400


def test_order_insufficient_stock(auth_client):
    s, base = auth_client
    # P4 数据线库存 200，买 201 应报库存不足
    r = s.post(base + "/order", json={"items": [{"product_id": "P4", "quantity": 201}]})
    assert r.status_code == 400


def test_order_requires_auth(client):
    s, base = client
    r = s.post(base + "/order", json={"items": [{"product_id": "P3", "quantity": 1}]})
    assert r.status_code == 401
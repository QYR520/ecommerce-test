# -*- coding: utf-8 -*-
"""优惠券域：领券、我的券、用券金额叠加、门槛校验、重复用券拦截。"""
import pytest


def test_claim_coupon(auth_client):
    s, base = auth_client
    assert s.post(base + "/coupons/C1/claim").status_code == 200


def test_list_my_coupons(auth_client):
    s, base = auth_client
    s.post(base + "/coupons/C1/claim")
    data = s.get(base + "/coupons").json()["coupons"]
    assert len(data) == 1
    assert data[0]["coupon_id"] == "C1"


def test_order_with_coupon_applied(auth_client):
    s, base = auth_client
    s.post(base + "/coupons/C1/claim")
    r = s.post(base + "/order",
               json={"items": [{"product_id": "P2", "quantity": 1}], "coupon_id": "C1"})
    assert r.status_code == 200
    d = r.json()
    assert d["coupon_amount"] == 20.0
    assert d["pay_amount"] == pytest.approx(299 - 10 - 20)


def test_order_coupon_below_threshold(auth_client):
    s, base = auth_client
    s.post(base + "/coupons/C1/claim")  # C1 门槛满100
    r = s.post(base + "/order",
               json={"items": [{"product_id": "P3", "quantity": 1}], "coupon_id": "C1"})  # 59
    assert r.status_code == 400


def test_order_without_claiming_coupon(auth_client):
    s, base = auth_client
    r = s.post(base + "/order",
               json={"items": [{"product_id": "P2", "quantity": 1}], "coupon_id": "C1"})
    assert r.status_code == 400


def test_coupon_used_only_once(auth_client):
    s, base = auth_client
    s.post(base + "/coupons/C1/claim")
    s.post(base + "/order", json={"items": [{"product_id": "P2", "quantity": 1}],
                                  "coupon_id": "C1"})
    # 第二次用同一张券应失败（已 used）
    r = s.post(base + "/order", json={"items": [{"product_id": "P2", "quantity": 2}],
                                      "coupon_id": "C1"})
    assert r.status_code == 400
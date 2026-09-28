# -*- coding: utf-8 -*-
"""「页面 ↔ 数据库」数据对账测试（核心，对应简历里的数据一致性校验）：

把接口返回给页面展示的数据，与直接查数据库拿到的真实数据逐项比对：
金额、订单明细、支付/退款流水、库存、优惠券。若缓存没被正确失效，
接口库存会与数据库不一致，test_stock_cache_consistency 抓这个 bug
（config.yaml 里 flaw.stale_cache 改 true 再跑，该用例会红）。
"""
import pytest


def test_order_money_consistency(db, auth_client):
    s, base = auth_client
    r = s.post(base + "/order", json={"items": [{"product_id": "P3", "quantity": 2}]})
    assert r.status_code == 200
    order_id = r.json()["order_id"]

    # ① 接口展示金额 == 数据库订单金额
    order_db = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    assert r.json()["subtotal"] == pytest.approx(order_db["subtotal"])
    assert r.json()["pay_amount"] == pytest.approx(order_db["pay_amount"])

    # ② 订单明细 subtotal 合计 == 订单 subtotal（多表联查）
    joined = db.execute(
        "SELECT SUM(oi.subtotal) s FROM orders o JOIN order_items oi ON oi.order_id=o.id "
        "WHERE o.id=?", (order_id,)).fetchone()
    assert joined["s"] == pytest.approx(order_db["subtotal"])

    # ③ 库存按数量正确扣减
    stock_after = db.execute("SELECT stock FROM products WHERE id='P3'").fetchone()["stock"]
    assert stock_after == 150 - 2


def test_pay_consistency(db, auth_client):
    s, base = auth_client
    order_id = s.post(base + "/order",
                      json={"items": [{"product_id": "P2", "quantity": 1}]}).json()["order_id"]
    s.post(base + f"/order/{order_id}/pay")

    order_db = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    assert order_db["status"] == "paid"
    pay_db = db.execute("SELECT * FROM payments WHERE order_id=? AND type='pay'",
                        (order_id,)).fetchone()
    assert pay_db["amount"] == pytest.approx(order_db["pay_amount"])

    detail = s.get(base + f"/order/{order_id}").json()
    assert detail["order"]["status"] == "paid"
    assert detail["payments"][0]["amount"] == pytest.approx(order_db["pay_amount"])


def test_stock_cache_consistency(db, auth_client):
    """页面(接口)展示库存 与 数据库库存 必须一致；缓存失效错时抓出不一致。"""
    s, base = auth_client
    first = s.get(base + "/products/P3").json()["product"]
    before_db = db.execute("SELECT stock FROM products WHERE id='P3'").fetchone()["stock"]
    assert first["stock"] == before_db

    r = s.post(base + "/order", json={"items": [{"product_id": "P3", "quantity": 2}]})
    assert r.status_code == 200
    after_db = db.execute("SELECT stock FROM products WHERE id='P3'").fetchone()["stock"]
    assert after_db == before_db - 2

    api = s.get(base + "/products/P3").json()["product"]
    assert api["stock"] == after_db


def test_cancel_restore_stock_consistency(db, auth_client):
    s, base = auth_client
    order_id = s.post(base + "/order",
                      json={"items": [{"product_id": "P3", "quantity": 2}]}).json()["order_id"]
    before = db.execute("SELECT stock FROM products WHERE id='P3'").fetchone()["stock"]
    assert before == 148  # 下单已扣 2
    s.post(base + f"/order/{order_id}/cancel")

    order_db = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    assert order_db["status"] == "cancelled"
    after = db.execute("SELECT stock FROM products WHERE id='P3'").fetchone()["stock"]
    assert after == before + 2  # 取消回滚库存


def test_refund_restore_stock_consistency(db, auth_client):
    s, base = auth_client
    order_id = s.post(base + "/order",
                      json={"items": [{"product_id": "P4", "quantity": 1}]}).json()["order_id"]
    s.post(base + f"/order/{order_id}/pay")
    before_refund = db.execute("SELECT stock FROM products WHERE id='P4'").fetchone()["stock"]
    s.post(base + f"/order/{order_id}/refund")

    order_db = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    assert order_db["status"] == "refunded"
    after = db.execute("SELECT stock FROM products WHERE id='P4'").fetchone()["stock"]
    assert after == before_refund + 1  # 退款回滚库存

    refund_db = db.execute("SELECT * FROM payments WHERE order_id=? AND type='refund'",
                           (order_id,)).fetchone()
    assert refund_db["amount"] == pytest.approx(-order_db["pay_amount"])


def test_coupon_consistency(db, auth_client):
    s, base = auth_client
    s.post(base + "/coupons/C1/claim")
    r = s.post(base + "/order",
               json={"items": [{"product_id": "P2", "quantity": 1}], "coupon_id": "C1"})
    assert r.status_code == 200
    data = r.json()
    # P2=299: 满减10、券满100减20 → 实付 269
    assert data["discount"] == 10.0
    assert data["coupon_amount"] == 20.0
    assert data["pay_amount"] == pytest.approx(299 - 10 - 20)

    order_db = db.execute("SELECT * FROM orders WHERE id=?", (data["order_id"],)).fetchone()
    assert order_db["coupon_amount"] == 20.0
    assert order_db["pay_amount"] == pytest.approx(269.0)
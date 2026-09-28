# -*- coding: utf-8 -*-
"""订单状态机域：支付/取消/退款 + 非法状态流转拦截 + 发货越权拦截。"""


def _mk_order(base, s):
    return s.post(base + "/order",
                  json={"items": [{"product_id": "P3", "quantity": 2}]}).json()["order_id"]


def test_cancel_unpaid(db, auth_client):
    s, base = auth_client
    oid = _mk_order(base, s)
    assert s.post(base + f"/order/{oid}/cancel").status_code == 200
    assert db.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()["status"] == "cancelled"


def test_refund_paid(db, auth_client):
    s, base = auth_client
    oid = _mk_order(base, s)
    s.post(base + f"/order/{oid}/pay")
    assert s.post(base + f"/order/{oid}/refund").status_code == 200
    assert db.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()["status"] == "refunded"


def test_cancel_paid_rejected(auth_client):
    s, base = auth_client
    oid = _mk_order(base, s)
    s.post(base + f"/order/{oid}/pay")
    assert s.post(base + f"/order/{oid}/cancel").status_code == 400


def test_refund_unpaid_rejected(auth_client):
    s, base = auth_client
    oid = _mk_order(base, s)
    assert s.post(base + f"/order/{oid}/refund").status_code == 400


def test_pay_cancelled_rejected(auth_client):
    s, base = auth_client
    oid = _mk_order(base, s)
    s.post(base + f"/order/{oid}/cancel")
    assert s.post(base + f"/order/{oid}/pay").status_code == 400


def test_complete_before_deliver_rejected(auth_client):
    s, base = auth_client
    oid = _mk_order(base, s)
    s.post(base + f"/order/{oid}/pay")
    assert s.post(base + f"/order/{oid}/complete").status_code == 400  # 未发货未收货


def test_ship_requires_admin(auth_client, admin_client):
    s, base = auth_client
    oid = _mk_order(base, s)
    s.post(base + f"/order/{oid}/pay")
    assert s.post(base + f"/order/{oid}/ship").status_code == 403  # 普通用户越权
    a, ab = admin_client
    assert a.post(ab + f"/order/{oid}/ship").status_code == 200  # admin 可发货


def test_state_machine_flow(db, auth_client, admin_client):
    s, base = auth_client
    oid = _mk_order(base, s)
    s.post(base + f"/order/{oid}/pay")
    a, ab = admin_client
    a.post(ab + f"/order/{oid}/ship")
    s.post(base + f"/order/{oid}/deliver")
    s.post(base + f"/order/{oid}/complete")
    status = db.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()["status"]
    assert status == "completed"
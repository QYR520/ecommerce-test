# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import threading

import pytest
import requests
import yaml
from werkzeug.serving import make_server

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db as dbmod
from app.main import create_app

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture()
def server():
    """每个用例起一个独立的被测系统（独立临时库 + 独立缓存），互不污染。"""
    with open(os.path.join(BASE, "config.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    cfg["app"]["db_path"] = db_path
    dbmod.init_db(db_path)
    app = create_app(cfg)
    srv = make_server("127.0.0.1", 0, app)
    base_url = f"http://127.0.0.1:{srv.server_port}"
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield {"base_url": base_url, "db_path": db_path, "cfg": cfg, "server": srv}
    finally:
        srv.shutdown()
        os.remove(db_path)


@pytest.fixture()
def db(server):
    """直连被测系统的数据库，供「页面 ↔ 数据库」对账用。"""
    conn = dbmod.connect(server["db_path"])
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture()
def client(server):
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"
    return s, server["base_url"]


@pytest.fixture()
def auth_client(server):
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"
    r = s.post(server["base_url"] + "/login",
               json={"username": "test_user", "password": "123456"})
    assert r.status_code == 200, r.text
    s.headers["Authorization"] = "Bearer " + r.json()["token"]
    return s, server["base_url"]


@pytest.fixture()
def admin_client(server):
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"
    r = s.post(server["base_url"] + "/login",
               json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    s.headers["Authorization"] = "Bearer " + r.json()["token"]
    return s, server["base_url"]


def _load_amount_cases():
    with open(os.path.join(BASE, "data", "cases.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)["amount_cases"]


@pytest.fixture(params=_load_amount_cases(), ids=lambda c: c["name"])
def amount_case(request):
    return request.param
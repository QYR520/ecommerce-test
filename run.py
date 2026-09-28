# -*- coding: utf-8 -*-
"""启动电商被测系统。

用法（在 shop 目录下）：
    python run.py
    然后浏览器/Postman 访问 http://127.0.0.1:5000

接口速览：
    POST /login                      登录拿 token
    GET  /products/<id>              查商品（走缓存）
    POST /cart                       加购（需 token）
    GET  /cart                       看购物车
    POST /order                      下单（{"items":[{"product_id","quantity"}]}）
    POST /order/<id>/pay             支付
    GET  /order/<id>                 订单查询
"""
import os

import yaml

from app import db as dbmod
from app.main import create_app

BASE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(BASE, "config.yaml"), encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

db_path = cfg["app"]["db_path"]
if not os.path.isabs(db_path):
    db_path = os.path.join(BASE, db_path)
cfg["app"]["db_path"] = db_path

dbmod.init_db(db_path)
app = create_app(cfg)

if __name__ == "__main__":
    print(f"电商被测系统启动：http://{cfg['app']['host']}:{cfg['app']['port']}")
    print(f"数据库：{db_path}")
    print("缓存开关 stale_cache =", cfg["app"]["flaw"]["stale_cache"])
    app.run(host=cfg["app"]["host"], port=cfg["app"]["port"], debug=True)
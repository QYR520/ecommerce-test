# -*- coding: utf-8 -*-
"""登录鉴权：签发 token + 校验 token（带过期）。

生产环境用 JWT，这里用「内存 token 表 + 过期时间」等价模拟，
便于自动化测试演示「token 过期 → 401 → 自动重登」。
"""
import time
import uuid

# token -> {"username": ..., "expire_at": ...}
TOKENS = {}


def issue_token(username, ttl):
    token = uuid.uuid4().hex
    TOKENS[token] = {"username": username, "expire_at": time.time() + ttl}
    return token


def validate_token(token):
    rec = TOKENS.get(token)
    if rec is None:
        return None
    if time.time() > rec["expire_at"]:
        TOKENS.pop(token, None)
        return None
    return rec["username"]


def expire_token(token):
    """让指定 token 立刻过期（测试用）。"""
    if token in TOKENS:
        TOKENS[token]["expire_at"] = 0


def revoke_token(token):
    TOKENS.pop(token, None)
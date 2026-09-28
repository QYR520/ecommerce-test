# -*- coding: utf-8 -*-
"""内存缓存层：模拟 Redis 的 get/set/delete + 过期（TTL）。

生产环境这里是 Redis，本项目用内存实现，API 语义保持与 Redis 一致，
方便演示「缓存与数据库不一致」：缓存里的旧数据没被失效时，就会返回
与数据库不同的值——这正是自动化「页面 ↔ 数据库」对账要抓的 bug。
"""
import time


class Cache:
    def __init__(self):
        self._data = {}

    def get(self, key):
        item = self._data.get(key)
        if item is None:
            return None
        value, expire_at = item
        if expire_at is not None and time.time() > expire_at:
            self._data.pop(key, None)
            return None
        return value

    def set(self, key, value, ttl=None):
        expire_at = time.time() + ttl if ttl else None
        self._data[key] = (value, expire_at)

    def delete(self, key):
        self._data.pop(key, None)

    def clear(self):
        self._data.clear()
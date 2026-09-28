# -*- coding: utf-8 -*-
import os
import sys

# 让 pytest 运行在 shop 目录时能把 app 包导入进来
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
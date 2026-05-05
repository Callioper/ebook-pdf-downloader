# !/usr/bin/env python3
# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2024 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""
常量

Authors: xiangyiqing(xiangyiqing@baidu.com)
Date:    2024/3/26
"""
import os

CACHE_HONE = os.getenv("AISTUDIO_CACHE_HOME", default=os.getenv("HOME"))

# token
AUTH_DIR = f'{CACHE_HONE}/.cache/aistudio/.auth'
AUTH_TOKEN_FILE = f'{AUTH_DIR}/token'

# log level
LOG_DIR = f'{CACHE_HONE}/.cache/aistudio/.log'
LOG_LEVEL_FILE = f'{LOG_DIR}/level'

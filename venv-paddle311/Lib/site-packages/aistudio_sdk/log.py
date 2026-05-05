# !/usr/bin/env python3
# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2023 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""
本文件实现了sdk日志的功能

Authors: xiangyiqing(xiangyiqing@baidu.com)
Date:    2023/07/24
"""
import os
import logging
from aistudio_sdk import config
from aistudio_sdk.constant.const import LOG_LEVEL_FILE

__all__ = [
    "info",
    "debug",
    "warn",
    "error",
    "get_level",
]


def get_level():
    """
    三种设置日志级别的方式，优先级从高到低：
    1、执行前, 设置环境变量 AISTUDIO_LOG 的值
    2、执行前, 设置level值到文件 ${AISTUDIO_CACHE_HOME}/.cache/aistudio/.log/level
    3、执行前, 设置config文件中DEFAULT_LOG_LEVEL的值
    """
    if "AISTUDIO_LOG" in os.environ:
        return os.getenv("AISTUDIO_LOG")
    
    if os.path.exists(LOG_LEVEL_FILE):
        try:
            with open(LOG_LEVEL_FILE, 'r') as file:
                return file.read().strip()
        except:
            pass
        
    return config.DEFAULT_LOG_LEVEL


# 初始化
logger = logging.getLogger("aistudio_sdk")
level = get_level()
if level == "debug":
    logger.setLevel(logging.DEBUG)
elif level == 'critical':
    logger.setLevel(logging.CRITICAL)
else:
    logger.setLevel(logging.INFO)

# 日志输出格式
formatter = logging.Formatter(fmt='%(levelname)-8s %(asctime)s %(process)-5s %(filename)s[line:%(lineno)d] %(message)s')

# 控制台输出
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

def cli_log():
    """
    cli log格式沿用原有的
    """
    console_handler.setFormatter(logging.Formatter(fmt='%(message)s'))



def info(msg):
    """log evel: INFO"""
    logger.log(logging.INFO, msg)

def debug(msg):
    """log evel: DEBUG"""
    logger.log(logging.DEBUG, f"[DEBUG] {msg}")

def warn(msg):
    """log evel: WARN"""
    logger.log(logging.WARN, msg)

def error(msg):
    """log evel: ERROR"""
    logger.log(logging.ERROR, msg)

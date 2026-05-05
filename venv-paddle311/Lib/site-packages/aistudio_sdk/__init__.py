# !/usr/bin/env python3
# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2023 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""
Authors: xiangyiqing(xiangyiqing@baidu.com)
Date:    2023/07/24
"""
from aistudio_sdk.constant.version import VERSION
from aistudio_sdk.log import get_level
from aistudio_sdk import hub

log_level = get_level()

__version__ = VERSION
__all__ = [
    "hub",
]

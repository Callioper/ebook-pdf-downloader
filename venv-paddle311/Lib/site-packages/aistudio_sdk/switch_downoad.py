# !/usr/bin/env python3
# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2025 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""
本文件实现了sdk cdn下载的功能

Authors: zhaoqingtao(zhaoqingtaog@baidu.com)
Date:    2025/05/23
"""
import re
import os
import copy
import requests
from urllib.parse import urlparse, urlunparse
from aistudio_sdk import config


def switch_cdn(url, headers, get_headers):
    """
    switch to cdn host
    """
    headers_range = {} if headers is None else copy.deepcopy(headers)
    headers_range['Range'] = f'bytes=0-1'
    response = requests.get(url, headers=headers_range, stream=True,
                            timeout=config.CONNECTION_TIMEOUT, allow_redirects=False)
    if response.status_code == 307 and response.headers.get("Location").startswith('/'):
        url_parsed = urlparse(url)
        new_parts = url_parsed._replace(path=response.headers.get("Location"), params='', query='', fragment='')
        response = requests.get(urlunparse(new_parts), headers=headers_range, stream=True,
                                timeout=config.CONNECTION_TIMEOUT, allow_redirects=False)
    match = re.search(r"/repos/([^/]+)/", url)
    paddle_repo = False
    if match:
        repo_name = match.group(1)
        if "paddlepaddle" == repo_name.lower() or "baidu" == repo_name.lower():
            paddle_repo = True
    if response.is_redirect:
        redirect_url = response.headers.get("Location")
        parsed = urlparse(redirect_url)
        cdn_host = os.getenv("STUDIO_CDN_HOST")
        if cdn_host:
            new_host = cdn_host
        elif paddle_repo:
            new_host = config.UNLIMITED_HOST
        else:
            new_host = config.LIMITED_HOST
        parsed = parsed._replace(netloc=new_host)
        new_url = urlunparse(parsed)
        get_headers.pop("Authorization", None)
        return new_url
    return url
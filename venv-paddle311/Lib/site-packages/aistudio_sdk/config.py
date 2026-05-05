#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2023 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""
config

Authors: xiangyiqing(xiangyiqing@baidu.com)
Date:    2023/07/24
"""
import os

ENV = os.environ.get("CURRENT_ENV", "online")  # sandbox or online
if ENV == "":
    ENV = "online"

# Set to either 'debug' or 'info', controls console logging

DEFAULT_LOG_LEVEL = "info"
CONNECTION_TIMEOUT = 30     # second
CONNECTION_RETRY_TIMES = 1
CONNECTION_TIMEOUT_UPLOAD = 60 * 60     # second
CONNECTION_TIMEOUT_DOWNLOAD = 60 * 60     # second

COMMON_FILE_SIZE_LIMIT = 5 * 1024 * 1024  # 5M
LFS_FILE_SIZE_LIMIT = 50 * 1024 * 1024 * 1024 # 50G
LFS_FILE_SIZE_LIMIT_PUT = 5 * 1024 * 1024 * 1024 # 5G

TOKEN_FILE = os.path.expanduser("~/.aistudio_token")

# host
if ENV == "sandbox":
    STUDIO_GIT_HOST_DEFAULT = "http://sandbox-git.aistudio.baidu.com"
    SALT = "2974edcb4e83f7965c3c6d5720e5f49f"
    STUDIO_MODEL_API_URL_PREFIX_DEFAULT = "https://sandbox-aistudio.baidu.com"
    STUDIO_CDN_HOST_DEFAULT= "gitea-sandbox.cdn.bcebos.com"
    UNLIMITED_HOST = "gitea-sandbox.cdn.bcebos.com"
    LIMITED_HOST = "gitea-sandbox.cdn.bcebos.com"
elif ENV == "online":
    STUDIO_GIT_HOST_DEFAULT = "https://git.aistudio.baidu.com"
    SALT = "f822a915a3785ef9c35bfa0d9a5bcc62"
    STUDIO_MODEL_API_URL_PREFIX_DEFAULT = "https://aistudio.baidu.com"
    STUDIO_CDN_HOST_DEFAULT = "gitea-cdn.baidu-tech.com"
    UNLIMITED_HOST = "gitea-cdn.baidu-tech.com"
    LIMITED_HOST = "bj-gitea-online.cdn.bcebos.com"

else:
    raise ValueError("Invalid ENV: {}".format(ENV))

# Hub API
HUB_URL = "/modelcenter/v2/models/sdk/add"
HUB_URL_VISIBLE_CHECK = "/modelcenter/v2/models/sdk/checkPermit"
APP_SERVICE_URL = "/serving/web/highapp/sdk/create"
BLACK_LIST_URL = "/modelcenter/v2/models/getSuffixBlackList"
README_CHECK_URL = "/modelcenter/v2/models/checkYaml"

# PP Pipeline API
MOUNT_DATASET_LIMIT = 3
PIPELINE_CODE_SIZE_LIMIT = 50 * 1024 * 1024     # bytes
PIPELINE_CREATE_URL = "/paddlex/v3/pipelines/sdk/create"
PIPELINE_CREATE_CALLBACK_URL = "/paddlex/v3/pipelines/sdk/create/callback"
PIPELINE_BOSACL_URL = "/paddlex/v3/file/api/bosacl"
PIPELINE_QUERY_URL = "/paddlex/v3/pipelines/sdk/list"
PIPELINE_STOP_URL = "/paddlex/v3/pipelines/sdk/stop"
REPO_TYPE_MODEL = "model"
REPO_TYPE_DATASET = "dataset"
REPO_TYPE_SUPPORT = [REPO_TYPE_MODEL, REPO_TYPE_DATASET]
MODEL_ID_SEPARATOR = "/"
DEFAULT_AISTUDIO_GROUP = "demo"
TEMPORARY_FOLDER_NAME = "._tmp"
FILE_HASH = "Sha256"
AISTUDIO_ENABLE_DEFAULT_HASH_VALIDATION = "AISTUDIO_ENABLE_DEFAULT_HASH_VALIDATION"
DEFAULT_REPOSITORY_REVISION = 'master'
DEFAULT_DATASET_REVISION = "master"
DEFAULT_MODEL_REVISION = "master"
AISTUDIO_PARALLEL_DOWNLOAD_THRESHOLD_MB = int(
    os.environ.get('AISTUDIO_PARALLEL_DOWNLOAD_THRESHOLD_MB', 160))
AISTUDIO_DOWNLOAD_PARALLELS = int(
    os.environ.get('AISTUDIO_DOWNLOAD_PARALLELS', 6))

API_FILE_DOWNLOAD_RETRY_TIMES = 3
API_FILE_DOWNLOAD_TIMEOUT = 60
API_FILE_DOWNLOAD_CHUNK_SIZE = 1024 * 1024 * 1
DEFAULT_MAX_WORKERS = 3
CACHE_KEY = "last_commit_sha"

UPLOAD_MAX_FILE_COUNT = int(os.environ.get('UPLOAD_MAX_FILE_COUNT', 100000))
UPLOAD_MAX_FILE_COUNT_IN_DIR = int(os.environ.get('UPLOAD_MAX_FILE_COUNT_IN_DIR', 50000))
UPLOAD_MAX_FILE_SIZE = int(os.environ.get('UPLOAD_MAX_FILE_SIZE', 100 * 1024 ** 3))
UPLOAD_SIZE_THRESHOLD_TO_ENFORCE_LFS = int(
    os.environ.get('UPLOAD_SIZE_THRESHOLD_TO_ENFORCE_LFS', 5 * 1024 * 1024))
UPLOAD_NORMAL_FILE_SIZE_TOTAL_LIMIT = int(
    os.environ.get('UPLOAD_NORMAL_FILE_SIZE_TOTAL_LIMIT', 500 * 1024 * 1024))
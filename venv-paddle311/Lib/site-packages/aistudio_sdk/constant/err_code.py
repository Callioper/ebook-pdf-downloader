#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2023 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""
error code

Authors: linyichong(linyichong@baidu.com)
Date:    2023/09/05
"""
from types import DynamicClassAttribute
from enum import Enum


class ErrorEnum(Enum):
    """
    usage:
        from aistudio_sdk.constant.err_code import ErrorEnum

        print(ErrorEnum.SUCCESS.code)
        print(ErrorEnum.SUCCESS.message)
    """
    
    SUCCESS = (0, "成功")
    
    # SDK Error
    INTERNAL_ERROR = (10000, "SDK Internal Error")
    PARAMS_INVALID = (10001, "参数无效")
    TOKEN_IS_EMPTY = (10002, "未设置Token")
    REPO_ALREADY_EXIST = (10003, "repo已经存在, 不能重复创建")
    FILE_NOT_FOUND = (10004, "文件不存在")
    UPLOAD_FILE_NOT_FOUND = (10005, "找不到要上传的本地文件")
    FILE_TOO_LARGE = (10006, "文件过大")
    UPLOAD_FOLDER_NO_SUPPORT = (10007, "不支持上传文件夹")
    NEED_FOLDER = (10008, "仅支持文件夹")
    CMDLINE_PARSE_ERROR = (10009, "命令行解析出错")
    UPLOAD_FILE_FORBIDDEN = (10010, "文件类型禁止上传")

    # AI Studio Error
    AISTUDIO_ERROR = (11000, "AI Studio Internal Error")
    AISTUDIO_CREATE_REPO_FAILED = (11001, "创建仓库失败")
    AISTUDIO_NO_REPO_READ_AUTH = (11002, "没有仓库查看权限")
    REQUEST_CREATE_PIPELINE_FAILED = (11003, "创建产线参数校验请求失败")
    REQUEST_BOSACL_FAILED = (11004, "BOS AK/SK申请失败")
    REQUEST_CREATE_PIPELINE_CALLBACK_FAILED = (11005, "创建产线回调请求失败")
    REQUEST_QUERY_PIPELINE_FAILED = (11006, "查询产线请求失败")
    REQUEST_STOP_PIPELINE_FAILED = (11007, "停止产线请求失败")
    DATASET_CREATION_FAILED = (11008, "数据集创建失败")

    # Gitea Error
    GITEA_FAILED = (12000, "Gitea Error")
    GITEA_GET_FILEINFO_FAILED = (12001, "获取文件信息失败")
    GITEA_DOWNLOAD_FILE_FAILED = (12002, "下载文件失败")
    GITEA_UPLOAD_FILE_FAILED = (12003, "上传文件失败")

    # BOS Error
    BOS_ERROR = (13000, "BOS Error")
    BOS_UPLOAD_FAILED = (13001, "BOS上传失败")
    BOS_LIST_FILES_FAILED = (13002, "BOS列出文件失败")
    BOS_DOWNLOAD_FAILED = (13003, "BOS下载失败")


    @DynamicClassAttribute
    def code(self):
        """error code"""
        return self._value_[0]
    
    @DynamicClassAttribute
    def message(self):
        """error message"""
        return self._value_[1]

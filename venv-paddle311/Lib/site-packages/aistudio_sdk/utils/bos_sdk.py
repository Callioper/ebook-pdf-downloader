# !/usr/bin/env python3
# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2023 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""
本文件实现了对bos的封装, 首先安装 bce-python-sdk

Authors: suoyi@baidu.com
Date:    2024/01/03

"""
from aistudio_sdk import log
import os
from baidubce.bce_client_configuration import BceClientConfiguration
from baidubce.auth.bce_credentials import BceCredentials
from baidubce.services.bos.bos_client import BosClient, BceClientError
from baidubce import utils
from typing import List
RETRY_TIMES = int(os.environ.get("AISTUDIO_BOS_RETRY_TIMES", 10))

class MyBosClient(BosClient):
    """
    重写BosClient的_upload方法，增加重试功能
    """

    def _upload_task(self, bucket_name, object_key, upload_id,
                     part_number, part_size, file_name, offset, part_list, uploadTaskHandle,
                     progress_callback=None, traffic_limit=None):
        if uploadTaskHandle.is_cancel():
            log.debug(f"upload task canceled with partNumber={part_number}!")
            return
        success = False

        for i in range(RETRY_TIMES):
            try:
                response = self.upload_part_from_file(bucket_name, object_key, upload_id,
                                                      part_number, part_size, file_name, offset,
                                                      progress_callback=progress_callback,
                                                      traffic_limit=traffic_limit)
                part_list.append({
                    "partNumber": part_number,
                    "eTag": response.metadata.etag
                })
                log.debug(f"upload task success with partNumber={part_number}!")
                success = True
                break
            except Exception as e:
                log.error(f"upload task failed with partNumber={part_number}!")
                log.debug(e)
                log.error(f"重试第{i + 1}次")

        if not success:
            uploadTaskHandle.cancel()
            log.error(f"upload task failed with partNumber={part_number}!已取消上传")
            raise BceClientError(f"upload task failed with partNumber={part_number}!")

    def put_super_obejct_from_file(self, bucket_name, key, file_name, chunk_size=5,
                                   thread_num=None,
                                   uploadTaskHandle=None,
                                   content_type=None,
                                   storage_class=None,
                                   user_headers=None,
                                   progress_callback=None,
                                   traffic_limit=None,
                                   config=None):
        """调用原始的 put_super_obejct_from_file，但这里会使用上面定义的 _upload_task"""
        return super().put_super_obejct_from_file(bucket_name, key, file_name, chunk_size,
                                                  thread_num, uploadTaskHandle,
                                                  content_type, storage_class,
                                                  user_headers, progress_callback,
                                                  traffic_limit, config)

    def _compute_service_id(self):
        """需要覆盖父类的方法，否则会报错"""
        return "bos"

def sts_client(bos_host, sts_ak, sts_sk, session_token) -> MyBosClient:
    """
    获取sts client
    """

    bos_client = MyBosClient(BceClientConfiguration(
                                credentials=BceCredentials(sts_ak, sts_sk),
                                endpoint=bos_host,
                                security_token=session_token))
    return bos_client


def upload_files(bos_client: MyBosClient, bucket: str, files: List[str], key_prefix=""):
    """
    上传文件
    key_prefix: 上传文件的前缀
    """
    for file in files:
        bos_client.put_super_obejct_from_file(bucket, key_prefix + file, file, chunk_size=5, thread_num=None)

def upload_file(bos_client: MyBosClient, bucket: str, file, key):
    """
    上传文件
    key: 存储路径
    """

    return bos_client.put_object_from_file(bucket, key, str(file))


def upload_super_file(bos_client: MyBosClient, bucket: str, file, key):
    """
    上传文件
    key: 存储路径
    """
    chunk_size = int(os.environ.get("AISTUDIO_UPLOAD_CHUNK_SIZE_MB", 5))
    thread_num = os.environ.get("AISTUDIO_UPLOAD_THREAD_NUM", None)
    if thread_num:
        thread_num = int(thread_num)
    res = bos_client.put_super_obejct_from_file(bucket, key, str(file),
                                                 chunk_size=chunk_size,
                                                 thread_num=thread_num,
                                                 progress_callback=None)
    if not res:
        log.error("upload file failed: 已经取消或者上传失败，如果上传失败，"
                      "请配置环境变量 AISTUDIO_UPLOAD_CHUNK_SIZE_MB (int类型，默认为5，单位MB)，减小分块大小后重试，"
                      "例如：export AISTUDIO_UPLOAD_CHUNK_SIZE_MB=3 后重新执行"
                      "如果带宽过小，需要配置环境变量 AISTUDIO_UPLOAD_THREAD_NUM 减少线程数，防止部分分块上传超时，"
                      "例如：export AISTUDIO_UPLOAD_THREAD_NUM=1 后重新执行")
    return res

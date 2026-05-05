# !/usr/bin/env python3
# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2024 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""
本文件实现了请求产线任务

Authors: suoyi@baidu.com
Date:    2024/7/20
"""
import json
import requests
from aistudio_sdk import config, log
from baidubce.bce_client_configuration import BceClientConfiguration
from baidubce.auth.bce_credentials import BceCredentials
from baidubce.services.bos.bos_client import BosClient
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
from urllib.parse import urljoin
from pathlib import Path
import re


class RequestDatasetException(Exception):
    """
    exception for requesting dataset server
    """
    pass
MAX_WORKERS_FILE = os.path.expanduser("~/.download_max_workers")

# 默认线程数
DEFAULT_MAX_WORKERS = 6


def get_max_workers():
    """max download worker"""
    try:
        with open(MAX_WORKERS_FILE, 'r') as f:
            return int(f.read().strip())
    except (Exception) as e:
        return DEFAULT_MAX_WORKERS


def post_request_get_file_ids(url, datasetId):
    """file info"""
    data = {"datasetId": datasetId}
    response = requests.post(url, data=data)
    response.raise_for_status()
    result = response.json().get("result", {})
    file_ids = result.get("fileIds", [])
    return file_ids


def load_token():
    """
    load
    """
    if not os.path.exists(config.TOKEN_FILE):
        return None
    with open(config.TOKEN_FILE, 'r') as f:
        return f.read().strip()


def _header_fill(params=None, token=''):
    """
    填充header
    """
    if token:
        auth = f'{token}'
    else:
        auth = f'{os.getenv("AISTUDIO_ACCESS_TOKEN", default="")}'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': auth
    }
    if params:
        headers.update(params)
    return headers


def get_file_url(host, datasetId, fileId):
    """get url"""
    path = f"/llm/files/datasets/{datasetId}/file/{fileId}/download"
    url = urljoin(host, path)
    token = load_token()
    print(token)
    if token is not None:
        headers = _header_fill(token=token)
    else:
        headers = _header_fill()
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    print(response.json())
    return response.json()["result"]["fileUrl"]

CHUNK_SIZE = 160 * 1024 * 1024  # 160MB


def parse_filename_from_cd(cd_header):
    """filename"""
    if not cd_header:
        return None
    fname = re.findall('filename="?([^";]+)"?', cd_header)
    return fname[0] if fname else None


def get_file_info(file_url):
    """获取文件大小和文件名"""
    r = requests.head(file_url, allow_redirects=True)
    r.raise_for_status()
    file_size = int(r.headers.get('Content-Length', 0))
    cd = r.headers.get("Content-Disposition", "")
    filename = parse_filename_from_cd(cd)
    if not filename:
        filename = os.path.basename(file_url.split("?")[0])
    return file_size, filename


def download_chunk(file_url, start, end, local_path, pbar, lock):
    """download"""
    headers = {'Range': f"bytes={start}-{end}"}
    response = requests.get(file_url, headers=headers, stream=True)
    response.raise_for_status()

    with open(local_path, 'rb+') as f:
        f.seek(start)
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                with lock:
                    pbar.update(len(chunk))


def download_file_multithreaded(file_url, local_dir, max_workers=None):
    """multi thread"""
    if max_workers is None:
        max_workers = get_max_workers()

    # Step 1: Get file size and filename
    file_size, filename = get_file_info(file_url)
    local_path = os.path.join(local_dir, filename)
    os.makedirs(local_dir, exist_ok=True)

    # Step 2: Create empty file if not exists
    if not os.path.exists(local_path):
        with open(local_path, 'wb') as f:
            f.truncate(file_size)

    # Step 3: Calculate chunks
    chunks = []
    for i in range(0, file_size, CHUNK_SIZE):
        start = i
        end = min(i + CHUNK_SIZE - 1, file_size - 1)
        chunks.append((start, end))

    # Step 4: Prepare download tasks
    from threading import Lock
    pbar = tqdm(total=file_size, unit='B', unit_scale=True, desc=filename)
    lock = Lock()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for start, end in chunks:
            # 检查是否已下载该块
            if os.path.exists(local_path):
                current_size = os.path.getsize(local_path)
                if current_size >= end + 1:
                    pbar.update(end - start + 1)
                    continue
            futures.append(
                executor.submit(download_chunk, file_url, start, end, local_path, pbar, lock)
            )
        for f in futures:
            f.result()
    pbar.close()


def download_datasets(datasetId, local_dir=None):
    """old dataset"""
    if local_dir is None:
        local_dir = os.getenv("HOME")
    host = os.getenv("STUDIO_GIT_HOST", default=config.STUDIO_MODEL_API_URL_PREFIX_DEFAULT)
    url = f"{host}/studio/dataset/detail"
    download_all_files(url, host, datasetId, local_dir)


def download_all_files(url, host, datasetId, localDir):
    """
    all
    """
    file_ids = post_request_get_file_ids(url, datasetId)
    os.makedirs(localDir, exist_ok=True)

    tasks = []
    pbar_lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=4) as executor:
        for fileId in file_ids:
            file_url = get_file_url(host, datasetId, fileId)
            tasks.append(executor.submit(download_file_multithreaded, file_url, localDir, pbar_lock))

    for task in tasks:
        task.result()

def bos_acl_dataset_file(
        token: str,
        bucket_name=None
    ):
    """
    申请ak/sk
    response:
    {
        "logId": "",
        "errorCode": 0,
        "errorMsg": "",
        "timestamp": 0,
        "result": {
            "accessKeyId": "",
            "secretAccessKey": "",
            "sessionToken": "",
            "fileKey": "",
            "serverTime": 0,
            "expiresIn": 0,
            "endpoint": "",
            "bucketName": ""
        }
    }
    """
    url = f"{config.STUDIO_MODEL_API_URL_PREFIX_DEFAULT}/llm/files/acl"
    headers = {
        "Authorization": f"{token}",
        "Content-Type": "application/json"
    }
    params = {}
    if bucket_name:
        params["bucketName"] = bucket_name

    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        raise RequestDatasetException(f"Failed to get bos acl: {response.text}")

def add_file_with_retry(token: str, file_origin_name: str, file_key: str, bucket_name=None, file_abs=None):
    """
    上传文件到指定的bucket，并返回文件ID。
    """
    for i in range(3):
        try:
            file_id = add_file(token, file_origin_name, file_key, bucket_name, file_abs)
            return file_id
        except RequestDatasetException as e:
            log.error(f"add file 失败，重试第{i+1}次")
            log.error(e)


def add_file(token: str, file_origin_name: str, file_key: str, bucket_name=None, file_abs=None):
    """
    上传文件到指定的bucket，并返回文件ID。

    Args:
        token (str): 认证token。
        file_origin_name (str): 文件的原始名称。
        file_key (str): 文件在存储中的键值。
        bucket_name (str, optional): 如果提供，则上传到此bucket，否则使用默认bucket。
        file_abs (str, optional): 文件的绝对路径，可选。

    Returns:
        dict: 包含操作结果的字典，其中包括logId, errorCode, errorMsg, timestamp和result（包含fileId）。

    Raises:
        HTTPError: 如果请求失败，抛出异常。
    """
    log.debug("add file..")
    url = f"{config.STUDIO_MODEL_API_URL_PREFIX_DEFAULT}/llm/files/addfile"
    headers = {
        "Authorization": f"{token}",
        "Content-Type": "application/json"
    }
    data = {
        "fileOriginName": file_origin_name,
        "fileKey": file_key,
        "bucketName": bucket_name,
        "fileAbs": file_abs
    }
    response = requests.post(url, headers=headers, json=data)

    if response.status_code == 200:
        if response.json().get("errorCode") == 0:
            log.debug(f"add file success")
            result = response.json()
            file_id = result.get("result", {}).get("fileId")
            return file_id
        else:
            log.error("落库失败")
            log.error(f"add file failed, response: {data} {response.text}")
            return None
    else:
        raise RequestDatasetException(f"Failed to add file: {response.text}")

def create_dataset_with_retry(token: str, dataset_name: str, file_ids: list,
                              dataset_type=1, dataset_abs="", dataset_license=1):
    """
    创建一个新的数据集，并返回数据集ID。
    """
    for i in range(3):
        try:
            dataset_id = create_dataset(token, dataset_name, file_ids, dataset_type, dataset_abs, dataset_license)
            return dataset_id
        except RequestDatasetException as e:
            log.error(f"create dataset 失败，重试第{i+1}次")
            log.error(e)


def create_dataset(token: str, dataset_name: str, file_ids: list, dataset_type=1, dataset_abs="", dataset_license=1):
    """
    创建一个新的数据集，并返回数据集ID。

    Args:
        token (str): 认证token。
        dataset_name (str): 数据集的名称。
        file_ids (list of int): 包含在数据集中的文件ID列表。
        dataset_type (int, optional): 数据集的类型，1 表示私有，2 表示公开。默认为0（私有）。
        dataset_abs (str, optional): 数据集的简介，可选。

    Returns:
        dict: 包含操作结果的字典，其中包括logId, errorCode, errorMsg, timestamp和result（包含datasetId）。
        None: 如果请求失败，返回None。

    """
    url = f"{config.STUDIO_MODEL_API_URL_PREFIX_DEFAULT}/llm/files/datasets"
    headers = {
        "Authorization": f"{token}",
        "Content-Type": "application/json"
    }

    data = {
        "datasetName": dataset_name,
        "datasetAbs": dataset_abs,
        "fileIds": file_ids,
        "datasetType": dataset_type,
        "protocolId": dataset_license
    }
    response = requests.post(url, headers=headers, json=data)


    if response.status_code == 200:
        log.debug(f"add file success")
        if response.json().get("errorCode") == 0:

            result = response.json()

            dataset_id = result.get("result", {}).get("datasetId")
            return dataset_id
        else:
            log.error(f"数据集创建失败:{response.json().get('errorMsg')}")
            log.debug(f"add file failed, response: {data} {response.text}")
            return None
    else:
        raise RequestDatasetException(f"Failed to create dataset: {response.text}")

def add_files_to_dataset_with_retry(token: str, dataset_id: int, file_ids: list):
    """
    向指定的数据集中添加文件。
    """
    for i in range(3):
        try:
            result = add_files_to_dataset(token, dataset_id, file_ids)
            return result
        except RequestDatasetException as e:
            log.error(f"add file to dataset 失败，重试第{i+1}次")
            log.error(e)

def add_files_to_dataset(token: str, dataset_id: int, file_ids: list):
    """
    向指定的数据集中添加文件。

    Args:
        token (str): 认证token。
        dataset_id (int): 数据集的ID。
        file_ids (list of int): 需要添加到数据集的文件ID列表。

    Returns:
        dict: 包含操作结果的字典，其中包括logId, errorCode, errorMsg, timestamp和result。
        None: 如果请求失败，返回None。

    """
    url = f"{config.STUDIO_MODEL_API_URL_PREFIX_DEFAULT}/llm/files/datasets/{dataset_id}/addfile"
    headers = {
        "Authorization": f"{token}",
        "Content-Type": "application/json"
    }

    data = {
        "fileIds": file_ids
    }
    response = requests.post(url, headers=headers, json=data)

    if response.status_code == 200:
        if response.json().get("errorCode") == 0:
            log.info(f"向数据集[{dataset_id}]中添加文件成功!")
            log.debug(f"向数据集[{dataset_id}]中添加文件成功[{file_ids}]")
            return response.json()
        else:
            log.error(f"添加文件失败: {response.json().get('errorMsg')}")
            log.debug(f"add file failed, response: {data} {response.text}")
            return None
    else:
        # log.error(f"Failed to add files to dataset: {response.text}")
        raise RequestDatasetException(f"Failed to add files to dataset: {response.text}")



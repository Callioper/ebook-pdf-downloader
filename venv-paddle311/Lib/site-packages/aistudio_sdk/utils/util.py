# !/usr/bin/env python3
# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2023 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""
本文件实现了常用的工具函数

Authors: xiangyiqing(xiangyiqing@baidu.com)
Date:    2023/07/24
"""
import tempfile
import sys
import os
import io
import re
import base64
import hashlib
from datetime import datetime, timezone, timedelta
import zipfile
from aistudio_sdk import log
from aistudio_sdk.errors import FileIntegrityError
from aistudio_sdk.config import DEFAULT_MAX_WORKERS
from functools import wraps
from tqdm.auto import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Union, BinaryIO, Optional
from aistudio_sdk.constant.version import VERSION
from pathlib import Path


class Dict(dict):
    """dict class"""
    def __getattr__(self, key):
        value = self.get(key, None)
        return Dict(value) if isinstance(value, dict) else value
    
    def __setattr__(self, key, value):
        self[key] = value


def convert_to_dict_object(resp):
    """
    Params
        :resp: dict, response from AIStudio
    Rerurns
        AIStudio object
    """
    if isinstance(resp, dict):
        return Dict(resp)
    
    return resp


def err_resp(sdk_code, msg, biz_code=None, log_id=None):
    """
    构造错误响应信息。

    Params:
        sdk_code (str): SDK错误码，标识错误类型。
        msg (str): 错误描述信息。
        biz_code (str, optional): 业务层面的错误码，透传自上游接口。
        log_id (str, optional): 与错误相关的日志ID，透传自上游接口。

    Returns:
        dict: 格式化好的错误信息。
    """
    return {
        "error_code": sdk_code,  # 错误码
        "error_msg": msg,  # 错误消息
        "biz_code": biz_code,  # 业务错误码
        "log_id": log_id  # 日志ID
    }


def is_valid_host(host):
    """检测host合法性"""
    # 去除可能的协议前缀 如http://、https://
    host = re.sub(r'^https?://', '', host, flags=re.IGNORECASE)
    result = is_valid_domain(host)
    # if not result:
    #     host = re.sub(r'^http?://', '', host, flags=re.IGNORECASE)
    #     result = is_valid_domain(host)
    return result


def is_valid_domain(domain):
    """检测域名合法性"""
    return True
    # pattern = r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.[A-Za-z]{2,})+$"
    # return re.match(pattern, domain) is not None


def calculate_sha256(file_path):
    """将文件计算为sha256值"""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as file:
        # 逐块更新哈希值，以适应大型文件
        while True:
            data = file.read(65536)  # 64K块大小
            if not data:
                break
            sha256_hash.update(data)

    return sha256_hash.hexdigest()


def gen_ISO_format_datestr():
    """
    # 生成 ISO 8601日期时间格式
    # 例如"2023-09-12T11:29:45.703Z"
    """
    # 获取当前日期和时间
    zone = timezone(timedelta(hours=8))
    now = datetime.now(zone)
    # 使用strftime函数将日期和时间格式化为所需的字符串格式
    formatted_date = now.isoformat(timespec='milliseconds')
    return formatted_date


def gen_MD5(file_path):
    """将文件计算为md5值"""
    md5_hash = hashlib.md5()
    try:
        with open(file_path, 'rb') as file:
            # 逐块读取文件并更新哈希对象
            while True:
                data = file.read(4096)  # 读取4K字节数据块
                if not data:
                    break
                md5_hash.update(data)
    except FileNotFoundError:
        print(f"The file '{file_path}' does not exist.")
        return None

    # 获取MD5哈希值的十六进制表示
    md5_hex = md5_hash.hexdigest()

    return md5_hex


def gen_base64(original_string):
    """将字符串计算为base64"""
    # 将原始字符串编码为字节数组
    bytes_data = original_string.encode('utf-8')
    # 使用base64进行编码
    base64_encoded = base64.b64encode(bytes_data).decode('utf-8')
    return base64_encoded


def create_sha256_file_and_encode_base64(sha256, size):
    """生成指定内容的文件并进行base64编码字符串返回"""
    content = f"version https://git-lfs.github.com/spec/v1\noid sha256:{sha256}\nsize {size}"
    with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.txt') as tmp:
        tmp.write(content)
        tmp_path = tmp.name
        log.debug(tmp_path)

    try:
        with open(tmp_path, 'rb') as f:
            encoded = base64.b64encode(f.read()).decode('utf-8')
        return encoded
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    # name = 'sha256_value'
    # with open(name, 'w') as file:
    #     file.write(content)
    #
    # ret = file_to_base64(name)
    # os.remove(name)
    # return ret


def file_to_base64(filename):
    """读取文件内容并进行Base64编码"""
    with open(filename, "rb") as file:
        contents = file.read()
        encoded_contents = base64.b64encode(contents)
    return encoded_contents.decode('utf-8')


def zip_dir(dirpath, out_full_name):
    """
    压缩指定文件夹
    :param dirpath: 目标文件夹路径
    :param out_full_name: 压缩文件保存路径 xxxx.zip
    :return: 无
    """
    zip_obj = zipfile.ZipFile(out_full_name, "w", zipfile.ZIP_DEFLATED)
    for path, dirnames, filenames in os.walk(dirpath):
        # 去掉目标跟路径，只对目标文件夹下边的文件及文件夹进行压缩
        fpath = path.replace(dirpath, '')
 
        for filename in filenames:
            zip_obj.write(os.path.join(path, filename), os.path.join(fpath, filename))
    zip_obj.close()


def compute_hash(file_path):
    """
    hash
    """
    BUFFER_SIZE = 1024 * 64  # 64k buffer size
    sha256_hash = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while True:
            data = f.read(BUFFER_SIZE)
            if not data:
                break
            sha256_hash.update(data)
    return sha256_hash.hexdigest()


def file_integrity_validation(file_path, expected_sha256):
    """Validate the file hash is expected, if not, delete the file

    Args:
        file_path (str): The file to validate
        expected_sha256 (str): The expected sha256 hash

    Raises:
        FileIntegrityError: If file_path hash is not expected.

    """
    file_sha256 = compute_hash(file_path)
    if not file_sha256 == expected_sha256:
        os.remove(file_path)
        msg = ('File %s integrity check failed, expected sha256 signature is %s, '
               'actual is %s, the download may be incomplete, please try again.') % (  # noqa E501
            file_path, expected_sha256, file_sha256)
        log.error(msg)
        raise FileIntegrityError(msg)


def thread_executor(max_workers: int = DEFAULT_MAX_WORKERS,
                    disable_tqdm: bool = False,
                    tqdm_desc: str = None):
    """
    A decorator to execute a function in a threaded manner using ThreadPoolExecutor.

    Args:
        max_workers (int): The maximum number of threads to use.
        disable_tqdm (bool): disable progress bar.
        tqdm_desc (str): Desc of tqdm.

    Returns:
        function: A wrapped function that executes with threading and a progress bar.


    """

    def decorator(func):

        @wraps(func)
        def wrapper(iterable, *args, **kwargs):
            results = []
            # Create a tqdm progress bar with the total number of items to process
            with tqdm(
                    unit_scale=True,
                    unit_divisor=1024,
                    initial=0,
                    total=len(iterable),
                    desc=tqdm_desc or f'Processing {len(iterable)} items',
                    disable=disable_tqdm,
            ) as pbar:
                # Define a wrapper function to update the progress bar
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Submit all tasks
                    futures = {
                        executor.submit(func, item, *args, **kwargs): item
                        for item in iterable
                    }

                    # Update the progress bar as tasks complete
                    for future in as_completed(futures):
                        pbar.update(1)
                        results.append(future.result())
            return results

        return wrapper

    return decorator


def get_model_masked_directory(directory, model_id):
    """
    目录
    """
    if sys.platform.startswith('win'):
        parts = directory.rsplit('\\', 2)
    else:
        parts = directory.rsplit('/', 2)
    # this is the actual directory the model files are located.
    masked_directory = os.path.join(parts[0], model_id.replace('.', '___'))
    return masked_directory


def convert_patterns(raw_input: Union[str, List[str]]):
    """
    处理规则
    """
    output = None
    if isinstance(raw_input, str):
        output = list()
        if ',' in raw_input:
            output = [s.strip() for s in raw_input.split(',')]
        else:
            output.append(raw_input.strip())
    elif isinstance(raw_input, list):
        output = list()
        for s in raw_input:
            if isinstance(s, str):
                if ',' in s:
                    output.extend([ss.strip() for ss in s.split(',')])
                else:
                    output.append(s.strip())
    return output


def header_fill(params=None, token=''):
    """
    填充header
    """
    if token:
        auth = f'token {token}'
    else:
        auth = f'token {os.getenv("AISTUDIO_ACCESS_TOKEN", default="")}'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': auth,
        'SDK-Version': str(VERSION)
    }
    if params:
        headers.update(params)
    return headers


def extract_yaml_block(file_path):
    """
    获取yaml
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 提取 --- 和 --- 之间的内容（非贪婪匹配）
    match = re.search(r'^---\s*(.*?)\s*---', content, re.DOTALL | re.MULTILINE)
    if match:
        return match.group(1).strip()
    else:
        raise ValueError("未找到两个 '---' 分隔的 YAML 内容")


def is_readme_md(file_path):
    """
    判断文件名
    """
    file_name = os.path.basename(file_path)
    return file_name == 'README.md'


def get_file_size(file_path_or_obj: Union[str, Path, bytes, BinaryIO]) -> int:
    """
    get size
    """
    if isinstance(file_path_or_obj, (str, Path)):
        file_path = Path(file_path_or_obj)
        return file_path.stat().st_size
    elif isinstance(file_path_or_obj, bytes):
        return len(file_path_or_obj)
    elif isinstance(file_path_or_obj, io.BufferedIOBase):
        current_position = file_path_or_obj.tell()
        file_path_or_obj.seek(0, os.SEEK_END)
        size = file_path_or_obj.tell()
        file_path_or_obj.seek(current_position)
        return size
    else:
        raise TypeError(
            'Unsupported type: must be string, Path, bytes, or io.BufferedIOBase'
        )


def get_file_hash(
    file_path_or_obj: Union[str, Path, bytes, BinaryIO],
    buffer_size_mb: Optional[int] = 1,
    tqdm_desc: Optional[str] = '[Calculating]',
    disable_tqdm: Optional[bool] = True,
) -> dict:
    """
    calculate hash
    """
    from tqdm.auto import tqdm

    file_size = get_file_size(file_path_or_obj)
    if file_size > 1024 * 1024 * 1024:  # 1GB
        disable_tqdm = False
        name = 'Large File'
        if isinstance(file_path_or_obj, (str, Path)):
            path = file_path_or_obj if isinstance(
                file_path_or_obj, Path) else Path(file_path_or_obj)
            name = path.name
        tqdm_desc = f'[Validating Hash for {name}]'

    buffer_size = buffer_size_mb * 1024 * 1024
    file_hash = hashlib.sha256()
    chunk_hash_list = []

    progress = tqdm(
        total=file_size,
        initial=0,
        unit_scale=True,
        dynamic_ncols=True,
        unit='B',
        desc=tqdm_desc,
        disable=disable_tqdm,
    )

    if isinstance(file_path_or_obj, (str, Path)):
        with open(file_path_or_obj, 'rb') as f:
            while byte_chunk := f.read(buffer_size):
                chunk_hash_list.append(hashlib.sha256(byte_chunk).hexdigest())
                file_hash.update(byte_chunk)
                progress.update(len(byte_chunk))
        file_hash = file_hash.hexdigest()
        final_chunk_size = buffer_size

    elif isinstance(file_path_or_obj, bytes):
        file_hash.update(file_path_or_obj)
        file_hash = file_hash.hexdigest()
        chunk_hash_list.append(file_hash)
        final_chunk_size = len(file_path_or_obj)
        progress.update(final_chunk_size)

    elif isinstance(file_path_or_obj, io.BufferedIOBase):
        while byte_chunk := file_path_or_obj.read(buffer_size):
            chunk_hash_list.append(hashlib.sha256(byte_chunk).hexdigest())
            file_hash.update(byte_chunk)
            progress.update(len(byte_chunk))
        file_hash = file_hash.hexdigest()
        final_chunk_size = buffer_size

    else:
        progress.close()
        raise ValueError(
            'Input must be str, Path, bytes or a io.BufferedIOBase')

    progress.close()

    return {
        'file_path_or_obj': file_path_or_obj,
        'file_hash': file_hash,
        'file_size': file_size,
        'chunk_size': final_chunk_size,
        'chunk_nums': len(chunk_hash_list),
        'chunk_hash_list': chunk_hash_list,
    }

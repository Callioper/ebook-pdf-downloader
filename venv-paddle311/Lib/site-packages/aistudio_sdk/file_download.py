# !/usr/bin/env python3
# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2025 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""
本文件实现了星河社区git文件的下载功能
"""
import psutil
import time
import io
import hashlib
import errno
import shutil

import requests
import uuid
import copy
from urllib.parse import quote
from typing import Dict, Optional, Union
import os
from .config import (
    REPO_TYPE_MODEL, REPO_TYPE_DATASET, REPO_TYPE_SUPPORT,
    MODEL_ID_SEPARATOR, DEFAULT_AISTUDIO_GROUP, TEMPORARY_FOLDER_NAME,
    STUDIO_GIT_HOST_DEFAULT, DEFAULT_DATASET_REVISION, AISTUDIO_PARALLEL_DOWNLOAD_THRESHOLD_MB,
    AISTUDIO_DOWNLOAD_PARALLELS, API_FILE_DOWNLOAD_RETRY_TIMES,
    API_FILE_DOWNLOAD_TIMEOUT, API_FILE_DOWNLOAD_CHUNK_SIZE, FILE_HASH, DEFAULT_MODEL_REVISION)
from .errors import InvalidParameter, NotExistError, RequestError
from pathlib import Path
from aistudio_sdk.requests.hub import request_aistudio_git_file_info
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import Retry
from tqdm.auto import tqdm
from .utils.caching import ModelFileSystemCache
from .utils.util import file_integrity_validation, header_fill
from aistudio_sdk import log
from aistudio_sdk import switch_downoad
from aistudio_sdk.dot import post_repo_statistic_async


__all__ = [
    "model_file_download",
    "file_download"
]


def file_download(
    repo_id: str,
    file_path: str,
    revision: Optional[str] = 'master',
    local_files_only: Optional[bool] = False,
    local_dir: Optional[str] = None,
    repo_type: Optional[str] = 'model',
    token: str=None
) -> Optional[str]:
    """
    增加入口
    """
    return model_file_download(
        repo_id,
        file_path,
        repo_type=repo_type,
        revision=revision,
        local_files_only=local_files_only,
        local_dir=local_dir,
        token=token
    )


def model_file_download(
    repo_id: str,
    file_path: str,
    revision: Optional[str] = 'master',
    local_files_only: Optional[bool] = False,
    local_dir: Optional[str] = None,
    repo_type: Optional[str] = 'model',
    token: str=None
) -> Optional[str]:
    """
    download repo
    """
    init()
    if revision is None:
        revision = DEFAULT_MODEL_REVISION
    action = {"path": file_path}
    try:
        post_repo_statistic_async(repo_id, revision, action)
    except Exception as e:
        log.debug(f"request.dot.fail: {e}")
    return _repo_file_download(
        repo_id,
        file_path,
        repo_type=repo_type,
        revision=revision,
        local_files_only=local_files_only,
        local_dir=local_dir,
        token=token
    )


def init():
    """初始化函数，从本地磁盘加载AI Studio认证令牌。

    Args:
        无参数。

    Returns:
        无返回值。
    """

    # 当用户已经设置了AISTUDIO_ACCESS_TOKEN环境变量，那么优先读取环境变量，忽略本地磁盘存的token
    # 未设置时才读存本地token
    if not os.getenv("AISTUDIO_ACCESS_TOKEN", default=""):
        cache_home = os.getenv("AISTUDIO_CACHE_HOME", default=os.getenv("HOME"))
        token_file_path = f'{cache_home}/.cache/aistudio/.auth/token'
        if os.path.exists(token_file_path):
            with open(token_file_path, 'r') as file:
                os.environ["AISTUDIO_ACCESS_TOKEN"] = file.read().strip()


def _repo_file_download(
    repo_id: str,
    file_path: str,
    *,
    repo_type: str = None,
    revision: Optional[str] = 'master',
    local_files_only: Optional[bool] = False,
    local_dir: Optional[str] = None,
    token: str=None
) -> Optional[str]:  # pragma: no cover
    """
    download repo
    """
    if not repo_type:
        repo_type = REPO_TYPE_MODEL
    if repo_type not in REPO_TYPE_SUPPORT:
        raise InvalidParameter('Invalid repo type: %s, only support: %s' %
                               (repo_type, REPO_TYPE_SUPPORT))

    temporary_cache_dir, cache = create_temporary_directory_and_cache(
        repo_id, local_dir=local_dir, repo_type=repo_type)

    # if local_files_only is `True` and the file already exists in cached_path
    # return the cached path
    if local_files_only:
        cached_file_path = cache.get_file_by_path(file_path)
        if cached_file_path is not None:
            log.warn(
                "File exists in local cache, but we're not sure it's up to date"
            )
            return cached_file_path
        else:
            raise ValueError(
                'Cannot find the requested files in the cached path and outgoing'
                ' traffic has been disabled. To enable look-ups and downloads'
                " online, set 'local_files_only' to False.")



    file_to_download_meta = None
    if repo_type == REPO_TYPE_MODEL or repo_type == REPO_TYPE_DATASET:
        repo_file = get_git_info(repo_id, file_path, revision, token)
        if not "path" in repo_file:
            raise NotExistError('The file path: %s not exist in: %s' %
                            (file_path, repo_id))
        if cache.exists(repo_file):
            file_name = repo_file['name']
            log.debug(
                f'File {file_name} already in cache with identical hash, skip downloading!'
            )
            return cache.get_file_by_info(repo_file)
        file_to_download_meta = repo_file

    if file_to_download_meta is None:
        raise NotExistError('The file path: %s not exist in: %s' %
                            (file_path, repo_id))

    # we need to download again
    if repo_type == REPO_TYPE_MODEL or repo_type == REPO_TYPE_DATASET:
        file_sha = file_to_download_meta['sha']
        file_path = file_to_download_meta['path']
        if file_path is None:
            raise NotExistError('The file path: %s not exist in: %s' %
                                (file_path, repo_id))
        user_name, repo_name = repo_id.split('/')
        user_name = user_name.strip()
        repo_name = repo_name.strip()
        git_host = os.getenv("STUDIO_GIT_HOST", default=STUDIO_GIT_HOST_DEFAULT)
        url_to_download = (
                f"{git_host}/api/v1/repos/"
                f"{quote(user_name, safe='')}/"
                f"{quote(repo_name, safe='')}/media/"
                f"{quote(file_path, safe='')}"
            )
        if revision != 'master':
            url_to_download += f"?ref={quote(revision, safe='')}"
    else:
        raise ValueError(f'Invalid repo type {repo_type}')

    return download_file(url_to_download, file_to_download_meta,
                         temporary_cache_dir, cache, token=token)


def create_temporary_directory_and_cache(model_id: str,
                                         local_dir: str = None,
                                         repo_type: str = REPO_TYPE_MODEL):
    """
    temp dir
    """
    if repo_type == REPO_TYPE_MODEL:
        default_cache_root = get_model_cache_root()
    elif repo_type == REPO_TYPE_DATASET:
        default_cache_root = get_dataset_cache_root()
    else:
        raise ValueError(
            f'repo_type only support model and dataset, but now is : {repo_type}'
        )

    group_or_owner, name = model_id_to_group_owner_name(model_id)
    if local_dir is not None:
        temporary_cache_dir = os.path.join(local_dir, TEMPORARY_FOLDER_NAME)
        cache = ModelFileSystemCache(local_dir)
    else:
        cache_dir = default_cache_root

        if isinstance(cache_dir, Path):
            cache_dir = str(cache_dir)
        temporary_cache_dir = os.path.join(cache_dir, TEMPORARY_FOLDER_NAME,
                                           group_or_owner, name)
        name = name.replace('.', '___')
        cache = ModelFileSystemCache(cache_dir, group_or_owner, name)

    os.makedirs(temporary_cache_dir, exist_ok=True)
    return temporary_cache_dir, cache


def get_model_cache_root() -> str:
    """Get model cache root path.

    Returns:
        str: the aistudio model cache root.
    """
    return os.path.join(get_aistudio_cache_dir(), 'models')


def get_aistudio_cache_dir() -> str:
    """Get aistudio cache dir, default location or
       setting with AISTUDIO_CACHE_HOME

    Returns:
        str: the aistudio cache root.
    """
    return os.path.expanduser(
        os.getenv('AISTUDIO_CACHE_HOME', get_default_aistudio_cache_dir()))


def get_default_aistudio_cache_dir():
    """
    default base dir: '~/.cache/aistudio
    """
    default_cache_dir = os.path.expanduser(Path.home().joinpath(
        '.cache', 'aistudio', 'hub'))
    return default_cache_dir


def get_dataset_cache_root() -> str:
    """Get dataset raw file cache root path.
    if `AISTUDIO_CACHE_HOME` is set, return `AISTUDIO_CACHE_HOME/datasets`,
    else return `~/.cache/aistudio/hub/datasets`

    Returns:
        str: the aistudio dataset raw file cache root.
    """
    return os.path.join(get_aistudio_cache_dir(), 'datasets')


def model_id_to_group_owner_name(model_id):
    """
    get name
    """
    if MODEL_ID_SEPARATOR in model_id:
        group_or_owner = model_id.split(MODEL_ID_SEPARATOR)[0]
        name = model_id.split(MODEL_ID_SEPARATOR)[1]
    else:
        group_or_owner = DEFAULT_AISTUDIO_GROUP
        name = model_id
    return group_or_owner, name


def get_git_info(repo_id, file_path, revision, token):
    """
    get meta
    """
    user_name, repo_name = repo_id.split('/')
    user_name = user_name.strip()
    repo_name = repo_name.strip()
    git_host = os.getenv("STUDIO_GIT_HOST", default=STUDIO_GIT_HOST_DEFAULT)
    if not token:
        token = os.getenv("AISTUDIO_ACCESS_TOKEN", default="")
    return request_aistudio_git_file_info(git_host, user_name, repo_name, file_path,
                                                  revision, token)


def download_file(
    url,
    file_meta,
    temporary_cache_dir,
    cache,
    disable_tqdm=False,
    token=None
):
    """
    download
    """
    file_path = os.path.join(temporary_cache_dir, file_meta['path'])
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    lock_path = file_path + '.lock'
    while True:
        if acquire_pid_lock(lock_path):
            break
        else:
            if os.environ.get("WAIT_UNTIL_DONE"):
                log.warn(f"[Download] WAITING '{file_meta['path']}' due to active lock.")
                time.sleep(10)
            else:
                print(f"[Download] Skipping '{file_meta['path']}' due to active lock.")
                return None

    try:
        headers = header_fill(token=token)
        if AISTUDIO_PARALLEL_DOWNLOAD_THRESHOLD_MB * 1024 * 1024 < file_meta[
            'size'] and AISTUDIO_DOWNLOAD_PARALLELS > 1:  # parallel download large file.
            file_digest = parallel_download(
                url,
                temporary_cache_dir,
                file_meta['path'],
                headers,
                file_size=file_meta['size'],
                disable_tqdm=disable_tqdm,
            )
        else:
            file_digest = http_get_model_file(
                url,
                temporary_cache_dir,
                file_meta['path'],
                file_size=file_meta['size'],
                headers=headers,
                disable_tqdm=disable_tqdm,
            )

        # check file integrity
        if not file_digest:
            return None
        temp_file = os.path.join(temporary_cache_dir, file_meta['path'])
        if FILE_HASH in file_meta:
            expected_hash = file_meta[FILE_HASH]
            # if a real-time hash has been computed
            if file_digest is not None:
                # if real-time hash mismatched, try to compute it again
                if file_digest != expected_hash:
                    print(
                        'Mismatched real-time digest found, falling back to lump-sum hash computation'
                    )
                    file_integrity_validation(temp_file, expected_hash)
            else:
                file_integrity_validation(temp_file, expected_hash)
        # put file into to cache
        return cache.put_file(file_meta, temp_file)
    except Exception as e:
        print(f"[Download] Error downloading {file_path}: {e}")
    finally:
        release_pid_lock(lock_path)


def parallel_download(url: str,
                      local_dir: str,
                      file_name: str,
                      headers: Optional[Dict[str, str]] = None,
                      file_size: int = None,
                      disable_tqdm: bool = False,):
    """
    large file downlooad
    """
    file_path = os.path.join(local_dir, file_name)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with tqdm(
            unit='B',
            unit_scale=True,
            unit_divisor=1024,
            total=file_size,
            initial=0,
            desc='Downloading [' + file_name + ']',
            leave=True,
            disable=disable_tqdm,
    ) as progress:
        PART_SIZE = AISTUDIO_PARALLEL_DOWNLOAD_THRESHOLD_MB * 1024 * 1024  # every part is 160M
        tasks = []
        # os.makedirs(os.path.dirname(file_path), exist_ok=True)
        for start in range(0, file_size, PART_SIZE):
            end = min(start + PART_SIZE - 1, file_size - 1)
            tasks.append((file_path, progress, start, end, url, file_name, headers))
        parallels = AISTUDIO_DOWNLOAD_PARALLELS
        # download every part
        with ThreadPoolExecutor(
                max_workers=parallels,
                thread_name_prefix='download') as executor:
            list(executor.map(download_part_with_retry, tasks))

    # merge parts.
    hash_sha256 = hashlib.sha256()
    merge_parts_to_file(local_dir, file_name, tasks, hash_sha256)
    return hash_sha256.hexdigest()



def merge_parts_to_file(local_dir, file_name, tasks, hash_sha256):
    """
    merge
    """
    target_path = os.path.join(local_dir, file_name)

    # 判断目标文件是否存在
    write_path = target_path
    use_temp = os.path.exists(target_path)

    if use_temp:
        temp_file_name = f".{file_name}.tmp"
        write_path = os.path.join(local_dir, temp_file_name)
        # 确保旧的临时文件被清除
        if os.path.exists(write_path):
            os.remove(write_path)

    # 开始写入（到目标文件或临时文件）
    with open(write_path, 'wb') as output_file:
        for task in tasks:
            part_file_name = task[0] + '_%s_%s' % (task[2], task[3])
            with open(part_file_name, 'rb') as part_file:
                while True:
                    chunk = part_file.read(16 * API_FILE_DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    output_file.write(chunk)
                    hash_sha256.update(chunk)
            os.remove(part_file_name)

    # 如果写入的是临时文件，则移动替换目标文件
    if use_temp:
        shutil.move(write_path, target_path)



def download_part_with_retry(params):
    """
    download part
    """
    # unpack parameters
    model_file_path, progress, start, end, url, file_name, headers = params
    get_headers = {} if headers is None else copy.deepcopy(headers)
    #get_headers['X-Request-ID'] = str(uuid.uuid4().hex)
    retry = Retry(
        total=API_FILE_DOWNLOAD_RETRY_TIMES,
        backoff_factor=1,
        allowed_methods=['GET'])
    part_file_name = model_file_path + '_%s_%s' % (start, end)
    while True:
        try:
            partial_length = 0
            if os.path.exists(
                    part_file_name):  # download partial, continue download
                with open(part_file_name, 'rb') as f:
                    partial_length = f.seek(0, io.SEEK_END)
                    progress.update(partial_length)
            download_start = start + partial_length
            if download_start > end:
                break  # this part is download completed.
            get_headers['Range'] = 'bytes=%s-%s' % (download_start, end)
            with open(part_file_name, 'ab+') as f:
                url = switch_downoad.switch_cdn(url, headers, get_headers)
                r = requests.get(
                    url,
                    stream=True,
                    headers=get_headers,
                    timeout=API_FILE_DOWNLOAD_TIMEOUT)
                if not r.ok:
                    log.debug(f"download res:{r.content}")
                    raise RequestError(f"download.fail:{r.status_code}")

                for chunk in r.iter_content(
                        chunk_size=API_FILE_DOWNLOAD_CHUNK_SIZE):
                    if chunk:  # filter out keep-alive new chunks
                        f.write(chunk)
                        progress.update(len(chunk))
            break
        except (Exception) as e:  # no matter what exception, we will retry.
            retry = retry.increment('GET', url, error=e)
            log.debug('Downloading: %s failed, reason: %s will retry' %
                           (model_file_path, e))
            retry.sleep()


def http_get_model_file(
    url: str,
    local_dir: str,
    file_name: str,
    file_size: int,
    headers: Optional[Dict[str, str]] = None,
    disable_tqdm: bool = False,
):
    """Download remote file, will retry 5 times before giving up on errors.

    Args:
        url(str):
            actual download url of the file
        local_dir(str):
            local directory where the downloaded file stores
        file_name(str):
            name of the file stored in `local_dir`
        file_size(int):
            The file size.
        cookies(CookieJar):
            cookies used to authentication the user, which is used for downloading private repos
        headers(Dict[str, str], optional):
            http headers to carry necessary info when requesting the remote file
        disable_tqdm(bool, optional): Disable the progress bar with tqdm.

    Raises:
        FileDownloadError: File download failed.

    """
    file_path = os.path.join(local_dir, file_name)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    get_headers = {} if headers is None else copy.deepcopy(headers)
    get_headers['X-Request-ID'] = str(uuid.uuid4().hex)
    temp_file_path = os.path.join(local_dir, file_name)
    os.makedirs(os.path.dirname(temp_file_path), exist_ok=True)
    log.debug(f'downloading {url} to {temp_file_path}')
    # retry sleep 0.5s, 1s, 2s, 4s
    has_retry = False
    hash_sha256 = hashlib.sha256()
    retry = Retry(
        total=API_FILE_DOWNLOAD_RETRY_TIMES,
        backoff_factor=1,
        allowed_methods=['GET'])
    while True:
        try:
            with tqdm(
                    unit='B',
                    unit_scale=True,
                    unit_divisor=1024,
                    total=file_size if file_size > 0 else 1,
                    initial=0,
                    desc='Downloading [' + file_name + ']',
                    leave=True,
                    disable=disable_tqdm,
            ) as progress:
                if file_size == 0:
                    # Avoid empty file server request
                    with open(temp_file_path, 'w+'):
                        progress.update(1)
                    break
                # Determine the length of any existing partial download
                partial_length = 0
                # download partial, continue download
                if os.path.exists(temp_file_path):
                    # resuming from interrupted download is also considered as retry
                    has_retry = True
                    with open(temp_file_path, 'rb') as f:
                        partial_length = f.seek(0, io.SEEK_END)
                        progress.update(partial_length)

                # Check if download is complete
                if partial_length >= file_size:
                    break
                # closed range[], from 0.
                get_headers['Range'] = 'bytes=%s-%s' % (partial_length,
                                                        file_size - 1)
                with open(temp_file_path, 'ab+') as f:
                    url = switch_downoad.switch_cdn(url, headers, get_headers)
                    r = requests.get(
                        url,
                        stream=True,
                        headers=get_headers,
                        timeout=API_FILE_DOWNLOAD_TIMEOUT)
                    r.raise_for_status()
                    for chunk in r.iter_content(
                            chunk_size=API_FILE_DOWNLOAD_CHUNK_SIZE):
                        if chunk:  # filter out keep-alive new chunks
                            progress.update(len(chunk))
                            f.write(chunk)
                            # hash would be discarded in retry case anyway
                            if not has_retry:
                                hash_sha256.update(chunk)
            break
        except Exception as e:  # no matter what happen, we will retry.
            has_retry = True
            retry = retry.increment('GET', url, error=e)
            retry.sleep()
    # if anything went wrong, we would discard the real-time computed hash and return None
    return None if has_retry else hash_sha256.hexdigest()


def is_process_alive(pid: int) -> bool:
    """判断进程是否存在且不是僵尸进程"""
    try:
        p = psutil.Process(pid)
        # 如果进程存在，检查状态是否是僵尸
        return p.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def acquire_pid_lock(lock_path: str):
    """Use atomic file creation to acquire a PID lock."""
    pid = str(os.getpid())
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, 'w') as f:
            f.write(pid)
        return True
    except FileExistsError:
        try:
            with open(lock_path, 'r') as f:
                existing_pid = int(f.read().strip())
            if is_process_alive(existing_pid):
                print(f"[Lock] File is locked by PID {existing_pid}")
                return False
            else:
                print(f"[Lock] Stale lock from PID {existing_pid}, removing.")
                os.remove(lock_path)
                return acquire_pid_lock(lock_path)  # retry once
        except Exception as e:
            print(f"[Lock] Error checking/removing stale lock: {e}")
            return False
    except Exception as e:
        print(f"[Lock] Cannot create lock file: {e}")
        return False


def release_pid_lock(lock_path: str):
    """Release the lock if it is still held by the current process."""
    try:
        if os.path.exists(lock_path):
            with open(lock_path, 'r') as f:
                pid = int(f.read().strip())
            if pid == os.getpid():
                os.remove(lock_path)
                log.debug(f"[Lock] Released lock {lock_path}")
    except Exception as e:
        print(f"[Lock] Error releasing lock: {e}")
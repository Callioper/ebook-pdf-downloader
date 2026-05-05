# !/usr/bin/env python3
# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2025 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""
本文件实现了星河社区git仓库的下载功能
"""
import requests
import uuid
import fnmatch
import os
import re
from symtable import Class
from typing import Dict, List, Optional, Union
from aistudio_sdk import log
from aistudio_sdk.file_download import (create_temporary_directory_and_cache,
                                          download_file, get_git_info)
from aistudio_sdk.errors import (InvalidParameter, raise_on_error)
from aistudio_sdk.config import (REPO_TYPE_SUPPORT, REPO_TYPE_DATASET,
                                 REPO_TYPE_MODEL, STUDIO_GIT_HOST_DEFAULT,
                                 DEFAULT_MODEL_REVISION, DEFAULT_DATASET_REVISION,
                                 DEFAULT_MAX_WORKERS)
from aistudio_sdk.utils.util import (thread_executor, get_model_masked_directory)
from urllib.parse import quote
from aistudio_sdk.utils.caching import ModelFileSystemCache
from aistudio_sdk.requests.hub import _header_fill
from pathlib import Path
from urllib.parse import urlparse
from .errors import InvalidParameter, NotExistError
from aistudio_sdk.dot import post_repo_statistic

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


def snapshot_download(
    revision: Optional[str] = None,
    local_files_only: Optional[bool] = False,
    local_dir: Optional[str] = None,
    allow_patterns: Optional[Union[List[str], str]] = None,
    ignore_patterns: Optional[Union[List[str], str]] = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    repo_id: str = None,
    repo_type: Optional[str] = REPO_TYPE_MODEL,
    token: str = None
) -> str:
    """prepare"""
    init()
    if not repo_id:
        raise ValueError('Please provide a valid model_id or repo_id')

    if repo_type not in REPO_TYPE_SUPPORT:
        raise ValueError(
            f'Invalid repo type: {repo_type}, only support: {REPO_TYPE_SUPPORT}'
        )

    if revision is None:
        revision = DEFAULT_DATASET_REVISION if repo_type == REPO_TYPE_DATASET else DEFAULT_MODEL_REVISION

    action = {"repo": repo_id}
    try:
        post_repo_statistic(repo_id, revision, action)
    except Exception as e:
        log.debug(f"request.dot.fail: {e}")
    return _snapshot_download(
        repo_id,
        repo_type=repo_type,
        revision=revision,
        local_files_only=local_files_only,
        local_dir=local_dir,
        ignore_patterns=ignore_patterns,
        allow_patterns=allow_patterns,
        max_workers=max_workers,
        token=token
    )


def _snapshot_download(
    repo_id: str,
    *,
    repo_type: Optional[str] = None,
    revision: Optional[str] = DEFAULT_MODEL_REVISION,
    cache_dir: Union[str, Path, None] = None,
    local_files_only: Optional[bool] = False,
    local_dir: Optional[str] = None,
    allow_patterns: Optional[Union[List[str], str]] = None,
    ignore_patterns: Optional[Union[List[str], str]] = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    token: str =  None
):
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
    system_cache = os.path.expanduser(
        os.getenv('AISTUDIO_CACHE', get_default_aistudio_cache_dir()))
    if local_files_only:
        if len(cache.cached_files) == 0:
            raise ValueError(
                'Cannot find the requested files in the cached path and outgoing'
                ' traffic has been disabled. To enable look-ups and downloads'
                " online, set 'local_files_only' to False.")
        log.warn('We can not confirm the cached file is for revision: %s'
                       % revision)
        return cache.get_root_location(
        )  # we can not confirm the cached file is for snapshot 'revision'
    else:
        # make headers
        headers = {
            'snapshot-identifier': str(uuid.uuid4()),
        }

        if repo_type == REPO_TYPE_MODEL or repo_type == REPO_TYPE_DATASET:
            if local_dir:
                directory = os.path.abspath(local_dir)
            elif cache_dir:
                directory = os.path.join(system_cache, *repo_id.split('/'))
            else:
                directory = os.path.join(system_cache, 'models' if repo_type == REPO_TYPE_MODEL else 'dataset',
                                         *repo_id.split('/'))
            log.info(
                f'Downloading Model from remote to directory: {directory}')


            repo_files, revision_detail = get_model_files(
                model_id=repo_id,
                revision=revision,
                token=token
            )
            _download_file_lists(
                repo_files=repo_files,
                cache=cache,
                temporary_cache_dir=temporary_cache_dir,
                repo_id=repo_id,
                repo_type=repo_type,
                revision=revision,
                ignore_patterns=ignore_patterns,
                allow_patterns=allow_patterns,
                max_workers=max_workers,
                token=token
            )
            if '.' in repo_id:
                masked_directory = get_model_masked_directory(
                    directory, repo_id)
                if os.path.exists(directory):
                    log.info(
                        'Target directory already exists, skipping creation.')
                else:
                    log.info(f'Creating symbolic link [{directory}].')
                    try:
                        os.symlink(
                            os.path.abspath(masked_directory),
                            directory,
                            target_is_directory=True)
                    except OSError:
                        log.warn(
                            f'Failed to create symbolic link {directory} for {os.path.abspath(masked_directory)}.'
                        )

        cache.save_model_version(revision_info=revision_detail)
        cache_root_path = cache.get_root_location()
        return cache_root_path


def get_default_aistudio_cache_dir():
    """
    default base dir: '~/.cache/aistudio'
    """
    default_cache_dir = os.path.expanduser(Path.home().joinpath(
        '.cache', 'aistudio', 'hub'))
    return default_cache_dir


def _download_file_lists(
    repo_files: List[dict],
    cache: ModelFileSystemCache,
    temporary_cache_dir: str,
    repo_id: str,
    repo_type: Optional[str] = None,
    revision: Optional[str] = DEFAULT_MODEL_REVISION,
    allow_patterns: Optional[Union[List[str], str]] = None,
    ignore_patterns: Optional[Union[List[str], str]] = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    token: str = None
):
    """
    download all
    """
    ignore_patterns = _normalize_patterns(ignore_patterns)
    allow_patterns = _normalize_patterns(allow_patterns)

    filtered_repo_files = []
    for repo_file in repo_files:
        if repo_file['type'] == 'tree':
            continue
        try:
            #repo_file = get_git_info(repo_id, repo_file['path'], revision)
            # processing patterns
            if ignore_patterns and any([
                    fnmatch.fnmatch(repo_file['path'], pattern)
                    for pattern in ignore_patterns
            ]):
                continue


            if allow_patterns is not None and allow_patterns:
                if not any(
                        fnmatch.fnmatch(repo_file['path'], pattern)
                        for pattern in allow_patterns):
                    continue

            # check model_file is exist in cache, if existed, skip download
            # if cache.exists(repo_file):
            #     file_name = os.path.basename(repo_file['path'])
            #     log.debug(
            #         f'File {file_name} already in cache with identical hash, skip downloading!'
            #     )
            #     continue
        except Exception as e:
            log.warn('The file pattern is invalid : %s' % e)
        else:
            filtered_repo_files.append(repo_file)


    @thread_executor(max_workers=max_workers, disable_tqdm=False)
    def _download_single_file(repo_file):
        """download each file"""
        repo_file = get_git_info(repo_id, repo_file['path'], revision, token)
        if cache.exists(repo_file):
            file_name = os.path.basename(repo_file['path'])
            log.info(
                f'\nFile {file_name} already in cache with identical hash, skip downloading!'
            )
            return

        if repo_type == REPO_TYPE_MODEL:
            file_path = repo_file['path']
            user_name, repo_name = repo_id.split('/')
            user_name = user_name.strip()
            repo_name = repo_name.strip()
            git_host = os.getenv("STUDIO_GIT_HOST", default=STUDIO_GIT_HOST_DEFAULT)
            url = (
                f"{git_host}/api/v1/repos/"
                f"{quote(user_name, safe='')}/"
                f"{quote(repo_name, safe='')}/media/"
                f"{quote(file_path, safe='')}"
            )
            if revision != 'master':
                url += f"?ref={quote(revision, safe='')}"
        elif repo_type == REPO_TYPE_DATASET:
            file_path = repo_file['path']
            user_name, repo_name = repo_id.split('/')
            user_name = user_name.strip()
            repo_name = repo_name.strip()
            git_host = os.getenv("STUDIO_GIT_HOST", default=STUDIO_GIT_HOST_DEFAULT)
            url = (
                f"{git_host}/api/v1/repos/"
                f"{quote(user_name, safe='')}/"
                f"{quote(repo_name, safe='')}/media/"
                f"{quote(file_path, safe='')}"
            )
            if revision != 'master':
                url += f"?ref={quote(revision, safe='')}"
        else:
            raise InvalidParameter(
                f'Invalid repo type: {repo_type}, supported types: {REPO_TYPE_SUPPORT}'
            )

        download_file(
            url,
            repo_file,
            temporary_cache_dir,
            cache,
            disable_tqdm=False,
            token=token
        )

    if len(filtered_repo_files) > 0:
        log.info(
            f'Got {len(filtered_repo_files)} files, start to download ...')
        _download_single_file(filtered_repo_files)
        log.info(f"Download {repo_type} '{repo_id}' successfully.")


def fetch_repo_files(_api, name, group_or_owner, revision):
    """get repo meta"""
    page_number = 1
    page_size = 150
    repo_files = []

    while True:
        files_list_tree = _api.list_repo_tree(
            dataset_name=name,
            namespace=group_or_owner,
            revision=revision,
            root_path='/',
            recursive=True,
            page_number=page_number,
            page_size=page_size)

        if not ('Code' in files_list_tree and files_list_tree['Code'] == 200):
            log.error(f'Get dataset file list failed, request_id:  \
                {files_list_tree["RequestId"]}, message: {files_list_tree["Message"]}'
                         )
            return None

        cur_repo_files = files_list_tree['Data']['Files']
        repo_files.extend(cur_repo_files)

        if len(cur_repo_files) < page_size:
            break

        page_number += 1

    return repo_files


def _is_valid_regex(pattern: str):
    """check"""
    try:
        re.compile(pattern)
        return True
    except BaseException:
        return False


def _normalize_patterns(patterns: Union[str, List[str]]):
    """normalize"""
    if isinstance(patterns, str):
        patterns = [patterns]
    if patterns is not None:
        patterns = [
            item if not item.endswith('/') else item + '*' for item in patterns
        ]
    return patterns


def _get_valid_regex_pattern(patterns: List[str]):
    """process regex"""
    if patterns is not None:
        regex_patterns = []
        for item in patterns:
            if _is_valid_regex(item):
                regex_patterns.append(item)
        return regex_patterns
    else:
        return None


def get_model_files(
                    model_id: str,
                    revision: Optional[str] = DEFAULT_MODEL_REVISION,
        token: str = None
) -> (List[dict], dict):
    """List the models files.

    """
    endpoint = os.getenv("STUDIO_GIT_HOST", default=STUDIO_GIT_HOST_DEFAULT)
    tag_path = f"{endpoint}/api/v1/repos/{model_id}/tags/{revision}"
    headers = _header_fill(token=token)
    headers['X-Request-ID'] = str(uuid.uuid4().hex)
    page = 1
    per_page = 1000
    files = []
    truncated = True
    revision_info = {}
    # 判断是否是tag
    tag_res = requests.get(tag_path, headers=headers)
    if tag_res.status_code in (200, 201):
        revision = tag_res.json()["commit"]["sha"]
    while truncated:
        path = f"{endpoint}/api/v1/repos/{model_id}/git/trees/{revision}?recursive=true&page={page}&per_page={per_page}"
        r = requests.get(path, headers=headers)

        if r.status_code not in (200, 201):
            print(r)
            raise NotExistError("repo not found")

        d = r.json()
        raise_on_error(d)

        if page == 1:
            parsed_url = urlparse(d["url"])
            file_name = os.path.basename(parsed_url.path)
            revision_info = {"Revision": file_name}

        for file in d.get('tree', []):
            if file['path'] in ('.gitignore', '.gitattributes'):
                continue
            files.append(file)

        truncated = d.get("truncated", False)
        page += 1
    return files, revision_info


def file_exists(
        repo_id: str,
        filename: str,
        *,
        revision: Optional[str] = None,
):
    """Get if the specified file exists

    Args:
        repo_id (`str`): The repo id to use
        filename (`str`): The queried filename, if the file exists in a sub folder,
            please pass <sub-folder-name>/<file-name>
        revision (`Optional[str]`): The repo revision
    Returns:
        The query result in bool value
    """
    files = get_model_files(repo_id, revision=revision)
    files = [file['path'] for file in files]
    return filename in files

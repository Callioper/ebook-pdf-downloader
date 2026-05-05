# !/usr/bin/env python3
# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2023 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""
本文件实现了请求hub

Authors: xiangyiqing(xiangyiqing@baidu.com)
Date:    2023/07/24
"""
import base64
import os
import time
import tqdm
import json
import requests
from urllib.parse import quote
from aistudio_sdk.constant.err_code import ErrorEnum
from aistudio_sdk import config, log
from aistudio_sdk.utils.util import err_resp
from aistudio_sdk.utils.util import gen_ISO_format_datestr
from aistudio_sdk.utils.util import file_to_base64, thread_executor
from aistudio_sdk.utils.util import create_sha256_file_and_encode_base64
from aistudio_sdk.constant.version import VERSION
from aistudio_sdk.errors import RequestError

CONNECTION_RETRY_TIMES = config.CONNECTION_RETRY_TIMES
CONNECTION_TIMEOUT = config.CONNECTION_TIMEOUT
CONNECTION_TIMEOUT_DOWNLOAD = config.CONNECTION_TIMEOUT_DOWNLOAD
CONNECTION_TIMEOUT_UPLOAD = config.CONNECTION_TIMEOUT_UPLOAD


#################### AIStudio 云端模型库 API ####################
def _request_aistudio_hub(method, url, headers, data):
    """
    request aistudio hub
    """
    for _ in range(CONNECTION_RETRY_TIMES):
        try:
            response = requests.request(method, url, headers=headers,
                                        data=data, timeout=CONNECTION_TIMEOUT)
            return response.json()
        except requests.exceptions.JSONDecodeError:
            err_msg = "Response body does not contain valid json: {}".format(response.text)
            biz_code = response.status_code
            log.debug(err_msg)
    return err_resp(ErrorEnum.INTERNAL_ERROR.code, 
                    err_msg[:500],
                    biz_code)


def request_aistudio_hub(**kwargs):
    """
    请求AIStudio hub: 模型库
    """
    headers = _header_fill(token=kwargs['token'])
    kwargs.pop('token')

    url = "{}{}".format(
        os.getenv("STUDIO_MODEL_API_URL_PREFIX", default=config.STUDIO_MODEL_API_URL_PREFIX_DEFAULT), 
        config.HUB_URL
    )

    body = {k: v for k, v in kwargs.items()}
    log.debug(f"request_aistudio_hub url: {url}")
    log.debug(f"request_aistudio_hub body: {body}")

    payload = json.dumps(body)
    resp = _request_aistudio_hub('POST', url, headers, payload)

    return resp

def request_aistudio_app_service(**kwargs):
    """
    请求AIStudio hub：应用库
    """

    headers = _header_fill(token=kwargs['token'])
    kwargs.pop('token')

    url = "{}{}".format(
        os.getenv("STUDIO_MODEL_API_URL_PREFIX", default=config.STUDIO_MODEL_API_URL_PREFIX_DEFAULT),
        config.APP_SERVICE_URL
    )

    body = {k: v for k, v in kwargs.items()}
    log.debug(f"request_aistudio_app_service url: {url}")
    log.debug(f"request_aistudio_app_service body: {body}")
    # log.debug(f"request_aistudio_app_service headers: {headers}")
    payload = json.dumps(body)
    resp = _request_aistudio_hub('POST', url, headers, payload)

    return resp

def request_aistudio_repo_visible(**kwargs):
    """
    请求AIStudio hub 查看repo可见权限
    """
    headers = _header_fill(token=kwargs['token'])

    url = "{}{}".format(
        os.getenv("STUDIO_MODEL_API_URL_PREFIX", default=config.STUDIO_MODEL_API_URL_PREFIX_DEFAULT), 
        config.HUB_URL_VISIBLE_CHECK
    )
    url = url + f"?repoId={quote(kwargs['repoId'], safe='')}&authorization=1"
    method = 'GET'
    try:
        err_msg = ''
        response = requests.request(method, url, headers=headers,
                                    timeout=CONNECTION_TIMEOUT)
        return response.json()
    except requests.exceptions.JSONDecodeError:
        err_msg = "Response body does not contain valid json: {}".format(response)
        biz_code = response.status_code

    return err_resp(ErrorEnum.INTERNAL_ERROR.code, 
                    err_msg[:500],
                    biz_code)


#################### AIStudio Gitea API ####################
def _request_gitea(method, url, headers, data):
    """
    request gitea
    """
    for _ in range(CONNECTION_RETRY_TIMES):
        session = requests.Session()
        response = session.request(method, url, headers=headers, data=data, timeout=CONNECTION_TIMEOUT)
        session.close()

        if response.status_code not in (200, 201):
            log.debug(f"response: {response.text} {response.status_code}")
            log.info(f"potential network problem while request{url}:{response}")
            extra_msg = "[仓库或分支不存在]" if response.status_code == 404 else ""
            return err_resp(ErrorEnum.GITEA_DOWNLOAD_FILE_FAILED.code if
                            method == "GET" else ErrorEnum.GITEA_UPLOAD_FILE_FAILED.code,
                            response.content.decode()[:500] + extra_msg,
                            biz_code=response.status_code)
        else:
            return response.json()


def timing_decorator(func):
    """
    time cost decorator
    """
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        elapsed_time = end_time - start_time
        print(f"{func.__name__} done, time cost: {elapsed_time:.2f}s")
        return result
    return wrapper


@timing_decorator
def _upload(method, url, headers, data):
    """
    _upload proc
    """
    session = requests.Session()
    response = session.request(method, url, headers=headers, data=data, 
                               stream=True, timeout=CONNECTION_TIMEOUT_UPLOAD)
    session.close()

    if response.status_code not in (200, 201):
        return err_resp(ErrorEnum.GITEA_UPLOAD_FILE_FAILED.code, 
                        response.content[:500],
                        biz_code=response.status_code)
    else:
        return response.json()


@timing_decorator
def _download(url, download_path, headers):
    """
    Params
        :url: http url
        :download_path: download path
        :headers: headers
    Returns
        file
    """
    # 默认allow_redirects=True，即自动重定向，如果是LFS文件会直接从BOS下载
    response = requests.request('GET', url, stream=True, headers=headers,
                                timeout=CONNECTION_TIMEOUT_DOWNLOAD)

    if response.status_code == 200:
        ret = {}
    elif response.status_code == 404:
        try:
            message = response.json()["message"]
        except requests.exceptions.JSONDecodeError:
            message = response.content.decode()

        ret = err_resp(ErrorEnum.FILE_NOT_FOUND.code,
                        message,
                        response.status_code)
    else:
        ret = err_resp(ErrorEnum.GITEA_DOWNLOAD_FILE_FAILED.code,
                        f'Download failed, response code: {response.status_code}',
                        response.status_code)

    total_size = int(response.headers.get('content-length', 0))
    block_size = 1024 * 100
    progress_bar = tqdm.tqdm(total=total_size, ncols=50, unit='iB', unit_scale=True,
                             desc='Downloading file')

    with open(download_path, 'wb') as file:
        for data in response.iter_content(block_size):
            progress_bar.update(len(data))
            file.write(data)

    progress_bar.close()
    if total_size != 0 and progress_bar.n != total_size:
        print("ERROR, something went wrong")

    return ret


def request_aistudio_git_download(url, download_path, token):
    """
    请求AIStudio gitea文件下载
    """
    headers = _header_fill(token=token)
    res = _download(url, download_path, headers)
    return res


def request_aistudio_git_file_info(call_host, user_name, repo_name, file_path, 
                                   revision, token):
    """
    请求AIStudio gitea 文件info
    GET /api/v1/repos/{owner}/{repo}/contents/{filepath} 返回的文件的数据、大小、编码等metadata信息+文件内容，或者文件夹中的文件列表
    """
    # 构建查询url
    url = f"{call_host}/api/v1/repos/{quote(user_name, safe='')}/" \
      f"{quote(repo_name, safe='')}/contents/{quote(file_path, safe='')}"
    if revision != 'master':
        url += f"?ref={quote(revision, safe='')}"

    headers = _header_fill(token=token)
    res = _request_gitea('GET', url, headers, "")
    log.debug(f"...result of GET /contents/{file_path}: {res}")
    return res


def request_aistudio_git_file_type(call_host, user_name, repo_name, revision, 
                                   path_in_repo, token):
    """
    请求AIStudio gitea 确认文件类型
    """
    headers = _header_fill(token=token)

    url = f"{call_host}/{quote(user_name, safe='')}/{quote(repo_name, safe='')}/preupload/{quote(revision, safe='')}"
    
    params = {
        "files": [{
            "path": path_in_repo # 远程文件路径（相对于仓库根路径）
        }]
    }

    payload = json.dumps(params)
    result = _request_gitea('POST', url, headers, data=payload)
    log.debug(f"...result of POST /preupload: {url}: {result}")
    if 'error_code' in result:
        res = result
    elif 'files' not in result or not result['files'] or 'lfs' not in result['files'][0]:
        res = err_resp(ErrorEnum.GITEA_FAILED.code, 
                        str(result)[:500])
    else:
        res = {
            'is_lfs': result['files'][0]['lfs']
        }

    return res


def request_aistudio_git_files_type(call_host, user_name, repo_name, revision,
                                   path_in_repo_list, token):
    """
        批量请求 AIStudio gitea 确认多个文件是否为 LFS 类型

        :param path_list: List[str]，每个元素是 repo 内的相对路径
        :return: Dict[str, bool]，key 是路径，value 是是否为 LFS
        """
    headers = _header_fill(token=token)

    url = (f"{call_host}/api/v1/repos/"
           f"{quote(user_name, safe='')}/{quote(repo_name, safe='')}/preupload/{quote(revision, safe='')}")

    params = {
        "files": [{"path": path} for path in path_in_repo_list]
    }

    payload = json.dumps(params)
    result = _request_gitea('POST', url, headers, data=payload)
    log.debug(f"...result of POST /preupload: {url}: {result}")

    if 'error_code' in result:
        raise ValueError(f"preupload fail, there is error_code in result")
    elif 'files' not in result or not isinstance(result['files'], list):
        raise ValueError(f"preupload fail, wrong result format")

    lfs_map = {}
    for file_info in result['files']:
        path = file_info.get('path')
        is_lfs = file_info.get('lfs', False)
        if path:
            lfs_map[path] = is_lfs

    return lfs_map

def _parse_sts_token(upload_section: dict) -> dict:
    """
    解析sts_token

    "upload": {
        "href": "https://some-download.com",
        "header": {
            "Key": "value"
        },
        "sts_token": {
            "bosHost":""
            "bucketName": "",
            "key":"",
            "accessKeyId":"",
            "secretAccessKey":"",
            "sessionToken":"",
            "createTime":"",
            "expiration":""
            }
        "expires_at": "2016-11-10T15:29:07Z"
    }
    """
    sts_token = upload_section.get("sts_token", {})
    if sts_token and sts_token.get("accessKeyId"):
        return {
            "bos_host": sts_token.get("bosHost"),
            "bucket_name": sts_token.get("bucketName"),
            "key": sts_token.get("key"),
            "access_key_id": sts_token.get("accessKeyId"),
            "secret_access_key": sts_token.get("secretAccessKey"),
            "session_token": sts_token.get("sessionToken"),
            "expiration": sts_token.get("expiration")
        }
    return {}



def request_aistudio_git_upload_access(call_host, user_name, repo_name, revision, file_size, 
                                       sha256, token):
    """
    请求AIStudio gitea 申请上传LFS文件.
    只支持单文件
    """
    params = {
        'Content-Type': 'application/vnd.git-lfs+json; charset=utf-8',
        'Accept': 'application/vnd.git-lfs+json'
    }
    headers = _header_fill(params=params, token=token)

    url = f"{call_host}/{quote(user_name, safe='')}/{quote(repo_name, safe='')}.git/info/lfs/objects/batch"

    params = {
        "operation": "upload", # 申请动作为上传
        "objects": [
            {
                "oid": sha256, # SHA256哈希
                "size": file_size  # 单位byte
            }
        ],
        "transfers": [
            "lfs-standalone-file", "basic"
        ],
        "ref": {
            "name": f"refs/heads/{revision}" # 分支
        },
        "hash_algo": "sha256"
    }
    
    payload = json.dumps(params)
    result = _request_gitea('POST', url, headers, payload)
    log.debug(f"...result of POST /batch: {result}")
    if 'error_code' in result:
        res = result
    elif 'objects' not in result or not result['objects']:
        res = err_resp(ErrorEnum.GITEA_FAILED.code, 
                        str(result)[:500])
    else:
        tmp = result['objects'][0]
        # 已经存在的文件，不需要上传，actions为空
        res = {
            'upload': True if 'actions' in tmp and 'upload' in tmp['actions'] else False,
            'upload_href': tmp['actions']['upload']['href'] if 'actions' in tmp else '',
            'sts_token': _parse_sts_token(tmp['actions']['upload']) if 'actions' in tmp else {},
            'verify_href': tmp['actions']['verify']['href'] if 'actions' in tmp else ''
        }

    return res


@timing_decorator
def _lfs_upload(url, path_or_fileobj, headers):
    """
    上传LFS文件到bos
    """
    with open(path_or_fileobj, 'rb') as file:
        response = requests.request('PUT', url, headers=headers, data=file, 
                                    timeout=CONNECTION_TIMEOUT_UPLOAD, stream=True)
    return {'Content-Md5': response.headers['Content-Md5']}


def request_bos_upload(url, path_or_fileobj):
    """
    上传LFS文件到bos
    """
    params = {'Content-Type': 'application/octet-stream'}
    headers = _header_fill(params=params, token='')
    return _lfs_upload(url, path_or_fileobj, headers)


def get_exist_file_old_sha(info_res):
    """
    解析info_res
    """
    if 'error_code' in info_res and info_res['error_code'] != ErrorEnum.SUCCESS.code:
        return ''
    elif not info_res or 'sha' not in info_res:
        return ''
    else:
        old_sha = info_res['sha']
        return old_sha


def request_aistudio_git_upload_pointer(call_host, user_name, repo_name, revision, commit_message, 
                                        sha256, file_size, path_in_repo, token):
    """
    请求AIStudio gitea 上传LFS指针文件（到仓库）
    """
    # 检查指针文件是否已存在，存在的话，要调用更新接口
    info_res = request_aistudio_git_file_info(call_host, user_name, repo_name, path_in_repo, 
                                              revision, token)
    old_sha = get_exist_file_old_sha(info_res)
    if old_sha == '':
        method = 'POST'
    else:
        # 文件已存在，需要调用PUT接口更新
        method = 'PUT'

    headers = _header_fill(token=token)

    url = f"{call_host}/api/v1/repos/{quote(user_name, safe='')}/" \
      f"{quote(repo_name, safe='')}/contents/{quote(path_in_repo, safe='')}"

    params = {
        "branch": revision,     # 提交的分支
        "new_branch": revision, # 提交的分支
        "content": create_sha256_file_and_encode_base64(sha256, file_size),
        "lfsPointer": True,
        "dates": {
            "author": gen_ISO_format_datestr(),
            "committer": gen_ISO_format_datestr()
        },
        "message": commit_message
    }
    if method == 'PUT':
        params['sha'] = old_sha
    payload = json.dumps(params)

    res = _request_gitea(method, url, headers, payload)
    return res


def request_single_git_upload_pointer(call_host, user_name, repo_name, revision,
                                      sha256, file_size, path_in_repo, token):
    """
    请求AIStudio gitea 上传LFS指针文件（到仓库）
    """
    # 检查指针文件是否已存在，存在的话，要调用更新接口
    info_res = request_aistudio_git_file_info(call_host, user_name, repo_name, path_in_repo,
                                              revision, token)
    old_sha = get_exist_file_old_sha(info_res)
    if old_sha == '':
        method = 'POST'
    else:
        # 文件已存在，需要调用PUT接口更新
        method = 'PUT'

    headers = _header_fill(token=token)

    url = f"{call_host}/api/v1/repos/{quote(user_name, safe='')}/" \
      f"{quote(repo_name, safe='')}/contents/{quote(path_in_repo, safe='')}"

    params = {
        "branch": revision,     # 提交的分支
        "new_branch": revision, # 提交的分支
        "content": create_sha256_file_and_encode_base64(sha256, file_size),
        "lfsPointer": True,
        # "dates": {
        #     "author": gen_ISO_format_datestr(),
        #     "committer": gen_ISO_format_datestr()
        # },
        # "message": commit_message
    }
    if method == 'PUT':
        params['sha'] = old_sha
    payload = json.dumps(params)

    res = _request_gitea(method, url, headers, payload)
    return res


def request_aistudio_git_upload_common(call_host, user_name, repo_name, revision, 
                                       commit_message, 
                                       path_or_fileobj, path_in_repo, token):
    """
    请求AIStudio gitea 上传普通文件（到仓库）
    """
    # 检查文件是否已存在，存在的话，要调用更新接口
    info_res = request_aistudio_git_file_info(call_host, user_name, repo_name, path_in_repo, 
                                              revision, token)
    old_sha = get_exist_file_old_sha(info_res)
    if old_sha == '':
        method = 'POST'
    else:
        # 文件已存在，需要调用PUT接口更新
        method = 'PUT'

    url = f"{call_host}/api/v1/repos/{quote(user_name, safe='')}/" \
      f"{quote(repo_name, safe='')}/contents/{quote(path_in_repo, safe='')}"
    headers = _header_fill(token=token)

    base64_data = file_to_base64(path_or_fileobj)

    params = {
        "branch": revision,     # 提交的分支
        "new_branch": revision, # 提交的分支
        "content": base64_data,
        "lfs": False,
        "dates": {
            "author": gen_ISO_format_datestr(),
            "committer": gen_ISO_format_datestr()
        },
        "message": commit_message
    }
    if method == 'PUT':
        params['sha'] = old_sha
    payload = json.dumps(params)

    res = _upload(method, url, headers, payload)

    return res


def request_single_git_upload_common(call_host, user_name, repo_name, revision,
                                       path_or_fileobj, path_in_repo, token):
    """
    请求AIStudio gitea 上传普通文件（到仓库）
    """
    # 检查文件是否已存在，存在的话，要调用更新接口
    info_res = request_aistudio_git_file_info(call_host, user_name, repo_name, path_in_repo,
                                              revision, token)
    old_sha = get_exist_file_old_sha(info_res)
    if old_sha == '':
        method = 'POST'
    else:
        # 文件已存在，需要调用PUT接口更新
        method = 'PUT'

    url = f"{call_host}/api/v1/repos/{quote(user_name, safe='')}/" \
      f"{quote(repo_name, safe='')}/contents/{quote(path_in_repo, safe='')}"
    headers = _header_fill(token=token)

    base64_data = file_to_base64(path_or_fileobj)

    params = {
        # "branch": revision,     # 提交的分支
        # "new_branch": revision, # 提交的分支
        "content": base64_data,
        "lfs": False,
        # "dates": {
        #     "author": gen_ISO_format_datestr(),
        #     "committer": gen_ISO_format_datestr()
        # },
        # "message": commit_message
    }
    if method == 'PUT':
        params['sha'] = old_sha
    payload = json.dumps(params)

    res = _upload(method, url, headers, payload)

    return res

def request_aistudio_verify_lfs_file(call_host, oid: str, size: int, token=''):
    """
    param
        call_host: verify url
        oid: sha256, without sha256prefix
        size: file size

    """
    headers = {
        'Content-Type': 'application/vnd.git-lfs+json',
        'Accept': 'application/vnd.git-lfs+json'
    }
    params = {
        "oid": oid,
        "size": size
    }
    header = _header_fill(headers, token=token)
    res = requests.request("POST", call_host, headers=header, json=params, data=json.dumps(params))
    log.debug(f"...result of POST /verify: {res.text}")
    if res.status_code not in (200, 201):
        return err_resp(ErrorEnum.GITEA_UPLOAD_FILE_FAILED.code,
                        res.text,
                        biz_code=res.status_code)
    else:
        return res.json()


def _header_fill(params=None, token=''):
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


def file_exists_and_sha(repo_id, revision, path, token):
    """检查目标文件是否存在，返回 (exists: bool, sha: str or None)"""
    host = os.getenv("STUDIO_GIT_HOST", default=config.STUDIO_GIT_HOST_DEFAULT)
    url = f"{host}/api/v1/repos/{repo_id}/contents/{path}?ref={revision}"
    headers = _header_fill(token=token)
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        return True, resp.json().get("sha")
    return False, None


def get_lfs_pointer_content(sha256, size):
    """构造 LFS pointer 文件内容（纯文本）"""
    return f"version https://git-lfs.github.com/spec/v1\n" \
           f"oid sha256:{sha256}\nsize {size}\n"


@thread_executor(disable_tqdm=False, max_workers=os.cpu_count())
def prepare_entry(q, repo_id, revision, token):
    """
    prepare body data
    """
    path, local_path, is_lfs, sha256_input = q
    try:
        exists, sha = file_exists_and_sha(repo_id, revision, path, token)
    except Exception as e:
        log.error(f"{path} request git error,skip")
        return None
    if is_lfs:

        size = os.path.getsize(local_path)
        content_b64 = create_sha256_file_and_encode_base64(sha256_input or sha256_input, size)
    else:
        with open(local_path, "rb") as f:
            content_bytes = f.read()
        try:
            content_str = base64.b64encode(content_bytes)
            content_b64 = content_str.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError(f"❌ Non-UTF8 content in {local_path}. Consider LFS or base64 with encoding field.")

    entry = {
        "lfsPointer": is_lfs,
        "path": path,
        "content": content_b64,
        "operation": "update" if exists else "create"
    }
    if sha:
        entry["sha"] = sha

    return entry

MAX_PAYLOAD_MB = 200
MAX_PAYLOAD_BYTES = MAX_PAYLOAD_MB * 1024 * 1024


def split_files_by_size(files, max_bytes=MAX_PAYLOAD_BYTES):
    """
    将 files 拆分为多个分组，每组最大总大小不超过 max_bytes,每组个数不超过1k
    要求每个 file 是一个 dict，包含 'size' 字段（单位字节）。
    """
    chunks = []
    current_chunk = []
    current_size = 0
    current_count = 0

    for file in files:
        file_size = file.get("size", 0)
        if file_size > max_bytes:
            raise ValueError(f"单个文件超过最大限制：{file_size / 1024 / 1024:.2f}MB")

        if (current_size + file_size > max_bytes or current_count + 1 >
                int(os.environ.get("MAX_COMMIT_FILE_COUNT", "500"))):
            chunks.append(current_chunk)
            current_chunk = [file]
            current_size = file_size
            current_count = 0
        else:
            current_chunk.append(file)
            current_size += file_size
            current_count += 1

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def commit_files(log_list, repo_id, revision, commit_message, file_quads, token, author=None, committer=None):
    """
    commit
    """
    if author is None:
        author = {"name": "Auto Commit", "email": "auto@example.com"}
    if committer is None:
        committer = author

    log.info("calculate files")
    log.debug(f"cpu:{os.cpu_count()}")
    files = prepare_entry(file_quads, repo_id=repo_id, revision=revision, token=token)
    files = [item for item in files if item is not None]
    file_chunks = split_files_by_size(files)
    if len(file_chunks) > 1:
        log.info("files will be commited in multi batches")
    host = os.getenv("STUDIO_GIT_HOST", default=config.STUDIO_GIT_HOST_DEFAULT)
    headers = _header_fill(token=token)
    url = f"{host}/api/v1/repos/{repo_id}/contents"
    for i, chunk in enumerate(file_chunks, start=1):
        commit_message_current = commit_message if len(file_chunks) == 1 \
            else f"{commit_message} (part {i}/{len(file_chunks)})"
        chunk_payload = {
            "branch": revision,
            "message": commit_message_current,
            "author": author,
            "committer": committer,
            "files": chunk
        }

        resp = requests.post(url, headers=headers, json=chunk_payload)

        if resp.status_code // 100 == 2:
            print(resp.status_code)
            print(f"✅ Commit part {i} successful!")
        else:
            for entry in chunk:
                for path, local_path, is_lfs, sha256_input in file_quads:
                    if entry['path'] == path:
                        log_list.append((local_path, "commit fail"))
            print(f"❌ Commit part {i} failed: {resp.status_code}")
            print(resp.text)

# !/usr/bin/env python3
# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2023 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""
本文件实现了模型库hub接口封装

TODO: 
    当前脚本后续将移动至sdk目录下, 但用法将发生变化, 需和pm确认
    旧：
        from aistudio_sdk.hub import create_repo
        create_repo()
    新：
        from aistudio_sdk import hub
        hub.create_repo()

Authors: linyichong(linyichong@baidu.com)
Date:    2023/08/21
"""
from typing import Optional
import requests
import os
import io
import logging
import traceback
from pathlib import Path
from aistudio_sdk.constant.err_code import ErrorEnum
from aistudio_sdk.requests.hub import request_aistudio_hub, request_aistudio_app_service
from aistudio_sdk.requests.hub import request_aistudio_git_file_info, commit_files
from aistudio_sdk.requests.hub import request_aistudio_git_file_type, request_aistudio_git_files_type
from aistudio_sdk.requests.hub import request_aistudio_git_upload_access
from aistudio_sdk.requests.hub import request_bos_upload
from aistudio_sdk.requests.hub import request_aistudio_git_upload_pointer
from aistudio_sdk.requests.hub import request_aistudio_git_upload_common, request_single_git_upload_common
from aistudio_sdk.requests.hub import get_exist_file_old_sha
from aistudio_sdk.requests.hub import request_aistudio_repo_visible
from aistudio_sdk.requests.hub import request_aistudio_verify_lfs_file, request_single_git_upload_pointer
from aistudio_sdk.utils.util import convert_to_dict_object, is_valid_host, calculate_sha256
from aistudio_sdk.utils.util import err_resp
from aistudio_sdk.utils.util import (extract_yaml_block, is_readme_md, get_file_size,
                                     get_file_hash, thread_executor)
from aistudio_sdk import log
from aistudio_sdk import config
from aistudio_sdk.dot import post_upload_statistic_async
from typing import (List, Union, BinaryIO, Iterable, Callable, Generator, TypeVar,
                    Dict, Any, Literal, Iterator)
from dataclasses import dataclass
from fnmatch import fnmatch
from contextlib import contextmanager

T = TypeVar('T')


__all__ = [
    "create_repo",
    "upload",
    "file_exists",
    "upload_folder",
    "upload_file"
]

UploadMode = Literal['lfs', 'normal']

FORBIDDEN_FOLDERS = ['.git', '.cache']

class UploadFileException(Exception):
    """
    上传文件异常
    """
    pass

class Hub():
    """Hub类"""
    OBJECT_NAME = "hub"

    def __init__(self):
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

        self.upload_checker = UploadingCheck()

    def create_repo(self, **kwargs):
        """
        创建一个repo仓库并返回创建成功后的信息。
        Params:
            repo_id (str): 仓库名称，格式为user_name/repo_name 或者 repo_name，必填。
            repo_type (str): 仓库类型，取值为app/model，分别为应用仓库和模型仓库。如果未指定，默认为model。
            app_name (str): 应用名称，如果repo_type为app，则必填。默认值为repo_id (如果不填，后端自动生成）。

            app_sdk (str): 应用SDK, 如果repo_type为app，则必填，可以填写 streamlit, gradio, static 三种
            version (str): streamlit 或 gradio 版本，必填
                * gradio版本支持"4.26.0", "4.0.0"
                * streamlit版本支持"1.33.0", "1.30.0"
            model_name (str): 模型名称，如果repo_type为model，则必填。默认值为repo_id。
            desc (str): 仓库描述，可选，默认为空。
            license (str): 仓库许可证，可选，默认为"Apache License 2.0"。
            private (bool): 是否私有仓库，可选，默认为False。
            token (str): 认证令牌，可选，默认为环境变量的值。
        Demo:
            创建应用仓库：
            create_repo(repo_id='app_repo_0425',
                        app_sdk='streamlit',
                        version="1.33.0"
                        desc='my app demo')
        Returns:
            dict: 仓库创建结果。
        """
        params = {}
        if "repo_id" not in kwargs:
            return err_resp(ErrorEnum.PARAMS_INVALID.code, ErrorEnum.PARAMS_INVALID.message)

        # 设置默认repo_type为'model'
        repo_type = kwargs.get('repo_type', 'model')
        if repo_type == 'app':
            if 'app_name' not in kwargs:
                return err_resp(ErrorEnum.PARAMS_INVALID.code,
                                ErrorEnum.PARAMS_INVALID.message + "should provide param app_name")

            app_sdk = kwargs.get('app_sdk')
            if not app_sdk or app_sdk not in ['streamlit', 'gradio', 'static']:
                return err_resp(ErrorEnum.PARAMS_INVALID.code,
                                ErrorEnum.PARAMS_INVALID.message + "app_sdk should be streamlit, gradio or static.")
            if app_sdk == "streamlit":
                if 'version' not in kwargs:
                    return err_resp(ErrorEnum.PARAMS_INVALID.code,
                                    "streamlit version needed.")
                params["streamlitVersion"] = kwargs['version']

            if app_sdk == "gradio":
                if 'version' not in kwargs:
                    return err_resp(ErrorEnum.PARAMS_INVALID.code,
                                    "gradio version needed.")
                params["gradioVersion"] = kwargs['version']

        elif repo_type == 'model' and 'model_name' not in kwargs:
            kwargs['model_name'] = kwargs.get('repo_id')

        if 'private' in kwargs and not isinstance(kwargs['private'], bool):
            return err_resp(ErrorEnum.PARAMS_INVALID.code, "private should be bool type.")

        for key in ['repo_id', 'model_name', 'license', 'token']:
            if key in kwargs:
                if not isinstance(kwargs[key], str):
                    return err_resp(ErrorEnum.PARAMS_INVALID.code, "should be str type: " + key)
                kwargs[key] = kwargs[key].strip()
                if not kwargs[key]:
                    return err_resp(ErrorEnum.PARAMS_INVALID.code, "should not be empty: " + key)

        if not os.getenv("AISTUDIO_ACCESS_TOKEN") and 'token' not in kwargs:
            return err_resp(ErrorEnum.TOKEN_IS_EMPTY.code, ErrorEnum.TOKEN_IS_EMPTY.message)

        if 'desc' in kwargs and not isinstance(kwargs['desc'], str):
            return err_resp(ErrorEnum.PARAMS_INVALID.code, ErrorEnum.PARAMS_INVALID.message)

        repo_name_raw = kwargs['repo_id']
        if "/" in repo_name_raw:
            user_name, repo_name = repo_name_raw.split('/')
            user_name = user_name.strip()
            repo_name = repo_name.strip()
            if not repo_name or not user_name:
                return err_resp(ErrorEnum.PARAMS_INVALID.code,
                                "user_name or repo_name is empty. repo_id should be user_name/repo_name format.")
            kwargs['repo_id'] = repo_name
        else:
            kwargs['repo_id'] = repo_name_raw.strip()
            # return err_resp(ErrorEnum.PARAMS_INVALID.code,
            #                 "r epo_id should be user_name/repo_name format.")

        if repo_type == 'model':

            more_params = {
                'repoType': 0 if kwargs.get('private') else 1,
                'repoName': kwargs['repo_id'],
                'modelName': kwargs.get('model_name', ''),  # 添加模型名
                'desc': kwargs.get('desc', ''),
                'license': kwargs.get('license', 'Apache License 2.0'),
                'token': kwargs.get('token', '')
            }
            params.update(more_params)
            resp = convert_to_dict_object(request_aistudio_hub(**params))
        else:
            more_params = {
                'repoType': 0 if kwargs.get('private') else 1,
                'repoName': kwargs['repo_id'],
                'appName': kwargs.get('app_name', ''),
                'appType': kwargs.get('app_sdk', ''),
                'desc': kwargs.get('desc', ''),
                'license': kwargs.get('license', 'Apache License 2.0'),
                'token': kwargs.get('token', '')
            }
            params.update(more_params)

            resp_raw = request_aistudio_app_service(**params)
            log.debug(f"create_repo resp: {resp_raw}")
            resp = convert_to_dict_object(resp_raw)
            log.debug(f"create_repo resp dict: {resp}")

        if 'errorCode' in resp and resp['errorCode'] != 0:
            log.error(f"create_repo failed: {resp}")
            if "repo already created" in resp['errorMsg']:
                res = err_resp(ErrorEnum.REPO_ALREADY_EXIST.code, 
                               resp['errorMsg'],
                               resp['errorCode'],
                               resp['logId'])  # 错误logid透传
            else:
                res = err_resp(ErrorEnum.AISTUDIO_CREATE_REPO_FAILED.code, 
                               resp['errorMsg'],
                               resp['errorCode'],
                               resp['logId'])
            return res

        if repo_type == 'model':
            res = {
                'model_name': resp['result']['modelName'],
                'repo_id': resp['result']['repoName'],
                'private': True if resp['result']['repoType'] == 0 else False,
                'desc': resp['result']['desc'],
                'license': resp['result']['license']
            }
        else:
            res = {
                'app_id': resp['result']['appId'],
                'app_name': resp['result']['appName'],
                'repo_id': resp['result']['repoName'],
                'desc': resp['result']['desc'],
                'license': resp['result']['license']
            }
        return res

    def _upload_lfs_file(self, settings, file_path, file_size):
        """
        上传文件
        settings: 上传文件的配置信息
        settings = {
            'upload'[bool]: True or False
            'upload_href'[str]:  upload url
            'sts_token'[dict]: sts token
                {
                "bos_host":"",
                "bucket_name": "",
                "key":"",
                "access_key_id": "",
                "secret_access_key": "",
                "session_token": "",
                "expiration": ""
                }
        }
        file_path: 本地文件路径
        """
        if not settings.get('upload'):
            logging.info("file already exists, skip the upload.")
            return True

        upload_href = settings['upload_href']
        sts_token = settings.get('sts_token', {})
        is_sts_valid = False
        if sts_token and sts_token.get("bos_host"):
            is_sts_valid = True

        is_http_valid = True if upload_href and file_size < config.LFS_FILE_SIZE_LIMIT_PUT else False

        def _uploading_using_sts():
            """
            使用sts上传文件
            """
            from aistudio_sdk.utils.bos_sdk import sts_client, upload_file, upload_super_file
            try:
                client = sts_client(sts_token.get("bos_host"), sts_token.get("access_key_id"),
                           sts_token.get("secret_access_key"), sts_token.get("session_token"))
                res = upload_super_file(client,
                                        bucket=sts_token.get("bucket_name"), file=file_path, key=sts_token.get("key"))
                return res
            except Exception as e:
                raise UploadFileException(e)


        def _uploading_using_http():
            """
            使用http上传文件
            """
            try:
                res = request_bos_upload(upload_href, file_path)
                if 'error_code' in res and res['error_code'] != ErrorEnum.SUCCESS.code:
                    return res
                return True
            except Exception as e:
                raise UploadFileException(e)

        functions = []
        if is_sts_valid:
            functions.append(_uploading_using_sts)
        if is_http_valid:
            functions.append(_uploading_using_http)
        if not os.environ.get("PERFER_STS_UPLOAD", default="true") == "true":
            functions.reverse()
        if not functions:
            logging.error("no upload method available.")
            return False

        upload_success = False
        for func in functions:
            try:
                logging.info(f"uploading file using {func.__name__}")
                res = func()
                if res is True:
                    logging.info(f"upload lfs file success. {func.__name__}")
                    upload_success = True
                    break
                else:
                    logging.error(f"upload lfs file failed. {func.__name__}: {res}")
            except UploadFileException as e:
                logging.error(f"upload lfs file failed. {func.__name__}: {e}")
                logging.debug(traceback.format_exc())

        return upload_success


    @staticmethod
    def _get_suffix_forbidden(repo_id):
        try:
            url = "{}{}".format(
                os.getenv("STUDIO_MODEL_API_URL_PREFIX", default=config.STUDIO_MODEL_API_URL_PREFIX_DEFAULT),
                config.BLACK_LIST_URL
            )
            if repo_id:
                url = f"{url}?repoId={repo_id}"
            response = requests.get(url)
            if response.status_code == 200:
                r = response.json()
                if r['errorCode'] == 0:
                    return r['result']
                else:
                    return []
        except Exception as e:
            log.error(f"get black list fail:{e}")
        return []



    def file_exists(self, repo_id, filename, *args, **kwargs):
        """
        文件是否存在
        params:
            repo_id: 仓库id，格式为user_name/repo_name
            filename: 仓库中的文件路径
            revision: 分支名
            token: 认证令牌
        """
        # 参数检查
        str_params_not_valid = 'params not valid.'
        kwargs['repo_id'] = repo_id
        kwargs['filename'] = filename

        # 检查入参值的格式类型
        for key in ['filename', 'repo_id', 'revision', 'token']:
            if key in kwargs:
                if type(kwargs[key]) != str:
                    return err_resp(ErrorEnum.PARAMS_INVALID.code, 
                                    ErrorEnum.PARAMS_INVALID.message)
                kwargs[key] = kwargs[key].strip()
                if not kwargs[key]:
                    return err_resp(ErrorEnum.PARAMS_INVALID.code, 
                                    ErrorEnum.PARAMS_INVALID.message)
        revision = kwargs['revision'] if kwargs.get('revision') else 'master'
        file_path = kwargs['filename']
        token = kwargs['token'] if 'token' in kwargs else ''

        repo_name = kwargs['repo_id']
        if "/" not in repo_name:
            return err_resp(ErrorEnum.PARAMS_INVALID.code, 
                            ErrorEnum.PARAMS_INVALID.message)

        user_name, repo_name = repo_name.split('/')
        user_name = user_name.strip()
        repo_name = repo_name.strip()
        if not repo_name or not user_name:
            return err_resp(ErrorEnum.PARAMS_INVALID.code, 
                            ErrorEnum.PARAMS_INVALID.message)

        call_host = os.getenv("STUDIO_GIT_HOST", default=config.STUDIO_GIT_HOST_DEFAULT)
        if not is_valid_host(call_host):
            return err_resp(ErrorEnum.PARAMS_INVALID.code, 
                            'host not valid.')

        if os.environ.get("SKIP_REPO_VISIBLE_CHECK", default="false") != "true":
            # 检查仓库可见权限(他人的预发布仓库不能下载、查看)
            params = {
                'repoId': kwargs['repo_id'],
                'token': kwargs['token'] if 'token' in kwargs else ''
            }
            resp = convert_to_dict_object(request_aistudio_repo_visible(**params))
            if 'errorCode' in resp and resp['errorCode'] != 0:
                res = err_resp(ErrorEnum.AISTUDIO_NO_REPO_READ_AUTH.code,
                                resp['errorMsg'],
                                resp['errorCode'],
                                resp['logId'])
                return res

        # 查询文件是否存在
        info_res = request_aistudio_git_file_info(call_host, user_name, repo_name, file_path, 
                                                  revision, token)
        if get_exist_file_old_sha(info_res) == '':
            return False
        else:
            return True

    def _prepare_upload_folder(
            self,
            folder_path_or_files: Union[str, Path, List[str], List[Path]],
            path_in_repo: str,
            allow_patterns: Optional[Union[List[str], str]] = None,
            ignore_patterns: Optional[Union[List[str], str]] = None,
    ):
        folder_path = None
        files_path = None
        if isinstance(folder_path_or_files, list):
            if os.path.isfile(folder_path_or_files[0]):
                files_path = folder_path_or_files
            else:
                raise ValueError('Uploading multiple folders is not supported now.')
        else:
            if os.path.isfile(folder_path_or_files):
                files_path = [folder_path_or_files]
            else:
                folder_path = folder_path_or_files

        if files_path is None:
            self.upload_checker.check_folder(folder_path)
            folder_path = Path(folder_path).expanduser().resolve()
            if not folder_path.is_dir():
                raise ValueError(f"Provided path: '{folder_path}' is not a directory")

            # List files from folder
            relpath_to_abspath = {
                path.relative_to(folder_path).as_posix(): path
                for path in sorted(folder_path.glob('**/*'))  # sorted to be deterministic
                if path.is_file()
            }
        else:
            relpath_to_abspath = {}
            for path in files_path:
                if os.path.isfile(path):
                    self.upload_checker.check_file(path)
                    relpath_to_abspath[os.path.basename(path)] = path

        # Filter files
        filtered_repo_objects = list(
            UploadingCheck.filter_repo_objects(
                relpath_to_abspath.keys(), allow_patterns=allow_patterns, ignore_patterns=ignore_patterns
            )
        )

        prefix = f"{path_in_repo.strip('/')}/" if path_in_repo else ''

        prepared_repo_objects = [
            (prefix + relpath, str(relpath_to_abspath[relpath]))
            for relpath in filtered_repo_objects
        ]

        return prepared_repo_objects

    def upload_file(
            self,
            *,
            path_or_fileobj: Union[str, Path, bytes, BinaryIO],
            path_in_repo: str,
            repo_id: str,
            token: Union[str, None] = None,
            repo_type: Optional[str] = config.REPO_TYPE_MODEL,
            commit_message: Optional[str] = None,
            revision: Optional[str] = config.DEFAULT_REPOSITORY_REVISION,
    ):
        """
        upload single file
        """

        if repo_type not in config.REPO_TYPE_SUPPORT:
            raise ValueError(f'Invalid repo type: {repo_type}, supported repos: {config.REPO_TYPE_SUPPORT}')

        if not path_or_fileobj:
            raise ValueError('Path or file object cannot be empty!')

        if isinstance(path_or_fileobj, (str, Path)):
            path_or_fileobj = os.path.abspath(os.path.expanduser(path_or_fileobj))
            path_in_repo = path_in_repo or os.path.basename(path_or_fileobj)

        else:
            # If path_or_fileobj is bytes or BinaryIO, then path_in_repo must be provided
            if not path_in_repo:
                raise ValueError('Arg `path_in_repo` cannot be empty!')

        commit_message = (
            commit_message if commit_message is not None else f'Add {path_in_repo}'
        )
        # Read file content if path_or_fileobj is a file-like object (BinaryIO)
        if isinstance(path_or_fileobj, io.BufferedIOBase):
            path_or_fileobj = path_or_fileobj.read()

        self.upload_folder(repo_id=repo_id, folder_path=path_or_fileobj,
                      path_in_repo=path_in_repo, token=token, repo_type=repo_type, commit_message=commit_message,
                      revision=revision, single=True)


    def upload_folder(
            self,
            repo_id: str,
            folder_path: Union[str, Path, List[str], List[Path]] = None,
            path_in_repo: Optional[str] = '',
            commit_message: Optional[str] = None,
            token: Union[str, None] = None,
            repo_type: Optional[str] = config.REPO_TYPE_MODEL,
            allow_patterns: Optional[Union[List[str], str]] = None,
            ignore_patterns: Optional[Union[List[str], str]] = None,
            max_workers: int = config.DEFAULT_MAX_WORKERS,
            revision: Optional[str] = config.DEFAULT_REPOSITORY_REVISION,
            single: bool = False
    ):
        """upload"""
        if repo_type not in config.REPO_TYPE_SUPPORT:
            raise ValueError(f'Invalid repo type: {repo_type}, supported repos: {config.REPO_TYPE_SUPPORT}')
        if token is None:
            token = os.getenv("AISTUDIO_ACCESS_TOKEN")

        allow_patterns = allow_patterns if allow_patterns else None
        ignore_patterns = ignore_patterns if ignore_patterns else None

        # Ignore .git folder
        if ignore_patterns is None:
            ignore_patterns = []
        elif isinstance(ignore_patterns, str):
            ignore_patterns = [ignore_patterns]

        commit_message = (
            commit_message if commit_message is not None else f'Upload folder to repo'
        )

        if single:
            prepared_repo_objects = [(path_in_repo, folder_path)]
        else:
            # Get the list of files to upload, e.g. [('data/abc.png', '/path/to/abc.png'), ...]
            prepared_repo_objects = self._prepare_upload_folder(
                folder_path_or_files=folder_path,
                path_in_repo=path_in_repo,
                allow_patterns=allow_patterns,
                ignore_patterns=ignore_patterns,
            )

        git_host = os.getenv("STUDIO_GIT_HOST", default=config.STUDIO_GIT_HOST_DEFAULT)
        user_name, repo_name = repo_id.split('/')
        user_name = user_name.strip()
        repo_name = repo_name.strip()
        if not repo_name or not user_name:
            raise ValueError("repo_name or user_name is empty,abort upload.")

        repo_path_list = []
        for name, _ in prepared_repo_objects:
            repo_path_list.append(name)

        if len(repo_path_list) == 0:
            return

        lfs_map = request_aistudio_git_files_type(git_host, user_name, repo_name,
                                             revision, repo_path_list, token)

        lfs_local_path_map = {}

        for remote_path, local_path in prepared_repo_objects:
            lfs_local_path_map[local_path] = lfs_map[remote_path]

        self.upload_checker.check_normal_files(
            file_path_list=[item for _, item in prepared_repo_objects],
            lfs_map=lfs_local_path_map
        )
        black_extensions = self._get_suffix_forbidden(repo_id)


        @thread_executor(max_workers=max_workers, disable_tqdm=False)
        def _upload_items(item_pair, log_list):
            file_path_in_repo, file_path = item_pair
            if is_readme_md(file_path=file_path) and file_path_in_repo == 'README.md' and revision == "master":
                try:
                    url = "{}{}".format(
                        os.getenv("STUDIO_MODEL_API_URL_PREFIX", default=config.STUDIO_MODEL_API_URL_PREFIX_DEFAULT),
                        config.README_CHECK_URL)
                    yaml_content = extract_yaml_block(file_path)
                    payload = {
                        "yaml": yaml_content,
                        "repoId": repo_id
                    }
                    headers = {
                        "Content-Type": "application/json"
                    }
                    response = requests.post(url, json=payload, headers=headers, timeout=(10, 10))
                    if response.status_code == 200:
                        data = response.json()
                        if data.get('errorCode') == 0:
                            log.debug(f"调用成功，logId:{data.get('logId')}")
                        else:
                            error_msg = data.get("errorMsg")
                            log.error(f"check readme fail:{error_msg},skip{file_path}")
                            log_list.append((file_path, f"check readme fail{error_msg}"))
                            return None
                except Exception as e:
                    log.info(f"check readme fail:{e}")
                    log_list.append((file_path, f"check readme fail:{e}"))
                    return None
            suffix = Path(file_path).suffix.lower()
            if black_extensions and suffix in black_extensions:
                log.info(f"File:{file_path}  forbidden! Skip.")
                log_list.append((file_path, "file type forbidden"))
                return None

            hash_info_d: dict = get_file_hash(
                file_path_or_obj=file_path,
            )
            file_size: int = hash_info_d['file_size']
            file_hash: str = hash_info_d['file_hash']


            return self._upload_and_gather_commit_info(
                repo_id=repo_id,
                sha256=file_hash,
                size=file_size,
                data=file_path,
                token=token,
                revision=revision,
                file_path_in_repo=file_path_in_repo,
                git_host=git_host,
                is_lfs=lfs_map.get(file_path_in_repo),
                log_list=log_list
            )

        skip_list = []
        uploaded_item_raw = _upload_items(
            prepared_repo_objects,
            log_list=skip_list
        )
        uploaded_item_list = [item for item in uploaded_item_raw if item is not None]
        if len(uploaded_item_list) == 0 or uploaded_item_list is None:
            log.error('nothing to commit')
            return

        commit_files(
            log_list=skip_list,
            repo_id=repo_id,
            revision=revision,
            commit_message=commit_message,
            file_quads=uploaded_item_list,
            token=token
        )
        if len(skip_list) > 0:
            print('these files were skipped with reasons:')
            for local_path, reason in skip_list:
                print(f"{local_path}: {reason}")


    def _upload_and_gather_commit_info(
            self,
            *,
            repo_id: str,
            sha256: str,
            size: int,
            data: str,
            token: str,
            revision: str,
            file_path_in_repo: str,
            git_host: str,
            is_lfs: bool,
            log_list
    ):


        if "/" not in repo_id:
            raise ValueError("repo_id should be user_name/repo_name format.")

        user_name, repo_name = repo_id.split('/')
        user_name = user_name.strip()
        repo_name = repo_name.strip()
        if not repo_name or not user_name:
            raise ValueError("repo_name or user_name is empty,abort upload.")


        if is_lfs:
            try:
                pre_res = request_aistudio_git_upload_access(git_host, user_name, repo_name, revision,
                                                             size, sha256, token)
            except Exception as e:
                log.error(f"{data} request upload_access fail,skip，{e}")
                log_list.append((data, "request upload_access fail"))
                return None
            logging.debug(f"the request_aistudio_git_upload_access res: {pre_res}")
            if 'error_code' in pre_res and pre_res['error_code'] != ErrorEnum.SUCCESS.code:
                log.error(f"{data} upload fail due to request git upload error:{pre_res}")
                log_list.append((data, "upload fail due to request git upload error"))
                return None
            if not pre_res.get('upload'):
                log.info(f'file {data} with sha {sha256[:8]} has already uploaded.')
                return file_path_in_repo, data, is_lfs, sha256
            upload_res = self._upload_lfs_file(pre_res, data, size)
            if not upload_res:
                log.error(f"upload this lfs file {data} failed. 文件上传终止")
                log_list.append((data, "upload lfs file failed,server error "))
                return None
            if pre_res.get("verify_href"):
                verify_res = request_aistudio_verify_lfs_file(pre_res.get("verify_href"), sha256, size, token)
                logging.info(f"verify lfs file res: {verify_res}")
                if 'error_code' in verify_res and verify_res['error_code'] != ErrorEnum.SUCCESS.code:
                    logging.error(f"verify lfs file failed:{data}.")
                    log_list.append((data, "verify lfs file failed"))
                    return None

            # 第五步：上传LFS指针文件（到仓库）
            # lfs_res = request_single_git_upload_pointer(git_host, user_name, repo_name, revision,
            #                                         sha256, size, file_path_in_repo, token)
            return file_path_in_repo, data, is_lfs, sha256
        else:
            log.debug("Start uploading this common file.")
            # 如果大小超标，报错返回
            if size > config.COMMON_FILE_SIZE_LIMIT:
                log.error(f"File:{data} is larger than 5MB for a common file. Fail")
                log_list.append((data, "larger than 5MB for a common file"))
                return None
        return file_path_in_repo, data, is_lfs, sha256


class UploadingCheck:
    """
    check class
    """
    def __init__(
            self,
            max_file_count: int = config.UPLOAD_MAX_FILE_COUNT,
            max_file_count_in_dir: int = config.UPLOAD_MAX_FILE_COUNT_IN_DIR,
            max_file_size: int = config.UPLOAD_MAX_FILE_SIZE,
            size_threshold_to_enforce_lfs: int = config.UPLOAD_SIZE_THRESHOLD_TO_ENFORCE_LFS,
            normal_file_size_total_limit: int = config.UPLOAD_NORMAL_FILE_SIZE_TOTAL_LIMIT,
    ):
        self.max_file_count = max_file_count
        self.max_file_count_in_dir = max_file_count_in_dir
        self.max_file_size = max_file_size
        self.size_threshold_to_enforce_lfs = size_threshold_to_enforce_lfs
        self.normal_file_size_total_limit = normal_file_size_total_limit

    def check_file(self, file_path_or_obj):
        """
        check size
        """

        if isinstance(file_path_or_obj, (str, Path)):
            if not os.path.exists(file_path_or_obj):
                raise ValueError(f'File {file_path_or_obj} does not exist')

        file_size: int = get_file_size(file_path_or_obj)
        if file_size > self.max_file_size:
            log.warn(f'File exceeds size limit: {self.max_file_size / (1024 ** 3)} GB, '
                           f'got {round(file_size / (1024 ** 3), 4)} GB')

    def check_folder(self, folder_path: Union[str, Path]):
        """
        check
        """
        file_count = 0
        dir_count = 0

        if isinstance(folder_path, str):
            folder_path = Path(folder_path)

        for item in folder_path.iterdir():
            if item.is_file():
                file_count += 1
                item_size: int = get_file_size(item)
                if item_size > self.max_file_size:
                    log.warn(f'File {item} exceeds size limit: {self.max_file_size / (1024 ** 3)} GB, '
                             f'got {round(item_size / (1024 ** 3), 4)} GB')
            elif item.is_dir():
                dir_count += 1
                sub_file_count, sub_dir_count = self.check_folder(item)
                if (sub_file_count + sub_dir_count) > self.max_file_count_in_dir:
                    raise ValueError(f'Directory {item} contains {sub_file_count + sub_dir_count} items '
                                     f'and exceeds limit: {self.max_file_count_in_dir}')
                file_count += sub_file_count
                dir_count += sub_dir_count

        if file_count > self.max_file_count:
            raise ValueError(f'Total file count {file_count} and exceeds limit: {self.max_file_count}')

        return file_count, dir_count



    def check_normal_files(self, file_path_list: List[Union[str, Path]], lfs_map: dict):
        """
        check
        """

        normal_file_list = [item for item in file_path_list if not lfs_map[item]]
        total_size = sum([get_file_size(item) for item in normal_file_list])

        if total_size > self.normal_file_size_total_limit:
            raise ValueError(f'Total size of non-lfs files {total_size / (1024 * 1024)}MB '
                             f'and exceeds limit: {self.normal_file_size_total_limit / (1024 * 1024)}MB')

    @staticmethod
    def filter_repo_objects(
            items: Iterable[T],
            *,
            allow_patterns: Optional[Union[List[str], str]] = None,
            ignore_patterns: Optional[Union[List[str], str]] = None,
            key: Optional[Callable[[T], str]] = None,
    ):
        """Filter repo objects based on an allowlist and a denylist.

        Input must be a list of paths (`str` or `Path`) or a list of arbitrary objects.
        In the later case, `key` must be provided and specifies a function of one argument
        that is used to extract a path from each element in iterable.

        Patterns are Unix shell-style wildcards which are NOT regular expressions. See
        https://docs.python.org/3/library/fnmatch.html for more details.

        Args:
            items (`Iterable`):
                List of items to filter.
            allow_patterns (`str` or `List[str]`, *optional*):
                Patterns constituting the allowlist. If provided, item paths must match at
                least one pattern from the allowlist.
            ignore_patterns (`str` or `List[str]`, *optional*):
                Patterns constituting the denylist. If provided, item paths must not match
                any patterns from the denylist.
            key (`Callable[[T], str]`, *optional*):
                Single-argument function to extract a path from each item. If not provided,
                the `items` must already be `str` or `Path`.

        Returns:
            Filtered list of objects, as a generator.

        Raises:
            :class:`ValueError`:
                If `key` is not provided and items are not `str` or `Path`.

        Example usage with paths:
        ```python
        >>> # Filter only PDFs that are not hidden.
        >>> list(UploadingCheck.filter_repo_objects(
        ...     ["aaa.PDF", "bbb.jpg", ".ccc.pdf", ".ddd.png"],
        ...     allow_patterns=["*.pdf"],
        ...     ignore_patterns=[".*"],
        ... ))
        ["aaa.pdf"]
        ```
        """

        allow_patterns = allow_patterns if allow_patterns else None
        ignore_patterns = ignore_patterns if ignore_patterns else None

        if isinstance(allow_patterns, str):
            allow_patterns = [allow_patterns]

        if isinstance(ignore_patterns, str):
            ignore_patterns = [ignore_patterns]

        if allow_patterns is not None:
            allow_patterns = [
                UploadingCheck._add_wildcard_to_directories(p)
                for p in allow_patterns
            ]
        if ignore_patterns is not None:
            ignore_patterns = [
                UploadingCheck._add_wildcard_to_directories(p)
                for p in ignore_patterns
            ]

        if key is None:

            def _identity(item: T):
                if isinstance(item, str):
                    return item
                if isinstance(item, Path):
                    return str(item)
                raise ValueError(
                    f'Please provide `key` argument in `filter_repo_objects`: `{item}` is not a string.'
                )

            key = _identity  # Items must be `str` or `Path`, otherwise raise ValueError

        for item in items:
            path = key(item)

            # Skip if there's an allowlist and path doesn't match any
            if allow_patterns is not None and not any(
                    fnmatch(path, r) for r in allow_patterns):
                continue

            # Skip if there's a denylist and path matches any
            if ignore_patterns is not None and any(
                    fnmatch(path, r) for r in ignore_patterns):
                continue

            yield item

    @staticmethod
    def _add_wildcard_to_directories(pattern: str):
        if pattern[-1] == '/':
            return pattern + '*'
        return pattern

def create_repo(**kwargs):
    """
    创建
    """
    return Hub().create_repo(**kwargs)


def upload(**kwargs):
    """
    上传
    """
    log.error("This function is not supported.Please use upload_file instead.")
    return None


def upload_file(*,
            path_or_fileobj: Union[str, Path, bytes, BinaryIO],
            path_in_repo: str,
            repo_id: str,
            token: Union[str, None] = None,
            repo_type: Optional[str] = config.REPO_TYPE_MODEL,
            commit_message: Optional[str] = None,
            revision: Optional[str] = config.DEFAULT_REPOSITORY_REVISION,):
    """
    single file
    """
    return Hub().upload_file(path_or_fileobj=path_or_fileobj,
                             path_in_repo=path_in_repo,
                             repo_id=repo_id,
                             token=token,
                             repo_type=repo_type,
                             commit_message=commit_message,
                             revision=revision)


def upload_folder(*,
            repo_id: str,
            folder_path: Union[str, Path, List[str], List[Path]] = None,
            path_in_repo: Optional[str] = '',
            commit_message: Optional[str] = None,
            token: Union[str, None] = None,
            repo_type: Optional[str] = config.REPO_TYPE_MODEL,
            allow_patterns: Optional[Union[List[str], str]] = None,
            ignore_patterns: Optional[Union[List[str], str]] = None,
            max_workers: int = config.DEFAULT_MAX_WORKERS,
            revision: Optional[str] = config.DEFAULT_REPOSITORY_REVISION,):
    """
    上传
    """
    return Hub().upload_folder(
            repo_id,
            folder_path,
            path_in_repo,
            commit_message,
            token,
            repo_type,
            allow_patterns,
            ignore_patterns,
            max_workers,
            revision,)


def file_exists(repo_id, filename, *args, **kwargs):
    """
    检查云端文件存在与否
    """
    return Hub().file_exists(repo_id, filename, *args, **kwargs)

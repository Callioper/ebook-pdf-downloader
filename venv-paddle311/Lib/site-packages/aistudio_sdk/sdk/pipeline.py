# !/usr/bin/env python3
# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2024 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""
本文件实现了产线任务提交、查询、停止功能

Authors: xiangyiqing(xiangyiqing@baidu.com), suoyi@baidu.com
Date:    2024/3/2
"""
import os
from pathlib import Path
from prettytable import PrettyTable
from aistudio_sdk import log, config
from aistudio_sdk.constant.err_code import ErrorEnum
from aistudio_sdk.constant.const import AUTH_DIR, AUTH_TOKEN_FILE, LOG_DIR, LOG_LEVEL_FILE
from aistudio_sdk.utils.util import zip_dir, err_resp
from aistudio_sdk.utils.bos_sdk import upload_super_file, MyBosClient, upload_file
from aistudio_sdk.requests import pipeline as pp_request
from aistudio_sdk.requests import dataset as ds_request
from baidubce.bce_client_configuration import BceClientConfiguration
from baidubce.auth.bce_credentials import BceCredentials
from baidubce.exception import BceHttpClientError
from baidubce.services.bos.bos_client import BosClient

__all__ = [
    "set_config",
    "create",
    "query",
    "stop",
]


def get_detail_url(pipeline_id):
    """拼接产线详情链接"""
    return f"{config.STUDIO_MODEL_API_URL_PREFIX_DEFAULT}/pipeline/{pipeline_id}/detail"


def tabled_log_info(detail_list):
    """
    表格化打印
    tabled_log_info([
        ["pipeline_id", "args.summit_name", "status", "get_detail_url(pipeline_id)", "create_ime"], 
        [], 
        ...
    ])
    """
    table = PrettyTable()
    table.field_names = ["pid", "name", "status", "url", "createTime"]
    for detail in detail_list:
        table.add_row(detail)
    log.info(table)


class Pipeline():
    """
    pipeline类
    """
    OBJECT_NAME = "pipeline"

    def set_config(self, args):
        """
        配置: token, log_level
        """
        log.debug(f'鉴权配置，参数: {args}')
        token = args.token
        if token:
            try:
                # create folder
                if not os.path.exists(AUTH_DIR):
                    Path(AUTH_DIR).mkdir(parents=True, exist_ok=True)
                # save in file
                with open(AUTH_TOKEN_FILE, 'w') as file:
                    file.write(token)
                log.info(f"[OK] Configuration saved to: {AUTH_TOKEN_FILE}")
            except Exception as e:
                log.error(f"[Error] Configuration faild: {e}")

        log_level = args.log
        if log_level:
            try:
                # create folder
                if not os.path.exists(LOG_DIR):
                    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
                # save in file
                with open(LOG_LEVEL_FILE, 'w') as file:
                    file.write(log_level)
                log.info(f"[OK] Configuration saved to: {LOG_LEVEL_FILE}")
            except Exception as e:
                log.error(f"[Error] Configuration faild: {e}")


    def get_auth(self):
        """
        获取鉴权token
        """
        if not os.path.exists(AUTH_TOKEN_FILE):
            return None
        try:
            with open(AUTH_TOKEN_FILE, 'r') as file:
                return file.read().strip()
        except Exception as e:
            log.error(f"[Error] Read configuration faild: {e}")
            return None
    

    def create(self, args):
        """
        创建产线任务
        """
        log.debug(f'创建产线，参数: {args}')

        # 校验
        token = self.get_auth()
        if not token:
            log.error(err_resp(
                ErrorEnum.TOKEN_IS_EMPTY.code, 
                ErrorEnum.TOKEN_IS_EMPTY.message + ', 请使用 aistudio config --token {yourToken}'
            ))
            return
        if len(args.mount_dataset) > config.MOUNT_DATASET_LIMIT:
            log.error(err_resp(
                ErrorEnum.PARAMS_INVALID.code, 
                f"{ErrorEnum.PARAMS_INVALID.message}: 单个任务最多挂载{config.MOUNT_DATASET_LIMIT}个数据集"
            ))
            return

        # 代码打包
        input_path = args.path
        zip_file = f"{input_path}.zip"
        if not os.path.exists(input_path):
            log.error(err_resp(
                ErrorEnum.FILE_NOT_FOUND.code, 
                ErrorEnum.FILE_NOT_FOUND.message
            ))
            return
        if not os.path.isdir(input_path):
            log.error(err_resp(
                ErrorEnum.NEED_FOLDER.code, 
                ErrorEnum.NEED_FOLDER.message
            ))
            return
        try:
            log.debug(f"step 1: 开始打包代码... {input_path}")
            zip_dir(input_path, zip_file)
            log.debug(f"代码打包完成! {zip_file}")
        except Exception as e:
            log.error(err_resp(
                ErrorEnum.INTERNAL_ERROR.code, 
                f"{ErrorEnum.INTERNAL_ERROR.message}: 压缩出错\n{e}"
            ))
            return
        if config.PIPELINE_CODE_SIZE_LIMIT < os.stat(zip_file).st_size:
            log.error(err_resp(
                ErrorEnum.FILE_TOO_LARGE.code, 
                f"{ErrorEnum.FILE_TOO_LARGE.message}: 代码包总体积不能超过 {config.PIPELINE_CODE_SIZE_LIMIT / 1024 / 1024} MB"
            ))
            return
        
        # 请求创建产线（仅参数校验）
        try:
            log.debug("step 2: 请求参数校验...")
            dataset_list = []
            for dataset_id in args.mount_dataset:
                dataset_list.append({
                    "datasetId": dataset_id
                })
            resp = pp_request.create(
                token, 
                args.summit_name, 
                args.cmd, 
                args.env, 
                args.device, 
                args.gpus,
                args.payment, 
                dataset_list
            )
        except pp_request.RequestPipelineException as e:
            log.error(err_resp(
                ErrorEnum.REQUEST_CREATE_PIPELINE_FAILED.code, 
                f"{ErrorEnum.REQUEST_CREATE_PIPELINE_FAILED.message}: {e[:500]}"
            ))
            return
        if resp["errorCode"] != ErrorEnum.SUCCESS.code:
            log.error(err_resp(
                ErrorEnum.REQUEST_CREATE_PIPELINE_FAILED.code, 
                f'{ErrorEnum.REQUEST_CREATE_PIPELINE_FAILED.message}: {resp["errorMsg"]}',
                resp["errorCode"],
                resp["logId"],
            ))
            return
        log.debug("参数校验成功!")
        pipeline_id = resp["result"]["pipelineId"]
        
        # 申请ak/sk
        try:
            log.debug("step 3: 请求申请ak/sk...")
            resp = pp_request.bosacl(token, pipeline_id)
        except pp_request.RequestPipelineException as e:
            log.error(err_resp(
                ErrorEnum.REQUEST_BOSACL_FAILED.code, 
                f"{ErrorEnum.REQUEST_BOSACL_FAILED.message}: {e[:500]}"
            ))
            return
        if resp["errorCode"] != ErrorEnum.SUCCESS.code:
            log.error(err_resp(
                ErrorEnum.REQUEST_BOSACL_FAILED.code, 
                f'{ErrorEnum.REQUEST_BOSACL_FAILED.message}: {resp["errorMsg"]}',
                resp["errorCode"],
                resp["logId"],
            ))
            return
        log.debug("申请ak/sk成功!")

        result = resp["result"]
        endpoint = result["endpoint"]
        bucket_name = result["bucketName"]
        file_key = result["fileKey"]
        access_key_id = result["accessKeyId"]
        secret_access_key = result["secretAccessKey"]
        session_token = result["sessionToken"]
        
        # bos上传
        try:
            log.debug("step 4: 代码上传bos...")
            pp_request.bos_upload(
                zip_file, 
                endpoint, 
                bucket_name, 
                file_key, 
                access_key_id, 
                secret_access_key, 
                session_token
            )
        except Exception as e:
            # 创建产线回调
            pp_request.create_callback(
                token, 
                pipeline_id, 
                False
            )
            log.error(err_resp(
                ErrorEnum.BOS_UPLOAD_FAILED.code, 
                f"{ErrorEnum.BOS_UPLOAD_FAILED.message}: {e[:500]}"
            ))
            return
        log.debug("代码上传成功!")
        
        # 创建产线回调
        try:
            log.debug("step 5: 回调请求创建产线...")
            resp = pp_request.create_callback(
                token, 
                pipeline_id, 
                True, 
                file_key, 
                os.path.basename(zip_file)
            )
        except pp_request.RequestPipelineException as e:
            log.error(err_resp(
                ErrorEnum.REQUEST_CREATE_PIPELINE_CALLBACK_FAILED.code, 
                f"{ErrorEnum.REQUEST_CREATE_PIPELINE_CALLBACK_FAILED.message}: {e[:500]}"
            ))
            return
        if resp["errorCode"] != ErrorEnum.SUCCESS.code:
            log.error(err_resp(
                ErrorEnum.REQUEST_CREATE_PIPELINE_CALLBACK_FAILED.code, 
                f'{ErrorEnum.REQUEST_CREATE_PIPELINE_CALLBACK_FAILED.message}: {resp["errorMsg"]}',
                resp["errorCode"],
                resp["logId"],
            ))
            return
        log.debug("创建成功!")
        
        result = resp["result"]
        stage = result["stage"]
        create_ime = result["createTime"]
        tabled_log_info([
            [
                pipeline_id, 
                args.summit_name, 
                stage, 
                get_detail_url(pipeline_id), 
                create_ime
            ]
        ])


    def query(self, args):
        """
        查询产线
        """
        log.debug(f'查询产线，参数: {args}')

        # 校验
        token = self.get_auth()
        if not token:
            log.error(err_resp(
                ErrorEnum.TOKEN_IS_EMPTY.code, 
                ErrorEnum.TOKEN_IS_EMPTY.message + ', 请使用 aistudio config --token {yourToken}'
            ))
            return
        
        # 请求
        try:
            resp = pp_request.query(
                token, 
                args.query_pipeline_id, 
                args.name, 
                args.status
            )
        except pp_request.RequestPipelineException as e:
            log.error(err_resp(
                ErrorEnum.REQUEST_QUERY_PIPELINE_FAILED.code, 
                f"{ErrorEnum.REQUEST_QUERY_PIPELINE_FAILED.message}: {e[:500]}"
            ))
            return
        if resp["errorCode"] != ErrorEnum.SUCCESS.code:
            log.error(err_resp(
                ErrorEnum.REQUEST_QUERY_PIPELINE_FAILED.code, 
                f'{ErrorEnum.REQUEST_QUERY_PIPELINE_FAILED.message}: {resp["errorMsg"]}',
                resp["errorCode"],
                resp["logId"],
            ))
            return
        
        data = list()
        for res in resp["result"]:
            data.append(
                [
                    res["pipelineId"], 
                    res["pipelineName"], 
                    res["stage"], 
                    get_detail_url(res["pipelineId"]), 
                    res["createTime"]
                ]
            )
        tabled_log_info(data)

    def stop(self, args):
        """
        停止产线
        """
        log.debug(f'停止产线，参数: {args}')

        # 校验
        token = self.get_auth()
        if not token:
            log.error(err_resp(
                ErrorEnum.TOKEN_IS_EMPTY.code, 
                ErrorEnum.TOKEN_IS_EMPTY.message + ', 请使用 aistudio config --token {yourToken}'
            ))
            return
        
        # 请求
        try:
            resp = pp_request.stop(token, args.stop_pipeline_id)
        except pp_request.RequestPipelineException as e:
            log.error(err_resp(
                ErrorEnum.REQUEST_STOP_PIPELINE_FAILED.code, 
                f"{ErrorEnum.REQUEST_STOP_PIPELINE_FAILED.message}: {e[:500]}"
            ))
            return
        if resp["errorCode"] != ErrorEnum.SUCCESS.code:
            log.error(err_resp(
                ErrorEnum.REQUEST_STOP_PIPELINE_FAILED.code, 
                f'{ErrorEnum.REQUEST_STOP_PIPELINE_FAILED.message}: {resp["errorMsg"]}',
                resp["errorCode"],
                resp["logId"],
            ))
            return
        log.info('[OK] 停止成功.')

    def list_output_files(self, args):
        """
        列出某个 job 的 output 目录下的文件
        """
        log.debug(f'列出 job 输出文件，参数: {args}')

        # 校验
        token = self.get_auth()
        if not token:
            log.error(err_resp(
                ErrorEnum.TOKEN_IS_EMPTY.code,
                ErrorEnum.TOKEN_IS_EMPTY.message + ', 请使用 aistudio config --token {yourToken}'
            ))
            return

        # 申请ak/sk
        try:
            log.debug("请求申请ak/sk...")
            resp = pp_request.bosacl_ls_cp(token, args.job_id)
        except pp_request.RequestPipelineException as e:
            log.error(err_resp(
                ErrorEnum.REQUEST_BOSACL_FAILED.code,
                f"{ErrorEnum.REQUEST_BOSACL_FAILED.message}: {str(e)[:500]}"
            ))
            return
        if resp["errorCode"] != ErrorEnum.SUCCESS.code:
            log.error(err_resp(
                ErrorEnum.REQUEST_BOSACL_FAILED.code,
                f'{ErrorEnum.REQUEST_BOSACL_FAILED.message}: {resp["errorMsg"]}',
                resp["errorCode"],
                resp["logId"],
            ))
            return
        log.debug("申请ak/sk成功!")

        result = resp["result"]
        endpoint = result["endpoint"]
        bucket_name = result["bucketName"]
        access_key_id = result["accessKeyId"]
        secret_access_key = result["secretAccessKey"]
        session_token = result["sessionToken"]
        file_key = result["fileKey"]
        file_key = file_key.lstrip('/')
        # 以 / 结尾，列出文件夹下所有文件
        file_key = file_key.rstrip('/') + '/'
        if args.directory:
            args.directory = args.directory.lstrip('/')
            args.directory = args.directory.rstrip('/')

            if args.directory:
                args.directory = args.directory + '/'
                file_key = file_key + args.directory
        # 创建 BOS 客户端配置
        bos_conf = BceClientConfiguration(
            credentials=BceCredentials(access_key_id, secret_access_key),
            endpoint=endpoint,
            security_token=session_token
        )
        bos_client = BosClient(bos_conf)

        # 列出 output 目录下的文件
        try:
            log.debug(f"列出 output 目录下的文件和文件夹...[{file_key}]")
            respose = bos_client.list_objects(bucket_name, prefix=file_key, delimiter="/")
            log.info(f'文件和文件夹列表:')
            for file in respose.contents:
                key = file.key.replace(file_key, '')
                if key:
                    log.info(key)
            for d in respose.common_prefixes:
                log.info(d.prefix.replace(file_key, ''))

        except BceHttpClientError as e:
            log.error(err_resp(
                ErrorEnum.BOS_LIST_FILES_FAILED.code,
                f"{ErrorEnum.BOS_LIST_FILES_FAILED.message}: {str(e)}"
            ))
            return

    def download_output_file(self, args):
        """
        下载某个 job 的 output 目录下的文件到本地
        """
        log.debug(f'下载 job 输出文件，参数: {args}')

        # 校验
        token = self.get_auth()
        if not token:
            log.error(err_resp(
                ErrorEnum.TOKEN_IS_EMPTY.code,
                ErrorEnum.TOKEN_IS_EMPTY.message + ', 请使用 aistudio config --token {yourToken}'
            ))
            return

        # 申请ak/sk
        try:
            log.debug("请求申请ak/sk...")
            resp = pp_request.bosacl_ls_cp(token, args.job_id)
        except pp_request.RequestPipelineException as e:
            log.error(err_resp(
                ErrorEnum.REQUEST_BOSACL_FAILED.code,
                f"{ErrorEnum.REQUEST_BOSACL_FAILED.message}: {str(e)[:500]}"
            ))
            return
        if resp["errorCode"] != ErrorEnum.SUCCESS.code:
            log.error(err_resp(
                ErrorEnum.REQUEST_BOSACL_FAILED.code,
                f'{ErrorEnum.REQUEST_BOSACL_FAILED.message}: {resp["errorMsg"]}',
                resp["errorCode"],
                resp["logId"],
            ))
            return
        log.debug("申请ak/sk成功!")

        result = resp["result"]
        endpoint = result["endpoint"]
        bucket_name = result["bucketName"]
        access_key_id = result["accessKeyId"]
        secret_access_key = result["secretAccessKey"]
        session_token = result["sessionToken"]
        file_key = result["fileKey"]
        file_key = file_key.lstrip('/')
        # 以 / 结尾，列出文件夹下所有文件
        file_key = file_key.rstrip('/') + '/'

        # 创建 BOS 客户端配置
        bos_conf = BceClientConfiguration(
            credentials=BceCredentials(access_key_id, secret_access_key),
            endpoint=endpoint,
            security_token=session_token
        )
        bos_client = BosClient(bos_conf)
        bos_file = file_key + args.result_file
        # 下载 output 目录下的文件
        local_file_name = os.path.basename(args.result_file)
        if args.local_path == ".":
            args.local_path = os.path.join(os.getcwd(), local_file_name)
        if os.path.isdir(args.local_path):
            args.local_path = os.path.join(args.local_path, local_file_name)
        log.debug(f"下载 output 目录下的文件[{bos_file}] 到 {args.local_path}")
        try:

            bos_client.get_object_to_file(bucket_name, file_key + args.result_file, args.local_path)
            log.info(f'文件下载成功: {args.local_path}')
        except BceHttpClientError as e:
            log.error(f"下载失败：请检查文件是否存在：{args.result_file}")
            log.error(err_resp(
                ErrorEnum.BOS_DOWNLOAD_FAILED.code,
                f"{ErrorEnum.BOS_DOWNLOAD_FAILED.message}: {str(e)[:500]}"
            ))
            return

    def _upload_files(self, token, files):
        """
        上传文件
        """
        # 申请ak/sk
        # 上传文件
        file_ids = []
        local_files = files
        i = 1
        for local_file_path in local_files:
            try:
                log.debug("请求申请ak/sk...")
                resp = ds_request.bos_acl_dataset_file(token)
            except ds_request.RequestDatasetException as e:
                log.error(err_resp(
                    ErrorEnum.REQUEST_BOSACL_FAILED.value[0],
                    f"{ErrorEnum.REQUEST_BOSACL_FAILED.value[1]}: {str(e)[:500]}"
                ))
                return None

            if resp["errorCode"] != ErrorEnum.SUCCESS.value[0]:
                log.error(err_resp(
                    ErrorEnum.REQUEST_BOSACL_FAILED.value[0],
                    f'{ErrorEnum.REQUEST_BOSACL_FAILED.value[1]}: {resp["errorMsg"]}',
                    resp["errorCode"],
                    resp["logId"],
                ))
                return None
            log.debug(f"申请ak/sk成功!")

            result = resp["result"]
            endpoint = result["endpoint"]
            bucket_name = result["bucketName"]
            access_key_id = result["accessKeyId"]
            secret_access_key = result["secretAccessKey"]
            session_token = result["sessionToken"]
            file_key = result["fileKey"]

            # 创建 BOS 客户端配置
            bos_conf = BceClientConfiguration(
                credentials=BceCredentials(access_key_id, secret_access_key),
                endpoint=endpoint,
                security_token=session_token
            )
            bos_client = MyBosClient(bos_conf)

            if local_file_path.startswith("/"):
                local_file_path = os.path.abspath(local_file_path)
            log.debug(f"上传第{i}个文件[{local_file_path}]到BOS路径")
            i += 1
            if not os.path.exists(local_file_path):
                log.error(err_resp(
                    ErrorEnum.UPLOAD_FILE_NOT_FOUND.value[0],
                    f"{ErrorEnum.UPLOAD_FILE_NOT_FOUND.value[1]}: {local_file_path}"
                ))
                log.info(f"上传失败（文件不存在）：{local_file_path}")
                continue
            try:
                upload_super_file(bos_client, bucket_name, local_file_path, file_key)
                # bos_client.put_object_from_file(bucket_name, f"{file_key}", local_file_path)
                log.debug(f'BOS文件上传成功')
            except BceHttpClientError as e:
                log.error(err_resp(
                    ErrorEnum.BOS_UPLOAD_FAILED.value[0],
                    f"{ErrorEnum.BOS_UPLOAD_FAILED.value[1]}: {str(e)[:500]}"
                ))
                log.error(f"BOS文件上传失败：{local_file_path}")
                continue
            file_id = ds_request.add_file(token, os.path.basename(local_file_path), file_key, bucket_name)
            if file_id:
                file_ids.append(file_id)
                log.debug(f"add file: {file_id}")
            else:
                log.error(err_resp(
                    ErrorEnum.BOS_UPLOAD_FAILED.value[0],
                    f"{ErrorEnum.BOS_UPLOAD_FAILED.value[1]}: 上传文件失败"
                ))
                log.info("add file 失败")
        log.debug(f"所有文件上传结束: {file_ids}")
        return file_ids

    def create_dataset(self, args):
        """
        创建数据集
        """
        log.debug(f'创建数据集，参数: {args}')
        if len(args.name) > 40:
            log.error(err_resp(
                ErrorEnum.PARAMS_INVALID.value[0],
                f"{ErrorEnum.PARAMS_INVALID.value[1]}: 数据集名称长度不能超过40个字符"
            ))
            return

        # 校验
        token = self.get_auth()
        if not token:
            log.error(err_resp(
                ErrorEnum.TOKEN_IS_EMPTY.value[0],
                ErrorEnum.TOKEN_IS_EMPTY.value[1] + ', 请使用 aistudio config --token {yourToken}'
            ))
            return
        file_ids = self._upload_files(token, args.files)

        if file_ids:
            log.debug("创建数据集...")
            # 创建数据集
            dataset_type = 2 if args.public else 1
            dataset_id = ds_request.create_dataset(token, args.name, file_ids,
                                                   dataset_type=dataset_type,
                                                   dataset_abs=args.description,
                                                   dataset_license=args.license)
            if dataset_id:
                log.info(f'数据集创建成功: {args.name} id: {dataset_id}')
            else:
                log.error("数据集创建失败")
        else:
            log.error(err_resp(
                ErrorEnum.DATASET_CREATION_FAILED.value[0],
                f"{ErrorEnum.DATASET_CREATION_FAILED.value[1]}: 本地文件上传失败"
            ))


    def add_file(self, args):
        """
        上传数据集文件
        """
        log.debug(f'上传数据集文件，参数: {args}')
        token = self.get_auth()
        if not token:
            log.error(err_resp(
                ErrorEnum.TOKEN_IS_EMPTY.value[0],
                ErrorEnum.TOKEN_IS_EMPTY.value[1] + ', 请使用 aistudio config --token {yourToken}'
            ))
            return
        file_ids = self._upload_files(token, args.files)
        if file_ids:
            log.debug(f'add file 成功 {file_ids}')
            res = ds_request.add_files_to_dataset(token, args.id, file_ids)

        else:
            log.error(f"add file 失败")
            log.error(err_resp(
                ErrorEnum.DATASET_CREATION_FAILED.value[0],
                f"{ErrorEnum.DATASET_CREATION_FAILED.value[1]}: 本地文件上传失败"
            ))

def set_config(*args):
    """config"""
    return Pipeline().set_config(*args)

def create(*args):
    """create"""
    return Pipeline().create(*args)

def query(*args):
    """query"""
    return Pipeline().query(*args)

def stop(*args):
    """stop"""
    return Pipeline().stop(*args)

def list_output_files(*args):
    """stop"""
    return Pipeline().list_output_files(*args)

def download_output_file(*args):
    """stop"""
    return Pipeline().download_output_file(*args)

def create_dataset(*args):
    """stop"""
    return Pipeline().create_dataset(*args)

def add_file(*args):
    """stop"""
    return Pipeline().add_file(*args)


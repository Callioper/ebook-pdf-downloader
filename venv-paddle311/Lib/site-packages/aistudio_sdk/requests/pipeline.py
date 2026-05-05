# !/usr/bin/env python3
# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2024 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""
本文件实现了请求产线任务

Authors: xiangyiqing(xiangyiqing@baidu.com)
Date:    2024/3/2
"""
import json
import requests
from aistudio_sdk import config, log
from baidubce.bce_client_configuration import BceClientConfiguration
from baidubce.auth.bce_credentials import BceCredentials
from baidubce.services.bos.bos_client import BosClient

class RequestPipelineException(Exception):
    """
    exception for requesting pipeline server
    """
    pass


def _request(
        method: str, 
        url: str, 
        headers: dict, 
        params: dict, 
        data
    ):
    """request api
    :param url: http url
    :param headers: dictionary of HTTP Headers to send
    :param json_data: json data to send in the body
    :param data: dictionary, list of tuples, bytes, or file-like object to send in the body
    :return: response data in json format
    """
    log.debug(f"\n- method: {method}\n- url: {url}\n- headers: {headers}\n- params: {params}\n- data: {data}")
    err_msg = ''
    for _ in range(config.CONNECTION_RETRY_TIMES):
        try:
            response = requests.request(
                method, 
                url, 
                headers=headers, 
                params=params, 
                data=data, 
                timeout=config.CONNECTION_TIMEOUT
            )
            log.debug(f"\n- response: {response.json()}")
            return response.json()
        except requests.exceptions.JSONDecodeError:
            err_msg = "Response body does not contain valid json: {}".format(response)
        except Exception as e:
            err_msg = 'Error occurred when request for "{}": {}.'.format(url, str(e))
    log.debug(f"\n- err_msg: {err_msg}")
    raise RequestPipelineException(err_msg)


def _request_pipepline(
        token: str, 
        method: str, 
        url: str, 
        params: dict, 
        data
    ):
    """
    请求pp-pipeline API
    """
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'token {token}'
    }
    access_url = f"{config.STUDIO_MODEL_API_URL_PREFIX_DEFAULT}{url}"
    return _request(method, access_url, headers, params, data)
    

def create(
        token: str, 
        name: str, 
        cmd: str, 
        env: str, 
        device: str, 
        gpus: str, 
        payment: str, 
        dataset: dict
    ):
    """
    请求创建产线
    """
    body = {
        "name": name,
        "cmd": cmd,
        "env": env,
        "device": device,
        "gpus": gpus,
        "payment": payment,
        "dataset": dataset,
    }
    return _request_pipepline(
        token, 
        "POST", 
        config.PIPELINE_CREATE_URL, 
        None,
        json.dumps(body)
    )


def bosacl(
        token: str, 
        pipeline_id: str
    ):
    """
    申请ak/sk
    """
    body = {
        'source': 'SDK',
        'pipelineId': pipeline_id,
    }
    return _request_pipepline(
        token, 
        "GET", 
        config.PIPELINE_BOSACL_URL, 
        body,
        None
    )

def bosacl_ls_cp(
        token: str,
        pipeline_id: str
    ):
    """
    申请ak/sk
    """
    body = {
        'source': 'customCodeOutput',
        'pipelineId': pipeline_id,
    }
    return _request_pipepline(
        token,
        "GET",
        config.PIPELINE_BOSACL_URL,
        body,
        None
    )



def bos_upload(
        local_file: str, 
        endpoint: str, 
        bucket_name: str, 
        file_key: str, 
        access_key_id: str, 
        secret_access_key: str, 
        session_token: str
    ):
    """
    本地文件 上传至bos指定位置
    """
    # sts配置
    bos_conf = BceClientConfiguration(
        credentials=BceCredentials(access_key_id, secret_access_key),
        endpoint=endpoint,  # "bj.bcebos.com"
        security_token=session_token
    )
    bos_client = BosClient(bos_conf)

    # 从文件中上传的Object
    bos_client.put_object_from_file(bucket_name, file_key.lstrip("/"), local_file)


def create_callback(
        token: str, 
        pipeline_id: str, 
        is_succuss: bool, 
        file_key: str = None, 
        file_name: str = None
    ):
    """
    创建产线回调, 成功or失败
    """
    body = {
        "pipelineId": pipeline_id,
        "success": is_succuss,
        "fileKey": file_key,
        "fileName": file_name, # 真实文件名
    }
    return _request_pipepline(
        token, 
        "POST", 
        config.PIPELINE_CREATE_CALLBACK_URL, 
        None,
        json.dumps(body)
    )


def query(
        token: str, 
        pipeline_id: str, 
        name: str, 
        status: str
    ):
    """
    查询产线
    """
    body = {
        "pipelineId": pipeline_id,
        "pipelineName": name,
        "stage": status,
    }
    return _request_pipepline(
        token, 
        "POST", 
        config.PIPELINE_QUERY_URL, 
        None,
        json.dumps(body)
    )


def stop(
        token: str, 
        pipeline_id: str
    ):
    """
    停止产线
    """
    body = {
        "pipelineId": pipeline_id,
    }
    return _request_pipepline(
        token, 
        "POST", 
        config.PIPELINE_STOP_URL, 
        None,
        json.dumps(body)
    )

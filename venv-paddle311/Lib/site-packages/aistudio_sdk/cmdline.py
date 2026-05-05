#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2024 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""
命令行

Authors: xiangyiqing(xiangyiqing@baidu.com),suoyi@baidu.com
Date:    2024/03/05
"""
import sys
import argparse
import click
import os
from aistudio_sdk import log
from aistudio_sdk.sdk import pipeline
from aistudio_sdk.file_download import model_file_download, file_download
from aistudio_sdk.snapshot_download import snapshot_download
from aistudio_sdk.utils.util import convert_patterns
from aistudio_sdk.config import (DEFAULT_MAX_WORKERS, REPO_TYPE_SUPPORT, REPO_TYPE_MODEL,
                                 DEFAULT_DATASET_REVISION, REPO_TYPE_DATASET)
from aistudio_sdk.hub import upload_file, upload_folder

__all__ = [
    'main',
]


class CustomHelpFormatter(argparse.RawTextHelpFormatter):
    """
    自定义帮助信息格式
    """
    pass

def init():
    """
    构建CLI Parser
    """
    log.cli_log()
    parser = argparse.ArgumentParser(prog='PROG', formatter_class=CustomHelpFormatter)
    subparser_aistudio = parser.add_subparsers(
        help='AI Studio CLI SDK',
        dest='command'
    )

    # config 子命令，用于身份认证和日志级别设置
    # 用法示例:
    # aistudio config -t <token> -l info
    config = subparser_aistudio.add_parser(
        'config',
        help='首次使用AI Studio CLI管理任务时, 需要先使用AI Studio账号的访问令牌进行身份认证。\
            一次认证后，再次使用时无需认证。'
    )
    config.add_argument(
        '-t', '--token',
        type=str,
        required=False,
        default='',
        help='AI Studio账号的访问令牌'
    )
    config.add_argument(
        '-l', '--log',
        type=str,
        required=False,
        default='',
        choices=['info', 'debug', ''],
        help='日志级别'
    )

    # submit 子命令，用于提交SDK产线任务
    # 用法示例:
    # aistudio submit job -n <name> -p <path> -c <cmd> -e <env> -d <device> -g <gpus> -pay <payment> -m <mount_dataset>
    submit = subparser_aistudio.add_parser(
        'submit',
        help='提交SDK产线任务'
    )
    subparser_submit = submit.add_subparsers()

    # submit job 子命令及其参数
    submit_job = subparser_submit.add_parser(
        'job',
        help='提交SDK产线任务'
    )
    submit_job.add_argument(
        '-n', '--name',
        type=str,
        required=True,
        dest='summit_name',
        help='产线任务名称'
    )
    submit_job.add_argument(
        '-p', '--path',
        type=str,
        required=True,
        help='代码包本地路径(文件夹)，要求文件总体积不超过50MB'
    )
    submit_job.add_argument(
        '-c', '--cmd',
        type=str,
        required=True,
        help='任务启动命令'
    )
    submit_job.add_argument(
        '-e', '--env',
        type=str,
        required=False,
        default='paddle2.6_py3.10',
        choices=['paddle2.4_py3.7', 'paddle2.5_py3.10', 'paddle2.6_py3.10', 'paddle3.0_py3.10'],
        help='飞桨框架版本, 默认paddle2.6_py3.10'
    )
    submit_job.add_argument(
        '-d', '--device',
        type=str,
        required=False,
        default='v100',
        choices=['v100'],
        help='硬件资源, 默认v100'
    )
    submit_job.add_argument(
        '-g', '--gpus',
        type=int,
        required=False,
        default='1',
        choices=[1, 4, 8],
        help='gpu数量, 默认单卡'
    )
    submit_job.add_argument(
        '-pay', '--payment',
        type=str,
        required=False,
        default='acoin',
        choices=['acoin', 'coupon'],
        help='计费方式: * acoin-A币 * coupon-算力点. 默认使用A币'
    )
    submit_job.add_argument(
        '-m', '--mount_dataset',
        action='append',
        type=int,
        required=False,
        default=[],
        help='数据集挂载, 单个任务最多挂载3个'
    )

    # jobs 子命令，用于查询SDK产线任务
    # 用法示例:
    # aistudio jobs <query_pipeline_id> -n <name> -s <status>
    jobs = subparser_aistudio.add_parser(
        'jobs',
        help='查询SDK产线任务'
    )
    jobs.add_argument(
        'query_pipeline_id',
        type=str,
        nargs='?',
        default='',
        help='产线id'
    )
    jobs.add_argument(
        '-n', '--name',
        type=str,
        required=False,
        default='',
        help='产线名称'
    )
    jobs.add_argument(
        '-s', '--status',
        type=str,
        required=False,
        default='',
        help='状态'
    )

    # stop 子命令，用于停止SDK产线任务
    # 用法示例:
    # aistudio stop job <stop_pipeline_id> -f
    stop = subparser_aistudio.add_parser(
        'stop',
        help='停止SDK产线任务'
    )
    subparser_stop = stop.add_subparsers()

    # stop job 子命令及其参数
    stop_job = subparser_stop.add_parser(
        'job',
        help='停止SDK产线任务'
    )
    stop_job.add_argument(
        'stop_pipeline_id',
        type=str,
        help='产线id'
    )
    stop_job.add_argument(
        '-f', '--force',
        action='store_true',
        help='强制停止，无需二次确认'
    )

    # 创建主命令解析器
    job = subparser_aistudio.add_parser(
        'job',
        help='管理SDK产线任务'
    )

    # 添加 'job_id' 参数
    job.add_argument(
        'job_id',
        type=str,
        help='任务ID'
    )
    # 创建job子命令的解析器
    subparser_job = job.add_subparsers(dest='command', required=True, help='job子命令')

    # 'ls' 子命令，用于查询 output 目录下的文件
    job_ls = subparser_job.add_parser(
        'ls',
        help='查询某个 job 的 output 目录下文件夹内容'
    )
    job_ls.add_argument(
        'directory',
        type=str,
        nargs='?',
        default='',
        help='输出目录路径'
    )

    # 'cp' 子命令，用于下载 output 目录下的文件到本地
    job_cp = subparser_job.add_parser(
        'cp',
        help='下载某个 job 的 output 目录下的文件到本地'
    )
    job_cp.add_argument(
        'result_file',
        type=str,
        help='结果文件路径'
    )
    job_cp.add_argument(
        'local_path',
        type=str,
        help='本地保存路径'
    )


    # 许可证ID到许可证名称的映射
    license_mapping = {
        1: '公共领域 (CC0)',
        2: '署名 (CC BY 4.0)',
        3: '署名-非商业性使用-相同方式共享 (CC BY-NC-SA 4.0)',
        4: '署名-相同方式共享 (CC BY-SA 4.0)',
        5: '署名-禁止演绎 (CC-BY-ND)',
        6: '自由软件基金会 (GPL 2)',
        7: '署名-允许演绎 (ODC-BY)',
        8: '其他'
    }
    # 创建主命令解析器
    dataset = subparser_aistudio.add_parser(
        'dataset',
        help='管理数据集，此命令不在支持，请使用新的命令',
        formatter_class=CustomHelpFormatter
    )
    # 构建许可证的帮助信息，每个选项单独一行
    license_help = (
            "数据集许可协议的ID，仅在设置public后生效。默认为1 (公共领域 CC0)。\n"
            "可选项包括：\n" + '\n'.join(f"  {k}: {v}" for k, v in license_mapping.items())
    )
    # 添加 dataset 子命令
    datasets_create = dataset.add_subparsers(help='数据集操作')

    # 创建数据集的子命令(create)
    # aistudio datasets create [flags]
    #
    # flags:
    # --name ppocr_v1 (required) (-n)
    # --files ./file.zip (required) (文件路径，支持多文件上传)(-f)
    # --tags 大模型 (optional) (-t)
    # --public (optional， 默认不公开)(-p)
    # --license CC0 (optional，默认CC0，只在设置public后生效 )(-l)
    # --description testdata (optional) (-d)
    create = datasets_create.add_parser(
        'create',
        help='创建数据集',
        formatter_class=CustomHelpFormatter
    )
    create.add_argument(
        '-n', '--name',
        type=str,
        required=True,
        help='数据集名称'
    )
    create.add_argument(
        '-f', '--files',
        type=str,
        required=True,
        nargs='+',
        help='本地文件路径，支持多个文件'
    )
    create.add_argument(
        '-p', '--public',
        action='store_true',
        help='是否公开数据集'
    )
    create.add_argument(
        '-l', '--license',
        type=int,
        required=False,
        choices=list(license_mapping.keys()),
        default=1,
        help=license_help
    )
    create.add_argument(
        '-d', '--description',
        type=str,
        required=False,
        help='数据集描述'
    )
    # # ** 上传数据集文件 ******************
    # aistudio datasets add [flags]
    #
    # flags:
    # --id 123645 (required) (数据集id) (-i)
    # --files ./file.zip (required) (文件路径)(-f)

    add = datasets_create.add_parser(
        'add',
        help='上传数据集文件',
        formatter_class=CustomHelpFormatter
    )

    add.add_argument(
        '-id', '--id',
        type=int,
        required=True,
        help='数据集id'
    )
    add.add_argument(
        '-f', '--files',
        type=str,
        required=True,
        nargs='+',
        help='本地文件路径，支持多个文件'
    )

    # 新增model模块
    download = subparser_aistudio.add_parser(
        'download',
        help='下载文件',
        formatter_class=CustomHelpFormatter
    )
    download.add_argument(
        '--model',
        type=str,
        help='模型ID，例如 myname/myrepoid'
    )
    download.add_argument(
            '--dataset',
            type=str,
            help='The id of the dataset to be downloaded. For download, '
            'the id of either a model or dataset must be provided.')
    download.add_argument(
        '--revision',
        type=str,
        default=None,
        help='Revision of the entity.')
    download.add_argument(
        '--local_dir',
        type=str,
        default=None,
        help='File will be downloaded to local location specified by'
             'local_dir, in this case.')
    download.add_argument(
        'files',
        type=str,
        default=None,
        nargs='*',
        help='Specify relative path to the repository file(s) to download.'
             "(e.g 'tokenizer.json', 'dir/decoder_model.onnx').")
    download.add_argument(
        '--include',
        nargs='*',
        default=None,
        type=str,
        help='Glob patterns to match files to download.'
             'Ignored if file is specified')
    download.add_argument(
        '--exclude',
        nargs='*',
        type=str,
        default=None,
        help='Glob patterns to exclude from files to download.'
             'Ignored if file is specified')
    download.add_argument(
        '--token',
        type=str,
        default=None,
        help='A User Access Token'
    )
    download.add_argument(
        '--max-workers',
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help='The maximum number of workers to download files.')

    upload = subparser_aistudio.add_parser(
        'upload',
        help='上传文件',
        formatter_class=CustomHelpFormatter)

    upload.add_argument(
        'repo_id',
        type=str,
        help='The ID of the repo to upload to (e.g. `username/repo-name`)')

    upload.add_argument(
        'local_path',
        type=str,
        nargs='?',
        default=None,
        help='Optional, '
             'Local path to the file or folder to upload. Defaults to current directory.'
    )
    upload.add_argument(
        'path_in_repo',
        type=str,
        nargs='?',
        default=None,
        help='Optional, '
             'Path of the file or folder in the repo. Defaults to the relative path of the file or folder.'
    )
    upload.add_argument(
        '--repo-type',
        choices=REPO_TYPE_SUPPORT,
        default=REPO_TYPE_MODEL,
        help='Type of the repo to upload to (e.g. `dataset`, `model`). Defaults to be `model`.',
    )
    upload.add_argument(
        '--include',
        nargs='*',
        type=str,
        help='Glob patterns to match files to upload.')
    upload.add_argument(
        '--exclude',
        nargs='*',
        type=str,
        help='Glob patterns to exclude from files to upload.')
    upload.add_argument(
        '--commit-message',
        type=str,
        default=None,
        help='The message of commit. Default to be `None`.')
    upload.add_argument(
        '--token',
        type=str,
        default=None,
        help='A User Access Token'
    )
    upload.add_argument(
        '--max-workers',
        type=int,
        default=min(8,
                    os.cpu_count() + 4),
        help='The number of workers to use for uploading files.')


    return parser

cache_home = os.getenv("AISTUDIO_CACHE_HOME", default=os.getenv("HOME"))
TOKEN_FILE = os.path.expanduser(f'{cache_home}/.cache/aistudio/.auth/token')


def save_token(token):
    """
    save to separate location
    """
    print(token)
    with open(TOKEN_FILE, 'w') as f:
        f.write(str(token))
    os.chmod(TOKEN_FILE, 0o600)


def main():
    """CLI入口"""
    parser = init()
    args = sys.argv[1:]
    print(f"{args}")
    try:
        args = parser.parse_args(args)
    except:
        return
    if getattr(args, 'command', None) == 'upload':
        assert args.repo_id, '`repo_id` is required'
        assert args.repo_id.count(
            '/') == 1, 'repo_id should be in format of username/repo-name'
        repo_name: str = args.repo_id.split('/')[-1]
        parser.repo_id = args.repo_id

        # Check path_in_repo
        if args.local_path is None and os.path.isfile(repo_name):
            # Case 1: modelscope upload owner_name/test_repo
            parser.local_path = repo_name
            parser.path_in_repo = repo_name
        elif args.local_path is None and os.path.isdir(repo_name):
            # Case 2: modelscope upload owner_name/test_repo  (run command line in the `repo_name` dir)
            # => upload all files in current directory to remote root path
            parser.local_path = repo_name
            parser.path_in_repo = '.'
        elif args.local_path is None:
            # Case 3: user provided only a repo_id that does not match a local file or folder
            # => the user must explicitly provide a local_path => raise exception
            raise ValueError(
                f"'{repo_name}' is not a local file or folder. Please set `local_path` explicitly."
            )
        elif args.path_in_repo is None and os.path.isfile(
                args.local_path):
            # Case 4: modelscope upload owner_name/test_repo /path/to/your_file.csv
            # => upload it to remote root path with same name
            parser.local_path = args.local_path
            parser.path_in_repo = os.path.basename(args.local_path)
        elif args.path_in_repo is None:
            # Case 5: modelscope upload owner_name/test_repo /path/to/your_folder
            # => upload all files in current directory to remote root path
            parser.local_path = args.local_path
            parser.path_in_repo = ''
        else:
            # Finally, if both paths are explicit
            parser.local_path = args.local_path
            parser.path_in_repo = args.path_in_repo



        if os.path.isfile(parser.local_path):
            upload_file(
                path_or_fileobj=parser.local_path,
                path_in_repo=parser.path_in_repo,
                repo_id=parser.repo_id,
                repo_type=args.repo_type,
                commit_message=args.commit_message,
                token=args.token,
            )
        elif os.path.isdir(parser.local_path):
            upload_folder(
                repo_id=parser.repo_id,
                folder_path=parser.local_path,
                path_in_repo=parser.path_in_repo,
                commit_message=args.commit_message,
                repo_type=args.repo_type,
                allow_patterns=convert_patterns(args.include),
                ignore_patterns=convert_patterns(args.exclude),
                max_workers=args.max_workers,
                token=args.token,
            )
        else:
            raise ValueError(f'{parser.local_path} is not a valid local path')

        print(f'Finished uploading to {parser.repo_id}')
    elif hasattr(args, 'model')  and args.model:
        if len(args.files) == 1:  # download single file
            model_file_download(
                args.model,
                args.files[0],
                local_dir=args.local_dir,
                revision=args.revision,
                token=args.token
            )
        elif len(
                args.files) > 1:  # download specified multiple files.
            snapshot_download(
                repo_id=args.model,
                revision=args.revision,
                local_dir=args.local_dir,
                allow_patterns=args.files,
                max_workers=args.max_workers,
                token=args.token
            )
        else:  # download repo
            snapshot_download(
                repo_id=args.model,
                revision=args.revision,
                local_dir=args.local_dir,
                allow_patterns=convert_patterns(args.include),
                ignore_patterns=convert_patterns(args.exclude),
                max_workers=args.max_workers,
                token=args.token
            )
    elif hasattr(args, 'dataset') and args.dataset:
        dataset_revision: str = args.revision if args.revision else DEFAULT_DATASET_REVISION
        if len(args.files) == 1:  # download single file
            file_download(
                args.dataset,
                args.files[0],
                local_dir=args.local_dir,
                revision=dataset_revision,
                repo_type=REPO_TYPE_DATASET,
                token=args.token
            )
        elif len(
                args.files) > 1:  # download specified multiple files.
            snapshot_download(
                repo_id=args.dataset,
                revision=dataset_revision,
                local_dir=args.local_dir,
                allow_patterns=args.files,
                max_workers=args.max_workers,
                token=args.token
            )
        else:  # download repo
            snapshot_download(
                repo_id=args.dataset,
                revision=dataset_revision,
                local_dir=args.local_dir,
                allow_patterns=convert_patterns(args.include),
                ignore_patterns=convert_patterns(args.exclude),
                max_workers=args.max_workers,
                token=args.token
            )
        print(
            f'\nSuccessfully Downloaded from dataset {args.dataset}.\n'
        )
    elif "token" in args:
        pipeline.set_config(args)
    elif "summit_name" in args:
        pipeline.create(args)
    elif "query_pipeline_id" in args:
        pipeline.query(args)
    elif "stop_pipeline_id" in args:
        if not args.force:
            # 二次确认
            if not click.confirm('Do you want to continue?', default=False):
                log.info('Aborted.')
                return
            log.info('Confirmed.')
        pipeline.stop(args)
    elif "directory" in args:
        # 查询某个 job 的 output 目录下文件夹内容
        pipeline.list_output_files(args)
    elif "result_file" in args and "local_path" in args:
        # 下载某个 job 的 output 目录下的文件到本地
        pipeline.download_output_file(args)
    elif "name" in args and "files" in args:
        # 创建数据集
        log.error("This command is not supported any more")
        pipeline.create_dataset(args)
    elif "id" in args and "files" in args:
        # 上传数据集文件
        log.error("This command is not supported any more")
        pipeline.add_file(args)
    else:
        log.info("无效的命令")

if __name__ == '__main__':
    main()
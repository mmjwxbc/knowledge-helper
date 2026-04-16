import os
import re
import shutil
import subprocess
import zipfile
import tarfile
import aiofiles
from typing import Optional, Tuple
from fastapi import UploadFile
from .interview_sandbox import get_sandbox_path


def is_github_url(url: str) -> bool:
    """检查是否是 GitHub URL"""
    return bool(re.match(r'https?://(www\.)?github\.com/[^/]+/[^/]+', url))


def is_gitlab_url(url: str) -> bool:
    """检查是否是 GitLab URL"""
    return bool(re.match(r'https?://(www\.)?gitlab\.com/[^/]+/[^/]+', url))


def extract_repo_info(url: str) -> Tuple[str, str]:
    """
    从 URL 中提取仓库信息

    Args:
        url: GitHub 或 GitLab 仓库 URL

    Returns:
        tuple: (platform, repo_url)
    """
    url = url.strip()

    if is_github_url(url):
        return "github", url
    elif is_gitlab_url(url):
        return "gitlab", url
    else:
        raise ValueError(f"不支持的代码托管平台: {url}")


async def download_from_git(url: str, target_dir: str, depth: int = 1) -> Tuple[bool, str]:
    """
    使用 git clone 下载代码仓库

    Args:
        url: 仓库 URL (GitHub/GitLab)
        target_dir: 目标目录
        depth: 克隆深度 (1 表示只克隆最新提交，减少下载量)

    Returns:
        tuple: (success, message)
    """
    try:
        # 转换为 HTTPS URL (避免 SSH 权限问题)
        if url.startswith('git@'):
            # git@github.com:user/repo.git -> https://github.com/user/repo.git
            url = url.replace('git@github.com:', 'https://github.com/')
            url = url.replace('git@gitlab.com:', 'https://gitlab.com/')

        # 添加 --depth 参数限制克隆深度
        clone_command = ['git', 'clone', '--depth', str(depth), url, target_dir]

        # 执行 git clone 命令
        result = subprocess.run(
            clone_command,
            capture_output=True,
            text=True,
            timeout=300  # 5分钟超时
        )

        if result.returncode == 0:
            return True, f"成功下载仓库到 {target_dir}"
        else:
            return False, f"git clone 失败: {result.stderr}"

    except subprocess.TimeoutExpired:
        return False, "下载超时 (超过 5 分钟)"
    except Exception as e:
        return False, f"下载过程中发生错误: {str(e)}"


async def extract_zip(file: UploadFile, target_dir: str) -> Tuple[bool, str]:
    """
    解压 ZIP 文件到目标目录

    Args:
        file: 上传的 ZIP 文件
        target_dir: 目标目录

    Returns:
        tuple: (success, message)
    """
    try:
        # 读取文件内容
        content = await file.read()

        # 创建临时文件
        temp_zip_path = os.path.join(target_dir, 'temp.zip')
        async with aiofiles.open(temp_zip_path, 'wb') as f:
            await f.write(content)

        # 解压文件
        with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
            zip_ref.extractall(target_dir)

        # 删除临时文件
        os.remove(temp_zip_path)

        return True, f"成功解压 ZIP 文件到 {target_dir}"

    except Exception as e:
        return False, f"解压 ZIP 文件失败: {str(e)}"


async def extract_tar(file: UploadFile, target_dir: str) -> Tuple[bool, str]:
    """
    解压 TAR/GZ 文件到目标目录

    Args:
        file: 上传的 TAR/GZ 文件
        target_dir: 目标目录

    Returns:
        tuple: (success, message)
    """
    try:
        # 读取文件内容
        content = await file.read()

        # 创建临时文件
        temp_tar_path = os.path.join(target_dir, 'temp.tar')
        async with aiofiles.open(temp_tar_path, 'wb') as f:
            await f.write(content)

        # 判断压缩格式并解压
        if file.filename.endswith('.tar.gz') or file.filename.endswith('.tgz'):
            with tarfile.open(temp_tar_path, 'r:gz') as tar_ref:
                tar_ref.extractall(target_dir)
        elif file.filename.endswith('.tar.bz2'):
            with tarfile.open(temp_tar_path, 'r:bz2') as tar_ref:
                tar_ref.extractall(target_dir)
        else:
            with tarfile.open(temp_tar_path, 'r') as tar_ref:
                tar_ref.extractall(target_dir)

        # 删除临时文件
        os.remove(temp_tar_path)

        return True, f"成功解压 TAR 文件到 {target_dir}"

    except Exception as e:
        return False, f"解压 TAR 文件失败: {str(e)}"


async def extract_archive(file: UploadFile, target_dir: str) -> Tuple[bool, str]:
    """
    根据文件类型自动解压压缩文件

    Args:
        file: 上传的压缩文件
        target_dir: 目标目录

    Returns:
        tuple: (success, message)
    """
    if not file.filename:
        return False, "文件名不能为空"

    filename = file.filename.lower()

    if filename.endswith('.zip'):
        return await extract_zip(file, target_dir)
    elif filename.endswith('.tar') or filename.endswith('.tar.gz') or filename.endswith('.tgz') or filename.endswith('.tar.bz2'):
        return await extract_tar(file, target_dir)
    else:
        return False, f"不支持的压缩格式: {file.filename}"


async def download_code(sandbox_id: str, url: Optional[str] = None, file: Optional[UploadFile] = None) -> Tuple[bool, str]:
    """
    统一的代码下载入口

    Args:
        sandbox_id: 沙箱 ID
        url: GitHub/GitLab 仓库 URL
        file: 上传的压缩包文件

    Returns:
        tuple: (success, message)
    """
    # 获取沙箱路径
    sandbox_path = get_sandbox_path(sandbox_id)
    if not sandbox_path:
        return False, f"沙箱不存在: {sandbox_id}"

    # 确保沙箱目录存在
    os.makedirs(sandbox_path, exist_ok=True)

    try:
        if url:
            # 从 URL 下载
            platform, repo_url = extract_repo_info(url)
            success, message = await download_from_git(repo_url, sandbox_path)

            if success:
                return True, f"成功从 {platform} 下载代码: {message}"
            else:
                return False, message

        elif file:
            # 解压上传的压缩包
            success, message = await extract_archive(file, sandbox_path)

            if success:
                return True, f"成功解压压缩包: {message}"
            else:
                return False, message

        else:
            return False, "必须提供 URL 或压缩包文件"

    except ValueError as e:
        return False, str(e)
    except Exception as e:
        return False, f"代码下载失败: {str(e)}"


def get_code_structure(sandbox_id: str) -> Optional[dict]:
    """
    获取沙箱中代码的文件结构

    Args:
        sandbox_id: 沙箱 ID

    Returns:
        dict: 文件结构树，如果失败则返回 None
    """
    sandbox_path = get_sandbox_path(sandbox_id)
    if not sandbox_path or not os.path.exists(sandbox_path):
        return None

    def build_tree(path: str) -> dict:
        """递归构建文件树"""
        name = os.path.basename(path)
        is_dir = os.path.isdir(path)

        if is_dir:
            # 过滤隐藏目录和特定目录
            skip_dirs = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', '.idea', '.vscode', 'dist', 'build'}
            children = []
            try:
                for item in os.listdir(path):
                    if item.startswith('.') or item in skip_dirs:
                        continue
                    child_path = os.path.join(path, item)
                    children.append(build_tree(child_path))
            except PermissionError:
                pass

            return {
                'name': name,
                'type': 'directory',
                'children': children,
                'path': path
            }
        else:
            return {
                'name': name,
                'type': 'file',
                'size': os.path.getsize(path),
                'path': path
            }

    try:
        return build_tree(sandbox_path)
    except Exception as e:
        print(f"获取代码结构失败: {str(e)}")
        return None


def get_source_files(sandbox_id: str, extensions: Optional[list] = None) -> list:
    """
    获取沙箱中的所有源代码文件路径

    Args:
        sandbox_id: 沙箱 ID
        extensions: 文件扩展名过滤列表，如 ['.py', '.js', '.ts']

    Returns:
        list: 源代码文件路径列表
    """
    sandbox_path = get_sandbox_path(sandbox_id)
    if not sandbox_path or not os.path.exists(sandbox_path):
        return []

    if extensions is None:
        # 默认支持常见的源代码扩展名
        extensions = [
            '.py', '.js', '.ts', '.jsx', '.tsx',
            '.java', '.kt', '.go', '.rs', '.cpp', '.c', '.h',
            '.cs', '.php', '.rb', '.swift', '.dart'
        ]

    source_files = []
    skip_dirs = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', '.idea', '.vscode', 'dist', 'build'}

    def walk_directory(path: str):
        """递归遍历目录"""
        try:
            for item in os.listdir(path):
                if item in skip_dirs:
                    continue

                item_path = os.path.join(path, item)
                if os.path.isdir(item_path):
                    walk_directory(item_path)
                elif os.path.isfile(item_path):
                    if any(item_path.endswith(ext) for ext in extensions):
                        source_files.append(item_path)
        except PermissionError:
            pass

    try:
        walk_directory(sandbox_path)
        return source_files
    except Exception as e:
        print(f"获取源代码文件失败: {str(e)}")
        return []


def read_file_content(filepath: str, max_size: int = 10000) -> Optional[str]:
    """
    读取文件内容，限制最大大小

    Args:
        filepath: 文件路径
        max_size: 最大读取字节数

    Returns:
        str: 文件内容，如果失败则返回 None
    """
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read(max_size)
            # 如果文件超过最大大小，添加截断标记
            if len(f.read(1)) > 0:
                content += "\n\n... (文件内容已截断) ..."
            return content
    except Exception as e:
        print(f"读取文件失败 {filepath}: {str(e)}")
        return None

import os
import uuid
import shutil
import asyncio
from typing import Optional, Dict
from datetime import datetime, timedelta
import aiofiles

# 沙箱配置
SANDBOX_BASE_PATH = "/tmp/interview_sandbox"
SANDBOX_TIMEOUT_HOURS = 24

# 全局沙箱状态跟踪
sandbox_registry: Dict[str, Dict] = {}


def _ensure_base_path():
    """确保沙箱基础目录存在"""
    if not os.path.exists(SANDBOX_BASE_PATH):
        os.makedirs(SANDBOX_BASE_PATH, mode=0o755, exist_ok=True)


def create_sandbox() -> str:
    """
    创建一个新的沙箱目录并返回沙箱 ID

    Returns:
        str: 沙箱 ID (UUID)
    """
    _ensure_base_path()

    sandbox_id = str(uuid.uuid4())
    sandbox_path = os.path.join(SANDBOX_BASE_PATH, sandbox_id)

    # 创建沙箱目录
    os.makedirs(sandbox_path, mode=0o755, exist_ok=True)

    # 注册沙箱信息
    sandbox_registry[sandbox_id] = {
        "id": sandbox_id,
        "path": sandbox_path,
        "created_at": datetime.now().isoformat(),
        "status": "active"
    }

    return sandbox_id


def get_sandbox_path(sandbox_id: str) -> Optional[str]:
    """
    获取沙箱目录的绝对路径

    Args:
        sandbox_id: 沙箱 ID

    Returns:
        str: 沙箱路径，如果不存在则返回 None
    """
    if sandbox_id not in sandbox_registry:
        return None

    return sandbox_registry[sandbox_id]["path"]


def sandbox_exists(sandbox_id: str) -> bool:
    """
    检查沙箱是否存在

    Args:
        sandbox_id: 沙箱 ID

    Returns:
        bool: 沙箱是否存在
    """
    if sandbox_id not in sandbox_registry:
        return False

    path = sandbox_registry[sandbox_id]["path"]
    return os.path.exists(path)


def get_sandbox_info(sandbox_id: str) -> Optional[Dict]:
    """
    获取沙箱的详细信息

    Args:
        sandbox_id: 沙箱 ID

    Returns:
        dict: 沙箱信息，如果不存在则返回 None
    """
    if sandbox_id not in sandbox_registry:
        return None

    return {
        "id": sandbox_registry[sandbox_id]["id"],
        "path": sandbox_registry[sandbox_id]["path"],
        "created_at": sandbox_registry[sandbox_id]["created_at"],
        "status": sandbox_registry[sandbox_id]["status"],
        "exists": sandbox_exists(sandbox_id)
    }


def cleanup_sandbox(sandbox_id: str) -> bool:
    """
    清理指定的沙箱目录

    Args:
        sandbox_id: 沙箱 ID

    Returns:
        bool: 清理是否成功
    """
    if sandbox_id not in sandbox_registry:
        return False

    sandbox_path = sandbox_registry[sandbox_id]["path"]

    try:
        if os.path.exists(sandbox_path):
            # 递归删除目录
            shutil.rmtree(sandbox_path)

        # 从注册表中移除
        del sandbox_registry[sandbox_id]

        return True
    except Exception as e:
        print(f"清理沙箱失败: {sandbox_id}, 错误: {str(e)}")
        return False


def cleanup_expired_sandboxes() -> int:
    """
    清理所有过期的沙箱（超过超时时间）

    Returns:
        int: 清理的沙箱数量
    """
    now = datetime.now()
    timeout = timedelta(hours=SANDBOX_TIMEOUT_HOURS)
    cleaned_count = 0

    expired_ids = []
    for sandbox_id, info in sandbox_registry.items():
        created_at = datetime.fromisoformat(info["created_at"])
        if now - created_at > timeout:
            expired_ids.append(sandbox_id)

    for sandbox_id in expired_ids:
        if cleanup_sandbox(sandbox_id):
            cleaned_count += 1

    return cleaned_count


def cleanup_all_sandboxes() -> int:
    """
    清理所有沙箱目录

    Returns:
        int: 清理的沙箱数量
    """
    count = 0
    sandbox_ids = list(sandbox_registry.keys())

    for sandbox_id in sandbox_ids:
        if cleanup_sandbox(sandbox_id):
            count += 1

    return count


def get_all_sandboxes() -> list:
    """
    获取所有沙箱的信息列表

    Returns:
        list: 沙箱信息列表
    """
    return [get_sandbox_info(sandbox_id) for sandbox_id in sandbox_registry.keys()]


async def async_cleanup_expired_sandboxes():
    """
    异步清理过期的沙箱
    """
    return await asyncio.to_thread(cleanup_expired_sandboxes)


async def async_cleanup_sandbox(sandbox_id: str) -> bool:
    """
    异步清理指定的沙箱

    Args:
        sandbox_id: 沙箱 ID

    Returns:
        bool: 清理是否成功
    """
    return await asyncio.to_thread(cleanup_sandbox, sandbox_id)

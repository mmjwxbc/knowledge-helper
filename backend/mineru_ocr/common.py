"""
通用工具函数模块
"""
import filetype
from io import BytesIO
from typing import Tuple, Union
from pathlib import Path


def guess_file_type(file_input: Union[str, Path, BytesIO]) -> Tuple[str, str]:
    """
    检测文件类型
    
    Args:
        file_input: 文件路径（str 或 Path）或文件对象（BytesIO）
    
    Returns:
        Tuple[str, str]: (文件类型扩展名, MIME类型)，如 ("pdf", "application/pdf")
                        如果无法识别，返回 (None, "unknown file type")
    """
    # 如果是文件路径，读取文件内容
    if isinstance(file_input, (str, Path)):
        file_path = Path(file_input)
        if not file_path.exists():
            return None, "file not found"
        with open(file_path, 'rb') as f:
            file_buffer = BytesIO(f.read())
    else:
        # 如果是 BytesIO，需要确保位置在开头
        file_buffer = file_input
        if hasattr(file_buffer, 'seek'):
            file_buffer.seek(0)
    
    # 检测文件类型
    file_type = filetype.guess(file_buffer)
    if file_type is None:
        return None, "unknown file type"
    
    # 检查是否为支持的文件类型
    supported_mimes = ["image/jpeg", "image/png", "application/pdf", "image/gif"]
    if file_type.mime not in supported_mimes:
        return None, file_type.mime
    
    # 返回文件扩展名和 MIME 类型
    extension = file_type.mime.split("/")[1]
    return extension, file_type.mime

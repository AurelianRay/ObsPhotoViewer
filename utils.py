"""
工具函数：图片验证、缩略图生成、格式化
"""

import os
import io
from PIL import Image

# 支持的图片扩展名
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".ico", ".svg"}

# 缩略图尺寸
THUMBNAIL_SIZE = (120, 90)


def is_image_file(filename: str) -> bool:
    """根据扩展名判断是否为图片文件"""
    return os.path.splitext(filename)[1].lower() in IMAGE_EXTENSIONS


def filename_from_key(object_key: str) -> str:
    """从 OBS 对象键中提取文件名"""
    key = object_key.rstrip("/")
    return os.path.basename(key) or key


def make_thumbnail(image_bytes: bytes) -> Image.Image:
    """从图片字节数据生成缩略图

    Returns:
        PIL.Image 缩略图对象，或 None（数据不可解析时）
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)
        return img
    except Exception:
        return None


def resize_for_preview(image_bytes: bytes, max_width: int, max_height: int) -> Image.Image:
    """从图片字节数据生成适合预览的缩放图片

    保持宽高比，缩放到 max_width x max_height 以内。
    """
    img = Image.open(io.BytesIO(image_bytes))
    img.thumbnail((max_width, max_height), Image.LANCZOS)
    return img


def format_file_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def extract_leaf_name(key: str, max_len: int = 20) -> str:
    """从对象键提取简称用做显示名称"""
    name = filename_from_key(key)
    if len(name) > max_len:
        ext = os.path.splitext(name)[1]
        name = name[: max_len - len(ext) - 2] + ".." + ext
    return name

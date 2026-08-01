"""
配置文件持久化管理（YAML 格式）
存储位置: %APPDATA%/OBSImageBrowser/config.yaml
"""

import os
import yaml


APP_NAME = "OBSImageBrowser"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.yaml")

DEFAULT_CONFIG = {
    "credentials": {
        "ak": "",
        "sk": "",
        "endpoint": "obs.cn-north-4.myhuaweicloud.com",
        "bucket": ""
    },
    "preferences": {
        "last_download_path": os.path.join(os.path.expanduser("~"), "Downloads"),
        "page_size": 50,
    }
}


def load_config():
    """加载 YAML 配置文件，文件不存在或损坏时返回默认配置"""
    if not os.path.exists(CONFIG_FILE):
        return _copy_default()

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        config = _copy_default()
        _deep_merge(config, data)
        return config
    except (yaml.YAMLError, ValueError, IOError):
        return _copy_default()


def save_config(config):
    """原子写入 YAML 配置文件"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp_file = CONFIG_FILE + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False, indent=2)
        os.replace(tmp_file, CONFIG_FILE)
    except IOError:
        pass


def _copy_default():
    """深拷贝默认配置"""
    return yaml.safe_load(yaml.safe_dump(DEFAULT_CONFIG))


def _deep_merge(base, override):
    """递归合并 override 到 base"""
    if not isinstance(override, dict):
        return
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value

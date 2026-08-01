"""
华为云 OBS 客户端封装（基于 boto3 S3 兼容 API）
参考 MinerU 项目的 S3 客户端实现模式
"""

import os
import io

from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError, ConnectionClosedError
import boto3


# ---------- 自定义异常 ----------
class ObsError(Exception):
    """OBS 通用异常"""


class ObsAuthError(ObsError):
    """认证失败 (403)"""


class ObsNetworkError(ObsError):
    """网络错误（无法连接、超时）"""


class ObsNotFoundError(ObsError):
    """桶或对象不存在 (404)"""


# ---------- 支持的图片扩展名 ----------
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".ico", ".svg"}


def _classify_error(e: Exception) -> ObsError:
    """根据 botocore 异常进行分类"""
    if isinstance(e, ClientError):
        code = e.response.get("Error", {}).get("Code", "")
        status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        if status == 403 or code == "AccessDenied" or code == "SignatureDoesNotMatch":
            return ObsAuthError(f"认证失败，请检查 Access Key 和 Secret Key: {e}")
        if status == 404 or code == "NoSuchBucket" or code == "NoSuchKey":
            return ObsNotFoundError(f"桶或对象不存在: {e}")
        return ObsError(f"请求失败 [{code}]: {e}")

    if isinstance(e, (EndpointConnectionError, ConnectionClosedError)):
        return ObsNetworkError(f"网络连接失败: {e}")

    msg = str(e).lower()
    if any(kw in msg for kw in ("timeout", "timed out", "connection refused", "name resolution")):
        return ObsNetworkError(f"网络连接失败: {e}")

    return ObsError(str(e))


def _normalize_endpoint(endpoint: str) -> str:
    """标准化 endpoint URL，确保包含 https:// 前缀"""
    endpoint = endpoint.strip()
    if not endpoint.startswith("http://") and not endpoint.startswith("https://"):
        endpoint = "https://" + endpoint
    return endpoint


# ---------- 客户端封装 ----------
class ObsClientWrapper:
    """华为云 OBS 客户端封装（boto3 S3 兼容模式）"""

    def __init__(self):
        self._client = None
        self._ak = ""
        self._sk = ""
        self._endpoint = ""
        self._bucket = ""

    @property
    def connected(self):
        return self._client is not None

    @property
    def ak(self):
        return self._ak

    def connect(self, ak: str, sk: str, endpoint: str, bucket: str = "") -> bool:
        """建立连接并验证凭证有效性

        Returns:
            True 表示连接成功
        Raises:
            ObsAuthError / ObsNetworkError / ObsError
        """
        try:
            endpoint_url = _normalize_endpoint(endpoint)

            client = boto3.client(
                service_name="s3",
                aws_access_key_id=ak,
                aws_secret_access_key=sk,
                endpoint_url=endpoint_url,
                config=Config(
                    s3={"addressing_style": "virtual"},
                    retries={"max_attempts": 3, "mode": "standard"},
                    connect_timeout=10,
                    read_timeout=30,
                ),
            )

            # 通过 list_objects 验证凭证和桶（比 head_bucket 兼容性更好）
            if bucket:
                client.list_objects_v2(Bucket=bucket, MaxKeys=1)

            self._client = client
            self._ak = ak
            self._sk = sk
            self._endpoint = endpoint
            self._bucket = bucket
            return True

        except ClientError as e:
            raise _classify_error(e)
        except (EndpointConnectionError, ConnectionClosedError) as e:
            raise _classify_error(e)
        except (ObsAuthError, ObsNetworkError, ObsNotFoundError):
            raise
        except Exception as e:
            raise _classify_error(e)

    def disconnect(self):
        """断开连接"""
        self._client = None

    def list_images(self, bucket: str, prefix: str = "", marker: str = "", max_keys: int = 50):
        """列出桶中的图片对象（仅返回常见图片格式）

        Args:
            bucket: 桶名称
            prefix: 对象名前缀（用于搜索/过滤）
            marker: 分页标记（首次为空，使用 ContinuationToken）
            max_keys: 每页最大数量

        Returns:
            {
                "objects": [{"key": str, "size": int, "last_modified": str}, ...],
                "is_truncated": bool,
                "next_marker": str | None
            }
        """
        if not self._client:
            raise ObsError("未连接到 OBS")

        try:
            kwargs = {
                "Bucket": bucket,
                "Prefix": prefix,
                "MaxKeys": max_keys,
            }
            if marker:
                kwargs["ContinuationToken"] = marker

            resp = self._client.list_objects_v2(**kwargs)

            objects = []
            contents = resp.get("Contents", [])
            for obj in contents:
                key = obj.get("Key", "")
                if not key or key.endswith("/"):
                    continue
                # 按扩展名筛选图片
                lower_key = key.lower()
                if any(lower_key.endswith(ext) for ext in IMAGE_EXTENSIONS):
                    objects.append({
                        "key": key,
                        "size": obj.get("Size", 0),
                        "last_modified": str(obj.get("LastModified", ""))
                    })

            return {
                "objects": objects,
                "is_truncated": resp.get("IsTruncated", False),
                "next_marker": resp.get("NextContinuationToken", None)
            }

        except ClientError as e:
            raise _classify_error(e)
        except (ObsAuthError, ObsNotFoundError, ObsNetworkError):
            raise
        except ObsError:
            raise
        except Exception as e:
            raise _classify_error(e)

    def search_images(self, bucket: str, query: str, max_keys: int = 500):
        """按文件名递归搜索图片（支持多层子目录）

        策略：
        1. 先用 query 做前缀搜索（适合知道路径前缀的场景）
        2. 无论前缀搜索有无结果，都递归扫描桶内对象，按文件名匹配
           （只要文件名包含搜索词就返回，不受目录层级影响）

        Returns:
            {"objects": [...], "is_truncated": bool, "next_marker": str|None}
        """
        if not self._client:
            raise ObsError("未连接到 OBS")

        all_objects = []
        seen_keys = set()
        query_lower = query.strip().lower()
        if not query_lower:
            return {"objects": [], "is_truncated": False, "next_marker": None}

        try:
            # 策略1：前缀搜索（快速命中）
            prefix_result = self.list_images(bucket, prefix=query, max_keys=100)
            for obj in prefix_result["objects"]:
                if obj["key"] not in seen_keys:
                    all_objects.append(obj)
                    seen_keys.add(obj["key"])

            # 策略2：递归扫描（穿透多层目录，按文件名匹配）
            # 最多扫 20 页，每页最多 max_keys 条
            marker = ""
            for _ in range(20):
                resp = self._client.list_objects_v2(
                    Bucket=bucket,
                    MaxKeys=max_keys,
                    ContinuationToken=marker if marker else None
                )
                contents = resp.get("Contents", [])
                for obj in contents:
                    key = obj.get("Key", "")
                    if not key or key.endswith("/") or key in seen_keys:
                        continue

                    # 只处理图片扩展名
                    lower_key = key.lower()
                    if not any(lower_key.endswith(ext) for ext in IMAGE_EXTENSIONS):
                        continue

                    # 文件名包含搜索词（不区分大小写）
                    fname = key.split("/")[-1].lower()
                    if query_lower in fname:
                        all_objects.append({
                            "key": key,
                            "size": obj.get("Size", 0),
                            "last_modified": str(obj.get("LastModified", ""))
                        })
                        seen_keys.add(key)

                if not resp.get("IsTruncated"):
                    break
                marker = resp.get("NextContinuationToken", "")
                if not marker:
                    break

            return {
                "objects": all_objects,
                "is_truncated": False,
                "next_marker": None
            }

        except ClientError as e:
            raise _classify_error(e)
        except (ObsAuthError, ObsNotFoundError, ObsNetworkError):
            raise
        except Exception as e:
            raise _classify_error(e)

    def get_object_bytes(self, bucket: str, object_key: str) -> bytes:
        """获取对象字节内容（用于缩略图/预览）"""
        if not self._client:
            raise ObsError("未连接到 OBS")

        try:
            resp = self._client.get_object(Bucket=bucket, Key=object_key)
            return resp["Body"].read()

        except ClientError as e:
            raise _classify_error(e)
        except ObsError:
            raise
        except Exception as e:
            raise _classify_error(e)

    def download_file(self, bucket: str, object_key: str, local_path: str, progress_callback=None) -> str:
        """下载对象到本地文件

        Args:
            bucket: 桶名称
            object_key: 对象键
            local_path: 本地保存路径（完整文件路径）
            progress_callback: 可选进度回调

        Returns:
            本地文件路径
        """
        if not self._client:
            raise ObsError("未连接到 OBS")

        try:
            self._client.download_file(
                Bucket=bucket,
                Key=object_key,
                Filename=local_path
            )
            return local_path

        except ClientError as e:
            raise _classify_error(e)
        except ObsError:
            raise
        except Exception as e:
            raise _classify_error(e)

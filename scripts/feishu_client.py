"""飞书多维表格 API 封装。

提供飞书 Base API 的读写操作，包括 token 管理、批量记录读写、重试机制。
"""

import time
import logging
from typing import List, Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)

# 飞书 API 基础 URL
BASE_URL = "https://open.feishu.cn/open-apis"


class FeishuClient:
    """飞书多维表格 API 客户端。"""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        app_token: str,
        base_url: str = BASE_URL,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.app_token = app_token
        self.base_url = base_url
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._http = httpx.Client(timeout=30.0)

    def _get_token(self) -> str:
        """获取或刷新 tenant_access_token。"""
        now = time.time()
        if self._token and now < self._token_expires_at:
            return self._token

        url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
        resp = self._http.post(
            url,
            json={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise FeishuAPIError(f"获取 token 失败: {data.get('msg')}")

        self._token = data["tenant_access_token"]
        # 提前 5 分钟过期
        self._token_expires_at = now + data.get("expire", 7200) - 300
        return self._token

    def _request(
        self,
        method: str,
        path: str,
        json_data: dict = None,
        params: dict = None,
        max_retries: int = 3,
    ) -> dict:
        """发送 API 请求，带指数退避重试。"""
        url = f"{self.base_url}{path}"
        token = self._get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        for attempt in range(max_retries):
            try:
                resp = self._http.request(
                    method, url, headers=headers, json=json_data, params=params
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("code") == 99991663:  # 频率限制
                    wait = 2 ** attempt
                    logger.warning(f"飞书 API 频率限制，等待 {wait}s 后重试")
                    time.sleep(wait)
                    continue

                if data.get("code") != 0:
                    raise FeishuAPIError(
                        f"API 错误: code={data.get('code')}, msg={data.get('msg')}"
                    )

                return data

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning(f"HTTP 429，等待 {wait}s 后重试")
                    time.sleep(wait)
                    continue
                raise FeishuAPIError(f"HTTP {e.response.status_code}: {e}")

        raise FeishuAPIError(f"请求失败，已重试 {max_retries} 次")

    def get_records(
        self,
        table_id: str,
        page_size: int = 500,
        filter_expr: str = None,
    ) -> List[Dict[str, Any]]:
        """获取数据表的所有记录。"""
        all_records = []
        page_token = None

        while True:
            params = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            if filter_expr:
                params["filter"] = filter_expr

            data = self._request(
                "GET",
                f"/bitable/v1/apps/{self.app_token}/tables/{table_id}/records",
                params=params,
            )

            items = data.get("data", {}).get("items", [])
            all_records.extend(items)

            if not data.get("data", {}).get("has_more"):
                break
            page_token = data.get("data", {}).get("page_token")
            if not page_token:
                break

        return all_records

    def batch_create_records(
        self,
        table_id: str,
        records: List[Dict[str, Any]],
        chunk_size: int = 500,
    ) -> List[Dict[str, Any]]:
        """批量新增记录，自动分片。"""
        results = []
        for i in range(0, len(records), chunk_size):
            chunk = records[i : i + chunk_size]
            payload = {"records": [{"fields": r} for r in chunk]}
            data = self._request(
                "POST",
                f"/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/batch_create",
                json_data=payload,
            )
            results.extend(data.get("data", {}).get("records", []))
            logger.info(f"已写入 {i + len(chunk)}/{len(records)} 条记录")
        return results

    def batch_update_records(
        self,
        table_id: str,
        records: List[Dict[str, Any]],
        chunk_size: int = 500,
    ) -> List[Dict[str, Any]]:
        """批量更新记录，自动分片。

        Args:
            table_id: 数据表 ID
            records: 每个元素必须包含 record_id 和 fields 字段
                [{"record_id": "recXXX", "fields": {...}}, ...]
            chunk_size: 单次请求最大记录数
        """
        # 校验 records 格式
        for r in records:
            if "record_id" not in r or "fields" not in r:
                raise FeishuAPIError(
                    "batch_update_records 每条记录必须包含 record_id 和 fields 字段"
                )

        results = []
        for i in range(0, len(records), chunk_size):
            chunk = records[i : i + chunk_size]
            # 飞书 batch_update API 要求 payload 格式:
            # {"records": [{"record_id": "recXXX", "fields": {...}}, ...]}
            payload = {"records": chunk}
            data = self._request(
                "POST",
                f"/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/batch_update",
                json_data=payload,
            )
            results.extend(data.get("data", {}).get("records", []))
            logger.info(f"已更新 {i + len(chunk)}/{len(records)} 条记录")
        return results

    def batch_delete_records(
        self,
        table_id: str,
        record_ids: List[str],
        chunk_size: int = 500,
    ) -> List[str]:
        """批量删除记录，自动分片。

        Args:
            table_id: 数据表 ID
            record_ids: 要删除的记录 ID 列表
            chunk_size: 单次请求最大记录数
        """
        results = []
        for i in range(0, len(record_ids), chunk_size):
            chunk = record_ids[i : i + chunk_size]
            payload = {"records": chunk}
            data = self._request(
                "POST",
                f"/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/batch_delete",
                json_data=payload,
            )
            results.extend(data.get("data", {}).get("records", []))
            logger.info(f"已删除 {i + len(chunk)}/{len(record_ids)} 条记录")
        return results

    def get_table_list(self) -> List[Dict[str, Any]]:
        """获取 Base 下所有数据表。"""
        data = self._request(
            "GET",
            f"/bitable/v1/apps/{self.app_token}/tables",
        )
        return data.get("data", {}).get("items", [])

    def create_table(
        self,
        name: str,
        fields: List[Dict[str, Any]],
        default_view_name: str = "默认视图",
    ) -> Dict[str, Any]:
        """创建数据表。"""
        data = self._request(
            "POST",
            f"/bitable/v1/apps/{self.app_token}/tables",
            json_data={
                "table": {
                    "name": name,
                    "default_view_name": default_view_name,
                    "fields": fields,
                }
            },
        )
        return data.get("data", {})


class FeishuAPIError(Exception):
    """飞书 API 错误。"""
    pass
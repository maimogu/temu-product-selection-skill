"""keepa-mcp 调用封装。

通过持久化子进程方式调用 keepa-mcp，避免每次调用都重新启动 npx 进程。
使用 JSON-RPC over stdio 与 MCP 服务通信，复用单个子进程连接。

协议：
1. 启动子进程 `npx -y keepa-mcp`
2. 发送 initialize 请求完成握手
3. 后续 tools/call 请求复用同一进程
"""

import json
import os
import subprocess
import logging
import threading
from typing import List, Dict, Any, Optional, Union

logger = logging.getLogger(__name__)


class KeepaClient:
    """keepa-mcp 客户端，持久化子进程。"""

    def __init__(self, api_key: str = None, mcp_command: List[str] = None):
        """
        Args:
            api_key: Keepa API Key（也会从 KEEPA_API_KEY 环境变量读取）
            mcp_command: 自定义 MCP 启动命令，默认 ["npx", "-y", "keepa-mcp"]
        """
        self.api_key = api_key or os.environ.get("KEEPA_API_KEY")
        self.mcp_command = mcp_command or ["npx", "-y", "keepa-mcp"]
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._request_id = 0
        self._initialized = False

    def _start_process(self) -> subprocess.Popen:
        """启动 MCP 子进程。"""
        env = {**os.environ}
        if self.api_key:
            env["KEEPA_API_KEY"] = self.api_key

        logger.info(f"启动 keepa-mcp 子进程: {' '.join(self.mcp_command)}")
        proc = subprocess.Popen(
            self.mcp_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            bufsize=1,  # 行缓冲
        )
        return proc

    def _initialize(self) -> None:
        """完成 MCP 协议握手。"""
        if self._initialized:
            return

        init_request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "keepa-client", "version": "1.0.0"},
            },
        }
        self._send_request(init_request)

        # 发送 initialized 通知（无 id）
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        self._send_notification(notification)
        self._initialized = True
        logger.info("keepa-mcp 握手完成")

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _send_request(self, request: dict, timeout: int = 120) -> dict:
        """发送 JSON-RPC 请求并等待响应。

        注意：MCP 子进程的 stderr 可能混杂其他输出，stdout 输出 JSON 行。
        本函数按行读取 stdout，跳过非 JSON 行，直到拿到对应 id 的响应。
        """
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self._process = self._start_process()
                self._initialized = False

            if not self._initialized:
                self._initialize()

            request_str = json.dumps(request) + "\n"
            try:
                self._process.stdin.write(request_str)
                self._process.stdin.flush()
            except BrokenPipeError as e:
                raise KeepaError(f"keepa-mcp 子进程已退出: {e}")

            # 按行读取响应，跳过非 JSON 行
            expected_id = request.get("id")
            deadline = _now_plus_seconds(timeout)
            while True:
                if _now() > deadline:
                    raise KeepaError("keepa-mcp 调用超时")

                line = self._process.stdout.readline()
                if not line:
                    # 进程可能已退出
                    stderr_output = ""
                    if self._process.poll() is not None:
                        stderr_output = self._process.stderr.read() or ""
                    raise KeepaError(
                        f"keepa-mcp 子进程关闭 stdout。stderr: {stderr_output[:500]}"
                    )

                line = line.strip()
                if not line:
                    continue

                # 跳过非 JSON 行（如 npx 启动提示）
                if not line.startswith("{"):
                    logger.debug(f"跳过非 JSON 行: {line[:100]}")
                    continue

                try:
                    response = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug(f"跳过无法解析的 JSON 行: {line[:100]}")
                    continue

                # 只返回与请求 id 匹配的响应
                if response.get("id") == expected_id:
                    if "error" in response:
                        err = response["error"]
                        raise KeepaError(
                            f"keepa-mcp 错误: code={err.get('code')}, msg={err.get('message')}"
                        )
                    return response.get("result", {})

    def _send_notification(self, notification: dict) -> None:
        """发送 JSON-RPC 通知（无 id，不等待响应）。"""
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self._process = self._start_process()

            notification_str = json.dumps(notification) + "\n"
            try:
                self._process.stdin.write(notification_str)
                self._process.stdin.flush()
            except BrokenPipeError as e:
                raise KeepaError(f"keepa-mcp 子进程已退出: {e}")

    def _call_mcp_tool(self, tool_name: str, args: dict, timeout: int = 120) -> Any:
        """调用 MCP 工具。"""
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": args},
        }
        result = self._send_request(request, timeout=timeout)

        # MCP 工具响应格式: {"content": [{"type": "text", "text": "..."}]}
        # 提取 text 字段并尝试 JSON 解析
        if isinstance(result, dict) and "content" in result:
            content = result["content"]
            if isinstance(content, list) and content:
                text = content[0].get("text", "")
                if text:
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return text
        return result

    def get_best_sellers(
        self, category_id: int, domain: str = "US", limit: int = 100
    ) -> List[Dict[str, Any]]:
        """获取指定类目的 Best Sellers 列表。

        Args:
            category_id: Keepa 类目 ID（必传，0 无效）
            domain: 市场域名 (US, UK, DE 等)
            limit: 返回数量

        Returns:
            List[dict]: 每个 dict 至少包含 asin 字段
        """
        if not category_id or category_id <= 0:
            raise KeepaError(
                f"category_id 必须为正整数，当前为 {category_id}。请从类目 URL 解析正确的 Keepa category_id"
            )

        try:
            result = self._call_mcp_tool(
                "get_best_sellers",
                {"categoryId": category_id, "domain": domain, "limit": limit},
            )
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                return result.get("asins", result.get("products", []))
            return []
        except KeepaError as e:
            logger.warning(f"keepa-mcp get_best_sellers 失败: {e}")
            return []

    def get_product(self, asin: str, domain: str = "US") -> Optional[Dict[str, Any]]:
        """获取单个商品详情。

        Args:
            asin: 商品 ASIN
            domain: 市场域名

        Returns:
            dict: 商品详情，包含 title, brand, price, rating, reviewCount 等
        """
        if not asin:
            return None

        try:
            result = self._call_mcp_tool(
                "get_product",
                {"asin": asin, "domain": domain},
            )
            return result if isinstance(result, dict) else {}
        except KeepaError as e:
            logger.warning(f"keepa-mcp get_product 失败: {asin}: {e}")
            return None

    def get_price_history(self, asin: str, domain: str = "US") -> Optional[Dict[str, Any]]:
        """获取商品价格历史。"""
        if not asin:
            return None
        try:
            result = self._call_mcp_tool(
                "get_price_history",
                {"asin": asin, "domain": domain},
            )
            return result if isinstance(result, dict) else {}
        except KeepaError as e:
            logger.warning(f"keepa-mcp get_price_history 失败: {asin}: {e}")
            return None

    def get_sales_rank_history(self, asin: str, domain: str = "US") -> Optional[Dict[str, Any]]:
        """获取商品 BSR 历史。"""
        if not asin:
            return None
        try:
            result = self._call_mcp_tool(
                "get_sales_rank_history",
                {"asin": asin, "domain": domain},
            )
            return result if isinstance(result, dict) else {}
        except KeepaError as e:
            logger.warning(f"keepa-mcp get_sales_rank_history 失败: {asin}: {e}")
            return None

    def close(self) -> None:
        """关闭子进程。"""
        with self._lock:
            if self._process and self._process.poll() is None:
                try:
                    self._process.stdin.close()
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                finally:
                    self._process = None
                    self._initialized = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def _now() -> float:
    import time
    return time.monotonic()


def _now_plus_seconds(seconds: int) -> float:
    return _now() + seconds


class KeepaError(Exception):
    """keepa-mcp 错误。"""
    pass
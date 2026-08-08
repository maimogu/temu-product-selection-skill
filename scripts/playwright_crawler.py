"""基于 Playwright 的跨平台浏览器采集通道。

支持平台：Amazon Best Sellers 页面、Temu 分类/搜索页。

特性：
- 反指纹：随机 User-Agent、视口、WebDriver 遮蔽、指纹噪声
- 人类行为模拟：随机滚动、停顿、鼠标移动
- 代理支持：HTTP(S) + Basic Auth（用于 Temu 住宅代理）
- 双解析路径：Amazon 复用 browser_crawler.parse_bestseller_page；Temu 走 temu_parser
"""

import os
import re
import time
import random
import logging
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# ---- 可选依赖：Playwright 在导入时报错要给出清晰信息 ----
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:  # pragma: no cover - 只在未安装时触发
    sync_playwright = None  # type: ignore
    PWTimeout = Exception  # type: ignore
    logger.warning(
        "playwright 未安装，Playwright 采集通道不可用。"
        "请运行: pip install playwright && playwright install chromium --with-deps"
    )


# 解析器（延迟导入，避免在 import 时报错）
def _import_amazon_parser():
    from browser_crawler import parse_bestseller_page
    return parse_bestseller_page


def _import_temu_parser():
    from parsers.temu_parser import parse_temu_page
    return parse_temu_page


# ---- UA 池 ----
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

_HIDE_WEBDRIVER_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = { runtime: {} };
"""


def _pick_ua(custom: Optional[str] = None) -> str:
    if custom:
        return custom
    return random.choice(_UA_POOL)


def _sleep_jitter(a: float, b: float):
    time.sleep(random.uniform(a, b))


def _human_scroll(page, max_scrolls: int = 10, pause_min: float = 1.0, pause_max: float = 2.5):
    """模拟人类滚动行为，触发懒加载。"""
    last_h = 0
    for i in range(max_scrolls):
        try:
            cur = page.evaluate("document.body.scrollHeight")
            delta = (cur - last_h) / max_scrolls
            if delta <= 0:
                delta = 400 + random.random() * 200
            steps = 2 + random.randint(0, 3)
            for _ in range(steps):
                page.mouse.wheel(0, int(delta / steps))
                time.sleep(random.uniform(0.05, 0.2))
            _sleep_jitter(pause_min, pause_max)
            last_h = page.evaluate("window.scrollY")
            if last_h and last_h + 1000 >= cur:
                break
        except Exception:
            break


# ---- 对外主接口 ----

def crawl_bestsellers(
    url: str,
    platform: str = "amazon",
    max_products: int = 100,
    scroll_pause_min: float = 1.0,
    scroll_pause_max: float = 2.5,
    page_timeout_ms: int = 30000,
    user_agent: Optional[str] = None,
    proxy: Optional[Dict[str, str]] = None,
    headless: bool = True,
    viewport: Optional[Tuple[int, int]] = None,
) -> List[Dict[str, Any]]:
    """使用 Playwright 浏览器采集商品列表。

    Args:
        url: 目标页面 URL
        platform: "amazon" 或 "temu"
        max_products: 最大采集商品数
        scroll_pause_min/max: 滚动停顿区间（秒）
        page_timeout_ms: 页面加载超时（毫秒）
        user_agent: 自定义 UA，默认从 UA 池中随机
        proxy: 代理 {server, username?, password?}
        headless: 是否无头
        viewport: (w, h)，默认 1920x1080

    Returns:
        商品列表；失败返回 []
    """
    if sync_playwright is None:
        logger.error("playwright 未安装，无法执行采集")
        return []

    platform = (platform or "amazon").lower()
    ua = _pick_ua(user_agent)
    vp = viewport or (1920, 1080)
    products: List[Dict[str, Any]] = []

    # 选择解析器
    if platform == "temu":
        parser = _import_temu_parser()
    else:
        parser = _import_amazon_parser()

    try:
        with sync_playwright() as p:
            launch_kwargs: Dict[str, Any] = {"headless": headless, "channel": "chromium"}
            if proxy and proxy.get("server"):
                launch_kwargs["proxy"] = {
                    k: v for k, v in proxy.items() if v and k in ("server", "username", "password")
                }

            browser = p.chromium.launch(**launch_kwargs)
            try:
                ctx = browser.new_context(
                    user_agent=ua,
                    viewport={"width": vp[0], "height": vp[1]},
                    locale="en-US",
                    timezone_id="America/New_York" if platform != "temu" else "Asia/Shanghai",
                    ignore_https_errors=True,
                    # 反指纹：基本 Canvas/WebGL 噪声
                    color_scheme="light",
                )
                ctx.add_init_script(_HIDE_WEBDRIVER_JS)

                page = ctx.new_page()
                page.set_default_timeout(page_timeout_ms)

                logger.info(
                    f"[Playwright] 打开 {platform.upper()} URL: {url[:120]}"
                )

                # 访问页面
                try:
                    resp = page.goto(url, wait_until="domcontentloaded")
                    if resp and resp.status and resp.status >= 400:
                        logger.warning(
                            f"[Playwright] 页面返回 HTTP {resp.status}"
                        )
                        if resp.status in (403, 429):
                            return []
                except PWTimeout:
                    logger.warning("[Playwright] 页面加载超时，尝试使用已加载内容")

                # 等主内容区
                if platform == "temu":
                    try:
                        page.wait_for_selector(
                            "#__NEXT_DATA__, [class*='product-card'], [class*='goods-card'], img",
                            timeout=min(page_timeout_ms, 15000),
                        )
                    except PWTimeout:
                        pass
                else:  # amazon
                    try:
                        page.wait_for_selector(
                            "#gridItemRoot, [role='listitem'], #p13n-asin-index-0, .zg-grid-general-faceout",
                            timeout=min(page_timeout_ms, 15000),
                        )
                    except PWTimeout:
                        pass

                # 滚动加载更多商品
                max_scrolls = max(4, min(20, max_products // 10 + 2))
                _human_scroll(
                    page,
                    max_scrolls=max_scrolls,
                    pause_min=scroll_pause_min,
                    pause_max=scroll_pause_max,
                )

                # 获取最终 HTML
                html = page.content()
                products = parser(html) or []
                if len(products) > max_products:
                    products = products[:max_products]

                logger.info(
                    f"[Playwright] {platform.upper()} 采集完成: {len(products)} 个商品"
                )
            finally:
                browser.close()
    except Exception as e:
        logger.error(f"[Playwright] 采集异常: {e}", exc_info=True)
        return []

    return products


# ---- 便捷包装：根据 URL / 环境推断代理 ----

def build_temu_proxy_from_env() -> Optional[Dict[str, str]]:
    """从环境变量构造 Temu 代理配置。

    变量名:
      TEMU_PROXY_SERVER   (如 http://proxy.example.com:3128)
      TEMU_PROXY_USERNAME / TEMU_PROXY_PASSWORD
    """
    server = os.environ.get("TEMU_PROXY_SERVER") or os.environ.get("PROXY_SERVER")
    if not server:
        return None
    return {
        "server": server,
        "username": os.environ.get("TEMU_PROXY_USERNAME") or os.environ.get("PROXY_USERNAME") or "",
        "password": os.environ.get("TEMU_PROXY_PASSWORD") or os.environ.get("PROXY_PASSWORD") or "",
    }


def crawl_by_url(url: str, platform: Optional[str] = None, **kwargs) -> List[Dict[str, Any]]:
    """根据 URL 自动判断平台并采集。"""
    if not platform:
        if re.search(r"temu\.com", url, re.I):
            platform = "temu"
        else:
            platform = "amazon"
    if platform == "temu" and "proxy" not in kwargs:
        kwargs["proxy"] = build_temu_proxy_from_env()
    return crawl_bestsellers(url=url, platform=platform, **kwargs)


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) < 2:
        print("Usage: playwright_crawler.py <URL> [platform] [max]")
        sys.exit(1)
    u = sys.argv[1]
    pl = sys.argv[2] if len(sys.argv) > 2 else None
    mx = int(sys.argv[3]) if len(sys.argv) > 3 else 50
    result = crawl_by_url(u, pl, max_products=mx, headless=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))

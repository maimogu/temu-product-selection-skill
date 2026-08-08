"""采集主入口。

编排采集流程：
1. 读取飞书「类目管理」表获取启用的类目（含 platform 字段，支持 amazon/temu）
2. 通道优先级：
   - Amazon: Playwright 浏览器 → keepa-mcp → agent-browser
   - Temu:   Playwright 浏览器（支持住宅代理）
3. 将采集结果写入飞书「榜单快照」表，并更新（非跳过）「商品详情」表
"""

import os
import re
import sys
import json
import logging
from datetime import date
from typing import List, Dict, Any, Optional, Callable

# 将脚本所在目录加入 sys.path，使同目录模块可被 import（无论从哪个 cwd 运行）
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from feishu_client import FeishuClient, FeishuAPIError
from keepa_client import KeepaClient, KeepaError
from browser_crawler import parse_bestseller_page

# Playwright 通道：延迟导入避免未安装时报错
def _import_playwright_crawl():
    try:
        from playwright_crawler import crawl_by_url, build_temu_proxy_from_env
        return crawl_by_url, build_temu_proxy_from_env
    except Exception:
        return None, None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("crawl")


# Amazon URL 中提取 browseNode ID（Amazon 类目节点 ID）
# 示例 URL: https://www.amazon.com/Best-Sellers-Kitchen-Dining/zgbss/kitchen/ref=zg_bs_nav_kitchen_0
# 或: https://www.amazon.com/gp/bestsellers/kitchen/13801
# 或: https://www.amazon.com/best-sellers/pc/zgbss/pc/ref=zg_bs_nav_pc_0_0
BROWSE_NODE_PATTERN = re.compile(
    r'/gp/bestsellers/(\d+)|/bestsellers/[\w-]+/(\d+)|zg_bs/([\w-]+)/(\d+)',
    re.IGNORECASE,
)


def parse_category_id_from_url(category_url: str) -> int:
    """从 Amazon Best Sellers URL 中解析出数字类目 ID。

    Amazon Best Sellers URL 中通常包含数字 ID（Amazon browseNode），
    Keepa 也使用该 ID 作为 category_id。

    Args:
        category_url: Amazon Best Sellers 类目 URL

    Returns:
        int: 类目 ID，解析失败返回 0
    """
    if not category_url:
        return 0

    match = BROWSE_NODE_PATTERN.search(category_url)
    if match:
        # 匹配三个分组之一
        for group in match.groups():
            if group and group.isdigit():
                return int(group)

    # 兜底：直接从 URL 中提取所有 4-10 位数字串
    fallback_match = re.search(r'/(\d{4,10})(?:/|\?|$)', category_url)
    if fallback_match:
        return int(fallback_match.group(1))

    return 0


class CrawlOrchestrator:
    """采集编排器。"""

    def __init__(
        self,
        feishu: FeishuClient,
        keepa: KeepaClient,
        categories_table_id: str,
        snapshots_table_id: str,
        products_table_id: str,
        browser_crawl_func: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
    ):
        """
        Args:
            feishu: 飞书客户端
            keepa: keepa 客户端
            categories_table_id: 类目管理表 table_id
            snapshots_table_id: 榜单快照表 table_id
            products_table_id: 商品详情表 table_id
            browser_crawl_func: agent-browser 抓取函数，输入 URL，返回商品列表。
                在 Skill 环境中调用 agent-browser 时注入；非 Skill 环境可为 None（降级失效）。
        """
        self.feishu = feishu
        self.keepa = keepa
        self.categories_table_id = categories_table_id
        self.snapshots_table_id = snapshots_table_id
        self.products_table_id = products_table_id
        self.browser_crawl_func = browser_crawl_func

    def get_enabled_categories(self) -> List[Dict[str, Any]]:
        """获取启用的类目列表。"""
        records = self.feishu.get_records(self.categories_table_id)
        categories = []
        for record in records:
            fields = record.get("fields", {})

            # 「是否启用」在飞书中为复选框，返回 True/False
            is_enabled = fields.get("是否启用", False)
            if isinstance(is_enabled, dict):
                # 飞书某些字段返回 {"text": "...", "value": true} 结构
                is_enabled = is_enabled.get("value", False)

            if not is_enabled:
                continue

            # 「抓取URL」字段：飞书链接字段返回 {"link": "...", "text": "..."} 或 None
            url_field = fields.get("抓取URL")
            if isinstance(url_field, dict):
                url = url_field.get("link", "")
            elif isinstance(url_field, str):
                url = url_field
            else:
                url = ""

            # 「类目名称」字段：可能是字符串或 {"text": "..."} 结构
            name_field = fields.get("类目名称", "")
            if isinstance(name_field, dict):
                name = name_field.get("text", "")
            else:
                name = name_field

            # 平台字段：可选，默认 "amazon"
            platform_field = fields.get("平台") or fields.get("platform")
            if isinstance(platform_field, dict):
                platform = platform_field.get("text", "amazon")
            elif isinstance(platform_field, str):
                platform = platform_field
            else:
                platform = "amazon"
            platform = (platform or "amazon").lower()

            categories.append({
                "record_id": record.get("record_id"),
                "name": name,
                "url": url,
                "platform": platform,
            })

        logger.info(f"获取到 {len(categories)} 个启用的类目")
        return categories

    def crawl_via_keepa(
        self, category_name: str, category_url: str
    ) -> List[Dict[str, Any]]:
        """通过 keepa-mcp 采集榜单数据。"""
        logger.info(f"使用 keepa-mcp 采集: {category_name}")

        # 从 URL 解析 Keepa category_id（Amazon browseNode）
        category_id = parse_category_id_from_url(category_url)
        if not category_id:
            logger.warning(
                f"无法从 URL 解析 category_id: {category_url}，"
                f"keepa-mcp 采集将失败"
            )
            return []

        try:
            best_sellers = self.keepa.get_best_sellers(
                category_id=category_id,
                domain="US",
                limit=100,
            )

            if not best_sellers:
                logger.warning(f"keepa-mcp 返回空列表: {category_name}")
                return []

            products = []
            for rank, asin_item in enumerate(best_sellers, 1):
                if isinstance(asin_item, str):
                    asin = asin_item
                elif isinstance(asin_item, dict):
                    asin = asin_item.get("asin", "")
                else:
                    continue

                if not asin:
                    continue

                # 获取商品详情
                detail = self.keepa.get_product(asin) or {}

                products.append({
                    "asin": asin,
                    "bsr_rank": rank,
                    "title": detail.get("title", ""),
                    "price": detail.get("price", 0.0),
                    "star_rating": detail.get("rating", 0.0),
                    "review_count": detail.get("reviewCount", 0),
                    "brand": detail.get("brand", ""),
                    "detail_page_url": f"https://www.amazon.com/dp/{asin}",
                })

            logger.info(f"keepa-mcp 采集完成: {category_name}，共 {len(products)} 个商品")
            return products

        except KeepaError as e:
            logger.error(f"keepa-mcp 采集失败: {category_name}: {e}")
            return []

    def crawl_via_browser(
        self, category_name: str, category_url: str
    ) -> List[Dict[str, Any]]:
        """通过 agent-browser 采集榜单数据（兜底通道）。

        Args:
            category_name: 类目名称
            category_url: Amazon Best Sellers URL

        Returns:
            List[dict]: 商品列表。若 browser_crawl_func 未注入则返回空列表。
        """
        if self.browser_crawl_func is None:
            logger.warning(
                f"agent-browser 降级未启用（未注入 browser_crawl_func）: {category_name}"
            )
            return []

        logger.info(f"使用 agent-browser 采集: {category_name}")

        try:
            html_content = self.browser_crawl_func(category_url)
            if not html_content:
                logger.warning(f"agent-browser 返回空内容: {category_name}")
                return []

            # 如果返回的是 HTML 字符串，解析它
            if isinstance(html_content, str):
                products = parse_bestseller_page(html_content)
            elif isinstance(html_content, list):
                # agent-browser 可能直接返回已解析的商品列表
                products = html_content
            else:
                logger.warning(f"agent-browser 返回未知类型: {type(html_content)}")
                return []

            logger.info(
                f"agent-browser 采集完成: {category_name}，共 {len(products)} 个商品"
            )
            return products

        except Exception as e:
            logger.error(f"agent-browser 采集失败: {category_name}: {e}")
            return []

    def crawl_via_playwright(
        self, category_name: str, category_url: str, platform: str
    ) -> List[Dict[str, Any]]:
        """通过 Playwright 浏览器采集（主通道）。

        Args:
            category_name: 类目名称
            category_url: 类目 URL
            platform: "amazon" 或 "temu"

        Returns:
            商品列表。Playwright 未安装或失败返回 []
        """
        crawl_fn, _proxy_fn = _import_playwright_crawl()
        if crawl_fn is None:
            logger.warning(
                f"Playwright 采集通道不可用（依赖未安装）: {category_name}"
            )
            return []

        logger.info(f"[Playwright] 采集 [{platform.upper()}] {category_name}")
        try:
            products = crawl_fn(
                url=category_url,
                platform=platform,
                max_products=100,
                headless=True,
            )
            if not products:
                logger.warning(f"[Playwright] 返回空: {category_name}")
                return []
            logger.info(
                f"[Playwright] 完成 [{platform.upper()}] {category_name}: {len(products)} 个商品"
            )
            return products
        except Exception as e:
            logger.error(f"[Playwright] 采集异常 [{platform.upper()}] {category_name}: {e}")
            return []

    def write_to_feishu(
        self, category_name: str, products: List[Dict[str, Any]], snapshot_date: str
    ) -> int:
        """将采集结果写入飞书多维表格。

        - 榜单快照：每次都新增记录（保留历史）
        - 商品详情：已存在的 ASIN 用 batch_update 更新价格/评分等字段；
          不存在的 ASIN 用 batch_create 新增
        """
        snapshot_records = []
        product_records_upsert = []

        for p in products:
            # 榜单快照记录
            snapshot_records.append({
                "快照日期": snapshot_date,
                "类目名称": category_name,
                "排名": p["bsr_rank"],
                "ASIN": p["asin"],
                "商品标题": p["title"],
                "价格": p["price"],
                "星级评分": p["star_rating"],
                "Review数量": p["review_count"],
                "估算销量": p.get("estimated_sales", 0),
                "估算销售额": p.get("estimated_revenue", 0.0),
                "供应商信息": p.get("brand", ""),
                "详情页链接": p.get("detail_page_url", ""),
            })

            # 商品详情记录（用于 upsert）
            product_records_upsert.append({
                "ASIN": p["asin"],
                "商品标题": p["title"],
                "品牌": p.get("brand", ""),
                "当前价格": p["price"],
                "星级评分": p["star_rating"],
                "Review数量": p["review_count"],
                "供应商信息": p.get("brand", ""),
                "详情页链接": p.get("detail_page_url", ""),
            })

        # 写入榜单快照
        if snapshot_records:
            self.feishu.batch_create_records(self.snapshots_table_id, snapshot_records)
            logger.info(f"写入榜单快照: {len(snapshot_records)} 条")

        # 商品详情 upsert
        if product_records_upsert:
            self._upsert_products(product_records_upsert)

        return len(snapshot_records)

    def _upsert_products(self, product_records: List[Dict[str, Any]]) -> None:
        """商品详情表的 upsert 操作。

        已存在的 ASIN：更新价格/评分/评论数等字段
        不存在的 ASIN：新增记录
        """
        # 读取已有商品详情
        existing_records = self.feishu.get_records(self.products_table_id)
        existing_map = {}  # asin -> record_id

        for record in existing_records:
            fields = record.get("fields", {})
            asin_field = fields.get("ASIN", "")
            # 飞书文本字段可能返回 {"text": "..."} 或纯字符串
            if isinstance(asin_field, dict):
                asin = asin_field.get("text", "")
            else:
                asin = asin_field

            if asin:
                existing_map[asin] = record.get("record_id")

        # 区分新增和更新
        to_create = []
        to_update = []

        for p in product_records:
            asin = p["ASIN"]
            if asin in existing_map:
                # 已存在，构造 update payload
                to_update.append({
                    "record_id": existing_map[asin],
                    "fields": {
                        "商品标题": p["商品标题"],
                        "品牌": p["品牌"],
                        "当前价格": p["当前价格"],
                        "星级评分": p["星级评分"],
                        "Review数量": p["Review数量"],
                        "供应商信息": p["供应商信息"],
                        "详情页链接": p["详情页链接"],
                    },
                })
            else:
                to_create.append(p)

        if to_create:
            self.feishu.batch_create_records(self.products_table_id, to_create)
            logger.info(f"新增商品详情: {len(to_create)} 条")

        if to_update:
            self.feishu.batch_update_records(self.products_table_id, to_update)
            logger.info(f"更新商品详情: {len(to_update)} 条")

    def run(self, snapshot_date: str = None) -> Dict[str, Any]:
        """执行完整采集流程。

        采集通道优先级（按平台）：
        - Amazon: Playwright → keepa-mcp → agent-browser
        - Temu:   Playwright（仅此通道，keepa 不支持 Temu）
        """
        if snapshot_date is None:
            snapshot_date = date.today().isoformat()

        categories = self.get_enabled_categories()
        if not categories:
            logger.warning("没有启用的类目")
            return {"status": "ok", "total": 0, "categories": []}

        results = []
        total_products = 0

        for cat in categories:
            platform = cat["platform"]
            cat_name = f"[{platform.upper()}] {cat['name']}"

            # 主通道：Playwright 浏览器（所有平台通用）
            products = self.crawl_via_playwright(cat["name"], cat["url"], platform)

            # Amazon 降级通道：keepa-mcp
            if not products and platform == "amazon":
                logger.warning(
                    f"类目 {cat_name} Playwright 采集失败，降级到 keepa-mcp"
                )
                products = self.crawl_via_keepa(cat["name"], cat["url"])

            # Amazon 降级通道：agent-browser（仅 Trae 环境可用）
            if not products and platform == "amazon" and self.browser_crawl_func is not None:
                logger.warning(
                    f"类目 {cat_name} keepa-mcp 也失败，降级到 agent-browser"
                )
                products = self.crawl_via_browser(cat["name"], cat["url"])

            if not products:
                results.append({
                    "category": cat["name"],
                    "platform": platform,
                    "count": 0,
                    "status": "failed",
                    "error": "所有采集通道均未返回数据",
                })
                continue

            count = self.write_to_feishu(cat["name"], products, snapshot_date)
            total_products += count
            results.append({
                "category": cat["name"],
                "platform": platform,
                "count": count,
                "status": "ok",
            })

        summary = {
            "status": "ok",
            "total": total_products,
            "snapshot_date": snapshot_date,
            "categories": results,
        }

        logger.info(f"采集完成: {json.dumps(summary, ensure_ascii=False)}")
        return summary


def main():
    """采集主函数。"""
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    app_token = os.environ.get("FEISHU_APP_TOKEN")
    keepa_api_key = os.environ.get("KEEPA_API_KEY")

    if not all([app_id, app_secret, app_token]):
        logger.error(
            "缺少环境变量: FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_APP_TOKEN"
        )
        sys.exit(1)

    categories_table_id = os.environ.get("FEISHU_CATEGORIES_TABLE_ID", "")
    snapshots_table_id = os.environ.get("FEISHU_SNAPSHOTS_TABLE_ID", "")
    products_table_id = os.environ.get("FEISHU_PRODUCTS_TABLE_ID", "")

    if not all([categories_table_id, snapshots_table_id, products_table_id]):
        logger.error("缺少表 ID 环境变量")
        sys.exit(1)

    feishu = FeishuClient(app_id, app_secret, app_token)
    keepa = KeepaClient(api_key=keepa_api_key)

    orchestrator = CrawlOrchestrator(
        feishu=feishu,
        keepa=keepa,
        categories_table_id=categories_table_id,
        snapshots_table_id=snapshots_table_id,
        products_table_id=products_table_id,
        # browser_crawl_func 在普通脚本环境中无法注入，需要 Skill 环境
        # 在 Skill 环境中通过依赖注入的方式传入 agent-browser 调用函数
        browser_crawl_func=None,
    )

    try:
        result = orchestrator.run()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result
    finally:
        keepa.close()


if __name__ == "__main__":
    main()
"""agent-browser 兜底采集模块。

当 keepa-mcp 不可用时，使用 agent-browser Skill 直接访问 Amazon Best Sellers 页面，
解析 HTML 提取榜单数据。

注意：此模块依赖 agent-browser Skill，需要在 Skill 环境中调用。
HTML 解析按商品卡片分块，每个卡片内提取字段，确保字段与 ASIN 正确对齐。
"""

import re
import json
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


# Amazon Best Sellers 页面商品卡片的容器（多种版本兼容）
# zg-grid-general-faceout: 新版页面
# zg-item-immersion: 旧版页面
# p13n-asin-card: 部分变体
CARD_CONTAINER_PATTERN = re.compile(
    r'<div[^>]*class="[^"]*(?:zg-grid-general-faceout|zg-item-immersion|p13n-asin-card|a-cardui)[^"]*"[^>]*>',
    re.IGNORECASE,
)


def parse_bestseller_page(html_content: str) -> List[Dict[str, Any]]:
    """从 Amazon Best Sellers 页面 HTML 中解析商品列表。

    解析策略：
    1. 按商品卡片分块（每个 <div class="zg-grid-general-faceout">...</div> 是一个商品）
    2. 每个卡片内独立提取 ASIN、排名、标题、价格、评分、评论数
    3. 这样可以保证字段与 ASIN 的对应关系正确

    Args:
        html_content: 页面 HTML 内容

    Returns:
        List[dict]: 商品列表，每个元素包含 asin, bsr_rank, title, price, star_rating, review_count, detail_page_url
    """
    if not html_content:
        return []

    # 按卡片分块
    cards = _split_into_cards(html_content)
    logger.info(f"页面分块得到 {len(cards)} 个商品卡片")

    products = []
    for idx, card_html in enumerate(cards):
        if idx >= 100:  # 最多取 Top100
            break

        product = _parse_single_card(card_html, default_rank=idx + 1)
        if product and product["asin"]:
            products.append(product)

    logger.info(f"从 HTML 解析出 {len(products)} 个商品")
    return products


def _split_into_cards(html_content: str) -> List[str]:
    """将 HTML 按商品卡片分块。

    采用改进的策略：以 ASIN 链接出现位置为锚点，从该锚点向后取一段 HTML 作为卡片。
    这样即使容器 class 名变化，也能可靠分块。
    """
    # 找到所有 ASIN 链接位置（作为卡片锚点）
    # ASIN 链接形如 /dp/B0ABCDEFGH 后跟 / ? " ' < > 空白 或字符串结尾
    asin_link_pattern = re.compile(r'/dp/([A-Z0-9]{10})(?:[/\?"\'<>\s]|$)')
    matches = list(asin_link_pattern.finditer(html_content))

    if not matches:
        return []

    # 以每个 ASIN 锚点为起点，到下一个锚点为止作为一个卡片
    cards = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(html_content)
        card_html = html_content[start:end]
        cards.append(card_html)

    return cards


def _parse_single_card(card_html: str, default_rank: int) -> Optional[Dict[str, Any]]:
    """从单个商品卡片的 HTML 中提取字段。

    所有字段都在同一卡片内提取，确保对齐。
    """
    # ASIN：从 /dp/ASIN 链接提取
    asin_match = re.search(r'/dp/([A-Z0-9]{10})(?:[/\?"\'<>\s]|$)', card_html)
    if not asin_match:
        return None
    asin = asin_match.group(1)

    # 排名：从 #N 格式提取（可能在卡片前部，也可能在卡片内）
    rank_match = re.search(r'#(\d+)[\s\n<]', card_html)
    bsr_rank = int(rank_match.group(1)) if rank_match else default_rank

    # 标题：从 alt="..." 或 title="..." 或 <span> 标签内提取
    title = ""
    title_match = re.search(r'(?:alt|title|aria-label)="([^"]{5,})"', card_html)
    if title_match:
        title = title_match.group(1)
    else:
        # 尝试从 <span> 标签提取（可能包含商品标题）
        span_match = re.search(r'<span[^>]*class="[^"]*a-text-normal[^"]*"[^>]*>\s*([^<]+)\s*</span>', card_html)
        if span_match:
            title = span_match.group(1).strip()

    # 价格：从 $N.NN 格式提取
    price = 0.0
    price_match = re.search(r'\$\s*([\d,]+\.?\d*)', card_html)
    if price_match:
        price = _parse_price(price_match.group(1))

    # 星级评分：从 N.N out of 5 格式提取
    star_rating = 0.0
    rating_match = re.search(r'(\d\.\d)\s*out of 5', card_html)
    if rating_match:
        try:
            star_rating = float(rating_match.group(1))
        except ValueError:
            pass

    # 评论数：从 NNN ratings? 格式提取
    review_count = 0
    review_match = re.search(r'([\d,]+)\s*ratings?', card_html, re.IGNORECASE)
    if review_match:
        review_count = _parse_review_count(review_match.group(1))

    return {
        "asin": asin,
        "bsr_rank": bsr_rank,
        "title": title,
        "price": price,
        "star_rating": star_rating,
        "review_count": review_count,
        "brand": "",  # 榜单页通常不显示品牌，需要从详情页获取
        "detail_page_url": f"https://www.amazon.com/dp/{asin}",
    }


def _parse_price(price_str: str) -> float:
    """解析价格字符串为浮点数。"""
    try:
        return float(price_str.replace(",", ""))
    except (ValueError, AttributeError):
        return 0.0


def _parse_review_count(review_str: str) -> int:
    """解析评论数字符串为整数。"""
    try:
        return int(review_str.replace(",", ""))
    except (ValueError, AttributeError):
        return 0


# 以下为 agent-browser Skill 的指令模板，用于在实际调用时生成 Skill 执行指令
# 实际使用时通过 Skill 机制调用 agent-browser

BROWSER_CRAWL_INSTRUCTION = """Navigate to the Amazon Best Sellers page for the category: {category_url}
Wait for the page to fully load (including product listings).
Scroll to the bottom to load all 100 products (lazy loading).
Extract the top 100 products with the following fields:
- ASIN (from the product link URL, pattern /dp/XXXXXXXXXX/)
- BSR rank (from the rank number displayed, e.g. #1, #2, ...)
- Product title (from the product link text or image alt attribute)
- Price (in USD, e.g. $29.99)
- Star rating (e.g. 4.5 out of 5 stars)
- Review count (e.g. 3,200 ratings)
- Product URL (https://www.amazon.com/dp/ASIN/)

Return the data as a JSON array of objects, one per product:
[
  {{
    "asin": "B0XXXXXXXX",
    "bsr_rank": 1,
    "title": "Product Title",
    "price": 29.99,
    "star_rating": 4.5,
    "review_count": 3200,
    "brand": "",
    "detail_page_url": "https://www.amazon.com/dp/B0XXXXXXXX"
  }},
  ...
]

Important: Each product's fields must be extracted from its own card on the page.
Do NOT mix fields between products."""
"""Temu 商品页面解析器。

支持两种解析路径：
1. 优先：从 __NEXT_DATA__ <script> 标签提取 Next.js 水合 JSON
2. 兜底：DOM 解析（正则/BeautifulSoup 提取卡片信息）
"""

import re
import json
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


# ------- 辅助函数 -------

def _safe_get(d: dict, *keys, default=None):
    """安全地深度获取字典值。"""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _to_float(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    m = re.search(r"[\d.]+", s)
    if not m:
        return 0.0
    try:
        return float(m.group())
    except ValueError:
        return 0.0


def _to_int(v) -> int:
    if v is None:
        return 0
    if isinstance(v, int):
        return v
    s = str(v).strip().replace(",", "")
    # "10万+" → 100000
    m_wan = re.search(r"([\d.]+)\s*万", s)
    if m_wan:
        try:
            return int(float(m_wan.group(1)) * 10000)
        except ValueError:
            return 0
    m = re.search(r"[\d,]+", s)
    if not m:
        return 0
    try:
        return int(m.group().replace(",", ""))
    except ValueError:
        return 0


# ------- 路径 1：__NEXT_DATA__ 提取 -------

_NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _extract_from_next_data(html_content: str) -> List[Dict[str, Any]]:
    m = _NEXT_DATA_RE.search(html_content)
    if not m:
        return []

    try:
        payload = json.loads(m.group(1))
    except json.JSONDecodeError:
        logger.warning("__NEXT_DATA__ JSON 解析失败")
        return []

    # Next.js props 路径可能因 Temu 版本而变化，探测几个常见位置
    candidates = []
    props = payload.get("props", {})
    page_props = props.get("pageProps", {})
    if isinstance(page_props, dict):
        for key, val in page_props.items():
            if isinstance(val, list):
                candidates.append(val)
            elif isinstance(val, dict):
                for k2, v2 in val.items():
                    if isinstance(v2, list):
                        candidates.append(v2)
    # Apollo state
    apollo = page_props.get("apolloState", page_props.get("__APOLLO_STATE__", {}))
    if isinstance(apollo, dict):
        for k, v in apollo.items():
            if isinstance(v, list):
                candidates.append(v)
            elif isinstance(v, dict):
                for k2, v2 in v.items():
                    if isinstance(v2, list):
                        candidates.append(v2)

    # 在所有候选列表中查找商品信息
    products = []
    seen_ids = set()

    def _try_normalize_item(item: dict, idx: int) -> Optional[Dict[str, Any]]:
        # Temu goods 常见字段名
        goods_id = (
            item.get("goods_id")
            or item.get("goodsId")
            or item.get("productId")
            or item.get("id")
        )
        if not goods_id:
            return None
        title = (
            item.get("goods_name")
            or item.get("goodsName")
            or item.get("title")
            or item.get("name")
            or ""
        )
        price = (
            item.get("price")
            or item.get("sale_price")
            or item.get("salePrice")
            or item.get("min_price")
            or item.get("minOnSalePrice")
            or 0
        )
        original_price = (
            item.get("original_price")
            or item.get("originPrice")
            or item.get("market_price")
            or 0
        )
        rating = item.get("rating") or item.get("star_rating") or item.get("starRating") or 0
        review_cnt = (
            item.get("review_count")
            or item.get("reviewCount")
            or item.get("comment_count")
            or item.get("commentNum")
            or 0
        )
        sales = (
            item.get("sales_count")
            or item.get("salesCount")
            or item.get("sold_count")
            or item.get("soldText")
            or ""
        )
        img = (
            item.get("img_url")
            or item.get("imageUrl")
            or item.get("thumb_url")
            or item.get("cover")
            or item.get("pic")
            or ""
        )
        if isinstance(img, dict):
            img = img.get("url", "")
        detail_url = (
            item.get("detail_url")
            or item.get("detailUrl")
            or item.get("link")
            or item.get("url")
            or ""
        )
        if not detail_url and goods_id:
            detail_url = f"https://www.temu.com/detail.html?goods_id={goods_id}"
        if detail_url and not detail_url.startswith("http"):
            detail_url = "https://www.temu.com" + detail_url

        return {
            "asin": str(goods_id),
            "bsr_rank": idx + 1,
            "title": str(title).strip(),
            "price": _to_float(price),
            "original_price": _to_float(original_price),
            "star_rating": _to_float(rating),
            "review_count": _to_int(review_cnt),
            "sales_count": sales if isinstance(sales, str) else _to_int(sales),
            "image_url": str(img),
            "detail_page_url": str(detail_url),
            "platform": "temu",
        }

    for lst in candidates:
        for i, item in enumerate(lst):
            if not isinstance(item, dict):
                continue
            p = _try_normalize_item(item, len(seen_ids))
            if p and p["asin"] not in seen_ids:
                seen_ids.add(p["asin"])
                products.append(p)

    return products[:200]


# ------- 路径 2：DOM 正则兜底 -------

_CARD_BLOCKS = re.split(
    r'(?:<div[^>]*class="[^"]*(?:product-card|goods-card|_3xUcp|_2Lso3|item)[^"]*"[^>]*>)',
    html_content,
    flags=re.IGNORECASE,
)

_TITLE_RE = re.compile(r'title="([^"]{5,})"', re.IGNORECASE)
_IMG_RE = re.compile(r'<img[^>]+(?:src|data-src)="([^"]+)"', re.IGNORECASE)
_HREF_RE = re.compile(r'<a[^>]+href="([^"]+)"', re.IGNORECASE)
_PRICE_RE = re.compile(r'\$([\d.]+)')
_RATING_RE = re.compile(r'([\d.]+)\s*<[^>]*aria-label="[^"]*\d+\s*out\s*of\s*5', re.IGNORECASE)
_REV_RE = re.compile(r'(\d[\d,]*)\s*(?:review|评价|评论)', re.IGNORECASE)
_SOLD_RE = re.compile(r'([\d.]+[万+]?)\s*(?:已售|sold|purchased)', re.IGNORECASE)


def _extract_from_dom(html_content: str) -> List[Dict[str, Any]]:
    products = []
    for idx, block in enumerate(_CARD_BLOCKS):
        if not block or len(block) < 200:
            continue
        title_m = _TITLE_RE.search(block)
        href_m = _HREF_RE.search(block)
        if not (title_m or href_m):
            continue
        title = (title_m.group(1) if title_m else "").strip()
        img = (_IMG_RE.search(block).group(1) if _IMG_RE.search(block) else "")
        price_m = _PRICE_RE.search(block)
        price = float(price_m.group(1)) if price_m else 0.0
        rating_m = _RATING_RE.search(block)
        rating = float(rating_m.group(1)) if rating_m else 0.0
        rev_m = _REV_RE.search(block)
        review_cnt = _to_int(rev_m.group(1)) if rev_m else 0
        sold_m = _SOLD_RE.search(block)
        sales = sold_m.group(1) if sold_m else ""
        detail_url = (href_m.group(1) if href_m else "")
        if detail_url and not detail_url.startswith("http"):
            detail_url = "https://www.temu.com" + detail_url
        # 简单的伪 ASIN：用 URL 末尾的 goods_id 或用序列
        gid = re.search(r"goods_id=([A-Za-z0-9_-]+)", detail_url or "")
        if gid:
            asin = gid.group(1)
        else:
            asin = f"temu-{idx}"
        products.append({
            "asin": asin,
            "bsr_rank": idx,
            "title": title,
            "price": price,
            "original_price": 0.0,
            "star_rating": rating,
            "review_count": review_cnt,
            "sales_count": sales,
            "image_url": img,
            "detail_page_url": detail_url,
            "platform": "temu",
        })

    # 去重并限制数量
    seen = set()
    uniq = []
    for p in products:
        if p["asin"] in seen:
            continue
        seen.add(p["asin"])
        p["bsr_rank"] = len(uniq) + 1
        uniq.append(p)
    return uniq[:200]


# ------- 对外接口 -------

def parse_temu_page(html_content: str) -> List[Dict[str, Any]]:
    """从 Temu 页面 HTML 中解析商品列表。

    优先使用 __NEXT_DATA__ 水合 JSON 提取，失败时降级到 DOM 解析。
    """
    if not html_content:
        return []

    products = _extract_from_next_data(html_content)
    if products:
        logger.info(f"从 __NEXT_DATA__ 提取到 {len(products)} 个 Temu 商品")
        return products

    products = _extract_from_dom(html_content)
    if products:
        logger.info(f"从 DOM 解析提取到 {len(products)} 个 Temu 商品")
        return products

    logger.warning("Temu 页面解析失败，未提取到任何商品")
    return []

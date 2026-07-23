"""综合得分计算引擎。

纯函数模块，不依赖 IO。从飞书多维表格读取的榜单快照数据传入后计算五维得分。
"""

import yaml
import os
from dataclasses import dataclass
from typing import List
from statistics import mean, stdev, StatisticsError


@dataclass
class RankingRecord:
    """单条榜单快照记录。"""
    asin: str
    bsr_rank: int
    price: float
    star_rating: float
    review_count: int
    brand: str
    estimated_sales: int
    estimated_revenue: float
    snapshot_date: str


@dataclass
class MetricScores:
    """五维指标得分。"""
    asin: str
    traffic_score: float
    conversion_score: float
    aov_score: float
    growth_score: float
    risk_score: float
    composite_score: float


def load_config(config_path: str = None) -> dict:
    """加载评分配置文件。

    默认路径为 Skill 根目录的 config/scoring.yaml。
    """
    if config_path is None:
        # Skill 标准目录结构：scripts/ 在根目录下，config/ 也在根目录下
        skill_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(skill_root, "config", "scoring.yaml")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def calculate_traffic_score(records: List[RankingRecord], total_snapshots: int) -> float:
    """计算流量得分。

    records: 该 ASIN 的所有历史快照记录
    total_snapshots: 所有类目的总快照次数
    """
    if not records:
        return 0.0

    latest = records[-1]
    ranks = [r.bsr_rank for r in records]

    # 排名分：排名越高分越高
    rank_score = (1.0 - latest.bsr_rank / 100.0) * 100.0

    # 排名稳定性
    if len(ranks) >= 2 and mean(ranks) > 0:
        try:
            stability = 1.0 - (stdev(ranks) / mean(ranks))
        except (ZeroDivisionError, StatisticsError):
            # StatisticsError: 数据少于 2 个或方差为 0
            stability = 0.5
    else:
        stability = 0.5  # 仅一条记录时默认值

    stability_score = max(0.0, min(100.0, stability * 100.0))

    # 出现频率
    frequency = (len(records) / max(total_snapshots, 1)) * 100.0

    return rank_score * 0.5 + stability_score * 0.3 + frequency * 0.2


def calculate_conversion_score(records: List[RankingRecord]) -> float:
    """计算转化得分。"""
    if not records:
        return 0.0

    latest = records[-1]

    # 评分分
    rating_score = latest.star_rating * 20.0

    # 评论量级分
    review_cap = 500
    review_volume_score = min(latest.review_count / review_cap, 1.0) * 100.0

    # 评分成长期
    earliest = records[0]
    if earliest.review_count > 0:
        review_growth = (latest.review_count - earliest.review_count) / earliest.review_count * 100.0
    else:
        review_growth = 50.0 if len(records) > 1 else 0.0

    review_growth_score = max(0.0, min(100.0, review_growth))

    return rating_score * 0.4 + review_volume_score * 0.4 + review_growth_score * 0.2


def calculate_aov_score(records: List[RankingRecord], category_avg_price: float) -> float:
    """计算客单价得分。"""
    if not records or category_avg_price <= 0:
        return 50.0

    latest = records[-1]

    # 价格分：价格在 0.5-2 倍类目均价区间最优
    ratio = latest.price / category_avg_price
    if 0.5 <= ratio <= 2.0:
        # 在最优区间内，越接近 1.0 分越高
        distance = abs(ratio - 1.0)
        price_score = 100.0 - distance * 50.0
    else:
        # 偏离最优区间越远，扣分越重
        deviation = abs(ratio - 1.0)
        price_score = max(0.0, 100.0 - deviation * 60.0)

    # 价格趋势
    if len(records) >= 2:
        earliest = records[0]
        if earliest.price > 0:
            price_trend = latest.price / earliest.price
        else:
            price_trend = 1.0
    else:
        price_trend = 1.0

    # 趋势分：涨价 0-20% 最优
    if 0.9 <= price_trend <= 1.2:
        trend_score = 100.0
    elif price_trend > 1.2:
        trend_score = max(0.0, 100.0 - (price_trend - 1.2) * 100.0)
    else:
        trend_score = max(0.0, 100.0 - (1.0 - price_trend) * 200.0)

    return price_score * 0.6 + trend_score * 0.4


def calculate_growth_score(records: List[RankingRecord]) -> float:
    """计算成长性得分。"""
    if not records:
        return 0.0

    latest = records[-1]
    earliest = records[0]

    # 销量增速
    if earliest.estimated_sales > 0:
        sales_growth = (latest.estimated_sales - earliest.estimated_sales) / earliest.estimated_sales
    else:
        sales_growth = 0.0
    sales_growth_normalized = max(0.0, min(100.0, (sales_growth + 0.5) * 50.0))

    # 排名提升
    rank_improvement = earliest.bsr_rank - latest.bsr_rank
    # 排名提升 10 位以上 = 满分
    rank_improvement_normalized = max(0.0, min(100.0, (rank_improvement + 10) * 5.0))

    # 生命周期（简化：用快照数量估算月份，首次快照=0月）
    months_since_listing = len(records) - 1
    lifecycle = 1.0 - min(months_since_listing / 12.0, 1.0)
    lifecycle_score = lifecycle * 100.0

    return sales_growth_normalized * 0.4 + rank_improvement_normalized * 0.4 + lifecycle_score * 0.2


def calculate_risk_score(brand: str, high_risk_brands: List[str]) -> float:
    """计算风险得分。"""
    if not brand or not brand.strip():
        return 70.0

    brand_lower = brand.strip().lower()
    for risk_brand in high_risk_brands:
        if risk_brand.lower() == brand_lower:
            return 0.0

    return 100.0


def calculate_composite(
    traffic: float,
    conversion: float,
    aov: float,
    growth: float,
    risk: float,
    config: dict = None,
) -> float:
    """计算综合得分。"""
    if config is None:
        config = load_config()
    weights = config["weights"]
    return (
        traffic * weights["traffic"]
        + conversion * weights["conversion"]
        + aov * weights["aov"]
        + growth * weights["growth"]
        + risk * weights["risk"]
    )


def compute_metrics(
    asin: str,
    records: List[RankingRecord],
    total_snapshots: int,
    category_avg_price: float,
    high_risk_brands: List[str],
    config: dict = None,
) -> MetricScores:
    """计算单个 ASIN 的完整五维指标得分。

    Args:
        asin: 商品 ASIN
        records: 该 ASIN 的所有历史快照记录
        total_snapshots: 所有类目的总快照次数
        category_avg_price: 类目均价
        high_risk_brands: 高风险品牌名单
        config: 评分配置（可选）

    Returns:
        MetricScores: 五维指标得分
    """
    if config is None:
        config = load_config()

    brand = records[-1].brand if records else ""

    traffic = calculate_traffic_score(records, total_snapshots)
    conversion = calculate_conversion_score(records)
    aov = calculate_aov_score(records, category_avg_price)
    growth = calculate_growth_score(records)
    risk = calculate_risk_score(brand, high_risk_brands)

    composite = calculate_composite(traffic, conversion, aov, growth, risk, config)

    return MetricScores(
        asin=asin,
        traffic_score=round(traffic, 2),
        conversion_score=round(conversion, 2),
        aov_score=round(aov, 2),
        growth_score=round(growth, 2),
        risk_score=round(risk, 2),
        composite_score=round(composite, 2),
    )
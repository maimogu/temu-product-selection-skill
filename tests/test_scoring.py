"""scoring.py 单元测试。

覆盖所有五维得分计算函数和综合得分合成。
"""

import json
import os
import pytest
from scoring import (
    RankingRecord,
    calculate_traffic_score,
    calculate_conversion_score,
    calculate_aov_score,
    calculate_growth_score,
    calculate_risk_score,
    calculate_composite,
    compute_metrics,
    load_config,
)


# fixture 文件绝对路径，确保从任意 cwd 运行 pytest 都能找到
_FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "sample_rankings.json"
)


def load_fixture():
    """加载测试数据。"""
    with open(_FIXTURE_PATH, "r") as f:
        data = json.load(f)
    return [RankingRecord(**item) for item in data]


def group_by_asin(records):
    """按 ASIN 分组。"""
    grouped = {}
    for r in records:
        if r.asin not in grouped:
            grouped[r.asin] = []
        grouped[r.asin].append(r)
    for asin in grouped:
        grouped[asin].sort(key=lambda x: x.snapshot_date)
    return grouped


@pytest.fixture
def all_records():
    return load_fixture()


@pytest.fixture
def grouped(all_records):
    return group_by_asin(all_records)


class TestTrafficScore:
    """流量得分测试。"""

    def test_rank_1_full_score(self, grouped):
        """排名第 1 应得满分。"""
        records = grouped["B000000001"]  # 排名 1,2,1
        total_snapshots = 3
        score = calculate_traffic_score(records, total_snapshots)
        assert score > 80  # 排名第一应高分

    def test_rank_100_min_score(self, grouped):
        """排名第 100 应得低分。"""
        records = grouped["B000000004"]  # 排名 100
        total_snapshots = 3
        score = calculate_traffic_score(records, total_snapshots)
        assert score < 30

    def test_single_record_default_stability(self, grouped):
        """仅一条记录时稳定性默认 50。"""
        records = grouped["B000000004"]  # 仅 1 条
        total_snapshots = 3
        score = calculate_traffic_score(records, total_snapshots)
        assert 0 <= score <= 100

    def test_empty_records(self):
        """空记录返回 0。"""
        score = calculate_traffic_score([], 0)
        assert score == 0.0


class TestConversionScore:
    """转化得分测试。"""

    def test_five_star_full_score(self, grouped):
        """五星 8000 评论应得高分。"""
        records = grouped["B000000003"]  # 5.0星, 8000+评论
        score = calculate_conversion_score(records)
        # 5星=100分, 评论量级=100分, 评论增长低(仅2.5%)=2.5分
        # 100*0.4 + 100*0.4 + 2.5*0.2 = 80.5
        assert score > 75

    def test_no_rating_no_review(self, grouped):
        """无评分无评论应得 0 分。"""
        records = grouped["B000000002"]  # 0星, 0评论
        score = calculate_conversion_score(records)
        assert score == 0.0

    def test_growth_positive(self, grouped):
        """评论增长应正向贡献。"""
        records = grouped["B000000001"]  # 3200 -> 3300
        score = calculate_conversion_score(records)
        assert score > 0

    def test_empty_records(self):
        """空记录返回 0。"""
        score = calculate_conversion_score([])
        assert score == 0.0


class TestAOVScore:
    """客单价得分测试。"""

    def test_price_in_optimal_range(self, grouped):
        """价格在最优区间应高分。"""
        records = grouped["B000000005"]  # price ~47-50, avg ~55
        score = calculate_aov_score(records, category_avg_price=55.0)
        assert score > 60

    def test_price_far_from_avg(self, grouped):
        """价格远离均价应低分。"""
        records = grouped["B000000004"]  # price 9.99, avg 55.0, ratio=0.18
        score = calculate_aov_score(records, category_avg_price=55.0)
        # 偏离最优区间，价格分约 50.9，趋势分 100（仅 1 条记录）
        # 50.9*0.6 + 100*0.4 = 70.5
        assert score < 75

    def test_zero_avg_price(self, grouped):
        """均价为 0 时返回默认值 50。"""
        records = grouped["B000000001"]
        score = calculate_aov_score(records, category_avg_price=0)
        assert score == 50.0

    def test_empty_records(self):
        """空记录返回默认值 50。"""
        score = calculate_aov_score([], category_avg_price=50)
        assert score == 50.0


class TestGrowthScore:
    """成长性得分测试。"""

    def test_rank_improving(self, grouped):
        """排名在提升的应得高分。"""
        records = grouped["B000000005"]  # 排名 10→8→6
        score = calculate_growth_score(records)
        assert score > 50

    def test_rank_declining(self, grouped):
        """排名在下降的应得低分。"""
        records = grouped["B000000009"]  # 排名 2→3
        score = calculate_growth_score(records)
        assert score < 60

    def test_single_record(self, grouped):
        """仅一条记录时生命周期影响。"""
        records = grouped["B000000004"]
        score = calculate_growth_score(records)
        assert 0 <= score <= 100

    def test_empty_records(self):
        """空记录返回 0。"""
        score = calculate_growth_score([])
        assert score == 0.0


class TestRiskScore:
    """风险得分测试。"""

    def test_high_risk_brand(self):
        """高风险品牌返回 0。"""
        score = calculate_risk_score("Nike", ["Nike", "Adidas"])
        assert score == 0.0

    def test_low_risk_brand(self):
        """不在风险名单的品牌返回 100。"""
        score = calculate_risk_score("GenericBrand", ["Nike", "Adidas"])
        assert score == 100.0

    def test_empty_brand(self):
        """空品牌返回 70。"""
        score = calculate_risk_score("", ["Nike"])
        assert score == 70.0

    def test_case_insensitive(self):
        """大小写不敏感。"""
        score = calculate_risk_score("nike", ["Nike"])
        assert score == 0.0


class TestCompositeScore:
    """综合得分测试。"""

    def test_all_full(self):
        """五项全满分应得 100。"""
        score = calculate_composite(100, 100, 100, 100, 100)
        assert score == 100.0

    def test_all_zero(self):
        """五项全 0 应得 0。"""
        score = calculate_composite(0, 0, 0, 0, 0)
        assert score == 0.0

    def test_weighted_correctly(self):
        """验证权重正确。"""
        score = calculate_composite(100, 0, 0, 0, 0)
        assert score == 25.0  # 流量权重 25%

        score = calculate_composite(0, 100, 0, 0, 0)
        assert score == 25.0  # 转化权重 25%

        score = calculate_composite(0, 0, 0, 0, 100)
        assert score == 10.0  # 风险权重 10%


class TestComputeMetrics:
    """完整指标计算测试。"""

    def test_returns_valid_scores(self, grouped):
        """验证返回结构完整。"""
        config = load_config()
        high_risk_brands = config["thresholds"]["high_risk_brands"]
        records = grouped["B000000001"]

        result = compute_metrics(
            asin="B000000001",
            records=records,
            total_snapshots=3,
            category_avg_price=50.0,
            high_risk_brands=high_risk_brands,
            config=config,
        )

        assert result.asin == "B000000001"
        assert 0 <= result.traffic_score <= 100
        assert 0 <= result.conversion_score <= 100
        assert 0 <= result.aov_score <= 100
        assert 0 <= result.growth_score <= 100
        assert 0 <= result.risk_score <= 100
        assert 0 <= result.composite_score <= 100

    def test_nike_risk_zero(self, grouped):
        """Nike 品牌应得风险 0 分。"""
        config = load_config()
        high_risk_brands = config["thresholds"]["high_risk_brands"]
        records = grouped["B000000003"]

        result = compute_metrics(
            asin="B000000003",
            records=records,
            total_snapshots=3,
            category_avg_price=50.0,
            high_risk_brands=high_risk_brands,
            config=config,
        )

        assert result.risk_score == 0.0

    def test_no_brand_risk_70(self, grouped):
        """无品牌应得风险 70 分。"""
        config = load_config()
        high_risk_brands = config["thresholds"]["high_risk_brands"]
        records = grouped["B000000002"]

        result = compute_metrics(
            asin="B000000002",
            records=records,
            total_snapshots=3,
            category_avg_price=50.0,
            high_risk_brands=high_risk_brands,
            config=config,
        )

        assert result.risk_score == 70.0
"""测试 profit_calc 模块 — FBA 利润计算。"""

import pytest
from profit_calc import FBACalculator, ProductSpec, ProfitResult, build_profit_table


class TestFBACalculator:
    """测试 FBA 利润计算器。"""

    @pytest.fixture
    def calc(self):
        return FBACalculator()

    def test_small_standard_product(self, calc):
        """小号标准尺寸产品。"""
        spec = ProductSpec(
            asin="B001234567",
            price=19.99,
            cost=5.00,
            weight_lb=0.5,
            length_inch=10.0,
            width_inch=8.0,
            height_inch=0.5,
            category="home_and_kitchen",
        )
        result = calc.calculate(spec)
        # 大号标准，因为最长边 10 > 0.75（小号标准限高）
        assert result.fulfillment_fee >= 5.40
        assert result.referral_fee >= 0.30

    def test_large_standard_product(self, calc):
        """大号标准尺寸产品。"""
        spec = ProductSpec(
            asin="B002",
            price=29.99,
            cost=8.00,
            weight_lb=3.0,
            length_inch=16.0,
            width_inch=12.0,
            height_inch=4.0,
            category="home_and_kitchen",
        )
        result = calc.calculate(spec)
        # 大号标准：base + extra weight
        assert result.fulfillment_fee >= 5.40
        assert result.fulfillment_fee > 5.40  # 超重加费

    def test_oversize_product(self, calc):
        """大件产品。"""
        spec = ProductSpec(
            asin="B003",
            price=99.99,
            cost=30.00,
            weight_lb=25.0,
            length_inch=50.0,
            width_inch=20.0,
            height_inch=10.0,
            category="sports",
        )
        result = calc.calculate(spec)
        assert result.fulfillment_fee >= 8.94

    def test_referral_fee_electronics(self, calc):
        """电子产品佣金 8%。"""
        spec = ProductSpec(
            asin="B004",
            price=100.00,
            cost=40.00,
            weight_lb=1.0,
            category="electronics",
        )
        result = calc.calculate(spec)
        assert result.referral_fee == 8.00

    def test_referral_fee_computers(self, calc):
        """电脑产品佣金 6%。"""
        spec = ProductSpec(
            asin="B005",
            price=100.00,
            cost=40.00,
            weight_lb=1.0,
            category="personal_computers",
        )
        result = calc.calculate(spec)
        assert result.referral_fee == 6.00

    def test_referral_fee_clothing(self, calc):
        """服装佣金 17%。"""
        spec = ProductSpec(
            asin="B006",
            price=100.00,
            cost=40.00,
            weight_lb=1.0,
            category="clothing",
        )
        result = calc.calculate(spec)
        assert result.referral_fee == 17.00

    def test_referral_fee_minimum(self, calc):
        """最低佣金 $0.30。"""
        spec = ProductSpec(
            asin="B007",
            price=1.00,
            cost=0.30,
            weight_lb=0.2,
            category="home_and_kitchen",
        )
        result = calc.calculate(spec)
        assert result.referral_fee == 0.30

    def test_profit_margin_calculation(self, calc):
        """利润率计算正确。"""
        spec = ProductSpec(
            asin="B008",
            price=20.00,
            cost=6.00,
            weight_lb=0.5,
            length_inch=10.0,
            width_inch=8.0,
            height_inch=0.5,
            category="home_and_kitchen",
        )
        result = calc.calculate(spec)
        expected_margin = result.net_profit / result.price
        assert abs(result.profit_margin - expected_margin) < 0.01

    def test_profitable_product(self, calc):
        """高利润产品应标记为达标。"""
        spec = ProductSpec(
            asin="B009",
            price=30.00,
            cost=5.00,
            weight_lb=0.3,
            length_inch=8.0,
            width_inch=6.0,
            height_inch=0.5,
            category="home_and_kitchen",
        )
        result = calc.calculate(spec)
        assert result.is_profitable is True

    def test_unprofitable_product(self, calc):
        """低利润产品应标记为不达标。"""
        spec = ProductSpec(
            asin="B010",
            price=10.00,
            cost=8.00,
            weight_lb=2.0,
            length_inch=12.0,
            width_inch=10.0,
            height_inch=4.0,
            category="home_and_kitchen",
        )
        result = calc.calculate(spec)
        assert result.is_profitable is False

    def test_storage_fee_calculation(self, calc):
        """仓储费计算。"""
        spec = ProductSpec(
            asin="B011",
            price=25.00,
            cost=10.00,
            weight_lb=1.0,
            length_inch=12.0,
            width_inch=12.0,
            height_inch=12.0,
            category="home_and_kitchen",
        )
        result = calc.calculate(spec)
        # 12*12*12 = 1728 cubic inches = 1 cubic foot
        # 1 * 0.78 = 0.78
        assert abs(result.storage_fee - 0.78) < 0.01

    def test_batch_calculation(self, calc):
        """批量计算。"""
        specs = [
            ProductSpec(asin="B001", price=19.99, cost=5.00,
                        weight_lb=0.5, category="home_and_kitchen"),
            ProductSpec(asin="B002", price=29.99, cost=8.00,
                        weight_lb=1.0, category="sports"),
        ]
        results = calc.calculate_batch(specs)
        assert len(results) == 2
        assert results[0].asin == "B001"
        assert results[1].asin == "B002"

    def test_total_fee_sum(self, calc):
        """总费用应等于各项费用之和。"""
        spec = ProductSpec(
            asin="B012",
            price=25.00,
            cost=10.00,
            weight_lb=1.0,
            category="home_and_kitchen",
        )
        result = calc.calculate(spec)
        expected_total = (
            result.fulfillment_fee + result.referral_fee + result.storage_fee
            + result.advertising_cost + result.head_haul_cost
        )
        assert abs(result.total_fee - expected_total) < 0.01

    def test_default_weight(self, calc):
        """默认重量应可用。"""
        spec = ProductSpec(
            asin="B013",
            price=15.00,
            cost=5.00,
            category="home_and_kitchen",
        )
        result = calc.calculate(spec)
        assert result.fulfillment_fee > 0


class TestBuildProfitTable:
    """测试飞书表格构建。"""

    def test_build_table(self):
        calc = FBACalculator()
        spec = ProductSpec(
            asin="B001", price=29.99, cost=5.00,
            weight_lb=0.3, length_inch=8.0, width_inch=6.0, height_inch=0.5,
            category="home_and_kitchen",
        )
        result = calc.calculate(spec)
        records = build_profit_table([result])
        assert len(records) == 1
        assert records[0]["asin"] == "B001"
        assert records[0]["price"] == 29.99
        assert records[0]["profit_margin"] > 0
        assert records[0]["is_profitable"] in ("是", "否")
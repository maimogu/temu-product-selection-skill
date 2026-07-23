"""risk_checker.py 单元测试。"""

import pytest
from risk_checker import check_risk, is_high_risk


class TestCheckRisk:
    """风险检查测试。"""

    def test_high_risk_brand(self):
        """高风险品牌返回 0。"""
        assert check_risk("Nike", ["Nike", "Adidas", "Apple"]) == 0.0

    def test_not_in_list(self):
        """不在名单中的品牌返回 100。"""
        assert check_risk("GenericBrand", ["Nike", "Adidas"]) == 100.0

    def test_empty_brand(self):
        """空品牌返回 70。"""
        assert check_risk("", ["Nike"]) == 70.0

    def test_none_brand(self):
        """None 品牌返回 70。"""
        assert check_risk(None, ["Nike"]) == 70.0

    def test_whitespace_brand(self):
        """纯空格品牌返回 70。"""
        assert check_risk("   ", ["Nike"]) == 70.0

    def test_case_insensitive(self):
        """大小写不敏感。"""
        assert check_risk("nike", ["Nike"]) == 0.0
        assert check_risk("NIKE", ["Nike"]) == 0.0
        assert check_risk("NiKe", ["Nike"]) == 0.0


class TestIsHighRisk:
    """高风险判断测试。"""

    def test_is_high_risk(self):
        assert is_high_risk("Nike", ["Nike", "Adidas"]) is True

    def test_is_not_high_risk(self):
        assert is_high_risk("GoodBrand", ["Nike", "Adidas"]) is False

    def test_empty_is_not_high_risk(self):
        assert is_high_risk("", ["Nike"]) is False
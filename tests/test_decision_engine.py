"""决策引擎单元测试。"""

import pytest
from decision_engine import (
    DecisionInput,
    decide,
    decide_batch,
    load_decision_config,
)


CONFIG = {
    "go": {
        "min_composite": 75,
        "min_profit_margin": 0.15,
        "min_risk_score": 60,
    },
    "no_go": {
        "max_composite": 40,
        "max_risk_score": 30,
        "max_profit_margin": 0.0,
    },
}


class TestDecide:
    def test_go_all_pass(self):
        """全部达标 → GO。"""
        inp = DecisionInput(asin="B001", composite_score=85, risk_score=80, profit_margin=0.20)
        r = decide(inp, CONFIG)
        assert r.decision == "GO"
        assert r.reason == "全部达标"
        assert r.failure_reason == ""

    def test_no_go_low_composite(self):
        """综合得分过低 → NO-GO。"""
        inp = DecisionInput(asin="B002", composite_score=30, risk_score=80, profit_margin=0.20)
        r = decide(inp, CONFIG)
        assert r.decision == "NO-GO"
        assert "综合得分" in r.reason

    def test_no_go_low_risk(self):
        """风险得分过低（高风险品牌）→ NO-GO。"""
        inp = DecisionInput(asin="B003", composite_score=85, risk_score=20, profit_margin=0.20)
        r = decide(inp, CONFIG)
        assert r.decision == "NO-GO"
        assert "风险得分" in r.reason

    def test_no_go_negative_margin(self):
        """亏损 → NO-GO。"""
        inp = DecisionInput(asin="B004", composite_score=85, risk_score=80, profit_margin=-0.05)
        r = decide(inp, CONFIG)
        assert r.decision == "NO-GO"
        assert "利润率" in r.reason

    def test_watch_composite_below_go(self):
        """综合得分低于 GO 阈值但未触发 NO-GO → WATCH。"""
        inp = DecisionInput(asin="B005", composite_score=60, risk_score=80, profit_margin=0.20)
        r = decide(inp, CONFIG)
        assert r.decision == "WATCH"
        assert "综合得分" in r.reason

    def test_watch_low_margin(self):
        """利润率不达标（但非亏损）→ WATCH。"""
        inp = DecisionInput(asin="B006", composite_score=85, risk_score=80, profit_margin=0.10)
        r = decide(inp, CONFIG)
        assert r.decision == "WATCH"
        assert "利润率" in r.reason

    def test_watch_missing_margin(self):
        """利润率缺失 → WATCH，failure_reason 记录原因。"""
        inp = DecisionInput(asin="B007", composite_score=85, risk_score=80, profit_margin=None)
        r = decide(inp, CONFIG)
        assert r.decision == "WATCH"
        assert r.failure_reason != ""
        assert "利润率" in r.failure_reason

    def test_no_go_takes_precedence_over_watch(self):
        """NO-GO 优先于 WATCH：综合得分低 + 利润率缺失 → NO-GO。"""
        inp = DecisionInput(asin="B008", composite_score=20, risk_score=80, profit_margin=None)
        r = decide(inp, CONFIG)
        assert r.decision == "NO-GO"
        # NO-GO 时 failure_reason 不必填充
        assert r.failure_reason == ""

    def test_multiple_no_go_reasons_joined(self):
        """多个 NO-GO 原因用分号拼接。"""
        inp = DecisionInput(asin="B009", composite_score=20, risk_score=20, profit_margin=-0.1)
        r = decide(inp, CONFIG)
        assert r.decision == "NO-GO"
        assert ";" in r.reason


class TestDecideBatch:
    def test_batch(self):
        inputs = [
            DecisionInput(asin="B001", composite_score=85, risk_score=80, profit_margin=0.20),
            DecisionInput(asin="B002", composite_score=30, risk_score=80, profit_margin=0.20),
            DecisionInput(asin="B003", composite_score=60, risk_score=80, profit_margin=0.20),
        ]
        results = decide_batch(inputs, CONFIG)
        assert len(results) == 3
        assert results[0].decision == "GO"
        assert results[1].decision == "NO-GO"
        assert results[2].decision == "WATCH"

    def test_empty_batch(self):
        assert decide_batch([], CONFIG) == []


class TestLoadConfig:
    def test_load_decision_config(self):
        """从 config/scoring.yaml 加载 decision 段。"""
        cfg = load_decision_config()
        assert "go" in cfg
        assert "no_go" in cfg
        assert "min_composite" in cfg["go"]
        assert "max_composite" in cfg["no_go"]

"""Go/No-Go 决策引擎。

基于五维指标 + 利润率，输出 GO / WATCH / NO-GO 三态决策。

设计要点（参见 docs/superpowers/specs/2026-07-29-task-orchestration-design.md §3）：
- 三态：GO（推荐上架）/ WATCH（观察）/ NO-GO（不推荐）
- 降级不引入第四状态，落 `failure_reason` 字段记录数据缺失
- 配置位于 config/scoring.yaml 的 decision 段

纯函数模块，不依赖 IO，便于单元测试。
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional

import yaml


@dataclass
class DecisionInput:
    """决策输入。"""
    asin: str
    composite_score: float       # 综合得分 0-100
    risk_score: float            # 风险得分 0-100（越高越安全）
    profit_margin: Optional[float] = None  # 利润率 0-1，可为 None（数据缺失）


@dataclass
class DecisionResult:
    """决策输出。"""
    asin: str
    decision: str                # GO / WATCH / NO-GO
    reason: str = ""             # 决策原因（可读）
    failure_reason: str = ""     # 数据缺失原因（仅当降级时填充）


def load_decision_config(config_path: Optional[str] = None) -> dict:
    """加载决策配置（scoring.yaml 的 decision 段）。"""
    if config_path is None:
        skill_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(skill_root, "config", "scoring.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        full = yaml.safe_load(f)
    return full.get("decision", {})


def _check_no_go(inp: DecisionInput, cfg: dict) -> str:
    """检查 NO-GO 否决条件，返回原因字符串（空表示未触发）。"""
    reasons: List[str] = []
    no_go = cfg.get("no_go", {})

    max_composite = no_go.get("max_composite", 40)
    if inp.composite_score < max_composite:
        reasons.append(f"综合得分 {inp.composite_score:.1f} < {max_composite}")

    max_risk = no_go.get("max_risk_score", 30)
    if inp.risk_score < max_risk:
        reasons.append(f"风险得分 {inp.risk_score:.1f} < {max_risk}")

    # 利润率缺失不触发 NO-GO（降级为 WATCH）
    max_margin = no_go.get("max_profit_margin", 0.0)
    if inp.profit_margin is not None and inp.profit_margin < max_margin:
        reasons.append(f"利润率 {inp.profit_margin:.1%} < {max_margin:.1%}")

    return "; ".join(reasons)


def _check_go(inp: DecisionInput, cfg: dict) -> str:
    """检查 GO 条件，返回原因字符串（空表示未满足任一条件）。

    注意：返回空字符串表示「未达 GO」，而非「全部达标」。
    调用方据此区分 GO 与 WATCH。
    """
    missing: List[str] = []
    go = cfg.get("go", {})

    min_composite = go.get("min_composite", 75)
    if inp.composite_score < min_composite:
        missing.append(f"综合得分 {inp.composite_score:.1f} < {min_composite}")

    min_risk = go.get("min_risk_score", 60)
    if inp.risk_score < min_risk:
        missing.append(f"风险得分 {inp.risk_score:.1f} < {min_risk}")

    min_margin = go.get("min_profit_margin", 0.15)
    if inp.profit_margin is None:
        missing.append("利润率数据缺失")
    elif inp.profit_margin < min_margin:
        missing.append(f"利润率 {inp.profit_margin:.1%} < {min_margin:.1%}")

    return "; ".join(missing)


def decide(inp: DecisionInput, config: Optional[dict] = None) -> DecisionResult:
    """对单个 ASIN 做决策。

    判定顺序：
    1. 先查 NO-GO 否决条件 → 命中即 NO-GO
    2. 再查 GO 条件 → 全部满足即 GO
    3. 否则 WATCH
    """
    if config is None:
        config = load_decision_config()

    # 1. NO-GO
    no_go_reason = _check_no_go(inp, config)
    if no_go_reason:
        return DecisionResult(
            asin=inp.asin,
            decision="NO-GO",
            reason=no_go_reason,
        )

    # 2. GO
    go_missing = _check_go(inp, config)
    if not go_missing:
        return DecisionResult(
            asin=inp.asin,
            decision="GO",
            reason="全部达标",
        )

    # 3. WATCH
    failure_reason = ""
    if inp.profit_margin is None:
        failure_reason = "利润率数据缺失，无法判定 GO"

    return DecisionResult(
        asin=inp.asin,
        decision="WATCH",
        reason=go_missing,
        failure_reason=failure_reason,
    )


def decide_batch(inputs: List[DecisionInput], config: Optional[dict] = None) -> List[DecisionResult]:
    """批量决策。"""
    if config is None:
        config = load_decision_config()
    return [decide(inp, config) for inp in inputs]

"""FBA 利润计算模块。

基于 Amazon FBA 费率表，计算产品的预估利润、利润率、盈亏平衡点。
纯函数计算，不依赖外部 API。

维度说明：
- 配送费：按产品尺寸重量匹配费率段
- 佣金：按品类百分比 + 最低佣金
- 仓储费：按月估算（非长期存储）
- 广告费：按默认 ACoS 估算
- 头程物流：按售价比例估算（可配置）
"""

import os
import yaml
from typing import Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class ProductSpec:
    """产品规格信息。"""
    asin: str = ""
    price: float = 0.0              # 售价 (USD)
    cost: float = 0.0               # 采购成本 (USD)
    weight_lb: float = 0.5          # 重量 (lb)
    length_inch: float = 10.0       # 长 (inch)
    width_inch: float = 8.0         # 宽 (inch)
    height_inch: float = 2.0        # 高 (inch)
    category: str = "home_and_kitchen"  # 品类 key
    monthly_sales: int = 100        # 预估月销量


@dataclass
class ProfitResult:
    """利润计算结果。"""
    asin: str
    price: float
    cost: float
    fulfillment_fee: float          # 配送费
    referral_fee: float             # 销售佣金
    storage_fee: float              # 月度仓储费
    advertising_cost: float         # 广告费
    head_haul_cost: float           # 头程物流
    total_fee: float                # 总费用
    net_profit: float               # 净利润
    profit_margin: float            # 利润率
    break_even_units: int           # 盈亏平衡月销量
    is_profitable: bool             # 是否达标


class FBACalculator:
    """FBA 利润计算器。

    从 config/fba_rates.yaml 加载费率表。
    """

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "config", "fba_rates.yaml"
            )
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

    def _get_fulfillment_fee(self, spec: ProductSpec) -> float:
        """计算配送费。"""
        ff = self.config["fulfillment"]
        weight_lb = max(spec.weight_lb, 0.1)
        dims = sorted([spec.length_inch, spec.width_inch, spec.height_inch])

        # 小号标准
        s = ff["small_standard"]
        if weight_lb <= s["max_weight_oz"] / 16 and all(
            d <= s["max_dimensions_inch"][i] for i, d in enumerate(sorted(dims))
        ):
            return s["fee"]

        # 大号标准
        ls = ff["large_standard"]
        if weight_lb <= ls["max_weight_lb"] and all(
            d <= ls["max_dimensions_inch"][i] for i, d in enumerate(sorted(dims))
        ):
            over_lb = max(0, weight_lb - 1)
            return ls["base_fee"] + over_lb * ls["fee_per_lb"]

        # 大件
        for tier_key in ["small_oversize", "medium_oversize", "large_oversize"]:
            tier = ff[tier_key]
            if weight_lb <= tier["max_weight_lb"]:
                return tier["base_fee"] + weight_lb * tier["fee_per_lb"]

        # 超大件兜底
        lo = ff["large_oversize"]
        return lo["base_fee"] + weight_lb * lo["fee_per_lb"]

    def _get_referral_fee(self, spec: ProductSpec) -> float:
        """计算销售佣金。"""
        rf = self.config["referral_fee"]
        rate = rf["categories"].get(spec.category, rf["default"])
        fee = spec.price * rate
        return max(fee, rf["categories"]["minimum"])

    def _get_storage_fee(self, spec: ProductSpec) -> float:
        """估算月度仓储费。"""
        cubic_ft = (spec.length_inch * spec.width_inch * spec.height_inch) / 1728
        ms = self.config["monthly_storage"]
        return cubic_ft * ms["jan_sep"]

    def _get_advertising_cost(self, spec: ProductSpec) -> float:
        """估算广告费。"""
        ad = self.config["advertising"]
        return spec.price * ad["default_acos"]

    def _get_head_haul_cost(self, spec: ProductSpec) -> float:
        """估算头程物流费。"""
        d = self.config["defaults"]
        return spec.price * d["head_haul_ratio"]

    def calculate(self, spec: ProductSpec) -> ProfitResult:
        """计算单个产品的利润。

        Args:
            spec: 产品规格信息

        Returns:
            ProfitResult: 完整的利润分析结果
        """
        fulfillment = self._get_fulfillment_fee(spec)
        referral = self._get_referral_fee(spec)
        storage = self._get_storage_fee(spec)
        advertising = self._get_advertising_cost(spec)
        head_haul = self._get_head_haul_cost(spec)

        total_fee = fulfillment + referral + storage + advertising + head_haul
        # 固定成本 + 可变成本（每件）
        net_profit = spec.price - spec.cost - total_fee
        profit_margin = net_profit / spec.price if spec.price > 0 else 0.0

        threshold = self.config["defaults"]["profit_margin_threshold"]
        is_profitable = profit_margin >= threshold

        # 盈亏平衡：固定成本 = 0（简化，FBA 无固定成本），直接算月销量
        if net_profit > 0:
            break_even = 1
        else:
            break_even = -1

        return ProfitResult(
            asin=spec.asin,
            price=spec.price,
            cost=spec.cost,
            fulfillment_fee=round(fulfillment, 2),
            referral_fee=round(referral, 2),
            storage_fee=round(storage, 2),
            advertising_cost=round(advertising, 2),
            head_haul_cost=round(head_haul, 2),
            total_fee=round(total_fee, 2),
            net_profit=round(net_profit, 2),
            profit_margin=round(profit_margin, 4),
            break_even_units=break_even,
            is_profitable=is_profitable,
        )

    def calculate_batch(self, specs: list) -> list:
        """批量计算利润。"""
        return [self.calculate(s) for s in specs]


def build_profit_table(results: list) -> list:
    """构建飞书多维表格写入用的记录列表。"""
    records = []
    for r in results:
        records.append({
            "asin": r.asin,
            "price": r.price,
            "cost": r.cost,
            "fulfillment_fee": r.fulfillment_fee,
            "referral_fee": r.referral_fee,
            "storage_fee": r.storage_fee,
            "advertising_cost": r.advertising_cost,
            "head_haul_cost": r.head_haul_cost,
            "total_fee": r.total_fee,
            "net_profit": r.net_profit,
            "profit_margin": r.profit_margin,
            "break_even_units": r.break_even_units,
            "is_profitable": "是" if r.is_profitable else "否",
        })
    return records
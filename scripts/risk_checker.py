"""品牌风险名单匹配模块。

纯函数，不依赖 IO。将品牌名与预配置的风险名单做大小写不敏感匹配。
"""

from typing import List


def check_risk(brand: str, high_risk_brands: List[str]) -> float:
    """检查品牌风险得分。

    Args:
        brand: 品牌名称
        high_risk_brands: 高风险品牌名单

    Returns:
        float: 风险得分
            - 0: 品牌在高风险名单中
            - 70: 品牌为空
            - 100: 品牌不在高风险名单中
    """
    if not brand or not brand.strip():
        return 70.0

    brand_lower = brand.strip().lower()
    for risk_brand in high_risk_brands:
        if risk_brand.lower() == brand_lower:
            return 0.0

    return 100.0


def is_high_risk(brand: str, high_risk_brands: List[str]) -> bool:
    """判断品牌是否为高风险。"""
    if not brand or not brand.strip():
        return False
    brand_lower = brand.strip().lower()
    return any(rb.lower() == brand_lower for rb in high_risk_brands)
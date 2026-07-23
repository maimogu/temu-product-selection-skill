"""指标计算主入口。

编排指标计算流程：
1. 读取飞书「榜单快照」表获取所有历史记录
2. 按 ASIN 聚合数据，并记录每个 ASIN 所属的类目
3. 按类目分别计算类目均价（而非全局均价）
4. 调用 scoring.py 计算五维得分
5. 清空「指标得分」表旧记录后写入新记录
"""

import os
import sys
import json
import logging
from datetime import date
from typing import List, Dict, Any, Tuple
from statistics import mean

# 将脚本所在目录加入 sys.path，使同目录模块可被 import（无论从哪个 cwd 运行）
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from feishu_client import FeishuClient, FeishuAPIError
from scoring import (
    RankingRecord,
    compute_metrics,
    load_config,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("metrics")


class MetricsCalculator:
    """指标计算编排器。"""

    def __init__(
        self,
        feishu: FeishuClient,
        snapshots_table_id: str,
        metrics_table_id: str,
        high_risk_brands: List[str],
    ):
        self.feishu = feishu
        self.snapshots_table_id = snapshots_table_id
        self.metrics_table_id = metrics_table_id
        self.high_risk_brands = high_risk_brands

    def fetch_snapshots(self) -> Tuple[Dict[str, List[RankingRecord]], Dict[str, str]]:
        """从飞书读取榜单快照，按 ASIN 聚合。

        Returns:
            grouped: {asin: [records]} 按 ASIN 聚合的记录列表，每个 ASIN 内按快照日期排序
            asin_to_category: {asin: category_name} ASIN 所属类目
        """
        raw_records = self.feishu.get_records(self.snapshots_table_id)
        logger.info(f"读取到 {len(raw_records)} 条榜单快照记录")

        grouped: Dict[str, List[RankingRecord]] = {}
        asin_to_category: Dict[str, str] = {}

        for raw in raw_records:
            fields = raw.get("fields", {})

            # ASIN 字段可能是字符串或 {"text": "..."} 结构
            asin_field = fields.get("ASIN", "")
            if isinstance(asin_field, dict):
                asin = asin_field.get("text", "")
            else:
                asin = asin_field

            if not asin:
                continue

            # 过滤价格异常值（价格为 0 或负数视为数据缺失）
            price = fields.get("价格", 0)
            if price is None:
                price = 0
            elif isinstance(price, dict):
                # 飞书货币字段可能返回 {"text": "$29.99", "value": 29.99}
                price = price.get("value", 0) or 0

            if float(price) <= 0:
                continue

            # 类目名称字段（用于按类目分组计算均价）
            category_field = fields.get("类目名称", "")
            if isinstance(category_field, dict):
                # 关联字段返回 [{"text": "...", "record_ids": [...]}]
                category_name = category_field.get("text", "")
            elif isinstance(category_field, list) and category_field:
                # 关联字段可能返回列表
                first = category_field[0]
                if isinstance(first, dict):
                    category_name = first.get("text", "")
                else:
                    category_name = str(first)
            else:
                category_name = str(category_field) if category_field else "默认类目"

            # 记录 ASIN 所属类目（首次出现时记录，后续以首次为准）
            if asin not in asin_to_category:
                asin_to_category[asin] = category_name

            # 快照日期可能是毫秒时间戳或字符串
            snapshot_date_field = fields.get("快照日期", "")
            snapshot_date = self._normalize_date(snapshot_date_field)

            record = RankingRecord(
                asin=asin,
                bsr_rank=int(fields.get("排名", 100) or 100),
                price=float(price),
                star_rating=float(fields.get("星级评分", 0) or 0),
                review_count=int(fields.get("Review数量", 0) or 0),
                brand=str(fields.get("供应商信息", "") or ""),
                estimated_sales=int(fields.get("估算销量", 0) or 0),
                estimated_revenue=float(fields.get("估算销售额", 0) or 0),
                snapshot_date=snapshot_date,
            )

            if asin not in grouped:
                grouped[asin] = []
            grouped[asin].append(record)

        # 每个 ASIN 按快照日期排序
        for asin in grouped:
            grouped[asin].sort(key=lambda r: r.snapshot_date)

        logger.info(f"聚合后共 {len(grouped)} 个 ASIN")
        return grouped, asin_to_category

    @staticmethod
    def _normalize_date(date_value: Any) -> str:
        """将飞书日期字段值规范化为 ISO 格式字符串。

        飞书日期字段返回毫秒时间戳（int）或 ISO 字符串。
        """
        if isinstance(date_value, (int, float)):
            # 毫秒时间戳转 ISO 日期
            from datetime import datetime, timezone
            try:
                return datetime.fromtimestamp(
                    date_value / 1000, tz=timezone.utc
                ).date().isoformat()
            except (OSError, ValueError):
                return str(date_value)
        elif isinstance(date_value, dict):
            return date_value.get("text", "") or str(date_value)
        elif date_value is None:
            return ""
        return str(date_value)

    def calculate_all_metrics(
        self,
        grouped: Dict[str, List[RankingRecord]],
        asin_to_category: Dict[str, str],
    ) -> List:
        """计算所有 ASIN 的指标得分。

        - total_snapshots: 该 ASIN 所属类目在所有快照中出现的总次数（用于计算出现频率）
        - category_avg_price: 该 ASIN 所属类目所有商品价格的均值
        """
        # 按类目聚合所有记录，用于计算类目级指标
        category_records: Dict[str, List[RankingRecord]] = {}
        for asin, records in grouped.items():
            category_name = asin_to_category.get(asin, "默认类目")
            if category_name not in category_records:
                category_records[category_name] = []
            category_records[category_name].extend(records)

        # 每个类目的快照次数 = 该类目不同快照日期的数量
        category_snapshot_counts: Dict[str, int] = {}
        # 每个类目的均价 = 该类目所有价格记录的均值
        category_avg_prices: Dict[str, float] = {}

        for category_name, records in category_records.items():
            unique_dates = set(r.snapshot_date for r in records if r.snapshot_date)
            category_snapshot_counts[category_name] = len(unique_dates) or 1

            prices = [r.price for r in records if r.price > 0]
            category_avg_prices[category_name] = mean(prices) if prices else 0.0

        config = load_config()
        results = []

        for asin, records in grouped.items():
            category_name = asin_to_category.get(asin, "默认类目")
            total_snapshots = category_snapshot_counts.get(category_name, 1)
            category_avg_price = category_avg_prices.get(category_name, 0.0)

            try:
                scores = compute_metrics(
                    asin=asin,
                    records=records,
                    total_snapshots=total_snapshots,
                    category_avg_price=category_avg_price,
                    high_risk_brands=self.high_risk_brands,
                    config=config,
                )
                results.append(scores)
            except Exception as e:
                logger.error(f"计算 {asin} 指标失败: {e}")

        # 按综合得分降序排序
        results.sort(key=lambda s: s.composite_score, reverse=True)
        logger.info(f"计算完成，共 {len(results)} 个商品得分")
        return results

    def clear_metrics_table(self) -> int:
        """清空指标得分表中的所有旧记录。

        每次重算前清空，避免指标得分表无限膨胀。
        """
        existing = self.feishu.get_records(self.metrics_table_id)
        if not existing:
            return 0

        record_ids = [r.get("record_id") for r in existing if r.get("record_id")]
        if not record_ids:
            return 0

        logger.info(f"清空指标得分表旧记录: {len(record_ids)} 条")
        deleted = self.feishu.batch_delete_records(self.metrics_table_id, record_ids)
        return len(deleted)

    def write_metrics(self, scores: List) -> int:
        """将指标得分写入飞书多维表格。

        写入前先清空旧记录，避免指标得分表无限膨胀。
        """
        # 先清空旧记录
        self.clear_metrics_table()

        records = []
        today = date.today().isoformat()

        for s in scores:
            records.append({
                "ASIN": s.asin,
                "计算时间": today,
                "流量得分": s.traffic_score,
                "转化得分": s.conversion_score,
                "客单价得分": s.aov_score,
                "成长性得分": s.growth_score,
                "风险得分": s.risk_score,
                "综合得分": s.composite_score,
                "指标明细JSON": json.dumps(
                    {
                        "traffic": s.traffic_score,
                        "conversion": s.conversion_score,
                        "aov": s.aov_score,
                        "growth": s.growth_score,
                        "risk": s.risk_score,
                        "composite": s.composite_score,
                    },
                    ensure_ascii=False,
                ),
            })

        if records:
            self.feishu.batch_create_records(self.metrics_table_id, records)
            logger.info(f"写入指标得分: {len(records)} 条")

        return len(records)

    def run(self) -> Dict[str, Any]:
        """执行完整指标计算流程。"""
        grouped, asin_to_category = self.fetch_snapshots()
        if not grouped:
            logger.warning("没有榜单快照数据")
            return {"status": "ok", "total": 0}

        scores = self.calculate_all_metrics(grouped, asin_to_category)
        count = self.write_metrics(scores)

        # 输出 Top 10 用于日志
        top10 = [
            {"asin": s.asin, "composite": s.composite_score}
            for s in scores[:10]
        ]

        summary = {
            "status": "ok",
            "total": count,
            "top10": top10,
        }

        logger.info(f"指标计算完成: {json.dumps(summary, ensure_ascii=False)}")
        return summary


def main():
    """指标计算主函数。"""
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    app_token = os.environ.get("FEISHU_APP_TOKEN")

    if not all([app_id, app_secret, app_token]):
        logger.error("缺少环境变量")
        sys.exit(1)

    snapshots_table_id = os.environ.get("FEISHU_SNAPSHOTS_TABLE_ID", "")
    metrics_table_id = os.environ.get("FEISHU_METRICS_TABLE_ID", "")

    if not snapshots_table_id or not metrics_table_id:
        logger.error("缺少表 ID 环境变量")
        sys.exit(1)

    config = load_config()
    high_risk_brands = config["thresholds"]["high_risk_brands"]

    feishu = FeishuClient(app_id, app_secret, app_token)

    calculator = MetricsCalculator(
        feishu=feishu,
        snapshots_table_id=snapshots_table_id,
        metrics_table_id=metrics_table_id,
        high_risk_brands=high_risk_brands,
    )

    result = calculator.run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    main()
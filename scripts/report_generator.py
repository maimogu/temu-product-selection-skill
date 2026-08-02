"""报告生成器。

编排 HTML + Excel 报告生成。本期不写飞书，仅落本地 reports/ 目录。

输入：决策结果列表 + 可选的指标/利润明细
输出：reports/<timestamp>_<category>_<cycle>.{html,xlsx}
"""

import os
import sys
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

# 将 scripts 目录加入 sys.path，使 renderers 可被 import
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from renderers.html_renderer import render_html
from renderers.excel_renderer import render_excel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("report_generator")


class ReportGenerator:
    """报告生成器。"""

    def __init__(self, output_dir: str = None):
        if output_dir is None:
            # 默认输出到 skill 根目录的 reports/
            skill_root = os.path.dirname(_SCRIPTS_DIR)
            output_dir = os.path.join(skill_root, "reports")
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def _build_filename(self, category: str, cycle: str, ext: str) -> str:
        """构建输出文件名。"""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        # 文件名安全化
        safe_category = "".join(c for c in category if c.isalnum() or c in "-_") or "all"
        safe_cycle = "".join(c for c in cycle if c.isalnum() or c in "-_") or "current"
        return os.path.join(
            self.output_dir,
            f"{ts}_{safe_category}_{safe_cycle}.{ext}",
        )

    def run(
        self,
        decision_rows: List[Dict[str, Any]],
        metrics_rows: Optional[List[Dict[str, Any]]] = None,
        profit_rows: Optional[List[Dict[str, Any]]] = None,
        category: str = "全部类目",
        cycle: str = "本周",
    ) -> Dict[str, str]:
        """生成 HTML + Excel 报告。

        Args:
            decision_rows: 决策明细行（每行含 asin/decision/composite_score 等）
            metrics_rows: 指标明细行（可选）
            profit_rows: 利润明细行（可选）
            category: 类目名称
            cycle: 周期标签

        Returns:
            dict: {"html": html_path, "excel": excel_path}
        """
        html_path = self._build_filename(category, cycle, "html")
        excel_path = self._build_filename(category, cycle, "xlsx")

        logger.info(f"生成 HTML 报告: {html_path}")
        render_html(
            rows=decision_rows,
            category=category,
            cycle=cycle,
            output_path=html_path,
        )

        logger.info(f"生成 Excel 报告: {excel_path}")
        render_excel(
            rows=decision_rows,
            metrics_rows=metrics_rows,
            profit_rows=profit_rows,
            category=category,
            cycle=cycle,
            output_path=excel_path,
        )

        summary = {"html": html_path, "excel": excel_path}
        logger.info(f"报告生成完成: {summary}")
        return summary


def main():
    """CLI 入口：演示用空数据生成报告。"""
    gen = ReportGenerator()
    result = gen.run(
        decision_rows=[],
        category=os.environ.get("REPORT_CATEGORY", "全部类目"),
        cycle=os.environ.get("REPORT_CYCLE", "本周"),
    )
    print(f"报告路径: {result}")


if __name__ == "__main__":
    main()

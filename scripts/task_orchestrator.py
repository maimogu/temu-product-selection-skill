"""任务编排器。

串联「采集 → 指标 → 利润 → 决策 → 报告」全链路。

设计要点（参见 docs/superpowers/specs/2026-07-29-task-orchestration-design.md §5）：
- 子进程调用已有脚本（crawl/metrics/profit_calc）
- 决策与报告在本进程内执行
- 任一步骤失败 → 任务 FAILED，记录 failure_reason
- 任务元数据落 reports/tasks/<task_id>.json

CLI:
    python task_orchestrator.py [--category 全部类目] [--cycle 本周] [--skip-crawl] [--operator]
"""

import os
import sys
import json
import argparse
import logging
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict

# 将 scripts 目录加入 sys.path
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from decision_engine import DecisionInput, decide_batch, load_decision_config
from report_generator import ReportGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("task_orchestrator")


@dataclass
class StepResult:
    """步骤执行结果。"""
    name: str
    status: str = "PENDING"          # PENDING / SUCCESS / FAILED / SKIPPED
    started_at: str = ""
    finished_at: str = ""
    failure_reason: str = ""
    output: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskResult:
    """任务执行结果。"""
    task_id: str
    status: str = "RUNNING"           # RUNNING / SUCCESS / FAILED
    started_at: str = ""
    finished_at: str = ""
    category: str = "全部类目"
    cycle: str = "本周"
    operator: str = ""
    trigger: str = "手动"
    steps: List[StepResult] = field(default_factory=list)
    failure_reason: str = ""
    reports: Dict[str, str] = field(default_factory=dict)
    decisions: List[Dict[str, Any]] = field(default_factory=list)


class TaskOrchestrator:
    """任务编排器。"""

    def __init__(
        self,
        scripts_dir: str = None,
        skill_root: str = None,
        reports_dir: str = None,
    ):
        if scripts_dir is None:
            scripts_dir = _SCRIPTS_DIR
        if skill_root is None:
            skill_root = os.path.dirname(scripts_dir)
        if reports_dir is None:
            reports_dir = os.path.join(skill_root, "reports")
        self.scripts_dir = scripts_dir
        self.skill_root = skill_root
        self.reports_dir = reports_dir
        self.tasks_dir = os.path.join(reports_dir, "tasks")
        os.makedirs(self.tasks_dir, exist_ok=True)

    def _now(self) -> str:
        return datetime.now().isoformat()

    def _run_subprocess(self, script_name: str, args: List[str] = None) -> StepResult:
        """运行 scripts/ 下的子脚本。

        失败不抛异常，返回 FAILED 状态的 StepResult。
        """
        step = StepResult(name=script_name, started_at=self._now())
        script_path = os.path.join(self.scripts_dir, script_name)
        if not os.path.exists(script_path):
            step.status = "FAILED"
            step.failure_reason = f"脚本不存在: {script_path}"
            step.finished_at = self._now()
            return step

        cmd = [sys.executable, script_path] + (args or [])
        logger.info(f"运行子进程: {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
                cwd=self.skill_root,
                env={**os.environ, "PYTHONPATH": self.scripts_dir},
            )
            step.output = {
                "returncode": result.returncode,
                "stdout_tail": result.stdout[-2000:] if result.stdout else "",
                "stderr_tail": result.stderr[-2000:] if result.stderr else "",
            }
            if result.returncode != 0:
                step.status = "FAILED"
                step.failure_reason = f"退出码 {result.returncode}: {result.stderr[-500:]}"
            else:
                step.status = "SUCCESS"
        except subprocess.TimeoutExpired:
            step.status = "FAILED"
            step.failure_reason = f"超时（>600s）"
        except Exception as e:
            step.status = "FAILED"
            step.failure_reason = f"异常: {e}"
        step.finished_at = self._now()
        return step

    def _load_decision_inputs(self) -> List[DecisionInput]:
        """从飞书「指标得分」表读取数据，构造决策输入。

        无飞书凭证或无数据时返回空列表（不报错，降级为空报告）。
        """
        try:
            from feishu_client import FeishuClient
        except ImportError:
            logger.warning("feishu_client 不可用，决策输入为空")
            return []

        app_id = os.environ.get("FEISHU_APP_ID")
        app_secret = os.environ.get("FEISHU_APP_SECRET")
        app_token = os.environ.get("FEISHU_APP_TOKEN")
        metrics_table_id = os.environ.get("FEISHU_METRICS_TABLE_ID")
        profit_table_id = os.environ.get("FEISHU_PROFIT_TABLE_ID", "")

        if not all([app_id, app_secret, app_token, metrics_table_id]):
            logger.warning("飞书凭证或表 ID 缺失，决策输入为空")
            return []

        try:
            feishu = FeishuClient(app_id, app_secret, app_token)
            metrics_records = feishu.get_records(metrics_table_id)
        except Exception as e:
            logger.error(f"读取飞书指标表失败: {e}")
            return []

        # 利润表可选
        profit_map: Dict[str, float] = {}
        if profit_table_id:
            try:
                profit_records = feishu.get_records(profit_table_id)
                for r in profit_records:
                    fields = r.get("fields", {})
                    asin_field = fields.get("ASIN", "")
                    asin = asin_field.get("text", "") if isinstance(asin_field, dict) else asin_field
                    margin_field = fields.get("利润率", None)
                    if isinstance(margin_field, dict):
                        margin = margin_field.get("value")
                    else:
                        margin = margin_field
                    if asin and margin is not None:
                        profit_map[asin] = float(margin)
            except Exception as e:
                logger.warning(f"读取利润表失败（降级为无利润数据）: {e}")

        inputs: List[DecisionInput] = []
        for r in metrics_records:
            fields = r.get("fields", {})
            asin_field = fields.get("ASIN", "")
            asin = asin_field.get("text", "") if isinstance(asin_field, dict) else asin_field
            if not asin:
                continue

            def _num(v):
                if isinstance(v, dict):
                    return v.get("value")
                return v

            composite = _num(fields.get("综合得分", 0)) or 0
            risk = _num(fields.get("风险得分", 0)) or 0
            margin = profit_map.get(asin)

            inputs.append(DecisionInput(
                asin=asin,
                composite_score=float(composite),
                risk_score=float(risk),
                profit_margin=margin,
            ))

        logger.info(f"加载决策输入: {len(inputs)} 个 ASIN")
        return inputs

    def _step_decide(self, inputs: List[DecisionInput]) -> StepResult:
        """决策步骤（纯计算，不失败）。"""
        step = StepResult(name="decide", started_at=self._now())
        try:
            results = decide_batch(inputs)
            step.output = {
                "total": len(results),
                "go": sum(1 for r in results if r.decision == "GO"),
                "watch": sum(1 for r in results if r.decision == "WATCH"),
                "no_go": sum(1 for r in results if r.decision == "NO-GO"),
            }
            step.status = "SUCCESS"
            step.output["results"] = [asdict(r) for r in results]
        except Exception as e:
            # 决策不应失败；若失败则任务降级为空报告
            step.status = "FAILED"
            step.failure_reason = f"决策异常: {e}"
        step.finished_at = self._now()
        return step

    def _step_report(
        self,
        decision_rows: List[Dict[str, Any]],
        category: str,
        cycle: str,
    ) -> StepResult:
        """报告生成步骤。"""
        step = StepResult(name="report", started_at=self._now())
        try:
            gen = ReportGenerator(output_dir=self.reports_dir)
            paths = gen.run(
                decision_rows=decision_rows,
                category=category,
                cycle=cycle,
            )
            step.status = "SUCCESS"
            step.output = paths
        except Exception as e:
            step.status = "FAILED"
            step.failure_reason = f"报告生成异常: {e}"
        step.finished_at = self._now()
        return step

    def run_task(
        self,
        category: str = "全部类目",
        cycle: str = "本周",
        trigger: str = "手动",
        operator: str = "",
        skip_crawl: bool = False,
    ) -> TaskResult:
        """执行完整任务。"""
        task_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        task = TaskResult(
            task_id=task_id,
            started_at=self._now(),
            category=category,
            cycle=cycle,
            operator=operator,
            trigger=trigger,
        )
        logger.info(f"任务开始: {task_id} (category={category}, cycle={cycle}, skip_crawl={skip_crawl})")

        # Step 1: crawl（可跳过）
        if skip_crawl:
            step_crawl = StepResult(name="crawl", status="SKIPPED", started_at=self._now(), finished_at=self._now())
            logger.info("跳过 crawl 步骤")
        else:
            step_crawl = self._run_subprocess("crawl.py")
        task.steps.append(step_crawl)

        if step_crawl.status == "FAILED":
            task.status = "FAILED"
            task.failure_reason = f"crawl 失败: {step_crawl.failure_reason}"
            return self._finalize(task)

        # Step 2: metrics
        step_metrics = self._run_subprocess("metrics.py")
        task.steps.append(step_metrics)
        if step_metrics.status == "FAILED":
            task.status = "FAILED"
            task.failure_reason = f"metrics 失败: {step_metrics.failure_reason}"
            return self._finalize(task)

        # Step 3: profit（失败不阻断，降级为无利润数据）
        step_profit = self._run_subprocess("profit_calc.py")
        task.steps.append(step_profit)
        if step_profit.status == "FAILED":
            logger.warning(f"profit 失败，降级为无利润数据: {step_profit.failure_reason}")
            step_profit.status = "SKIPPED"
            step_profit.failure_reason = f"原失败已降级: {step_profit.failure_reason}"

        # Step 4: decide
        inputs = self._load_decision_inputs()
        step_decide = self._step_decide(inputs)
        task.steps.append(step_decide)
        if step_decide.status == "FAILED":
            task.status = "FAILED"
            task.failure_reason = step_decide.failure_reason
            return self._finalize(task)

        decision_rows = step_decide.output.get("results", [])
        task.decisions = decision_rows

        # Step 5: report
        step_report = self._step_report(decision_rows, category, cycle)
        task.steps.append(step_report)
        if step_report.status == "FAILED":
            task.status = "FAILED"
            task.failure_reason = step_report.failure_reason
            return self._finalize(task)

        task.reports = step_report.output
        task.status = "SUCCESS"
        return self._finalize(task)

    def _finalize(self, task: TaskResult) -> TaskResult:
        """收尾：写任务元数据 JSON。"""
        task.finished_at = self._now()
        meta_path = os.path.join(self.tasks_dir, f"{task.task_id}.json")
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(asdict(task), f, ensure_ascii=False, indent=2)
            logger.info(f"任务元数据已写入: {meta_path}")
        except Exception as e:
            logger.error(f"写任务元数据失败: {e}")
        logger.info(f"任务结束: {task.task_id} status={task.status}")
        return task


def main():
    parser = argparse.ArgumentParser(description="选品任务编排器")
    parser.add_argument("--category", default="全部类目", help="类目名称")
    parser.add_argument("--cycle", default="本周", help="周期标签")
    parser.add_argument("--trigger", default="手动", help="触发方式")
    parser.add_argument("--operator", default="", help="操作人")
    parser.add_argument("--skip-crawl", action="store_true", help="跳过采集步骤")
    args = parser.parse_args()

    orchestrator = TaskOrchestrator()
    result = orchestrator.run_task(
        category=args.category,
        cycle=args.cycle,
        trigger=args.trigger,
        operator=args.operator,
        skip_crawl=args.skip_crawl,
    )
    print(json.dumps({
        "task_id": result.task_id,
        "status": result.status,
        "failure_reason": result.failure_reason,
        "reports": result.reports,
        "step_summary": [
            {"name": s.name, "status": s.status, "failure_reason": s.failure_reason}
            for s in result.steps
        ],
    }, ensure_ascii=False, indent=2))

    sys.exit(0 if result.status == "SUCCESS" else 1)


if __name__ == "__main__":
    main()

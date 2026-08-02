"""任务编排器单元测试。

不真正调用 crawl/metrics/profit 子进程，使用 --skip-crawl 并模拟子进程失败场景。
"""

import os
import json
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from task_orchestrator import TaskOrchestrator, StepResult, TaskResult
from decision_engine import DecisionInput


class TestTaskOrchestrator:
    @pytest.fixture
    def tmp_orchestrator(self, tmp_path):
        return TaskOrchestrator(
            scripts_dir=str(tmp_path / "scripts"),
            skill_root=str(tmp_path),
            reports_dir=str(tmp_path / "reports"),
        )

    def test_run_subprocess_missing_script(self, tmp_orchestrator):
        """脚本不存在时返回 FAILED。"""
        result = tmp_orchestrator._run_subprocess("nonexistent.py")
        assert result.status == "FAILED"
        assert "脚本不存在" in result.failure_reason

    def test_run_subprocess_success(self, tmp_orchestrator, tmp_path):
        """成功执行子脚本。"""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        script = scripts_dir / "ok.py"
        script.write_text("print('hello')\n")
        result = tmp_orchestrator._run_subprocess("ok.py")
        assert result.status == "SUCCESS"
        assert result.output["returncode"] == 0

    def test_run_subprocess_failure(self, tmp_orchestrator, tmp_path):
        """子脚本退出码非 0 时返回 FAILED。"""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        script = scripts_dir / "fail.py"
        script.write_text("import sys; sys.exit(2)\n")
        result = tmp_orchestrator._run_subprocess("fail.py")
        assert result.status == "FAILED"
        assert "退出码 2" in result.failure_reason

    def test_step_decide_success(self, tmp_orchestrator):
        inputs = [
            DecisionInput(asin="B001", composite_score=85, risk_score=80, profit_margin=0.20),
            DecisionInput(asin="B002", composite_score=30, risk_score=80, profit_margin=0.20),
        ]
        step = tmp_orchestrator._step_decide(inputs)
        assert step.status == "SUCCESS"
        assert step.output["total"] == 2
        assert step.output["go"] == 1
        assert step.output["no_go"] == 1
        assert len(step.output["results"]) == 2

    def test_step_decide_empty(self, tmp_orchestrator):
        """空输入也能正常决策。"""
        step = tmp_orchestrator._step_decide([])
        assert step.status == "SUCCESS"
        assert step.output["total"] == 0

    def test_step_report_success(self, tmp_orchestrator):
        decision_rows = [
            {"asin": "B001", "decision": "GO", "composite_score": 85, "risk_score": 80,
             "profit_margin": 0.20, "reason": "全部达标", "failure_reason": ""},
        ]
        step = tmp_orchestrator._step_report(decision_rows, "Kitchen", "本周")
        assert step.status == "SUCCESS"
        assert "html" in step.output
        assert "excel" in step.output
        assert os.path.exists(step.output["html"])
        assert os.path.exists(step.output["excel"])

    def test_run_task_skip_crawl_success(self, tmp_orchestrator):
        """--skip-crawl 模式下，无飞书凭证也能完成决策+报告。"""
        # 模拟 metrics 和 profit 子进程成功（写入空脚本）
        scripts_dir = os.path.dirname(tmp_orchestrator.scripts_dir)
        os.makedirs(tmp_orchestrator.scripts_dir, exist_ok=True)
        for name in ("metrics.py", "profit_calc.py"):
            p = os.path.join(tmp_orchestrator.scripts_dir, name)
            with open(p, "w") as f:
                f.write("print('ok')\n")

        # 无 FEISHU_* 环境变量 → _load_decision_inputs 返回空
        result = tmp_orchestrator.run_task(skip_crawl=True, category="测试", cycle="本周")
        assert result.status == "SUCCESS"
        assert len(result.steps) == 5
        assert result.steps[0].name == "crawl"
        assert result.steps[0].status == "SKIPPED"
        assert result.steps[1].status == "SUCCESS"  # metrics
        assert result.steps[3].name == "decide"
        assert result.steps[4].name == "report"
        assert result.reports  # 报告路径非空

        # 任务元数据 JSON 已写入
        meta_path = os.path.join(tmp_orchestrator.tasks_dir, f"{result.task_id}.json")
        assert os.path.exists(meta_path)
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        assert meta["status"] == "SUCCESS"
        assert meta["category"] == "测试"

    def test_run_task_metrics_failure(self, tmp_orchestrator):
        """metrics 失败 → 任务 FAILED。"""
        os.makedirs(tmp_orchestrator.scripts_dir, exist_ok=True)
        # metrics.py 退出码非 0
        with open(os.path.join(tmp_orchestrator.scripts_dir, "metrics.py"), "w") as f:
            f.write("import sys; sys.exit(1)\n")

        result = tmp_orchestrator.run_task(skip_crawl=True)
        assert result.status == "FAILED"
        assert "metrics 失败" in result.failure_reason
        # 失败后不应继续执行后续步骤
        step_names = [s.name for s in result.steps]
        assert "decide" not in step_names
        assert "report" not in step_names

    def test_load_decision_inputs_no_creds(self, tmp_orchestrator, monkeypatch):
        """无飞书凭证时返回空列表。"""
        # 清除所有飞书环境变量
        for k in ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_APP_TOKEN",
                  "FEISHU_METRICS_TABLE_ID", "FEISHU_PROFIT_TABLE_ID"):
            monkeypatch.delenv(k, raising=False)
        inputs = tmp_orchestrator._load_decision_inputs()
        assert inputs == []

# Phase 1 实施计划

> 关联 Spec：[2026-07-29-task-orchestration-design.md](../specs/2026-07-29-task-orchestration-design.md)

## 任务清单

- [ ] T1. 配置：`config/scoring.yaml` 增加 `decision` 段
- [ ] T2. 决策引擎：`scripts/decision_engine.py`
- [ ] T3. HTML 渲染器：`scripts/renderers/html_renderer.py` + 模板
- [ ] T4. Excel 渲染器：`scripts/renderers/excel_renderer.py`
- [ ] T5. 报告生成器：`scripts/report_generator.py`
- [ ] T6. 任务编排器：`scripts/task_orchestrator.py`
- [ ] T7. 入口：`bootstrap.sh` 增加 `task` 命令
- [ ] T8. 依赖：`requirements.txt` 增加 Jinja2 / openpyxl
- [ ] T9. 测试：`tests/test_decision_engine.py` + `tests/test_report_generator.py`
- [ ] T10. 提交并推送

## 验收标准

1. `bash bootstrap.sh task --skip-crawl` 在无飞书凭证时也能跑通决策+报告（基于空数据，状态 SUCCESS 但报告为空）。
2. `bash bootstrap.sh test` 全绿。
3. `reports/` 目录下生成 HTML + Excel 文件。
4. 决策结果含 `decision` / `reason` / `failure_reason` 三字段。

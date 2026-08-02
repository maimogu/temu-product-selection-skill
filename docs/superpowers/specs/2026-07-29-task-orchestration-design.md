# 任务编排设计（Task Orchestration Design）

> 日期：2026-07-29
> 状态：已确认（Phase 1 重新实现）
> 范围：S1 范围 + 方案 A；降级不引入第四状态，落「失败原因」字段；报告本地 HTML+Excel，不导入飞书。

## 1. 背景与目标

当前仓库已有 4 个独立原子脚本（crawl / metrics / keywords / profit），各自直接读写飞书多维表格。存在以下问题：

1. **流程零散**：用户需手动依次执行 4 条命令，无统一编排入口。
2. **决策缺失**：仅有五维指标，缺「GO / WATCH / NO-GO」业务决策。
3. **产物分散**：指标留在飞书，无可下载的本地报告（HTML / Excel）。
4. **失败溯源难**：子步骤失败后无结构化状态记录，需翻日志定位。

本设计构建**任务编排器**，串联「采集 → 指标 → 利润 → 决策 → 报告」全链路，落本地化报告，并支持任务级状态与失败原因记录。

## 2. 范围（Phase 1）

### In Scope（S1）
- 决策引擎：基于已有五维指标输出 GO / WATCH / NO-GO 三态。
- 报告生成器：本地 HTML（Jinja2）+ Excel（openpyxl），不写飞书。
- 任务编排器：CLI 入口 `bootstrap.sh task`，串联已有脚本。
- 失败原因字段：在决策结果中落 `failure_reason`，不引入第四状态。

### Out of Scope
- 定时调度、外部触发器（留 Phase 2）。
- 任务状态持久化到飞书（留 Phase 2，本期仅落本地 JSON）。
- 邮件 / IM 推送（留 Phase 3）。

## 3. 决策引擎设计

### 3.1 决策三态

| 状态 | 含义 | 触发条件 |
|---|---|---|
| `GO` | 推荐上架 | 综合得分 ≥ GO 阈值 且 利润率达标 且 风险得分 ≥ 安全线 |
| `WATCH` | 观察 | 既不满足 GO，也不触发 NO-GO |
| `NO-GO` | 不推荐 | 触发任一否决条件 |

### 3.2 否决条件（NO-GO）
- 综合得分 < NO-GO 阈值
- 风险得分 < 风险安全线（高风险品牌）
- 利润率 < 0（亏损）

### 3.3 降级与失败原因

> 用户确认：**降级不引入第四状态**，落「失败原因」字段。

- 任一否决条件命中 → `NO-GO`，`reason` 字段记录原因（多原因用 `;` 拼接）。
- GO 条件未全部满足但未触发 NO-GO → `WATCH`，`reason` 记录缺失项。
- GO 全部满足 → `GO`，`reason` 为「全部达标」。
- 输入数据缺失（如利润未算）→ 状态 `WATCH`，`failure_reason` 记录「利润数据缺失」，**不报错**。

### 3.4 配置（config/scoring.yaml 新增 decision 段）

```yaml
decision:
  go:
    min_composite: 75
    min_profit_margin: 0.15
    min_risk_score: 60
  no_go:
    max_composite: 40
    max_risk_score: 30
    max_profit_margin: 0.0
```

## 4. 报告生成器设计

### 4.1 输出
- HTML：基于 Jinja2 模板，含汇总卡片 + 决策明细表 + Top10。
- Excel：openpyxl 多 Sheet（汇总、决策明细、指标明细、利润明细）。
- 路径：`reports/<timestamp>_<category>_<cycle>.{html,xlsx}`。

### 4.2 不写飞书
本期报告仅落本地，飞书 IO 仅用于读取已有指标 / 利润数据。

## 5. 任务编排器设计

### 5.1 步骤

| 步骤 | 调用 | 失败行为 |
|---|---|---|
| 1. crawl | `crawl.py` | 失败 → 任务 `FAILED`，记录原因，跳过后续 |
| 2. metrics | `metrics.py` | 失败 → 任务 `FAILED` |
| 3. profit | `profit_calc.py` | 失败 → 任务 `FAILED` |
| 4. decide | `decision_engine.decide_batch` | 不失败（纯计算） |
| 5. report | `report_generator` | 失败 → 任务 `FAILED` |

### 5.2 CLI

```bash
bash bootstrap.sh task [--category 全部类目] [--cycle 本周] [--skip-crawl] [--operator]
```

### 5.3 任务状态

| 状态 | 说明 |
|---|---|
| `RUNNING` | 执行中 |
| `SUCCESS` | 全部步骤成功 |
| `FAILED` | 任一步骤失败，`failure_reason` 记录原因 |

任务元数据落 `reports/tasks/<task_id>.json`。

## 6. 风险与权衡

- **子进程调用方式**：本期用 `subprocess` 调用已有脚本，简单但跨进程开销略大；Phase 2 可重构为进程内调用。
- **报告本地化**：飞书仍作为数据源，报告不回写飞书，避免双向同步复杂度。

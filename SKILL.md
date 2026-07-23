---
name: amazon-product-selection
version: 1.0.0
description: "亚马逊站内类目热卖二阶选品法数据指标体系工具：采集 Amazon Best Sellers 榜单数据，计算五维指标综合得分，写入飞书多维表格展示与告警。当用户需要做亚马逊选品分析、采集 BSR 榜单、计算商品综合得分、监控侵权风险、生成选品看板时使用。"
metadata:
  requires:
    bins: ["npx", "python3"]
---

# 亚马逊二阶选品法 Skill

基于"二阶选品法"的亚马逊选品数据指标体系工具，以飞书多维表格为中心枢纽完成采集、计算、展示、告警全流程。

本 Skill 需要系统安装 Python 3.10+。首次运行时 `bootstrap.sh` 自动创建 `.venv` 虚拟环境并安装依赖，后续运行直接复用已有 venv。

## 适用场景

- "帮我采集 Amazon Kitchen 类目的 Best Sellers Top100"
- "计算这周采集商品的五维指标得分"
- "分析这个类目的关键词布局"
- "计算商品的 FBA 利润"
- "看看哪些商品综合得分最高"

## 工作流总览

```
飞书自动化定时触发（每周一 09:00）
       │
       ▼
  [子 Skill: amazon-bsr-crawl]
       │  读取「类目管理」表 → keepa-mcp 采集 → 写入「榜单快照」/「商品详情」表
       ▼
飞书自动化定时触发（每周一 10:00）
       │
       ▼
  [子 Skill: amazon-metrics-calc]
       │  读取「榜单快照」表 → 计算五维得分 → 写入「指标得分」表
       ▼
  ┌─────────────────┬──────────────────┐
  │                                    │
  ▼                                    ▼
[keyword-research]                  [profit-calc]
       │                                │
       ▼                                ▼
  「关键词库」表                    「利润分析」表
       │                                │
       └────────────────┬───────────────┘
                         │
                         ▼
              飞书多维表格仪表盘 + 自动化告警
```

## 前置条件

**MUST 先用 Read 工具读取以下参考文档**：

1. [`references/environment-setup.md`](references/environment-setup.md) — 环境变量与依赖配置
2. [`references/feishu-table-schema.md`](references/feishu-table-schema.md) — 飞书多维表格结构
3. [`references/scoring-formula.md`](references/scoring-formula.md) — 五维指标评分公式

## 子 Skill 索引

本 Skill 内置 4 个子 Skill，定义在 `references/sub-skills/`。可独立调用，也可被主流程编排：

| 子 Skill | 文件 | 职责 | 触发方式 |
|---|---|---|---|
| `amazon-bsr-crawl` | [sub-skills/bsr-crawl.md](references/sub-skills/bsr-crawl.md) | 采集榜单与商品详情 | 飞书自动化 Webhook / 手动 |
| `amazon-metrics-calc` | [sub-skills/metrics-calc.md](references/sub-skills/metrics-calc.md) | 计算五维指标得分 | 飞书自动化 Webhook / 手动 |
| `amazon-keyword-research` | [sub-skills/keyword-research.md](references/sub-skills/keyword-research.md) | 关键词采集与8维分类 | 飞书自动化 Webhook / 手动 |
| `amazon-profit-calc` | [sub-skills/profit-calc.md](references/sub-skills/profit-calc.md) | FBA利润计算 | 飞书自动化 Webhook / 手动 |

## 标准用法

所有命令通过 `bootstrap.sh` 调用，自动使用内嵌 Python 运行时：

### 用法 1：完整工作流（推荐）

agent 客户端按工作流顺序调用：

```bash
# Step 1: 采集榜单（每周一）
bash bootstrap.sh crawl

# Step 2: 计算指标（采集完成 1 小时后）
bash bootstrap.sh metrics

# Step 3: 深度分析（并行执行）
bash bootstrap.sh keywords
bash bootstrap.sh profit
```

### 用法 2：单独调用子 Skill

```bash
# 只采集
bash bootstrap.sh crawl

# 只计算指标
bash bootstrap.sh metrics

# 只分析关键词
bash bootstrap.sh keywords

# 只计算利润
bash bootstrap.sh profit

# 运行测试
bash bootstrap.sh test
```

### 用法 3：飞书自动化触发

飞书自动化定时触发 → Webhook → 调用 `bootstrap.sh crawl` / `bootstrap.sh metrics`，详见 [`references/feishu-automation-setup.md`](references/feishu-automation-setup.md)。

## 关键脚本

| 脚本 | 职责 |
|---|---|
| [bootstrap.sh](bootstrap.sh) | 启动入口，自动使用内嵌 Python 运行时 |
| [scripts/crawl.py](scripts/crawl.py) | 采集主入口，编排 keepa-mcp 和 agent-browser |
| [scripts/metrics.py](scripts/metrics.py) | 指标计算主入口，读快照→算得分→写回 |
| [scripts/scoring.py](scripts/scoring.py) | 综合得分计算引擎（纯函数） |
| [scripts/keyword_research.py](scripts/keyword_research.py) | 关键词采集与8维分类 |
| [scripts/profit_calc.py](scripts/profit_calc.py) | FBA 利润计算 |
| [scripts/feishu_client.py](scripts/feishu_client.py) | 飞书多维表格 API 封装 |
| [scripts/keepa_client.py](scripts/keepa_client.py) | keepa-mcp 持久化子进程封装 |
| [scripts/browser_crawler.py](scripts/browser_crawler.py) | agent-browser 兜底采集 + HTML 解析 |
| [scripts/risk_checker.py](scripts/risk_checker.py) | 品牌风险名单匹配（供 scoring.py 调用） |

## 运行时

本 Skill 不携带内置 Python 发行版。`bootstrap.sh` 处理运行时环境：

1. 检测系统 Python 3.10+ 是否存在
2. 首次运行：自动创建 `.venv/` 虚拟环境，`pip install -r requirements.txt`
3. 后续运行：检测 `.venv/` 已存在，直接复用
4. 若 `requirements.txt` 有变更，自动同步依赖

```bash
# 首次运行（自动创建 venv）
bash bootstrap.sh check

# 后续运行（秒级启动）
bash bootstrap.sh crawl
bash bootstrap.sh metrics
bash bootstrap.sh test
```

## 配置文件

- [config/scoring.yaml](config/scoring.yaml) — 综合得分权重与高风险品牌名单
- [config/keyword_categories.yaml](config/keyword_categories.yaml) — 关键词8维分类规则
- [config/fba_rates.yaml](config/fba_rates.yaml) — FBA 费率表与默认参数

修改权重或新增风险品牌后无需改代码，下次运行 `metrics.py` 自动生效。

## 错误处理

| 场景 | 处理 |
|---|---|
| keepa-mcp 不可用 | 自动降级到 agent-browser，仍失败则跳过该类目并触发告警 |
| 飞书 API 429 | 指数退避重试 3 次（1s→2s→4s） |
| 某 ASIN 详情失败 | 部分字段为空写入，不影响其他 ASIN |
| 指标得分表已有旧记录 | 写入前先清空，避免重复膨胀 |
| 商品详情已存在 | 用 `batch_update_records` 更新价格/评分，不跳过 |

## 测试

```bash
bash bootstrap.sh test
```

预期输出：`102 passed`，覆盖 scoring / risk_checker / feishu_client / crawl / keyword_research / profit_calc。

## 不做的（第一期范围）

- 详情页深度抓取（加购率、退货率、广告投放等）
- 自建 Web 前端
- PostgreSQL 数据库
- Celery/Redis 任务队列
- 用户登录认证

如需扩展，参考 [references/sub-skills/](references/sub-skills/) 中预留的子 Skill 定义。

## 扩展点

新增子 Skill 的标准流程：

1. 在 `references/sub-skills/` 新建 `<skill-name>.md`
2. 在 `scripts/` 新建对应 Python 脚本
3. 在本文件「子 Skill 索引」表格新增一行
4. 如需新增飞书自动化流程，更新 [references/feishu-automation-setup.md](references/feishu-automation-setup.md)

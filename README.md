# 亚马逊二阶选品法 Skill（amazon-product-selection）

基于"二阶选品法"的亚马逊选品数据指标体系工具。以飞书多维表格为中心枢纽，完成 **采集 → 计算 → 展示 → 告警** 全流程，帮助发现高潜力商品、监控侵权风险、生成选品看板。

> **北极星指标**：类目月销量（或销售额）—— 决定选品成败的核心目标。

---

## 它能做什么

- **采集榜单**：抓取 Amazon Best Sellers Top100，双通道（keepa-mcp 主力 + agent-browser 兜底）
- **五维评分**：流量 / 转化 / 客单价 / 成长性 / 侵权风险，加权得出综合得分
- **关键词调研**：8 维智能分类（否定词 / 品牌词 / 材质词 / 场景词 / 属性词 / 功能词 / 核心词 / 其他）+ 广告分组建议
- **FBA 利润测算**：按费率表计算配送费、佣金、仓储费、广告费、头程物流，输出利润率与盈亏平衡点
- **飞书看板**：6 张数据表 + 仪表盘 + 自动化告警（侵权风险 / 采集失败 / 高风险复查）

---

## 工作流总览

```
飞书自动化定时触发（每周一 09:00）
       │
       ▼
  [子 Skill: amazon-bsr-crawl]   读取「类目管理」→ keepa-mcp 采集 → 写入「榜单快照」/「商品详情」
       │
       ▼
飞书自动化定时触发（每周一 10:00）
       │
       ▼
  [子 Skill: amazon-metrics-calc]  读取「榜单快照」→ 计算五维得分 → 写入「指标得分」
       │
  ┌────┴────┐
  ▼         ▼
[keywords] [profit]
  │         │
  ▼         ▼
「关键词库」「利润分析」
       │
       ▼
  飞书多维表格仪表盘 + 自动化告警
```

---

## 项目结构

```
.
├── bootstrap.sh                # 启动入口（自动创建/复用 venv，分发子命令）
├── SKILL.md                    # Skill 定义与用法说明
├── requirements.txt            # Python 依赖
├── conftest.py                 # pytest 公共 fixture
├── config/
│   ├── scoring.yaml            # 综合得分权重 + 高风险品牌名单
│   ├── keyword_categories.yaml # 关键词 8 维分类规则
│   └── fba_rates.yaml          # FBA 费率表与默认参数
├── scripts/
│   ├── crawl.py                # 采集主入口（编排 keepa-mcp + agent-browser）
│   ├── metrics.py              # 指标计算主入口（读快照→算得分→写回）
│   ├── scoring.py              # 综合得分计算引擎（纯函数）
│   ├── keyword_research.py     # 关键词采集与 8 维分类
│   ├── profit_calc.py          # FBA 利润计算
│   ├── feishu_client.py        # 飞书多维表格 API 封装
│   ├── keepa_client.py         # keepa-mcp 持久化子进程封装
│   ├── browser_crawler.py      # agent-browser 兜底采集 + HTML 解析
│   └── risk_checker.py         # 品牌风险名单匹配
├── references/
│   ├── design.md               # 数据指标体系设计文档
│   ├── scoring-formula.md      # 五维评分公式详解
│   ├── feishu-table-schema.md  # 飞书多维表格结构（6 张表）
│   ├── feishu-automation-setup.md  # 飞书自动化与 Webhook 配置
│   ├── environment-setup.md    # 环境变量与依赖配置
│   └── sub-skills/             # 4 个子 Skill 定义
└── tests/                      # pytest 测试 + fixtures
```

---

## 前置条件

- **Python 3.10+**（`bootstrap.sh` 首次运行自动创建 `.venv` 并安装依赖）
- **keepa-mcp** 已配置并启用（主力采集通道，需 `KEEPA_API_KEY`）
- **agent-browser**（兜底采集通道，可选）
- **飞书多维表格 Base** 已按 [feishu-table-schema.md](references/feishu-table-schema.md) 建好 6 张表
- 飞书自建应用，授予 Base 读写权限（`FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_APP_TOKEN`）

---

## 快速开始

```bash
# 1. 检查运行时环境与依赖
bash bootstrap.sh check

# 2. 采集榜单（每周一）
bash bootstrap.sh crawl

# 3. 计算五维指标得分（采集完成 1 小时后）
bash bootstrap.sh metrics

# 4. 深度分析（可并行）
bash bootstrap.sh keywords    # 关键词调研
bash bootstrap.sh profit      # FBA 利润测算

# 5. 运行测试
bash bootstrap.sh test
```

所有命令通过 `bootstrap.sh` 调用，自动使用内嵌 Python 运行时；首次运行自动建 venv，后续秒级启动。若 `requirements.txt` 有变更，会自动同步依赖。

---

## 配置

修改权重、新增风险品牌或调整费率，**无需改代码**，下次运行自动生效：

| 配置文件 | 作用 |
|---|---|
| [config/scoring.yaml](config/scoring.yaml) | 五维权重 + 高风险品牌名单 + 评论封顶/价格区间等阈值 |
| [config/keyword_categories.yaml](config/keyword_categories.yaml) | 关键词 8 维分类规则 |
| [config/fba_rates.yaml](config/fba_rates.yaml) | FBA 配送费/佣金/仓储费费率表 + 默认 ACoS/头程物流比例 |

---

## 五维评分公式

综合得分 = 流量×0.25 + 转化×0.25 + 客单价×0.20 + 成长性×0.20 + 风险×0.10

| 维度 | 权重 | 主要输入 |
|---|---|---|
| 流量 | 25% | BSR 排名分、排名稳定性、出现频率 |
| 转化 | 25% | 星级评分、评论量级、评论增长 |
| 客单价 | 20% | 价格分（相对类目均价）、价格趋势 |
| 成长性 | 20% | 销量增速、排名提升、生命周期 |
| 风险 | 10% | 品牌风险名单匹配（越高越安全） |

详见 [references/scoring-formula.md](references/scoring-formula.md)。

---

## 错误处理

| 场景 | 处理 |
|---|---|
| keepa-mcp 不可用 | 自动降级到 agent-browser，仍失败则跳过该类目并告警 |
| 飞书 API 429 | 指数退避重试 3 次（1s→2s→4s） |
| 某 ASIN 详情失败 | 部分字段为空写入，不影响其他 ASIN |
| 指标得分表已有旧记录 | 写入前先清空，避免重复膨胀 |
| 商品详情已存在 | 用 `batch_update_records` 更新价格/评分，不跳过 |

---

## 测试

```bash
bash bootstrap.sh test
```

覆盖 scoring / risk_checker / feishu_client / crawl / keyword_research / profit_calc，含 10 个 ASIN、3 期快照的边界用例 fixture。

---

## 路线图

当前为 v1.0（数据采集 + 评分 + 飞书看板）。下一步规划与 MVP 方案见 [prd.md](prd.md)。

第一期不做的：详情页深度抓取（加购率/退货率/广告投放）、自建 Web 前端、PostgreSQL、Celery/Redis、用户登录认证。

---

## 扩展点

新增子 Skill 的标准流程：

1. 在 `references/sub-skills/` 新建 `<skill-name>.md`
2. 在 `scripts/` 新建对应 Python 脚本
3. 在 [SKILL.md](SKILL.md)「子 Skill 索引」表格新增一行
4. 如需新增飞书自动化流程，更新 [references/feishu-automation-setup.md](references/feishu-automation-setup.md)

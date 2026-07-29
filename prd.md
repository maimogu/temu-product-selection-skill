# PRD — 亚马逊二阶选品法 Skill 下一步规划

**日期**：2026-07-28
**当前版本**：v1.0（已交付）
**文档状态**：草案，待评审

---

## 1. 现状盘点

### 1.1 v1.0 已交付能力

| 模块 | 状态 | 说明 |
|---|---|---|
| BSR 采集 | ✅ | keepa-mcp 主力 + agent-browser 兜底，Top100 榜单快照 |
| 五维评分 | ✅ | 流量/转化/客单价/成长性/风险，权重可配置 |
| 关键词调研 | ✅ | 8 维分类 + 竞争度/季节性 + 广告分组建议 |
| FBA 利润测算 | ✅ | 费率表驱动，利润率 + 盈亏平衡点 |
| 飞书看板 | ✅ | 6 张表 + 仪表盘 + 3 个自动化告警 |
| 测试 | ✅ | pytest 覆盖 6 个模块 |

### 1.2 核心缺口（相对选品决策闭环）

1. **只有数据，没有结论**：综合得分是排序依据，但缺少明确的 Go/No-Go 决策输出
2. **交付物单一**：数据只落在飞书表，缺少可分享、可归档的报告文件（MD/HTML/Excel）
3. **缺详情页深度数据**：加购率、退货率、广告投放等留到二期，评分维度偏薄
4. **缺属性交叉分析**：未对 Top100 做属性维度打标与"高需求低供给"组合挖掘
5. **缺消费者痛点挖掘**：未利用差评数据识别真实需求
6. **缺供应链衔接**：无 1688 找源/供应商匹配环节

---

## 2. 下一步路线图

按"投入产出比"与"依赖关系"排序，分三阶段推进：

### 阶段一：决策与报告层（MVP，见第 4 节）

在现有飞书数据之上加一层"报告生成器"，补齐"结论 + 可分享交付物"。**不引入新数据源**，复用 v1.0 全部产出。

### 阶段二：深度数据层

- 详情页深度抓取：加购率、退货率、广告投放强度、上新月数
- Top100 属性维度打标 + 交叉分析（高需求低供给组合）
- 差评痛点挖掘（基于 product reviews）

### 阶段三：供应链与多源层

- 1688 / 供应商找源匹配
- 引入 Sorftime MCP 作为第三数据通道（与 keepa-mcp 互补）
- payload schema 标准化（v2 数据契约）

---

## 3. 待确认事项（评审输入）

以下决策点需在评审时拍板，会直接影响 MVP 范围：

1. **报告交付形态**：本地生成文件（MD/HTML/Excel） vs 写入飞书云文档 vs 两者都要？
2. **Go/No-Go 规则**：用规则引擎（阈值组合）还是引入轻量模型？MVP 建议先用规则。
3. **是否引入 Sorftime MCP**：参考项目 [zach-product-research](https://github.com/zach22-1999/amazon-skills/tree/main/skills/zach-product-research) 基于它，详见第 5 节评估，是否合入待定。
4. **详情页抓取通道**：keepa-mcp 是否覆盖加购率/退货率？还是需要 agent-browser 详情页解析？

---

## 4. MVP 实现方案：选品决策报告生成器（v1.1）

### 4.1 定位

**一句话**：把飞书多维表格里已有的"指标得分 + 关键词库 + 利润分析"数据，聚合成一份带 Go/No-Go 结论的可分享选品报告。

**为什么是这个 MVP**：
- 复用 v1.0 全部数据，零新数据源、零新外部依赖
- 直接补齐最大缺口（"只有数据没有结论"）
- 可独立验证、风险低、1 个新脚本即可落地
- 为阶段二的深度数据预留报告承载层

### 4.2 范围

| 项 | 说明 |
|---|---|
| 输入 | 飞书「指标得分」「利润分析」「关键词库」三张表 |
| 处理 | 聚合 → 排序 → Go/No-Go 规则判定 → 机会矩阵 |
| 输出 | Markdown 报告 + HTML 精简报告 + Excel 多 Sheet |
| 不做 | 详情页抓取、属性交叉分析、痛点挖掘（留阶段二） |

### 4.3 Go/No-Go 决策规则（MVP 用规则引擎）

```
GO     : 综合得分 ≥ 75  AND  利润率 ≥ 15%  AND  风险得分 ≥ 70
WATCH  : 综合得分 ≥ 60  OR   利润率 ≥ 15%   （任一达标，需人工复查）
NO-GO  : 风险得分 < 30  OR  利润率 < 0  OR  综合得分 < 50
其余   : WATCH
```

阈值集中在 `config/scoring.yaml` 新增 `decision` 段，可配置。

### 4.4 报告结构

**Markdown 报告**（`reports/YYYY-MM-DD-<类目>-selection-report.md`）：
1. 概览：类目、采集日期、商品数、Top10 概要
2. Go/No-Go 决策表：每个 ASIN 的结论 + 关键指标
3. 机会矩阵：综合得分 × 利润率 四象限分布
4. Top10 商品详情：五维得分雷达 + 利润结构
5. 关键词洞察：核心词 / 否定词 / 高竞争词 Top 列表
6. 风险提示：高风险品牌命中的 ASIN 清单

**HTML 精简报告**：Markdown 的可分享单页版本，适合发链接。

**Excel**：4 个 Sheet（决策表 / 指标得分 / 利润分析 / 关键词库）。

### 4.5 技术实现

| 新增 | 内容 |
|---|---|
| `scripts/report_generator.py` | 报告生成主入口：读飞书 → 判定 → 渲染 |
| `scripts/decision_engine.py` | Go/No-Go 规则引擎（纯函数，可单测） |
| `scripts/renderers/md_renderer.py` | Markdown 渲染 |
| `scripts/renderers/html_renderer.py` | HTML 渲染（基于模板） |
| `scripts/renderers/excel_renderer.py` | Excel 渲染（openpyxl） |
| `config/scoring.yaml` | 新增 `decision` 段阈值 |
| `references/sub-skills/report-gen.md` | 子 Skill 定义 |
| `tests/test_decision_engine.py` | 规则引擎单测 |
| `bootstrap.sh` | 新增 `report` 子命令 |
| `requirements.txt` | 新增 `openpyxl>=3.1`、`jinja2>=3.1` |

### 4.6 用法

```bash
# 生成全部类目报告
bash bootstrap.sh report

# 指定类目
bash bootstrap.sh report --category "Kitchen & Dining"

# 输出到自定义目录
bash bootstrap.sh report --output reports/2026-07/
```

### 4.7 验收标准

- [ ] `bash bootstrap.sh report` 生成 MD + HTML + Excel 三件套，无报错
- [ ] Go/No-Go 规则引擎单测全绿，覆盖 GO/WATCH/NO-GO/边界
- [ ] 报告内容与飞书表数据一致（抽样 5 个 ASIN 核对）
- [ ] HTML 报告可在浏览器直接打开，无乱码
- [ ] 阈值改 `config/scoring.yaml` 后重跑即生效

### 4.8 MVP 之外（明确不做）

- 不抓取新数据（不加购率/退货率/广告）
- 不做属性交叉分析
- 不接入 Sorftime MCP
- 不做 Web 前端

---

## 5. 参考项目评估：zach-product-research

> 仓库：https://github.com/zach22-1999/amazon-skills/tree/main/skills/zach-product-research
> 评估结论与待确认点见对话回复（第 5 节以对话形式给出，便于评审决策是否合入）。

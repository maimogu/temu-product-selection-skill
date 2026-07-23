---
name: amazon-metrics-calc
version: 1.0.0
parent: amazon-product-selection
description: "计算亚马逊商品五维指标综合得分。当用户需要计算商品流量/转化/客单价/成长性/风险得分、生成选品排行榜、更新飞书指标得分表时使用。"
---

# 子 Skill: amazon-metrics-calc

从飞书多维表格读取榜单快照数据，计算五维指标综合得分，写回飞书。

> **前置文档**：先阅读 [`../scoring-formula.md`](../scoring-formula.md) 了解评分公式，[`../feishu-table-schema.md`](../feishu-table-schema.md) 了解数据表结构。

## 触发方式

- **定时触发**：飞书自动化每周一 10:00（采集完成后 1 小时）→ Webhook → 调用 `scripts/metrics.py`
- **手动触发**：`python3 scripts/metrics.py`

## 执行流程

```
1. 读取飞书「榜单快照」表所有记录
   → 过滤价格 ≤ 0 的异常记录
   → 按 ASIN 聚合
   → 记录每个 ASIN 所属类目
   → 每个 ASIN 内按快照日期升序排序

2. 按类目聚合统计
   - 类目总快照次数 = 该类目不同快照日期的数量
   - 类目均价 = 该类目所有商品价格的均值

3. 对每个 ASIN 计算五维得分
   - 流量得分（25%）：排名分 + 排名稳定性 + 出现频率
   - 转化得分（25%）：评分分 + 评论量级 + 评论增长
   - 客单价得分（20%）：价格分 + 价格趋势
   - 成长性得分（20%）：销量增速 + 排名提升 + 生命周期
   - 风险得分（10%）：品牌风险匹配

4. 加权计算综合得分
   → 按综合得分降序排序

5. 写入飞书「指标得分」表
   → 先 batch_delete 清空旧记录
   → 再 batch_create 写入新记录
```

## 关键脚本

| 文件 | 职责 |
|---|---|
| [scripts/metrics.py](../../scripts/metrics.py) | 指标计算编排主入口 |
| [scripts/scoring.py](../../scripts/scoring.py) | 五维得分计算引擎（纯函数） |
| [scripts/risk_checker.py](../../scripts/risk_checker.py) | 品牌风险名单匹配 |
| [config/scoring.yaml](../../config/scoring.yaml) | 权重与高风险品牌配置 |

## 使用示例

### 示例 1：标准计算

```bash
python3 scripts/metrics.py
```

输出示例：

```json
{
  "status": "ok",
  "total": 95,
  "top10": [
    {"asin": "B000000001", "composite": 92.5},
    {"asin": "B000000005", "composite": 88.3},
    {"asin": "B000000010", "composite": 85.1}
  ]
}
```

### 示例 2：调整权重后重新计算

修改 `config/scoring.yaml`：

```yaml
weights:
  traffic: 0.30      # 提高流量权重
  conversion: 0.20
  aov: 0.20
  growth: 0.20
  risk: 0.10
```

重新运行：

```bash
python3 scripts/metrics.py
```

无需改代码，下次运行即生效。

### 示例 3：新增高风险品牌

在 `config/scoring.yaml` 的 `thresholds.high_risk_brands` 列表中追加：

```yaml
thresholds:
  high_risk_brands:
    - "Nike"
    - "Adidas"
    - "Apple"
    # 新增：
    - "NewBalance"
    - "Puma"
```

下次运行时这些品牌的风险得分自动变为 0。

### 示例 4：在 agent 客户端中调用

```python
from scripts.metrics import MetricsCalculator
from scripts.feishu_client import FeishuClient
from scripts.scoring import load_config

feishu = FeishuClient(app_id=..., app_secret=..., app_token=...)
config = load_config()

calculator = MetricsCalculator(
    feishu=feishu,
    snapshots_table_id="tblXXX",
    metrics_table_id="tblXXX",
    high_risk_brands=config["thresholds"]["high_risk_brands"],
)

result = calculator.run()
print(result["top10"])
```

## 评分公式速查

完整公式见 [`../scoring-formula.md`](../scoring-formula.md)，关键点：

| 维度 | 权重 | 主要输入 |
|---|---|---|
| 流量 | 25% | BSR 排名、历史排名稳定性、出现频率 |
| 转化 | 25% | 星级评分、评论数、评论增长率 |
| 客单价 | 20% | 当前价格 vs 类目均价、价格趋势 |
| 成长性 | 20% | 销量增速、排名提升、生命周期 |
| 风险 | 10% | 品牌名匹配高风险名单 |

## 错误处理

| 场景 | 处理 |
|---|---|
| 榜单快照表为空 | 返回 `{"status": "ok", "total": 0}` |
| 某 ASIN 计算失败 | 记录错误日志，跳过该 ASIN，继续处理其他 |
| 飞书 API 429 | 指数退避重试 3 次 |
| 指标得分表已有旧记录 | 写入前先 batch_delete 清空 |
| 价格异常（≤0） | 该条记录被过滤，不参与计算 |

## 边界情况处理

| 场景 | 默认值 |
|---|---|
| ASIN 仅 1 条快照 | 排名稳定性=50，评论增长=0 |
| 类目均价为 0 | 客单价得分=50 |
| 最早评论数为 0 | 评论增长率=50（多记录时），=0（单记录时） |
| 品牌为空 | 风险得分=70 |
| 品牌在高风险名单 | 风险得分=0 |

## 性能参考

- 100 个 ASIN × 3 期快照 = 300 条记录，计算约 1-2 秒
- 1000 个 ASIN × 12 期快照 = 12000 条记录，计算约 10-30 秒
- 主要瓶颈是飞书 API 读写（受 50 req/s 限制）

## 独立化建议

未来如需独立为单独的 Skill 包，操作同 [`bsr-crawl.md`](bsr-crawl.md) 中的「独立化建议」。
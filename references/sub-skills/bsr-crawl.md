---
name: amazon-bsr-crawl
version: 1.0.0
parent: amazon-product-selection
description: "采集 Amazon Best Sellers 榜单数据。当用户需要采集亚马逊热卖榜单、抓取 Top100 BSR 商品、获取商品详情、更新飞书多维表格榜单快照时使用。"
---

# 子 Skill: amazon-bsr-crawl

采集 Amazon Best Sellers 榜单数据并写入飞书多维表格。

> **前置文档**：先阅读 [`../environment-setup.md`](../environment-setup.md) 和 [`../feishu-table-schema.md`](../feishu-table-schema.md)。

## 触发方式

- **定时触发**：飞书自动化每周一 09:00 → Webhook → 调用 `scripts/crawl.py`
- **手动触发**：`python3 scripts/crawl.py`
- **单类目触发**：`python3 scripts/crawl.py --category "Kitchen & Dining"`

## 执行流程

```
1. 读取飞书「类目管理」表
   → 筛选「是否启用」=True 的类目
   → 解析每个类目的「抓取URL」

2. 对每个类目（双通道采集）：
   a. 主通道：keepa-mcp
      - 从 URL 解析 Amazon browseNode ID 作为 category_id
      - 调用 keepa-mcp get_best_sellers(category_id, domain="US", limit=100)
      - 对每个 ASIN 调用 get_product(asin) 获取详情
   b. 兜底通道：agent-browser
      - 当 keepa-mcp 返回空或失败时降级
      - 通过 Skill 环境注入的 browser_crawl_func 访问页面
      - 用 scripts/browser_crawler.py 的 parse_bestseller_page() 解析 HTML

3. 写入飞书多维表格
   - 「榜单快照」表：每次新增 100 条（保留历史）
   - 「商品详情」表：upsert 模式
     - 已存在的 ASIN：更新价格/评分/评论数
     - 不存在的 ASIN：新增
```

## 关键脚本

| 文件 | 职责 |
|---|---|
| [scripts/crawl.py](../../scripts/crawl.py) | 采集编排主入口 |
| [scripts/keepa_client.py](../../scripts/keepa_client.py) | keepa-mcp 持久化子进程封装 |
| [scripts/browser_crawler.py](../../scripts/browser_crawler.py) | agent-browser 兜底采集 + HTML 解析 |

## 使用示例

### 示例 1：定时全量采集

```bash
python3 scripts/crawl.py
```

输出示例：

```json
{
  "status": "ok",
  "total": 95,
  "snapshot_date": "2026-07-20",
  "categories": [
    {"category": "Kitchen & Dining", "count": 95, "status": "ok"},
    {"category": "PC", "count": 0, "status": "failed", "error": "keepa-mcp 和 agent-browser 均未返回数据"}
  ]
}
```

### 示例 2：在 agent 客户端中降级到浏览器

agent 客户端注入 `browser_crawl_func` 函数：

```python
from scripts.crawl import CrawlOrchestrator
from scripts.feishu_client import FeishuClient
from scripts.keepa_client import KeepaClient

def my_browser_crawl(url: str) -> str:
    # 调用 agent-browser Skill 或 Playwright 等
    return html_content

orchestrator = CrawlOrchestrator(
    feishu=feishu_client,
    keepa=keepa_client,
    categories_table_id="tblXXX",
    snapshots_table_id="tblXXX",
    products_table_id="tblXXX",
    browser_crawl_func=my_browser_crawl,  # 注入降级函数
)
result = orchestrator.run()
```

## URL → category_id 解析规则

支持的 Amazon URL 格式：

| URL 模式 | 示例 | 解析结果 |
|---|---|---|
| `/gp/bestsellers/{id}` | `/gp/bestsellers/12345` | 12345 |
| `/bestsellers/{slug}/{id}` | `/bestsellers/kitchen/67890` | 67890 |
| `/zg_bs/{slug}/{id}` | `/zg_bs/kitchen/11111` | 11111 |
| URL 中含 4-10 位数字 | `.../pc/541966?...` | 541966（兜底） |

解析失败（无数字 ID）→ 跳过该类目并记录告警。

## 错误处理

| 场景 | 处理 |
|---|---|
| keepa-mcp 不可用 | 自动降级到 agent-browser |
| keepa-mcp 429 频率限制 | 等待重试（由 keepa_client 处理） |
| 某 ASIN 详情失败 | 部分字段为空写入，不影响其他 ASIN |
| 飞书 API 429 | 指数退避重试 3 次 |
| 整个类目采集失败 | 记录失败原因到结果，继续下一个类目 |

## 性能参考

- 单个类目 Top100 采集约 2-5 分钟（keepa-mcp 主通道）
- agent-browser 降级采集约 5-10 分钟
- 5 个类目全量采集约 15-30 分钟

## 独立化建议

未来如果需要将本子 Skill 独立为单独的 Skill 包，操作步骤：

1. 复制本目录到 `skills/amazon-bsr-crawl/`
2. 创建独立的 `SKILL.md`（参考 [lark-skill-maker](https://github.com/larksuite/lark-cli) 模板）
3. 在主 Skill 的 `SKILL.md` 中改为通过相对路径引用：`../amazon-bsr-crawl/SKILL.md`
4. 更新 `scripts/` 路径或保持共享
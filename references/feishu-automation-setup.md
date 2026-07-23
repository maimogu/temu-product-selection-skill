# 飞书自动化流程配置

本 Skill 的 3 个自动化流程在飞书多维表格 UI 中手动配置。配置完成后，飞书会在指定时间自动触发脚本。

## 自动化流程 1：定时采集（每周一 09:00）

**目的**：每周一自动触发 `crawl.py` 采集 Amazon Best Sellers。

**配置步骤**：

1. 进入飞书多维表格 Base
2. 点击右上角「自动化」 → 「新建流程」
3. 触发条件：定时触发 → 每周一 09:00
4. 执行动作：发送 HTTP 请求
   - 方法：POST
   - URL：`http://<your-server>:8000/crawl/trigger`
   - Headers：`Content-Type: application/json`
   - Body：`{}`
5. 保存并启用

**预期响应**：

```json
{
  "status": "ok",
  "total": 95,
  "snapshot_date": "2026-07-20",
  "categories": [
    {"category": "Kitchen & Dining", "count": 95, "status": "ok"}
  ]
}
```

---

## 自动化流程 2：定时计算指标（每周一 10:00）

**目的**：采集完成 1 小时后自动计算五维指标得分。

**配置步骤**：

1. 新建流程
2. 触发条件：定时触发 → 每周一 10:00
3. 执行动作：发送 HTTP 请求
   - 方法：POST
   - URL：`http://<your-server>:8000/metrics/calculate`
   - Headers：`Content-Type: application/json`
   - Body：`{}`
4. 保存并启用

**预期响应**：

```json
{
  "status": "ok",
  "total": 95,
  "top10": [
    {"asin": "B000000001", "composite": 92.5},
    {"asin": "B000000005", "composite": 88.3}
  ]
}
```

---

## 自动化流程 3：侵权风险告警（实时触发）

**目的**：当指标得分表中新增记录且风险得分 < 30 时，立即发送飞书消息。

**配置步骤**：

1. 新建流程
2. 触发条件：记录新增或修改满足条件时
   - 数据表：指标得分
   - 条件：`风险得分 < 30`
3. 执行动作：发送飞书消息
   - 接收人：法务组、采购组
   - 消息内容模板：

```
⚠️ 侵权风险告警

商品 ASIN：{ASIN}
品牌：{供应商信息}
风险得分：{风险得分}/100
综合得分：{综合得分}/100
计算时间：{计算时间}

请法务/采购确认是否需要下架或暂停采购。
```

4. 保存并启用

---

## 自动化流程 4：高风险高排名商品复查（每周一 10:30）

**目的**：识别"综合得分高但风险得分低"的商品，提醒运营复查。

**配置步骤**：

1. 新建流程
2. 触发条件：定时触发 → 每周一 10:30
3. 执行动作：发送飞书消息
   - 接收人：运营
   - 消息内容模板：

```
🔍 高排名但风险商品复查

本周共有 {n} 个商品综合得分 > 70 但风险得分 < 50，请复查：
- {ASIN_1} 综合得分 {score_1} 风险得分 {risk_1}
- {ASIN_2} 综合得分 {score_2} 风险得分 {risk_2}
...

完整列表请查看「指标得分」表视图。
```

4. 保存并启用

---

## 自动化流程 5：采集失败告警（Webhook 触发）

**目的**：当 Python 脚本采集失败时主动推送告警。

**配置步骤**：

1. 新建流程
2. 触发条件：Webhook 接收
   - 复制生成的 Webhook URL，配置到 Python 脚本的环境变量 `FAILURE_WEBHOOK_URL`
3. 执行动作：发送飞书消息
   - 接收人：运营
   - 消息内容：

```
❌ 采集失败

类目：{category}
时间：{timestamp}
错误：{error}

请检查 keepa-mcp 服务状态或网络连接。
```

4. 保存并启用

**Python 脚本侧的触发代码**（已内置在 `crawl.py` 错误处理逻辑中）：

```python
import httpx
httpx.post(
    os.environ["FAILURE_WEBHOOK_URL"],
    json={"category": cat_name, "timestamp": now, "error": str(e)}
)
```

---

## HTTP 服务部署说明

飞书自动化流程 1、2、5 依赖一个能接收 HTTP 请求的服务。推荐部署方式：

### 方案 A：FastAPI 简单包装（推荐）

将 `crawl.py` 和 `metrics.py` 包装为 HTTP 服务：

```python
# server.py（可选，未在 scripts/ 中默认提供）
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import subprocess

app = FastAPI()

@app.post("/crawl/trigger")
def trigger_crawl():
    result = subprocess.run(
        ["python3", "scripts/crawl.py"],
        capture_output=True, text=True, timeout=600
    )
    if result.returncode == 0:
        return JSONResponse(result.stdout, status_code=200)
    return JSONResponse({"error": result.stderr}, status_code=500)

@app.post("/metrics/calculate")
def trigger_metrics():
    result = subprocess.run(
        ["python3", "scripts/metrics.py"],
        capture_output=True, text=True, timeout=300
    )
    if result.returncode == 0:
        return JSONResponse(result.stdout, status_code=200)
    return JSONResponse({"error": result.stderr}, status_code=500)
```

启动：`uvicorn server:app --host 0.0.0.0 --port 8000`

### 方案 B：直接用 crontab

不部署 HTTP 服务，改用系统 crontab：

```cron
# 每周一 09:00 采集
0 9 * * 1 cd /path/to/skill && python3 scripts/crawl.py >> /var/log/crawl.log 2>&1

# 每周一 10:00 计算指标
0 10 * * 1 cd /path/to/skill && python3 scripts/metrics.py >> /var/log/metrics.log 2>&1
```

此时仅自动化流程 3、4 有效（这两者不依赖外部 HTTP 服务）。
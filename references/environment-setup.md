# 环境变量与依赖配置

## 系统依赖

| 依赖 | 用途 | 安装方式 |
|---|---|---|
| Python ≥ 3.10 | 运行脚本 | `apt install python3` 或 `brew install python@3.12` |
| `npx` (Node.js) | 启动 keepa-mcp 子进程 | `apt install nodejs npm` 或 `brew install node` |
| `bash` ≥ 4.0 | 运行 bootstrap.sh | 系统自带 |

## 虚拟环境（自动管理）

本 Skill 不携带内置 Python 运行时，由 `bootstrap.sh` 自动管理虚拟环境：

- **首次运行**：自动创建 `.venv/` 虚拟环境，从 `requirements.txt` 安装依赖
- **后续运行**：检测到 `.venv/` 已存在，直接复用，秒级启动
- **依赖变更**：若 `requirements.txt` 有更新，下次运行时自动同步

```bash
# 首次运行（自动创建 venv + 安装依赖）
bash bootstrap.sh check
```

## 环境变量

所有环境变量必须配置，否则脚本会拒绝启动：

| 变量名 | 必填 | 说明 | 获取方式 |
|---|---|---|---|
| `FEISHU_APP_ID` | 是 | 飞书自建应用 App ID | 飞书开放平台 → 开发者后台 → 应用详情 |
| `FEISHU_APP_SECRET` | 是 | 飞书自建应用 App Secret | 同上 |
| `FEISHU_APP_TOKEN` | 是 | 多维表格 Base 的 app_token | 多维表格 URL 中 `https://xxx.feishu.cn/base/{app_token}` |
| `FEISHU_CATEGORIES_TABLE_ID` | 是 | 类目管理表 table_id | 多维表格 URL 中 `?table={table_id}` |
| `FEISHU_SNAPSHOTS_TABLE_ID` | 是 | 榜单快照表 table_id | 同上 |
| `FEISHU_PRODUCTS_TABLE_ID` | 是 | 商品详情表 table_id | 同上 |
| `FEISHU_METRICS_TABLE_ID` | 是 | 指标得分表 table_id | 同上 |
| `KEEPA_API_KEY` | 否 | keepa.com API Key | https://keepa.com/#!amazon › API keys |

## 配置示例

将以下内容保存为 `.env` 并 `source .env`：

```bash
export FEISHU_APP_ID="cli_aXXXXXXXXXXXXX"
export FEISHU_APP_SECRET="XXXXXXXXXXXXXXXXXXXXXXXX"
export FEISHU_APP_TOKEN="bascnXXXXXXXXXXXXXXXXXX"
export FEISHU_CATEGORIES_TABLE_ID="tblXXXXXXXX"
export FEISHU_SNAPSHOTS_TABLE_ID="tblXXXXXXXX"
export FEISHU_PRODUCTS_TABLE_ID="tblXXXXXXXX"
export FEISHU_METRICS_TABLE_ID="tblXXXXXXXX"
export KEEPA_API_KEY="XXXXXXXXXXXXXXXXXXXXXXXX"
```

## 飞书应用权限

应用需要在飞书开放平台开通以下权限：

| 权限 | 用途 |
|---|---|
| `bitable:app` | 读写多维表格 Base |
| `bitable:app:readonly` | 读取多维表格（最小权限模式） |

应用必须被添加为目标多维表格的协作者（至少「可编辑」权限）。

## 验证配置

```bash
# 检查运行时和依赖
bash bootstrap.sh check

# 运行测试
bash bootstrap.sh test
```

## 飞书多维表格创建

如果尚未创建多维表格，参考 [feishu-table-schema.md](feishu-table-schema.md) 中的字段定义手动创建。
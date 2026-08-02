"""HTML 报告渲染器（Jinja2）。

模板内联在本文件中，避免外部模板路径依赖，部署简单。
"""

from datetime import datetime
from typing import List, Dict, Any

from jinja2 import Template


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>选品决策报告 - {{ category }} - {{ cycle }}</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif; margin: 0; padding: 24px; background: #f5f7fa; color: #1f2937; }
  h1 { font-size: 24px; margin: 0 0 8px; }
  .meta { color: #6b7280; font-size: 13px; margin-bottom: 24px; }
  .cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 32px; }
  .card { background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
  .card .label { font-size: 12px; color: #6b7280; }
  .card .value { font-size: 28px; font-weight: 600; margin-top: 4px; }
  .card .sub { font-size: 12px; color: #6b7280; margin-top: 4px; }
  .go .value { color: #10b981; }
  .watch .value { color: #f59e0b; }
  .nogo .value { color: #ef4444; }
  table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.06); font-size: 13px; }
  th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #f3f4f6; }
  th { background: #f9fafb; font-weight: 600; color: #374151; }
  tr:hover { background: #f9fafb; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600; }
  .badge-go { background: #d1fae5; color: #065f46; }
  .badge-watch { background: #fef3c7; color: #92400e; }
  .badge-nogo { background: #fee2e2; color: #991b1b; }
  .empty { text-align: center; padding: 32px; color: #9ca3af; }
  .reason { color: #6b7280; font-size: 12px; }
  .footer { margin-top: 24px; font-size: 12px; color: #9ca3af; text-align: center; }
</style>
</head>
<body>
  <h1>选品决策报告</h1>
  <div class="meta">类目：{{ category }} | 周期：{{ cycle }} | 生成时间：{{ generated_at }}</div>

  <div class="cards">
    <div class="card"><div class="label">商品总数</div><div class="value">{{ total }}</div></div>
    <div class="card go"><div class="label">GO 推荐</div><div class="value">{{ go_count }}</div><div class="sub">{{ go_pct }}%</div></div>
    <div class="card watch"><div class="label">WATCH 观察</div><div class="value">{{ watch_count }}</div><div class="sub">{{ watch_pct }}%</div></div>
    <div class="card nogo"><div class="label">NO-GO 不推荐</div><div class="value">{{ nogo_count }}</div><div class="sub">{{ nogo_pct }}%</div></div>
  </div>

  <h2 style="font-size:18px;margin:24px 0 12px;">决策明细</h2>
  {% if rows %}
  <table>
    <thead>
      <tr>
        <th>ASIN</th>
        <th>决策</th>
        <th>综合得分</th>
        <th>风险得分</th>
        <th>利润率</th>
        <th>原因</th>
        <th>失败原因</th>
      </tr>
    </thead>
    <tbody>
      {% for r in rows %}
      <tr>
        <td>{{ r.asin }}</td>
        <td><span class="badge badge-{{ r.decision|lower }}">{{ r.decision }}</span></td>
        <td>{{ r.composite_score }}</td>
        <td>{{ r.risk_score }}</td>
        <td>{{ r.profit_margin_text }}</td>
        <td class="reason">{{ r.reason }}</td>
        <td class="reason">{{ r.failure_reason }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <div class="empty">暂无决策数据</div>
  {% endif %}

  <div class="footer">由 amazon-product-selection Skill 自动生成</div>
</body>
</html>
"""


def _format_margin(margin):
    """格式化利润率显示。"""
    if margin is None:
        return "—"
    return f"{margin*100:.1f}%"


def render_html(
    rows: List[Dict[str, Any]],
    category: str = "全部类目",
    cycle: str = "本周",
    output_path: str = None,
) -> str:
    """渲染 HTML 报告并写盘。

    Args:
        rows: 决策明细行，每行应含 asin/decision/composite_score/risk_score/profit_margin/reason/failure_reason
        category: 类目名称
        cycle: 周期标签
        output_path: 输出文件路径，为空则仅返回 HTML 字符串

    Returns:
        HTML 字符串
    """
    total = len(rows)
    go_count = sum(1 for r in rows if r.get("decision") == "GO")
    watch_count = sum(1 for r in rows if r.get("decision") == "WATCH")
    nogo_count = sum(1 for r in rows if r.get("decision") == "NO-GO")

    def pct(n):
        return f"{(n/total*100):.1f}" if total else "0.0"

    # 预处理行数据：格式化利润率
    rendered_rows = []
    for r in rows:
        rendered_rows.append({
            **r,
            "profit_margin_text": _format_margin(r.get("profit_margin")),
        })

    html = Template(HTML_TEMPLATE).render(
        category=category,
        cycle=cycle,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        total=total,
        go_count=go_count,
        watch_count=watch_count,
        nogo_count=nogo_count,
        go_pct=pct(go_count),
        watch_pct=pct(watch_count),
        nogo_pct=pct(nogo_count),
        rows=rendered_rows,
    )

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

    return html

#!/usr/bin/env bash
# =============================================================================
# amazon-product-selection Skill 启动脚本
#
# 首次运行时自动创建 venv 并安装依赖，后续运行复用已有 venv。
# 需要目标机器安装 Python 3.10+。
#
# 用法:
#   bash bootstrap.sh crawl      # 采集榜单
#   bash bootstrap.sh metrics    # 计算指标
#   bash bootstrap.sh keywords   # 关键词调研
#   bash bootstrap.sh profit     # FBA利润计算
#   bash bootstrap.sh task       # 任务编排（采集→指标→利润→决策→报告）
#   bash bootstrap.sh test       # 运行测试
#   bash bootstrap.sh python -- script.py [args]  # 直接运行 Python 脚本
# =============================================================================
set -euo pipefail

# --- 自动定位 Skill 根目录 ---
SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SKILL_ROOT/.venv"
SCRIPTS_DIR="$SKILL_ROOT/scripts"
REQUIREMENTS="$SKILL_ROOT/requirements.txt"

# --- 查找系统 Python 3.10+ ---
find_python() {
    for candidate in python3 python python3.14 python3.13 python3.12 python3.11 python3.10; do
        if command -v "$candidate" &>/dev/null; then
            local ver
            ver="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")"
            local major minor
            major="${ver%%.*}"
            minor="${ver#*.}"
            if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
                echo "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

SYSTEM_PYTHON="$(find_python)" || {
    echo "[ERROR] 未找到 Python 3.10+，请安装 Python 3.10 或更高版本。" >&2
    exit 1
}

# --- 首次运行：创建 venv 并安装依赖 ---
setup_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        echo "[INFO] 首次运行，正在创建虚拟环境..." >&2
        "$SYSTEM_PYTHON" -m venv --clear "$VENV_DIR"
        echo "[INFO] 正在安装依赖..." >&2
        "$VENV_DIR/bin/pip" install --quiet -r "$REQUIREMENTS"
        echo "[INFO] 虚拟环境初始化完成。" >&2
    fi
}

# --- 确保 venv 依赖与 requirements.txt 同步 ---
sync_deps() {
    local installed req_hash current_hash
    installed="$("$VENV_DIR/bin/pip" freeze 2>/dev/null | sort)"
    req_hash="$(echo "$installed" | md5sum | cut -d' ' -f1)"
    current_hash="$(cat "$VENV_DIR/.deps_hash" 2>/dev/null || echo "")"
    if [ "$req_hash" != "$current_hash" ]; then
        echo "[INFO] 依赖已更新，正在同步..." >&2
        "$VENV_DIR/bin/pip" install --quiet -r "$REQUIREMENTS"
        echo "$req_hash" > "$VENV_DIR/.deps_hash"
    fi
}

setup_venv
sync_deps

# --- venv Python ---
RT_PYTHON="$VENV_DIR/bin/python"
export PYTHONPATH="$SCRIPTS_DIR${PYTHONPATH:+:$PYTHONPATH}"

# --- 命令分发 ---
case "${1:-}" in
    crawl)
        shift
        exec "$RT_PYTHON" "$SCRIPTS_DIR/crawl.py" "$@"
        ;;
    metrics)
        shift
        exec "$RT_PYTHON" "$SCRIPTS_DIR/metrics.py" "$@"
        ;;
    keywords)
        shift
        exec "$RT_PYTHON" "$SCRIPTS_DIR/keyword_research.py" "$@"
        ;;
    profit)
        shift
        exec "$RT_PYTHON" "$SCRIPTS_DIR/profit_calc.py" "$@"
        ;;
    task)
        shift
        exec "$RT_PYTHON" "$SCRIPTS_DIR/task_orchestrator.py" "$@"
        ;;
    test)
        shift
        cd "$SKILL_ROOT"
        exec "$RT_PYTHON" -m pytest tests/ -v "$@"
        ;;
    python)
        shift
        exec "$RT_PYTHON" "$@"
        ;;
    check)
        echo "=== 运行时信息 ==="
        echo "Skill 根目录: $SKILL_ROOT"
        echo "系统 Python: $SYSTEM_PYTHON"
        echo "Python 版本: $($RT_PYTHON --version 2>&1)"
        echo "venv 路径: $VENV_DIR"
        echo ""
        echo "=== 依赖检查 ==="
        $RT_PYTHON -c "
import sys
print(f'Python: {sys.version}')
modules = ['httpx', 'yaml', 'pytest', 'lark_oapi', 'jinja2', 'openpyxl']
for m in modules:
    try:
        __import__(m)
        print(f'  {m}: OK')
    except ImportError:
        print(f'  {m}: MISSING')
"
        echo ""
        echo "=== 环境变量检查 ==="
        for var in FEISHU_APP_ID FEISHU_APP_SECRET FEISHU_APP_TOKEN KEEPA_API_KEY; do
            if [ -n "${!var:-}" ]; then
                echo "  $var: 已配置"
            else
                echo "  $var: 未配置 (需要采集/指标计算时配置)"
            fi
        done
        ;;
    *)
        echo "用法: bash bootstrap.sh <command> [args]"
        echo ""
        echo "命令:"
        echo "  crawl       采集 Amazon Best Sellers 榜单数据"
        echo "  metrics     计算五维指标综合得分"
        echo "  keywords    关键词调研与8维分类"
        echo "  profit      FBA利润计算"
        echo "  task        任务编排（采集→指标→利润→决策→报告）"
        echo "  test        运行测试 (pytest tests/ -v)"
        echo "  check       检查运行时环境和依赖"
        echo "  python --   <script.py> [args]  直接运行 Python 脚本"
        echo ""
        echo "示例:"
        echo "  bash bootstrap.sh crawl"
        echo "  bash bootstrap.sh metrics"
        echo "  bash bootstrap.sh keywords"
        echo "  bash bootstrap.sh profit"
        echo "  bash bootstrap.sh task --skip-crawl"
        echo "  bash bootstrap.sh test"
        echo "  bash bootstrap.sh check"
        exit 1
        ;;
esac
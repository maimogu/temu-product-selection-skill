"""pytest 配置：将 scripts/ 加入 sys.path。

让测试可以通过 `from scripts.crawl import ...` 或 `from crawl import ...` 导入模块。
scripts/ 内部脚本用 `from feishu_client import ...`（同目录相对导入），
因此需要将 scripts 目录加入 sys.path。
"""
import os
import sys

_SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

"""关键词采集与分类模块。

从 keepa-mcp 获取关键词数据，按 8 维分类体系进行智能分类，
输出结构化关键词库，写入飞书多维表格。

纯函数 + 分类引擎，IO 由调用方管理。
"""

import re
import os
import yaml
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class KeywordEntry:
    """单个关键词条目。"""
    keyword: str
    category_tag: str = ""
    category_name: str = ""
    search_volume_level: int = 0    # 1-5 搜索量级
    competition_level: int = 0      # 1-5 竞争度
    asin_count: int = 0             # 关联 ASIN 数
    seasonal: bool = False          # 是否季节性


class KeywordClassifier:
    """关键词 8 维分类器。

    从 config/keyword_categories.yaml 加载规则，按优先级匹配。
    """

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "config", "keyword_categories.yaml"
            )
        self._load_config(config_path)

    def _load_config(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        self.categories = []
        for cat in config["categories"]:
            compiled = [re.compile(p, re.IGNORECASE) for p in cat["patterns"]]
            self.categories.append({
                "name": cat["name"],
                "tag": cat["tag"],
                "patterns": compiled,
            })

    def classify(self, keyword: str) -> Tuple[str, str]:
        """对单个关键词分类。

        Returns:
            (tag, name): 分类标签和中文名。未匹配返回 ("other", "其他")
        """
        if not keyword or not keyword.strip():
            return ("other", "其他")
        kw = keyword.strip().lower()
        for cat in self.categories:
            for pat in cat["patterns"]:
                if pat.search(kw):
                    return (cat["tag"], cat["name"])
        return ("other", "其他")

    def classify_batch(self, keywords: List[str]) -> Dict[str, List[KeywordEntry]]:
        """批量分类，按 tag 分组返回。"""
        groups: Dict[str, List[KeywordEntry]] = {}
        for kw in keywords:
            tag, name = self.classify(kw)
            entry = KeywordEntry(keyword=kw, category_tag=tag, category_name=name)
            groups.setdefault(tag, []).append(entry)
        return groups


def estimate_search_volume(keyword: str, word_count: int) -> int:
    """根据关键词长度估算搜索量级（1-5）。

    长尾词搜索量通常更低。
    """
    words = keyword.split()
    n = len(words)
    if n <= 1:
        return 5
    elif n == 2:
        return 4
    elif n == 3:
        return 3
    elif n == 4:
        return 2
    else:
        return 1


def estimate_competition(asin_count: int) -> int:
    """根据关联 ASIN 数估算竞争度（1-5）。"""
    if asin_count == 0:
        return 1
    if asin_count <= 10:
        return 2
    if asin_count <= 50:
        return 3
    if asin_count <= 200:
        return 4
    return 5


def detect_seasonality(keyword: str) -> bool:
    """检测关键词是否具有季节性特征。"""
    seasonal_patterns = [
        r"christmas", r"halloween", r"thanksgiving", r"valentine",
        r"easter", r"mothers?\s?day", r"fathers?\s?day",
        r"summer", r"winter", r"spring", r"autumn", r"fall",
        r"back\s?to\s?school", r"black\s?friday", r"prime\s?day",
        r"holiday", r"gift\s?for", r"stocking\s?stuffer",
        r"snow", r"beach", r"pool", r"graduation",
    ]
    kw_lower = keyword.lower()
    return any(re.search(p, kw_lower) for p in seasonal_patterns)


def generate_ad_groups(classified: Dict[str, List[KeywordEntry]]) -> Dict[str, List[str]]:
    """根据分类结果生成广告投放建议分组。

    Returns:
        {
            "negative": [...],       # 否定词清单
            "exact_match": [...],    # 精准匹配组（品牌词 + 核心词）
            "broad_match": [...],    # 广泛匹配组（功能词 + 场景词）
            "scenario_ads": [...],   # 场景广告组
        }
    """
    ad_groups = {
        "negative": [],
        "exact_match": [],
        "broad_match": [],
        "scenario_ads": [],
    }

    for tag, entries in classified.items():
        keywords = [e.keyword for e in entries]
        if tag == "negative":
            ad_groups["negative"].extend(keywords)
        elif tag in ("brand", "core"):
            ad_groups["exact_match"].extend(keywords)
        elif tag == "scenario":
            ad_groups["scenario_ads"].extend(keywords)
        elif tag in ("function", "attribute", "material"):
            ad_groups["broad_match"].extend(keywords)

    return ad_groups


def build_keyword_table(classified: Dict[str, List[KeywordEntry]]) -> List[Dict]:
    """构建飞书多维表格写入用的记录列表。

    每个记录包含：关键词、分类标签、分类名、搜索量级、竞争度、季节性。
    """
    records = []
    for entries in classified.values():
        for entry in entries:
            records.append({
                "keyword": entry.keyword,
                "category_tag": entry.category_tag,
                "category_name": entry.category_name,
                "search_volume_level": entry.search_volume_level,
                "competition_level": entry.competition_level,
                "seasonal": "是" if entry.seasonal else "否",
            })
    return records
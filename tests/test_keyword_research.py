"""测试 keyword_research 模块 — 关键词分类与处理。"""

import pytest
from keyword_research import (
    KeywordClassifier,
    KeywordEntry,
    estimate_search_volume,
    estimate_competition,
    detect_seasonality,
    generate_ad_groups,
    build_keyword_table,
)


class TestKeywordClassifier:
    """测试 8 维分类器。"""

    @pytest.fixture
    def classifier(self):
        return KeywordClassifier()

    def test_classify_negative(self, classifier):
        tag, name = classifier.classify("cheap kitchen knife")
        assert tag == "negative"
        assert name == "否定词"

    def test_classify_brand(self, classifier):
        tag, name = classifier.classify("nike running shoes")
        assert tag == "brand"
        assert name == "品牌词"

    def test_classify_material(self, classifier):
        tag, name = classifier.classify("stainless steel water bottle")
        assert tag == "material"
        assert name == "材质词"

    def test_classify_scenario(self, classifier):
        tag, name = classifier.classify("camping tent")
        assert tag == "scenario"
        assert name == "场景词"

    def test_classify_attribute(self, classifier):
        tag, name = classifier.classify("portable bluetooth speaker")
        assert tag == "attribute"
        assert name == "属性词"

    def test_classify_function(self, classifier):
        tag, name = classifier.classify("vegetable cutter")
        assert tag == "function"
        assert name == "功能词"

    def test_classify_core(self, classifier):
        tag, name = classifier.classify("spatula")
        assert tag == "core"
        assert name == "核心词"

    def test_classify_other(self, classifier):
        tag, name = classifier.classify("xyzabc123")
        assert tag == "other"
        assert name == "其他"

    def test_classify_empty(self, classifier):
        tag, name = classifier.classify("")
        assert tag == "other"
        assert name == "其他"

    def test_classify_none(self, classifier):
        tag, name = classifier.classify("  ")
        assert tag == "other"
        assert name == "其他"

    def test_classify_case_insensitive(self, classifier):
        tag, name = classifier.classify("NIKE AIR MAX")
        assert tag == "brand"
        assert name == "品牌词"

    def test_classify_priority_brand_over_other(self, classifier):
        # "apple" 同时匹配品牌词和核心词，品牌词优先级更高
        tag, name = classifier.classify("apple")
        assert tag == "brand"
        assert name == "品牌词"


class TestKeywordProcessing:
    """测试关键词处理函数。"""

    def test_estimate_search_volume_short(self):
        assert estimate_search_volume("blender", 1) == 5

    def test_estimate_search_volume_two_words(self):
        assert estimate_search_volume("portable blender", 2) == 4

    def test_estimate_search_volume_three_words(self):
        assert estimate_search_volume("portable blender smoothie", 3) == 3

    def test_estimate_search_volume_five_words(self):
        assert estimate_search_volume("best portable blender for smoothies", 5) == 1

    def test_estimate_competition_zero(self):
        assert estimate_competition(0) == 1

    def test_estimate_competition_low(self):
        assert estimate_competition(8) == 2

    def test_estimate_competition_medium(self):
        assert estimate_competition(30) == 3

    def test_estimate_competition_high(self):
        assert estimate_competition(150) == 4

    def test_estimate_competition_very_high(self):
        assert estimate_competition(500) == 5

    def test_detect_seasonality_christmas(self):
        assert detect_seasonality("christmas gift box") is True

    def test_detect_seasonality_halloween(self):
        assert detect_seasonality("halloween decorations") is True

    def test_detect_seasonality_non_seasonal(self):
        assert detect_seasonality("kitchen knife set") is False

    def test_detect_seasonality_summer(self):
        assert detect_seasonality("summer dress") is True


class TestAdGroups:
    """测试广告分组建议。"""

    def test_generate_ad_groups(self):
        classified = {
            "negative": [KeywordEntry(keyword="cheap blender")],
            "brand": [KeywordEntry(keyword="ninja blender")],
            "core": [KeywordEntry(keyword="blender")],
            "function": [KeywordEntry(keyword="smoothie maker")],
            "scenario": [KeywordEntry(keyword="kitchen blender")],
            "attribute": [KeywordEntry(keyword="portable blender")],
            "material": [KeywordEntry(keyword="stainless steel blender")],
        }
        groups = generate_ad_groups(classified)
        assert "cheap blender" in groups["negative"]
        assert "ninja blender" in groups["exact_match"]
        assert "blender" in groups["exact_match"]
        assert "kitchen blender" in groups["scenario_ads"]
        assert "smoothie maker" in groups["broad_match"]
        assert "portable blender" in groups["broad_match"]
        assert "stainless steel blender" in groups["broad_match"]


class TestBuildKeywordTable:
    """测试飞书表格构建。"""

    def test_build_keyword_table(self):
        classified = {
            "core": [KeywordEntry(
                keyword="blender", category_tag="core",
                category_name="核心词", search_volume_level=5,
                competition_level=3, seasonal=False,
            )],
            "negative": [KeywordEntry(
                keyword="cheap blender", category_tag="negative",
                category_name="否定词", search_volume_level=2,
                competition_level=1, seasonal=False,
            )],
        }
        records = build_keyword_table(classified)
        assert len(records) == 2
        assert records[0]["keyword"] == "blender"
        assert records[0]["category_tag"] == "core"
        assert records[0]["search_volume_level"] == 5
        assert records[0]["seasonal"] == "否"
        assert records[1]["keyword"] == "cheap blender"
        assert records[1]["category_tag"] == "negative"
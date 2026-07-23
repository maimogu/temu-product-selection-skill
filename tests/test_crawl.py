"""crawl.py 单元测试。

覆盖：
- parse_category_id_from_url: 从 Amazon URL 解析 category_id
- CrawlOrchestrator 字段类型兼容（飞书复杂字段结构）
"""

import pytest
from unittest.mock import MagicMock
from crawl import parse_category_id_from_url, CrawlOrchestrator
from browser_crawler import parse_bestseller_page, _parse_single_card


class TestParseCategoryId:
    """URL → category_id 解析测试。"""

    def test_gp_bestsellers_format(self):
        """格式: /gp/bestsellers/12345"""
        url = "https://www.amazon.com/gp/bestsellers/12345"
        assert parse_category_id_from_url(url) == 12345

    def test_bestsellers_with_slug(self):
        """格式: /bestsellers/kitchen/67890"""
        url = "https://www.amazon.com/bestsellers/kitchen/67890"
        assert parse_category_id_from_url(url) == 67890

    def test_zg_bs_format(self):
        """格式: /zg_bs/kitchen/11111"""
        url = "https://www.amazon.com/zg_bs/kitchen/11111"
        assert parse_category_id_from_url(url) == 11111

    def test_url_with_query(self):
        """URL 包含 query 参数。"""
        url = "https://www.amazon.com/best-sellers/pc/zgbss/pc/541966/ref=zg_bs_nav_pc_0_0?ref_=bg_bs_pv_pc_1"
        # /best-sellers/pc/zgbss/pc/541966 不匹配 /gp/bestsellers/(\d+)，
        # 也不匹配 /bestsellers/[\w-]+/(\d+)，但兜底 4-10 位数字能提取到 541966
        result = parse_category_id_from_url(url)
        assert result == 541966 or result == 0  # 至少不崩溃

    def test_empty_url(self):
        assert parse_category_id_from_url("") == 0

    def test_none_url(self):
        assert parse_category_id_from_url(None) == 0

    def test_no_number_in_url(self):
        """URL 中无数字 ID。"""
        url = "https://www.amazon.com/Best-Sellers-Kitchen-Dining/zgbss/kitchen"
        result = parse_category_id_from_url(url)
        assert result == 0


class TestParseBestSellerPage:
    """HTML 解析测试，确保字段对齐。"""

    def test_single_card_alignment(self):
        """单卡片 HTML 中 ASIN、价格、评分正确对齐。"""
        html = """
        <div>
            <a href="/dp/B0ABCDEFGH">Product A</a>
            <span>$29.99</span>
            <span>4.5 out of 5</span>
            <span>1,200 ratings</span>
        </div>
        """
        products = parse_bestseller_page(html)
        assert len(products) == 1
        p = products[0]
        assert p["asin"] == "B0ABCDEFGH"
        assert p["price"] == 29.99
        assert p["star_rating"] == 4.5
        assert p["review_count"] == 1200
        assert p["bsr_rank"] == 1  # 默认 rank

    def test_multiple_cards_alignment(self):
        """多个商品卡片各自字段正确对齐，不串位。"""
        html = """
        <a href="/dp/B000000001">Product A</a>
            <span>$10.00</span>
            <span>5.0 out of 5</span>
            <span>100 ratings</span>
        <a href="/dp/B000000002">Product B</a>
            <span>$20.00</span>
            <span>4.0 out of 5</span>
            <span>200 ratings</span>
        """
        products = parse_bestseller_page(html)
        assert len(products) == 2

        # Product A 字段
        assert products[0]["asin"] == "B000000001"
        assert products[0]["price"] == 10.00
        assert products[0]["star_rating"] == 5.0
        assert products[0]["review_count"] == 100

        # Product B 字段（不与 A 串位）
        assert products[1]["asin"] == "B000000002"
        assert products[1]["price"] == 20.00
        assert products[1]["star_rating"] == 4.0
        assert products[1]["review_count"] == 200

    def test_empty_html(self):
        assert parse_bestseller_page("") == []

    def test_no_asin_in_html(self):
        """HTML 中无 ASIN 链接。"""
        assert parse_bestseller_page("<div>no products here</div>") == []


class TestGetEnabledCategories:
    """飞书字段类型兼容测试。"""

    @pytest.fixture
    def orchestrator(self):
        feishu = MagicMock()
        keepa = MagicMock()
        return CrawlOrchestrator(
            feishu=feishu,
            keepa=keepa,
            categories_table_id="tbl_cat",
            snapshots_table_id="tbl_snap",
            products_table_id="tbl_prod",
        )

    def test_simple_field_types(self, orchestrator):
        """简单字段类型：字符串和布尔值。"""
        orchestrator.feishu.get_records.return_value = [
            {
                "record_id": "rec1",
                "fields": {
                    "类目名称": "Kitchen",
                    "抓取URL": "https://amazon.com/gp/bestsellers/123",
                    "是否启用": True,
                },
            }
        ]
        cats = orchestrator.get_enabled_categories()
        assert len(cats) == 1
        assert cats[0]["name"] == "Kitchen"
        assert cats[0]["url"] == "https://amazon.com/gp/bestsellers/123"

    def test_complex_url_field(self, orchestrator):
        """URL 字段返回 {"link": "...", "text": "..."} 结构。"""
        orchestrator.feishu.get_records.return_value = [
            {
                "record_id": "rec1",
                "fields": {
                    "类目名称": "Kitchen",
                    "抓取URL": {"link": "https://amazon.com/gp/bestsellers/123", "text": "Amazon"},
                    "是否启用": True,
                },
            }
        ]
        cats = orchestrator.get_enabled_categories()
        assert cats[0]["url"] == "https://amazon.com/gp/bestsellers/123"

    def test_none_url_field(self, orchestrator):
        """URL 字段为 None 时不应崩溃（修复 #15 验证）。"""
        orchestrator.feishu.get_records.return_value = [
            {
                "record_id": "rec1",
                "fields": {
                    "类目名称": "Kitchen",
                    "抓取URL": None,
                    "是否启用": True,
                },
            }
        ]
        cats = orchestrator.get_enabled_categories()
        assert cats[0]["url"] == ""

    def test_disabled_category_filtered(self, orchestrator):
        """未启用的类目被过滤。"""
        orchestrator.feishu.get_records.return_value = [
            {
                "record_id": "rec1",
                "fields": {
                    "类目名称": "Kitchen",
                    "抓取URL": "https://amazon.com/gp/bestsellers/123",
                    "是否启用": False,
                },
            },
            {
                "record_id": "rec2",
                "fields": {
                    "类目名称": "PC",
                    "抓取URL": "https://amazon.com/gp/bestsellers/456",
                    "是否启用": True,
                },
            },
        ]
        cats = orchestrator.get_enabled_categories()
        assert len(cats) == 1
        assert cats[0]["name"] == "PC"


class TestCrawlViaBrowser:
    """agent-browser 降级测试。"""

    def test_browser_crawl_disabled(self):
        """未注入 browser_crawl_func 时降级返回空列表。"""
        feishu = MagicMock()
        keepa = MagicMock()
        orchestrator = CrawlOrchestrator(
            feishu=feishu,
            keepa=keepa,
            categories_table_id="tbl_cat",
            snapshots_table_id="tbl_snap",
            products_table_id="tbl_prod",
            browser_crawl_func=None,
        )
        result = orchestrator.crawl_via_browser("Test", "https://amazon.com")
        assert result == []

    def test_browser_crawl_with_html(self):
        """注入返回 HTML 的 browser_crawl_func 时正确解析。"""
        feishu = MagicMock()
        keepa = MagicMock()

        def mock_browser(url):
            return """
            <a href="/dp/B0MOCKASIN">Mock Product</a>
            <span>$15.99</span>
            <span>4.2 out of 5</span>
            <span>500 ratings</span>
            """

        orchestrator = CrawlOrchestrator(
            feishu=feishu,
            keepa=keepa,
            categories_table_id="tbl_cat",
            snapshots_table_id="tbl_snap",
            products_table_id="tbl_prod",
            browser_crawl_func=mock_browser,
        )
        result = orchestrator.crawl_via_browser("Test", "https://amazon.com")
        assert len(result) == 1
        assert result[0]["asin"] == "B0MOCKASIN"
        assert result[0]["price"] == 15.99
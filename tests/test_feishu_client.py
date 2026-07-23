"""feishu_client.py 修复后的测试。

覆盖：
- batch_update_records 的 payload 格式校验
- batch_delete_records
- page_token 缺失时不崩溃
"""

import pytest
from unittest.mock import patch, MagicMock
from feishu_client import FeishuClient, FeishuAPIError


class TestBatchUpdateRecords:
    """batch_update_records 修复后的测试（#10）。"""

    @pytest.fixture
    def client(self):
        c = FeishuClient(
            app_id="test_app_id",
            app_secret="test_app_secret",
            app_token="test_app_token",
        )
        c._token = "cached_token"
        c._token_expires_at = 9999999999
        return c

    def test_valid_payload(self, client):
        """正确的 payload 格式：[{record_id, fields}]。"""
        mock_resp = MagicMock()
        # 返回 2 条记录（与输入数量匹配）
        mock_resp.json.return_value = {
            "code": 0,
            "data": {"records": [{"record_id": "rec1"}, {"record_id": "rec2"}]},
        }
        mock_resp.raise_for_status = MagicMock()

        records = [
            {"record_id": "rec1", "fields": {"ASIN": "B000000001"}},
            {"record_id": "rec2", "fields": {"ASIN": "B000000002"}},
        ]

        with patch.object(client._http, "request", return_value=mock_resp):
            result = client.batch_update_records("tbl_test", records)
            assert len(result) == 2

    def test_missing_record_id_raises(self, client):
        """缺少 record_id 字段应抛 FeishuAPIError。"""
        records = [
            {"fields": {"ASIN": "B000000001"}},  # 缺 record_id
        ]
        with pytest.raises(FeishuAPIError, match="record_id"):
            client.batch_update_records("tbl_test", records)

    def test_missing_fields_raises(self, client):
        """缺少 fields 字段应抛 FeishuAPIError。"""
        records = [
            {"record_id": "rec1"},  # 缺 fields
        ]
        with pytest.raises(FeishuAPIError, match="fields"):
            client.batch_update_records("tbl_test", records)

    def test_chunks_large_batch(self, client):
        """大批量自动分片。"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 0,
            "data": {"records": [{"record_id": "rec_1"}]},
        }
        mock_resp.raise_for_status = MagicMock()

        records = [
            {"record_id": f"rec{i}", "fields": {"ASIN": f"B00{i}"}}
            for i in range(600)
        ]

        with patch.object(client._http, "request", return_value=mock_resp):
            result = client.batch_update_records("tbl_test", records, chunk_size=500)
            assert len(result) == 2  # 600/500 = 2 片


class TestBatchDeleteRecords:
    """batch_delete_records 测试。"""

    @pytest.fixture
    def client(self):
        c = FeishuClient(
            app_id="test_app_id",
            app_secret="test_app_secret",
            app_token="test_app_token",
        )
        c._token = "cached_token"
        c._token_expires_at = 9999999999
        return c

    def test_delete_records(self, client):
        """删除记录。"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 0,
            "data": {"records": [{"record_id": "rec_1"}, {"record_id": "rec_2"}]},
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._http, "request", return_value=mock_resp):
            result = client.batch_delete_records("tbl_test", ["rec_1", "rec_2"])
            assert len(result) == 2

    def test_empty_list(self, client):
        """空列表不发送请求。"""
        result = client.batch_delete_records("tbl_test", [])
        assert result == []


class TestGetRecordsPagination:
    """分页读取测试（#11）。"""

    @pytest.fixture
    def client(self):
        c = FeishuClient(
            app_id="test_app_id",
            app_secret="test_app_secret",
            app_token="test_app_token",
        )
        c._token = "cached_token"
        c._token_expires_at = 9999999999
        return c

    def test_missing_page_token_no_crash(self, client):
        """has_more=True 但 page_token 缺失时不应崩溃（#11）。"""
        mock_resp_1 = MagicMock()
        mock_resp_1.json.return_value = {
            "code": 0,
            "data": {
                "items": [{"record_id": "rec_1"}],
                "has_more": True,
                # 故意不返回 page_token
            },
        }
        mock_resp_1.raise_for_status = MagicMock()

        with patch.object(client._http, "request", return_value=mock_resp_1):
            # 不应崩溃，应返回已读取的记录
            result = client.get_records("tbl_test")
            assert len(result) == 1

    def test_normal_pagination(self, client):
        """正常分页流程。"""
        mock_resp_1 = MagicMock()
        mock_resp_1.json.return_value = {
            "code": 0,
            "data": {
                "items": [{"record_id": "rec_1"}],
                "has_more": True,
                "page_token": "token_abc",
            },
        }
        mock_resp_1.raise_for_status = MagicMock()

        mock_resp_2 = MagicMock()
        mock_resp_2.json.return_value = {
            "code": 0,
            "data": {
                "items": [{"record_id": "rec_2"}],
                "has_more": False,
            },
        }
        mock_resp_2.raise_for_status = MagicMock()

        with patch.object(
            client._http, "request", side_effect=[mock_resp_1, mock_resp_2]
        ):
            result = client.get_records("tbl_test")
            assert len(result) == 2
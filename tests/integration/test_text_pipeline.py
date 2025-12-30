"""
文本数据流水线集成测试

测试完整的数据获取流程：
1. 沪市股票 (601985.SH)
2. 深市股票 (000001.SZ)
"""

import pytest

from src.data_ingestion.text.a_share.coordinator import AShareTextCoordinator


class TestTextPipeline:
    """文本数据流水线集成测试"""

    @pytest.fixture
    def coordinator(self):
        """创建协调器实例"""
        return AShareTextCoordinator()

    @pytest.mark.integration
    def test_sh_stock_full_pipeline(self, coordinator):
        """测试沪市股票完整流程"""
        items = coordinator.fetch_texts(
            ticker="601985.SH",
            name="中国核电",
            lookback_hours=168,  # 一周
            max_items=10,
        )

        assert len(items) > 0
        # 检查数据来源多样性
        sources = {item.source for item in items}
        assert len(sources) >= 2  # 至少来自2个数据源

    @pytest.mark.integration
    def test_sz_stock_full_pipeline(self, coordinator):
        """测试深市股票完整流程"""
        items = coordinator.fetch_texts(
            ticker="000001.SZ",
            name="平安银行",
            lookback_hours=168,
            max_items=10,
        )

        assert len(items) > 0

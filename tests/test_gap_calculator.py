"""
Gap 计算器与信号判定测试

测试用例：
- test_opportunity_signal: Gap=15, Sentiment=30 → OPPORTUNITY
- test_overheated_signal: Sentiment=85 → OVERHEATED
- test_wait_signal: Gap=5, Sentiment=50 → WAIT
- test_calculate_gap: 基础 Gap 计算
- test_compute_audit_result: 完整审计结果生成
"""
from datetime import datetime

import pytest

from src.config.models import GapThresholdConfig
from src.engines.gap_calculator import AuditResult, AuditSignal, GapCalculator
from src.llm.models import ConsensusResult, ThesisProjectionResult


class TestGapCalculator:
    """Gap 计算器测试类"""

    def test_calculate_gap_positive(self):
        """测试正向 Gap 计算 (our > implied)"""
        calculator = GapCalculator()
        gap = calculator.calculate_gap(our_growth=20.0, implied_growth=5.0)
        assert gap == 15.0

    def test_calculate_gap_negative(self):
        """测试负向 Gap 计算 (our < implied)"""
        calculator = GapCalculator()
        gap = calculator.calculate_gap(our_growth=10.0, implied_growth=25.0)
        assert gap == -15.0

    def test_calculate_gap_zero(self):
        """测试零 Gap 计算 (our == implied)"""
        calculator = GapCalculator()
        gap = calculator.calculate_gap(our_growth=15.0, implied_growth=15.0)
        assert gap == 0.0


class TestSignalDetermination:
    """信号判定测试类"""

    def test_opportunity_signal(self):
        """
        测试机会信号判定

        条件：Gap > 10 且 Sentiment < 40
        输入：Gap=15, Sentiment=30
        预期：OPPORTUNITY
        """
        calculator = GapCalculator()
        signal = calculator.determine_signal(gap=15, sentiment_score=30)
        assert signal == AuditSignal.OPPORTUNITY

    def test_opportunity_signal_boundary_gap(self):
        """测试机会信号边界条件 - Gap 刚好等于 10 不触发"""
        calculator = GapCalculator()
        # Gap = 10（不大于 10）应返回 WAIT
        signal = calculator.determine_signal(gap=10, sentiment_score=30)
        assert signal == AuditSignal.WAIT

    def test_opportunity_signal_boundary_sentiment(self):
        """测试机会信号边界条件 - Sentiment 刚好等于 40 不触发"""
        calculator = GapCalculator()
        # Sentiment = 40（不小于 40）应返回 WAIT
        signal = calculator.determine_signal(gap=15, sentiment_score=40)
        assert signal == AuditSignal.WAIT

    def test_overheated_signal(self):
        """
        测试过热信号判定

        条件：Sentiment > 80
        输入：Sentiment=85
        预期：OVERHEATED
        """
        calculator = GapCalculator()
        signal = calculator.determine_signal(gap=5, sentiment_score=85)
        assert signal == AuditSignal.OVERHEATED

    def test_overheated_signal_boundary(self):
        """测试过热信号边界条件 - Sentiment 刚好等于 80 不触发"""
        calculator = GapCalculator()
        # Sentiment = 80（不大于 80）应返回 WAIT
        signal = calculator.determine_signal(gap=5, sentiment_score=80)
        assert signal == AuditSignal.WAIT

    def test_overheated_signal_extreme(self):
        """测试极端过热情绪"""
        calculator = GapCalculator()
        signal = calculator.determine_signal(gap=-10, sentiment_score=95)
        assert signal == AuditSignal.OVERHEATED

    def test_wait_signal(self):
        """
        测试观望信号判定

        条件：不满足 OPPORTUNITY 和 OVERHEATED 的条件
        输入：Gap=5, Sentiment=50
        预期：WAIT
        """
        calculator = GapCalculator()
        signal = calculator.determine_signal(gap=5, sentiment_score=50)
        assert signal == AuditSignal.WAIT

    def test_wait_signal_neutral_sentiment(self):
        """测试中性情绪下的观望信号"""
        calculator = GapCalculator()
        signal = calculator.determine_signal(gap=8, sentiment_score=55)
        assert signal == AuditSignal.WAIT

    def test_wait_signal_low_gap_low_sentiment(self):
        """测试低 Gap 低情绪的情况"""
        calculator = GapCalculator()
        # Gap 不够大，虽然情绪悲观也应该是 WAIT
        signal = calculator.determine_signal(gap=5, sentiment_score=25)
        assert signal == AuditSignal.WAIT

    def test_overheated_priority_over_opportunity(self):
        """测试过热信号优先级 - 即使 Gap 满足机会条件，高情绪仍判定为过热"""
        calculator = GapCalculator()
        # Gap=15 满足机会条件，但 Sentiment=85 触发过热
        signal = calculator.determine_signal(gap=15, sentiment_score=85)
        assert signal == AuditSignal.OVERHEATED


class TestCustomThresholds:
    """自定义阈值测试类"""

    def test_custom_opportunity_thresholds(self):
        """测试自定义机会阈值"""
        thresholds = GapThresholdConfig(
            opportunity_gap_min=5.0,  # 降低 Gap 阈值
            opportunity_sentiment_max=50,  # 提高情绪阈值
            overheated_sentiment_min=80,
        )
        calculator = GapCalculator(thresholds=thresholds)

        # 使用默认阈值会是 WAIT，但自定义阈值下是 OPPORTUNITY
        signal = calculator.determine_signal(gap=8, sentiment_score=45)
        assert signal == AuditSignal.OPPORTUNITY

    def test_custom_overheated_threshold(self):
        """测试自定义过热阈值"""
        thresholds = GapThresholdConfig(
            opportunity_gap_min=10.0,
            opportunity_sentiment_max=40,
            overheated_sentiment_min=70,  # 降低过热阈值
        )
        calculator = GapCalculator(thresholds=thresholds)

        # 使用默认阈值会是 WAIT，但自定义阈值下是 OVERHEATED
        signal = calculator.determine_signal(gap=5, sentiment_score=75)
        assert signal == AuditSignal.OVERHEATED


class TestComputeAuditResult:
    """完整审计结果生成测试类"""

    def test_compute_audit_result_opportunity(
        self,
        sample_consensus_result: ConsensusResult,
        sample_thesis_projection: ThesisProjectionResult,
    ):
        """测试生成机会信号的完整审计结果"""
        calculator = GapCalculator()
        audit_date = datetime(2024, 1, 15)

        result = calculator.compute_audit_result(
            ticker="600150.SH",
            name="中国船舶",
            price=35.50,
            pe_ttm=25.5,
            consensus=sample_consensus_result,
            thesis_projection=sample_thesis_projection,
            audit_date=audit_date,
        )

        # 验证基础信息
        assert result.ticker == "600150.SH"
        assert result.name == "中国船舶"
        assert result.price == 35.50
        assert result.pe_ttm == 25.5
        assert result.date == audit_date

        # 验证 Module A 输出
        assert result.sentiment_score == 35
        assert result.sentiment_label == "悲观"
        assert result.implied_growth == 5.0

        # 验证 Module B 输出
        assert result.thesis_aligned is True
        assert result.our_growth == 20.0
        assert result.confidence == "高"

        # 验证 Gap 计算和信号判定
        assert result.gap == 15.0  # 20.0 - 5.0
        assert result.signal == AuditSignal.OPPORTUNITY

    def test_compute_audit_result_overheated(self):
        """测试生成过热信号的完整审计结果"""
        calculator = GapCalculator()

        consensus = ConsensusResult(
            sentiment_score=85,
            sentiment_label="狂热",
            implied_growth=30.0,
            key_narrative="AI 芯片需求爆发",
            key_worry="估值过高",
            key_hope="AI 长期增长",
        )

        thesis = ThesisProjectionResult(
            thesis_aligned=True,
            our_growth=25.0,
            confidence="中",
            reasoning="AI 芯片领导者但估值已反映预期",
        )

        result = calculator.compute_audit_result(
            ticker="NVDA",
            name="英伟达",
            price=550.00,
            pe_ttm=65.0,
            consensus=consensus,
            thesis_projection=thesis,
            audit_date=datetime(2024, 1, 16),
        )

        assert result.signal == AuditSignal.OVERHEATED
        assert result.gap == -5.0  # 25.0 - 30.0

    def test_compute_audit_result_wait(self):
        """测试生成观望信号的完整审计结果"""
        calculator = GapCalculator()

        consensus = ConsensusResult(
            sentiment_score=50,
            sentiment_label="中性",
            implied_growth=12.0,
            key_narrative="游戏和广告业务稳定",
            key_worry="监管不确定性",
            key_hope="海外游戏增长",
        )

        thesis = ThesisProjectionResult(
            thesis_aligned=True,
            our_growth=15.0,
            confidence="中",
            reasoning="基本盘稳固但缺乏明显催化剂",
        )

        result = calculator.compute_audit_result(
            ticker="0700.HK",
            name="腾讯控股",
            price=320.00,
            pe_ttm=18.0,
            consensus=consensus,
            thesis_projection=thesis,
            audit_date=datetime(2024, 1, 17),
        )

        assert result.signal == AuditSignal.WAIT
        assert result.gap == 3.0  # 15.0 - 12.0

    def test_compute_audit_result_none_pe(self):
        """测试 PE 为 None 的情况"""
        calculator = GapCalculator()

        consensus = ConsensusResult(
            sentiment_score=30,
            sentiment_label="悲观",
            implied_growth=5.0,
            key_narrative="测试叙事",
            key_worry="测试担忧",
            key_hope="测试期望",
        )

        thesis = ThesisProjectionResult(
            thesis_aligned=True,
            our_growth=20.0,
            confidence="高",
            reasoning="这是一个测试推理说明文本",
        )

        result = calculator.compute_audit_result(
            ticker="TEST.SH",
            name="测试公司",
            price=10.0,
            pe_ttm=None,  # PE 为空
            consensus=consensus,
            thesis_projection=thesis,
        )

        assert result.pe_ttm is None
        assert result.signal == AuditSignal.OPPORTUNITY

    def test_compute_audit_result_default_date(self):
        """测试默认使用当前日期"""
        calculator = GapCalculator()

        consensus = ConsensusResult(
            sentiment_score=50,
            sentiment_label="中性",
            implied_growth=10.0,
            key_narrative="测试叙事",
            key_worry="测试担忧",
            key_hope="测试期望",
        )

        thesis = ThesisProjectionResult(
            thesis_aligned=True,
            our_growth=15.0,
            confidence="中",
            reasoning="这是一个测试推理说明文本",
        )

        before = datetime.now()
        result = calculator.compute_audit_result(
            ticker="TEST.SH",
            name="测试公司",
            price=10.0,
            pe_ttm=20.0,
            consensus=consensus,
            thesis_projection=thesis,
            # 不提供 audit_date，使用默认值
        )
        after = datetime.now()

        assert before <= result.date <= after


class TestAuditSignalEnum:
    """审计信号枚举测试类"""

    def test_audit_signal_values(self):
        """测试审计信号枚举值"""
        assert AuditSignal.OPPORTUNITY.value == "OPPORTUNITY"
        assert AuditSignal.OVERHEATED.value == "OVERHEATED"
        assert AuditSignal.WAIT.value == "WAIT"

    def test_audit_signal_string_conversion(self):
        """测试审计信号字符串转换"""
        assert str(AuditSignal.OPPORTUNITY) == "AuditSignal.OPPORTUNITY"
        assert AuditSignal("OPPORTUNITY") == AuditSignal.OPPORTUNITY

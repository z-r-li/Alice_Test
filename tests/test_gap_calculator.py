"""
Gap 计算器与信号判定测试（信号语义 v2：纯 α 差双向触发）

测试用例：
- test_opportunity_signal: gap=15 → OPPORTUNITY（正 α）
- test_overheated_signal: gap=-15 → OVERHEATED（负 α，D-20260705-1）
- test_wait_signal: |gap| 不超阈值 → WAIT；gap=NaN（fail-closed）→ WAIT
- 金丝雀（语义翻转验收锚）：gap=+30 且 sentiment=85 → v1 错判 OVERHEATED，v2 必须 OPPORTUNITY
- sentiment 不再触发信号，只产 sentiment_overheat flag
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
    """信号判定测试类（v2：只吃 gap，双向 α 差触发）"""

    def test_opportunity_signal(self):
        """gap=15 > 10 → OPPORTUNITY（正 α），与 sentiment 无关"""
        calculator = GapCalculator()
        signal = calculator.determine_signal(gap=15)
        assert signal == AuditSignal.OPPORTUNITY

    def test_opportunity_signal_boundary_gap(self):
        """边界：gap 刚好等于 +10 不触发 → WAIT"""
        calculator = GapCalculator()
        signal = calculator.determine_signal(gap=10)
        assert signal == AuditSignal.WAIT

    def test_overheated_signal_negative_alpha(self):
        """gap=-15 < -10 → OVERHEATED（负 α：市场 implied 定价高于我方，D-20260705-1）"""
        calculator = GapCalculator()
        signal = calculator.determine_signal(gap=-15)
        assert signal == AuditSignal.OVERHEATED

    def test_overheated_signal_boundary(self):
        """边界：gap 刚好等于 -10 不触发 → WAIT"""
        calculator = GapCalculator()
        signal = calculator.determine_signal(gap=-10)
        assert signal == AuditSignal.WAIT

    def test_overheated_signal_extreme(self):
        """极端负 α"""
        calculator = GapCalculator()
        signal = calculator.determine_signal(gap=-40)
        assert signal == AuditSignal.OVERHEATED

    def test_wait_signal(self):
        """|gap| 不超阈值 → WAIT"""
        calculator = GapCalculator()
        assert calculator.determine_signal(gap=5) == AuditSignal.WAIT
        assert calculator.determine_signal(gap=-5) == AuditSignal.WAIT
        assert calculator.determine_signal(gap=0) == AuditSignal.WAIT

    def test_nan_gap_fail_closed_wait(self):
        """gap=NaN（fail-closed 行）→ WAIT：所有比较为 False，不误触发双向信号"""
        calculator = GapCalculator()
        assert calculator.determine_signal(gap=float("nan")) == AuditSignal.WAIT


class TestSentimentDecoupledFromSignal:
    """v2：sentiment 摘出信号门——不再触发任何信号，只产 sentiment_overheat flag"""

    def test_high_sentiment_alone_no_longer_triggers_overheated(self):
        """v1 的「sentiment > 80 → OVERHEATED」已废：gap=5 不超阈值 → WAIT。

        （v2 里 determine_signal 不吃 sentiment；本用例锁死签名与语义。）
        """
        calculator = GapCalculator()
        assert calculator.determine_signal(gap=5) == AuditSignal.WAIT
        # flag 仍单列登记
        assert calculator.is_sentiment_overheat(85) is True

    def test_canary_positive_gap_high_sentiment_is_opportunity(self):
        """金丝雀用例（语义翻转验收锚，交接 §1）：

        gap=+30、sentiment=85 → v1 输出 OVERHEATED（错：与 α 差同号矛盾），
        v2 必须输出 OPPORTUNITY；情绪过热以 flag 单列。
        """
        calculator = GapCalculator()
        assert calculator.determine_signal(gap=30) == AuditSignal.OPPORTUNITY
        assert calculator.is_sentiment_overheat(85) is True

    def test_sentiment_overheat_flag_boundary(self):
        """flag 阈值沿用 80：等于不触发，大于触发"""
        calculator = GapCalculator()
        assert calculator.is_sentiment_overheat(80) is False
        assert calculator.is_sentiment_overheat(81) is True
        assert calculator.is_sentiment_overheat(30) is False


class TestCustomThresholds:
    """自定义阈值测试类（v2 字段）"""

    def test_custom_opportunity_threshold(self):
        """降低正 α 阈值：默认 WAIT 的 gap=8 变 OPPORTUNITY"""
        thresholds = GapThresholdConfig(opportunity_gap_min=5.0)
        calculator = GapCalculator(thresholds=thresholds)
        assert calculator.determine_signal(gap=8) == AuditSignal.OPPORTUNITY

    def test_custom_overheated_gap_threshold(self):
        """降低负 α 阈值：默认 WAIT 的 gap=-8 变 OVERHEATED（阈值可不对称）"""
        thresholds = GapThresholdConfig(overheated_gap_min=5.0)
        calculator = GapCalculator(thresholds=thresholds)
        assert calculator.determine_signal(gap=-8) == AuditSignal.OVERHEATED
        # 正向阈值不受影响
        assert calculator.determine_signal(gap=8) == AuditSignal.WAIT

    def test_custom_sentiment_overheat_flag_threshold(self):
        """overheated_sentiment_min 转任 flag 阈值后仍可自定义（显式设置带 deprecation 提示）"""
        with pytest.warns(DeprecationWarning, match="overheated_sentiment_min"):
            thresholds = GapThresholdConfig(overheated_sentiment_min=70)
        calculator = GapCalculator(thresholds=thresholds)
        assert calculator.is_sentiment_overheat(75) is True
        assert calculator.is_sentiment_overheat(70) is False


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
        assert result.sentiment_overheat is False  # sentiment=35 未过热

    def test_compute_audit_result_overheated(self):
        """测试生成过热信号的完整审计结果（v2：负 α gap < -10 触发）"""
        calculator = GapCalculator()

        consensus = ConsensusResult(
            sentiment_score=85,
            sentiment_label="狂热",
            implied_growth=40.0,
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
        assert result.gap == -15.0  # 25.0 - 40.0
        assert result.sentiment_overheat is True  # 情绪过热单列 flag（不参与信号）

    def test_compute_audit_result_canary_flip(self):
        """金丝雀（端到端）：gap=+30 且 sentiment=85 → v2 必须 OPPORTUNITY + flag。

        v1 旧门在此输入下输出 OVERHEATED（与 α 差同号矛盾）——若本用例失败，
        说明信号门回退到了 v1 语义。
        """
        calculator = GapCalculator()

        consensus = ConsensusResult(
            sentiment_score=85,
            sentiment_label="狂热",
            implied_growth=10.0,
            key_narrative="市场狂热但定价仍低于我方模型",
            key_worry="情绪透支",
            key_hope="产能落地",
        )
        thesis = ThesisProjectionResult(
            thesis_aligned=True,
            our_growth=40.0,
            confidence="高",
            reasoning="我方模型增长显著高于市场 implied",
        )

        result = calculator.compute_audit_result(
            ticker="TEST.SH",
            name="金丝雀",
            price=10.0,
            pe_ttm=20.0,
            consensus=consensus,
            thesis_projection=thesis,
            audit_date=datetime(2026, 7, 8),
        )

        assert result.gap == 30.0
        assert result.signal == AuditSignal.OPPORTUNITY  # v1 会错判 OVERHEATED
        assert result.sentiment_overheat is True

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

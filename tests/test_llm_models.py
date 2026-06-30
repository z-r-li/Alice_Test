"""
LLM 数据模型测试

测试用例：
- test_consensus_result_validation: 验证 sentiment_score 范围
- test_thesis_projection_validation: 验证 confidence 枚举值
- test_from_dict_parsing: 测试 LLM 响应解析
- test_validate_method: 测试 validate() 方法
"""
import pytest
from pydantic import ValidationError

from src.llm.models import (
    AuditSignal,
    ConsensusResult,
    LLMResponse,
    ThesisProjectionResult,
)


class TestConsensusResultValidation:
    """ConsensusResult 验证测试类"""

    def test_valid_consensus_result(self, sample_consensus_result: ConsensusResult):
        """测试有效的 ConsensusResult 创建"""
        assert sample_consensus_result.sentiment_score == 35
        assert sample_consensus_result.sentiment_label == "悲观"
        assert sample_consensus_result.implied_growth == 5.0

    def test_sentiment_score_range_valid(self):
        """测试有效的情绪评分范围 (0-100)"""
        # 边界值测试
        result_min = ConsensusResult(
            sentiment_score=0,
            sentiment_label="恐慌",
            implied_growth=0.0,
            key_narrative="极度恐慌",
            key_worry="担忧",
            key_hope="期望",
        )
        assert result_min.sentiment_score == 0

        result_max = ConsensusResult(
            sentiment_score=100,
            sentiment_label="狂热",
            implied_growth=50.0,
            key_narrative="极度狂热",
            key_worry="担忧",
            key_hope="期望",
        )
        assert result_max.sentiment_score == 100

    def test_sentiment_score_out_of_range_low(self):
        """测试情绪评分低于范围"""
        with pytest.raises(ValidationError) as exc_info:
            ConsensusResult(
                sentiment_score=-1,
                sentiment_label="恐慌",
                implied_growth=0.0,
                key_narrative="测试",
                key_worry="担忧",
                key_hope="期望",
            )
        assert "greater than or equal to 0" in str(exc_info.value)

    def test_sentiment_score_out_of_range_high(self):
        """测试情绪评分高于范围"""
        with pytest.raises(ValidationError) as exc_info:
            ConsensusResult(
                sentiment_score=101,
                sentiment_label="狂热",
                implied_growth=0.0,
                key_narrative="测试",
                key_worry="担忧",
                key_hope="期望",
            )
        assert "less than or equal to 100" in str(exc_info.value)

    def test_sentiment_label_valid_values(self):
        """测试有效的情绪标签枚举值"""
        valid_labels = ["恐慌", "悲观", "中性", "乐观", "狂热"]
        for label in valid_labels:
            result = ConsensusResult(
                sentiment_score=50,
                sentiment_label=label,
                implied_growth=10.0,
                key_narrative="测试叙事",
                key_worry="测试担忧",
                key_hope="测试期望",
            )
            assert result.sentiment_label == label

    def test_sentiment_label_invalid(self):
        """测试无效的情绪标签"""
        with pytest.raises(ValidationError) as exc_info:
            ConsensusResult(
                sentiment_score=50,
                sentiment_label="无效标签",
                implied_growth=10.0,
                key_narrative="测试",
                key_worry="担忧",
                key_hope="期望",
            )
        assert "pattern" in str(exc_info.value).lower()

    def test_implied_growth_range(self):
        """测试隐含增长率范围 (-50% ~ 100%)"""
        # 有效边界值
        result_min = ConsensusResult(
            sentiment_score=10,
            sentiment_label="恐慌",
            implied_growth=-50.0,
            key_narrative="极度悲观",
            key_worry="担忧",
            key_hope="期望",
        )
        assert result_min.implied_growth == -50.0

        result_max = ConsensusResult(
            sentiment_score=95,
            sentiment_label="狂热",
            implied_growth=100.0,
            key_narrative="极度乐观",
            key_worry="担忧",
            key_hope="期望",
        )
        assert result_max.implied_growth == 100.0

    def test_implied_growth_out_of_range(self):
        """测试隐含增长率超出范围"""
        with pytest.raises(ValidationError):
            ConsensusResult(
                sentiment_score=50,
                sentiment_label="中性",
                implied_growth=150.0,  # 超出范围
                key_narrative="测试",
                key_worry="担忧",
                key_hope="期望",
            )

    def test_text_fields_non_empty(self):
        """测试文本字段不能为空"""
        with pytest.raises(ValidationError):
            ConsensusResult(
                sentiment_score=50,
                sentiment_label="中性",
                implied_growth=10.0,
                key_narrative="",  # 空字符串
                key_worry="担忧",
                key_hope="期望",
            )


class TestConsensusResultMethods:
    """ConsensusResult 方法测试类"""

    def test_get_sentiment_level(self):
        """测试情绪级别获取方法"""
        test_cases = [
            (10, "panic"),
            (20, "panic"),
            (25, "pessimistic"),
            (40, "pessimistic"),
            (45, "neutral"),
            (60, "neutral"),
            (65, "optimistic"),
            (80, "optimistic"),
            (85, "euphoric"),
            (100, "euphoric"),
        ]

        for score, expected_level in test_cases:
            result = ConsensusResult(
                sentiment_score=score,
                sentiment_label="中性",  # 标签不影响此方法
                implied_growth=10.0,
                key_narrative="测试",
                key_worry="担忧",
                key_hope="期望",
            )
            assert result.get_sentiment_level() == expected_level

    def test_to_dict(self, sample_consensus_result: ConsensusResult):
        """测试转换为字典"""
        result_dict = sample_consensus_result.to_dict()

        assert result_dict["sentiment_score"] == 35
        assert result_dict["sentiment_label"] == "悲观"
        assert result_dict["implied_growth"] == 5.0
        assert "key_narrative" in result_dict
        assert "key_worry" in result_dict
        assert "key_hope" in result_dict

    def test_from_dict(self, sample_consensus_dict: dict):
        """测试从字典构造"""
        result = ConsensusResult.from_dict(sample_consensus_dict)

        assert result.sentiment_score == 35
        assert result.sentiment_label == "悲观"
        assert result.implied_growth == 5.0  # 从 implied_growth_rate 映射

    def test_from_dict_field_mapping(self):
        """测试 from_dict 字段名映射"""
        data = {
            "sentiment_score": 40,
            "sentiment_label": "悲观",
            "implied_growth_rate": 8.0,  # LLM 使用的字段名
            "key_narrative": "测试叙事",
            "key_worry": "测试担忧",
            "key_hope": "测试期望",
        }
        result = ConsensusResult.from_dict(data)
        assert result.implied_growth == 8.0

    def test_validate_success(self, sample_consensus_result: ConsensusResult):
        """测试 validate 方法成功"""
        assert sample_consensus_result.validate() is True

    def test_validate_failure_score_out_of_range(self):
        """测试 validate 方法 - 评分超范围"""
        # 手动创建对象绕过 Pydantic 验证（模拟解析后的数据）
        result = ConsensusResult.model_construct(
            sentiment_score=150,  # 超范围
            sentiment_label="中性",
            implied_growth=10.0,
            key_narrative="测试",
            key_worry="担忧",
            key_hope="期望",
        )
        assert result.validate() is False

    def test_validate_failure_invalid_label(self):
        """测试 validate 方法 - 无效标签"""
        result = ConsensusResult.model_construct(
            sentiment_score=50,
            sentiment_label="无效",  # 无效标签
            implied_growth=10.0,
            key_narrative="测试",
            key_worry="担忧",
            key_hope="期望",
        )
        assert result.validate() is False

    def test_validate_failure_empty_text(self):
        """测试 validate 方法 - 空文本"""
        result = ConsensusResult.model_construct(
            sentiment_score=50,
            sentiment_label="中性",
            implied_growth=10.0,
            key_narrative="",  # 空文本
            key_worry="担忧",
            key_hope="期望",
        )
        assert result.validate() is False


class TestThesisProjectionValidation:
    """ThesisProjectionResult 验证测试类"""

    def test_valid_thesis_projection(self, sample_thesis_projection: ThesisProjectionResult):
        """测试有效的 ThesisProjectionResult 创建"""
        assert sample_thesis_projection.thesis_aligned is True
        assert sample_thesis_projection.our_growth == 20.0
        assert sample_thesis_projection.confidence == "高"

    def test_confidence_valid_values(self):
        """测试有效的置信度枚举值 (高|中|低)"""
        valid_confidences = ["高", "中", "低"]
        for confidence in valid_confidences:
            result = ThesisProjectionResult(
                thesis_aligned=True,
                our_growth=15.0,
                confidence=confidence,
                reasoning="这是一个有效的推理说明文本",
            )
            assert result.confidence == confidence

    def test_confidence_invalid(self):
        """测试无效的置信度值"""
        with pytest.raises(ValidationError) as exc_info:
            ThesisProjectionResult(
                thesis_aligned=True,
                our_growth=15.0,
                confidence="超高",  # 无效值
                reasoning="测试推理说明",
            )
        assert "pattern" in str(exc_info.value).lower()

    def test_our_growth_range(self):
        """测试预期增长率范围 (-50% ~ 100%)"""
        # 有效边界值
        result_min = ThesisProjectionResult(
            thesis_aligned=False,
            our_growth=-50.0,
            confidence="低",
            reasoning="极度悲观的增长预期说明",
        )
        assert result_min.our_growth == -50.0

        result_max = ThesisProjectionResult(
            thesis_aligned=True,
            our_growth=100.0,
            confidence="高",
            reasoning="极度乐观的增长预期说明",
        )
        assert result_max.our_growth == 100.0

    def test_our_growth_out_of_range(self):
        """测试预期增长率超出范围"""
        with pytest.raises(ValidationError):
            ThesisProjectionResult(
                thesis_aligned=True,
                our_growth=150.0,  # 超出范围
                confidence="高",
                reasoning="测试推理",
            )

    def test_thesis_aligned_boolean(self):
        """测试 thesis_aligned 必须是布尔值"""
        result_true = ThesisProjectionResult(
            thesis_aligned=True,
            our_growth=15.0,
            confidence="高",
            reasoning="与投资信念一致的推理说明",
        )
        assert result_true.thesis_aligned is True

        result_false = ThesisProjectionResult(
            thesis_aligned=False,
            our_growth=5.0,
            confidence="低",
            reasoning="与投资信念不一致的推理说明",
        )
        assert result_false.thesis_aligned is False

    def test_reasoning_min_length(self):
        """测试推理文本不能为空"""
        with pytest.raises(ValidationError):
            ThesisProjectionResult(
                thesis_aligned=True,
                our_growth=15.0,
                confidence="高",
                reasoning="",  # 空字符串
            )


class TestThesisProjectionMethods:
    """ThesisProjectionResult 方法测试类"""

    def test_to_dict(self, sample_thesis_projection: ThesisProjectionResult):
        """测试转换为字典"""
        result_dict = sample_thesis_projection.to_dict()

        assert result_dict["thesis_aligned"] is True
        assert result_dict["our_growth"] == 20.0
        assert result_dict["confidence"] == "高"
        assert "reasoning" in result_dict

    def test_from_dict(self, sample_thesis_dict: dict):
        """测试从字典构造"""
        result = ThesisProjectionResult.from_dict(sample_thesis_dict)

        assert result.thesis_aligned is True
        assert result.our_growth == 20.0  # 从 expected_growth_rate 映射
        assert result.confidence == "高"

    def test_from_dict_field_mapping(self):
        """测试 from_dict 字段名映射"""
        data = {
            "thesis_aligned": True,
            "expected_growth_rate": 18.0,  # LLM 使用的字段名
            "confidence": "中",
            "reasoning": "这是一个有效的推理说明文本",
        }
        result = ThesisProjectionResult.from_dict(data)
        assert result.our_growth == 18.0

    def test_from_dict_string_boolean(self):
        """测试 from_dict 处理字符串布尔值"""
        data = {
            "thesis_aligned": "true",  # 字符串形式
            "our_growth": 15.0,
            "confidence": "高",
            "reasoning": "测试字符串布尔值处理的推理说明",
        }
        result = ThesisProjectionResult.from_dict(data)
        assert result.thesis_aligned is True

    def test_validate_success(self, sample_thesis_projection: ThesisProjectionResult):
        """测试 validate 方法成功"""
        assert sample_thesis_projection.validate() is True

    def test_validate_failure_invalid_confidence(self):
        """测试 validate 方法 - 无效置信度"""
        result = ThesisProjectionResult.model_construct(
            thesis_aligned=True,
            our_growth=15.0,
            confidence="超高",  # 无效值
            reasoning="测试推理说明",
        )
        assert result.validate() is False

    def test_validate_failure_short_reasoning(self):
        """测试 validate 方法 - 推理文本过短"""
        result = ThesisProjectionResult.model_construct(
            thesis_aligned=True,
            our_growth=15.0,
            confidence="高",
            reasoning="太短",  # 少于10字符
        )
        assert result.validate() is False

    def test_validate_failure_growth_out_of_range(self):
        """测试 validate 方法 - 增长率超范围"""
        result = ThesisProjectionResult.model_construct(
            thesis_aligned=True,
            our_growth=150.0,  # 超范围
            confidence="高",
            reasoning="这是一个测试推理说明文本",
        )
        assert result.validate() is False


class TestLLMResponse:
    """LLMResponse 测试类"""

    def test_create_llm_response(self):
        """测试创建 LLMResponse"""
        response = LLMResponse(
            content='{"sentiment_score": 50}',
            model="deepseek-v4-flash",
            prompt_tokens=100,
            completion_tokens=50,
        )
        assert response.content == '{"sentiment_score": 50}'
        assert response.model == "deepseek-v4-flash"

    def test_get_total_tokens(self):
        """测试获取总 token 数"""
        response = LLMResponse(
            content="test",
            model="deepseek-v4-flash",
            prompt_tokens=100,
            completion_tokens=50,
        )
        assert response.get_total_tokens() == 150

    def test_get_cost_estimate(self):
        """测试成本估算（DeepSeek-V4-Flash 现价）"""
        response = LLMResponse(
            content="test",
            model="deepseek-v4-flash",
            prompt_tokens=1_000_000,  # 1M tokens
            completion_tokens=1_000_000,  # 1M tokens
        )
        # V4-Flash 现价: 输入 $0.14/1M, 输出 $0.28/1M（旧 $0.27/$1.10 高估 2–4 倍）
        expected_cost = 0.14 + 0.28
        assert response.get_cost_estimate() == pytest.approx(expected_cost)

    def test_get_cost_estimate_with_cache_hits(self):
        """缓存命中 token 按 $0.0028/1M 计价，未命中部分按 $0.14/1M"""
        response = LLMResponse(
            content="test",
            model="deepseek-v4-flash",
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
        )
        # 60% 命中缓存：0.4M×0.14 + 0.6M×0.0028 + 1M×0.28
        expected = 0.4 * 0.14 + 0.6 * 0.0028 + 0.28
        assert response.get_cost_estimate(cached_tokens=600_000) == pytest.approx(
            expected
        )

    def test_get_cost_estimate_v4_pro(self):
        """v4-pro 价格档：按 self.model 自动选档（输入未命中 $0.435/1M、输出 $0.87/1M）。"""
        response = LLMResponse(
            content="test",
            model="deepseek-v4-pro",
            prompt_tokens=1_000_000,  # 1M tokens
            completion_tokens=1_000_000,  # 1M tokens
        )
        # v4-pro 现价（迁移计划 §1）：输入未命中 $0.435/1M，输出 $0.87/1M
        expected_cost = 0.435 + 0.87
        assert response.get_cost_estimate() == pytest.approx(expected_cost)

    def test_get_cost_estimate_v4_pro_with_cache_hits(self):
        """v4-pro 缓存命中按 $0.003625/1M 计价，未命中部分按 $0.435/1M。"""
        response = LLMResponse(
            content="test",
            model="deepseek-v4-pro",
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
        )
        # 60% 命中：0.4M×0.435 + 0.6M×0.003625 + 1M×0.87
        expected = 0.4 * 0.435 + 0.6 * 0.003625 + 0.87
        assert response.get_cost_estimate(cached_tokens=600_000) == pytest.approx(
            expected
        )

    def test_get_cost_estimate_explicit_override(self):
        """显式传价仍覆盖按-model 选档（向后兼容）。"""
        response = LLMResponse(
            content="test",
            model="deepseek-v4-pro",
            prompt_tokens=1_000_000,
            completion_tokens=0,
        )
        # 显式覆盖输入单价为 1.0 → 不走 pro 档
        assert response.get_cost_estimate(input_price_per_1m=1.0) == pytest.approx(1.0)


class TestAuditSignalModel:
    """AuditSignal Pydantic 模型测试类"""

    def test_create_audit_signal(self):
        """测试创建 AuditSignal"""
        signal = AuditSignal(signal="OPPORTUNITY", gap=15.0)
        assert signal.signal == "OPPORTUNITY"
        assert signal.gap == 15.0

    def test_auto_confidence_high(self):
        """测试自动设置高置信度 (gap >= 20)"""
        signal = AuditSignal(signal="OPPORTUNITY", gap=25.0)
        assert signal.confidence == "high"

    def test_auto_confidence_medium(self):
        """测试自动设置中置信度 (10 <= gap < 20)"""
        signal = AuditSignal(signal="OPPORTUNITY", gap=15.0)
        assert signal.confidence == "medium"

    def test_auto_confidence_low(self):
        """测试自动设置低置信度 (gap < 10)"""
        signal = AuditSignal(signal="WAIT", gap=5.0)
        assert signal.confidence == "low"

    def test_is_actionable_opportunity(self):
        """测试 OPPORTUNITY 信号可操作"""
        signal = AuditSignal(signal="OPPORTUNITY", gap=15.0)
        assert signal.is_actionable() is True

    def test_is_actionable_overheated(self):
        """测试 OVERHEATED 信号可操作"""
        signal = AuditSignal(signal="OVERHEATED", gap=-5.0)
        assert signal.is_actionable() is True

    def test_is_actionable_wait(self):
        """测试 WAIT 信号不可操作"""
        signal = AuditSignal(signal="WAIT", gap=3.0)
        assert signal.is_actionable() is False

    def test_invalid_signal_value(self):
        """测试无效的信号值"""
        with pytest.raises(ValidationError):
            AuditSignal(signal="INVALID", gap=10.0)

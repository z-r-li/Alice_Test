"""
LLM 响应数据模型定义

使用 Pydantic v2 定义 LLM 调用的输入输出数据结构，
包括 Module A (ConsensusResult) 和 Module B (ThesisProjectionResult) 的输出模型。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class LLMResponse(BaseModel):
    """
    LLM 原始响应封装

    封装 LLM API 返回的原始响应，包括内容、使用统计等。

    Attributes:
        content: 响应文本内容
        model: 使用的模型名称
        prompt_tokens: 输入 token 数
        completion_tokens: 输出 token 数
        raw_response: 原始响应对象（用于调试）
    """

    content: str = Field(..., description="响应文本内容")
    model: str = Field(..., description="使用的模型")
    prompt_tokens: int = Field(default=0, description="输入 token 数")
    completion_tokens: int = Field(default=0, description="输出 token 数")
    raw_response: Any = Field(default=None, exclude=True, description="原始响应对象")

    def get_total_tokens(self) -> int:
        """
        获取总 token 使用量

        Returns:
            int: 总 token 数
        """
        return self.prompt_tokens + self.completion_tokens

    def get_cost_estimate(
        self,
        input_price_per_1m: float = 0.27,
        output_price_per_1m: float = 1.10,
    ) -> float:
        """
        估算调用成本（基于 DeepSeek-Chat 定价）

        DeepSeek-Chat 定价（2024）:
        - 输入: $0.27 / 1M tokens
        - 输出: $1.10 / 1M tokens

        Args:
            input_price_per_1m: 输入每百万 token 价格（美元）
            output_price_per_1m: 输出每百万 token 价格（美元）

        Returns:
            float: 估算成本（美元）
        """
        input_cost = self.prompt_tokens / 1_000_000 * input_price_per_1m
        output_cost = self.completion_tokens / 1_000_000 * output_price_per_1m
        return input_cost + output_cost


class ConsensusResult(BaseModel):
    """
    Module A 输出：市场共识分析结果

    对应 PRD 4.2.2 节的 JSON Schema。
    由 ConsensusEngine 调用 LLM 后解析生成。

    Attributes:
        sentiment_score: 市场情绪评分 (0-100)
            - 0-20: 提及崩盘、危机、不可持续
            - 21-40: 关注成本风险、汇率风险、增长不及预期
            - 41-60: 多空平衡，价格已 Price-in
            - 61-80: 强调增长逻辑，弱化风险
            - 81-100: 使用"无限空间"、"新纪元"等极度乐观用语
        sentiment_label: 情绪标签 (恐慌|悲观|中性|乐观|狂热)
        implied_growth: 市场隐含年化增长率 (百分数，如 5.0 表示 5%)
        key_narrative: 市场主要叙事描述 (一句话总结)
        key_worry: 市场主要担忧
        key_hope: 市场主要期待

    Example:
        >>> result = ConsensusResult(
        ...     sentiment_score=35,
        ...     sentiment_label="悲观",
        ...     implied_growth=5.0,
        ...     key_narrative="市场担忧钢价上涨侵蚀利润",
        ...     key_worry="钢材成本压力",
        ...     key_hope="新船订单增长"
        ... )
    """

    sentiment_score: int = Field(
        ...,
        ge=0,
        le=100,
        description="市场情绪评分 (0-100)",
    )
    sentiment_label: str = Field(
        ...,
        pattern="^(恐慌|悲观|中性|乐观|狂热)$",
        description="情绪标签 (恐慌|悲观|中性|乐观|狂热)",
    )
    implied_growth: float = Field(
        ...,
        ge=-50.0,
        le=100.0,
        description="市场隐含年化增长率 (百分数)",
    )
    key_narrative: str = Field(
        ...,
        min_length=1,
        description="市场主要叙事描述",
    )
    key_worry: str = Field(
        ...,
        min_length=1,
        description="市场主要担忧",
    )
    key_hope: str = Field(
        ...,
        min_length=1,
        description="市场主要期待",
    )

    @field_validator("key_narrative", "key_worry", "key_hope")
    @classmethod
    def validate_text_fields(cls, v: str) -> str:
        """清理文本字段"""
        return v.strip()

    def get_sentiment_level(self) -> str:
        """
        获取情绪级别描述 (英文)

        Returns:
            str: 情绪级别 ("panic", "pessimistic", "neutral", "optimistic", "euphoric")
        """
        if self.sentiment_score <= 20:
            return "panic"
        elif self.sentiment_score <= 40:
            return "pessimistic"
        elif self.sentiment_score <= 60:
            return "neutral"
        elif self.sentiment_score <= 80:
            return "optimistic"
        else:
            return "euphoric"

    def to_dict(self) -> dict[str, Any]:
        """
        转换为字典格式

        Returns:
            dict: 包含所有字段的字典
        """
        return {
            "sentiment_score": self.sentiment_score,
            "sentiment_label": self.sentiment_label,
            "implied_growth": self.implied_growth,
            "key_narrative": self.key_narrative,
            "key_worry": self.key_worry,
            "key_hope": self.key_hope,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConsensusResult":
        """
        从字典构造 ConsensusResult 对象

        Args:
            data: 包含所有必需字段的字典

        Returns:
            ConsensusResult: 构造的结果对象

        Raises:
            ValidationError: 字段验证失败
        """
        return cls(
            sentiment_score=data.get("sentiment_score", 0),
            sentiment_label=data.get("sentiment_label", "中性"),
            implied_growth=data.get("implied_growth", 0.0),
            key_narrative=data.get("key_narrative", ""),
            key_worry=data.get("key_worry", ""),
            key_hope=data.get("key_hope", ""),
        )

    def validate(self) -> bool:
        """
        验证结果是否有效

        检查所有必需字段是否存在且有效。

        Returns:
            bool: 验证通过返回 True
        """
        # 检查情绪评分范围
        if not (0 <= self.sentiment_score <= 100):
            return False

        # 检查情绪标签是否有效
        valid_labels = {"恐慌", "悲观", "中性", "乐观", "狂热"}
        if self.sentiment_label not in valid_labels:
            return False

        # 检查隐含增长率范围
        if not (-50.0 <= self.implied_growth <= 100.0):
            return False

        # 检查文本字段非空
        if not self.key_narrative or not self.key_worry or not self.key_hope:
            return False

        return True


class ThesisProjectionResult(BaseModel):
    """
    Module B 输出：信念投影结果

    对应 PRD 4.3.1 节的 JSON Schema。
    由 ThesisProjector 调用 LLM 后解析生成。

    Attributes:
        thesis_aligned: 标的是否与用户投资信念一致
        our_growth: 我们预期的合理年化增长率 (百分数，如 15.0 表示 15%)
        confidence: 预测置信度 (高|中|低)
        reasoning: 推导逻辑说明 (2-3 句解释)

    Example:
        >>> result = ThesisProjectionResult(
        ...     thesis_aligned=True,
        ...     our_growth=15.0,
        ...     confidence="高",
        ...     reasoning="在全球供应链重构与高端制造国产替代的背景下..."
        ... )
    """

    thesis_aligned: bool = Field(
        ...,
        description="标的是否与用户投资信念一致",
    )
    our_growth: float = Field(
        ...,
        ge=-50.0,
        le=100.0,
        description="我们预期的合理年化增长率 (百分数)",
    )
    confidence: str = Field(
        ...,
        pattern="^(高|中|低)$",
        description="预测置信度 (高|中|低)",
    )
    reasoning: str = Field(
        ...,
        min_length=1,
        description="推导逻辑说明",
    )

    @field_validator("reasoning")
    @classmethod
    def validate_reasoning(cls, v: str) -> str:
        """清理推理文本"""
        return v.strip()

    def to_dict(self) -> dict[str, Any]:
        """
        转换为字典格式

        Returns:
            dict: 包含所有字段的字典
        """
        return {
            "thesis_aligned": self.thesis_aligned,
            "our_growth": self.our_growth,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ThesisProjectionResult":
        """
        从字典构造 ThesisProjectionResult 对象

        Args:
            data: 包含所有必需字段的字典

        Returns:
            ThesisProjectionResult: 构造的结果对象

        Raises:
            ValidationError: 字段验证失败
        """
        return cls(
            thesis_aligned=data.get("thesis_aligned", False),
            our_growth=data.get("our_growth", 0.0),
            confidence=data.get("confidence", "中"),
            reasoning=data.get("reasoning", ""),
        )

    def validate(self) -> bool:
        """
        验证结果是否有效

        检查所有必需字段是否存在且有效。

        Returns:
            bool: 验证通过返回 True
        """
        # 检查增长率范围
        if not (-50.0 <= self.our_growth <= 100.0):
            return False

        # 检查置信度是否有效
        valid_confidence = {"高", "中", "低"}
        if self.confidence not in valid_confidence:
            return False

        # 检查推理文本非空
        if not self.reasoning:
            return False

        return True


class AuditSignal(BaseModel):
    """
    审计信号

    封装 Gap 计算和信号判定的结果。

    Attributes:
        signal: 信号类型 ("OPPORTUNITY", "OVERHEATED", "WAIT")
        gap: 认知差 = Our_Growth - Implied_Growth
        confidence: 信号置信度描述
    """

    signal: str = Field(
        ...,
        pattern="^(OPPORTUNITY|OVERHEATED|WAIT)$",
        description="信号类型",
    )
    gap: float = Field(..., description="认知差")
    confidence: str = Field(default="medium", description="信号置信度")

    @model_validator(mode="after")
    def set_confidence(self) -> "AuditSignal":
        """根据 gap 大小自动设置置信度"""
        abs_gap = abs(self.gap)
        if abs_gap >= 20:
            self.confidence = "high"
        elif abs_gap >= 10:
            self.confidence = "medium"
        else:
            self.confidence = "low"
        return self

    def is_actionable(self) -> bool:
        """
        判断信号是否可操作

        Returns:
            bool: OPPORTUNITY 或 OVERHEATED 时返回 True
        """
        return self.signal in ("OPPORTUNITY", "OVERHEATED")

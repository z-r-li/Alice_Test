"""
LLM 响应数据模型定义
"""
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResponse:
    """LLM 原始响应封装"""
    content: str  # 响应文本内容
    model: str  # 使用的模型
    usage: dict[str, int] | None = None  # Token 使用统计
    raw_response: Any = None  # 原始响应对象


@dataclass
class ConsensusResult:
    """
    Module A 输出：市场共识分析结果

    对应 PRD 5.3 节的 JSON Schema
    """
    sentiment_score: int  # 市场情绪评分 (0-100)
    implied_growth: float  # 市场隐含年化增长率 (百分数，如 5.0 表示 5%)
    key_narrative: str  # 市场主要叙事描述

    def validate(self) -> bool:
        """
        验证数据有效性

        Returns:
            bool: 数据是否有效
        """
        return (
            0 <= self.sentiment_score <= 100
            and -50.0 <= self.implied_growth <= 100.0
            and len(self.key_narrative) > 0
        )


@dataclass
class ThesisProjectionResult:
    """
    Module B 输出：信念投影结果

    对应 PRD 5.4 节的 JSON Schema
    """
    our_growth: float  # 我们预期的合理年化增长率 (百分数，如 15.0 表示 15%)
    reasoning: str  # 推导逻辑说明

    def validate(self) -> bool:
        """
        验证数据有效性

        Returns:
            bool: 数据是否有效
        """
        return -50.0 <= self.our_growth <= 100.0 and len(self.reasoning) > 0

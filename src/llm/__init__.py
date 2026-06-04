"""
LLM 模块

提供 LLM 调用封装和响应数据模型。
"""
from .deepseek_client import (
    DeepSeekClient,
    DeepSeekClientError,
    JSONParseError,
    APICallError,
    ContentModerationError,
)
from .models import (
    ConsensusResult,
    ThesisProjectionResult,
    LLMResponse,
    AuditSignal,
    # P1 多阶段流水线模型 (S1–S5)
    RefinedThesis,
    Evidence,
    LogicChainLink,
    LogicChain,
    ProxyAssignment,
    ProxyMapping,
    ThesisProjection,
)
from .prompts import PromptTemplates

__all__ = [
    # Client
    "DeepSeekClient",
    "DeepSeekClientError",
    "JSONParseError",
    "APICallError",
    "ContentModerationError",
    # Models
    "ConsensusResult",
    "ThesisProjectionResult",
    "LLMResponse",
    "AuditSignal",
    # P1 多阶段流水线模型 (S1–S5)
    "RefinedThesis",
    "Evidence",
    "LogicChainLink",
    "LogicChain",
    "ProxyAssignment",
    "ProxyMapping",
    "ThesisProjection",
    # Prompts
    "PromptTemplates",
]

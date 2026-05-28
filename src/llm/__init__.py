"""
LLM 模块

提供 LLM 调用封装和响应数据模型。
"""
from .deepseek_client import (
    DeepSeekClient,
    DeepSeekClientError,
    JSONParseError,
    JSONValidationError,
    APICallError,
    ContentModerationError,
)
from .models import (
    ConsensusResult,
    ThesisProjectionResult,
    LLMResponse,
    AuditSignalRecord,
)
from .prompts import PromptTemplates

__all__ = [
    # Client
    "DeepSeekClient",
    "DeepSeekClientError",
    "JSONParseError",
    "JSONValidationError",
    "APICallError",
    "ContentModerationError",
    # Models
    "ConsensusResult",
    "ThesisProjectionResult",
    "LLMResponse",
    "AuditSignalRecord",
    # Prompts
    "PromptTemplates",
]

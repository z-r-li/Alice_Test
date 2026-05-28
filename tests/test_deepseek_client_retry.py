"""
DeepSeekClient 重试 / 内容审核 / 模型切换路径测试。

通过依赖注入一个 mock 的 `OpenAI` 客户端，覆盖：
1. JSON 解析失败时的修复重试
2. 字段验证失败时的非格式重试（不附加 JSON_REPAIR_SUFFIX）
3. 内容审核错误的默认中性回退
4. 思考模式下对非思考别名的自动切换
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.llm.deepseek_client import (
    DeepSeekClient,
    JSONParseError,
    JSONValidationError,
    _NON_THINKING_ALIAS_TO_THINKING,
)
from src.llm.models import ConsensusResult, ThesisProjectionResult


def _make_response(content: str, model: str = "deepseek-v4-flash") -> MagicMock:
    message = MagicMock()
    message.content = content
    message.reasoning_content = None
    choice = MagicMock()
    choice.message = message
    usage = MagicMock(prompt_tokens=10, completion_tokens=10)
    resp = MagicMock(choices=[choice], usage=usage, model=model)
    return resp


def _good_consensus_payload(score: int = 35) -> str:
    return json.dumps(
        {
            "sentiment_score": score,
            "sentiment_label": "悲观",  # 会被 from_dict 重写为 score 推导出的标签
            "implied_growth": 5.0,
            "key_narrative": "这是一句话总结",
            "key_worry": "成本压力",
            "key_hope": "订单增长",
        }
    )


class _FakeChatCompletions:
    """模拟 client.chat.completions; create() 按调用顺序返回预设响应。"""

    def __init__(self, responses: list[MagicMock | Exception]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _make_fake_client(responses: list) -> MagicMock:
    fc = _FakeChatCompletions(responses)
    client = MagicMock()
    client.chat.completions = fc
    client.__fake_completions__ = fc
    return client


def test_chat_passes_model_override_through():
    """chat(model=...) 应覆盖默认 self._model。"""
    client = _make_fake_client([_make_response('{}')])
    ds = DeepSeekClient(api_key="x", model="deepseek-v4-flash", client=client)

    ds.chat("sys", "user", model="deepseek-v4-pro")

    assert client.__fake_completions__.calls[0]["model"] == "deepseek-v4-pro"


def test_thinking_auto_switches_deepseek_chat_to_reasoner():
    """思考模式下，deepseek-chat 应被自动切换为 deepseek-reasoner。"""
    assert _NON_THINKING_ALIAS_TO_THINKING["deepseek-chat"] == "deepseek-reasoner"
    client = _make_fake_client([_make_response('{}')])
    ds = DeepSeekClient(api_key="x", model="deepseek-chat", client=client)

    ds.chat("sys", "user", use_thinking=True)

    call = client.__fake_completions__.calls[0]
    assert call["model"] == "deepseek-reasoner"
    assert call["extra_body"] == {"thinking": {"type": "enabled"}}


def test_thinking_keeps_v4_flash_unchanged():
    """v4-flash 原生支持思考，不应被切换。"""
    client = _make_fake_client([_make_response('{}')])
    ds = DeepSeekClient(api_key="x", model="deepseek-v4-flash", client=client)

    ds.chat("sys", "user", use_thinking=True)

    assert client.__fake_completions__.calls[0]["model"] == "deepseek-v4-flash"


def test_json_parse_failure_retries_with_repair_suffix():
    """首次返回坏 JSON → 重试时应附加 JSON_REPAIR_SUFFIX。"""
    client = _make_fake_client(
        [
            _make_response("this is not json"),
            _make_response(_good_consensus_payload()),
        ]
    )
    ds = DeepSeekClient(api_key="x", client=client)

    result = ds.chat_with_json_output("sys", "user", ConsensusResult, max_retries=2)

    assert isinstance(result, ConsensusResult)
    # 第二次调用的 system prompt 应包含修复提示
    second_call_system = client.__fake_completions__.calls[1]["messages"][0]["content"]
    assert "无法解析为有效 JSON" in second_call_system


def test_validation_failure_does_not_add_repair_suffix():
    """字段验证失败（不是格式问题）时不应附加 JSON 修复提示。

    ThesisProjectionResult.validate() 要求 reasoning >= 10 字符；
    Pydantic 只要求 min_length=1，所以一个短 reasoning 能通过构造但被 validate 拒绝。
    """
    short_reasoning = json.dumps(
        {
            "thesis_aligned": True,
            "our_growth": 10.0,
            "confidence": "中",
            "reasoning": "短",  # 1 字符 → 通过 Pydantic，但 validate() False
        }
    )
    good = json.dumps(
        {
            "thesis_aligned": True,
            "our_growth": 12.0,
            "confidence": "中",
            "reasoning": "推理理由足够长以通过 validate 检查",
        }
    )
    client = _make_fake_client(
        [
            _make_response(short_reasoning),
            _make_response(good),
        ]
    )
    ds = DeepSeekClient(api_key="x", client=client)

    result = ds.chat_with_json_output(
        "sys", "user", ThesisProjectionResult, max_retries=2
    )

    assert isinstance(result, ThesisProjectionResult)
    # 第二次调用的 system prompt 不应附加 JSON 修复提示
    # （因为上一轮是 validation 失败，不是格式失败）
    second_call_system = client.__fake_completions__.calls[1]["messages"][0]["content"]
    assert "无法解析为有效 JSON" not in second_call_system


def test_content_moderation_falls_back_to_neutral():
    """内容审核错误时 get_consensus 应返回中性默认结果。"""
    error = Exception("Content Exists Risk")
    client = _make_fake_client([error])
    ds = DeepSeekClient(api_key="x", client=client)

    result = ds.get_consensus(
        ticker="AAPL",
        ticker_name="Apple",
        price_close=180.0,
        pe_ttm=30.0,
        pb=40.0,
        texts_content="某些可能触发审核的文本",
    )

    assert result.sentiment_score == 50
    assert result.sentiment_label == "中性"
    assert "内容审核" in result.key_narrative


def test_thesis_model_used_for_module_b():
    """get_thesis_projection 应使用 thesis_model 而不是默认 model。"""
    client = _make_fake_client(
        [
            _make_response(
                json.dumps(
                    {
                        "thesis_aligned": True,
                        "our_growth": 12.0,
                        "confidence": "中",
                        "reasoning": "理由足够长以通过验证逻辑",
                    }
                )
            )
        ]
    )
    ds = DeepSeekClient(
        api_key="x",
        model="deepseek-v4-flash",
        thesis_model="deepseek-v4-pro",
        client=client,
    )

    ds.get_thesis_projection(
        ticker="AAPL",
        ticker_name="Apple",
        user_thesis="AI 周期",
    )

    assert client.__fake_completions__.calls[0]["model"] == "deepseek-v4-pro"


def test_retry_exhaustion_raises_json_parse_error():
    """重试用尽后应抛出 JSONParseError。"""
    client = _make_fake_client(
        [
            _make_response("garbage"),
            _make_response("still garbage"),
            _make_response("yet more garbage"),
        ]
    )
    ds = DeepSeekClient(api_key="x", client=client)

    with pytest.raises(JSONParseError):
        ds.chat_with_json_output("sys", "user", ConsensusResult, max_retries=2)


def test_sentiment_label_normalized_from_score():
    """from_dict 应根据 score 重写 label，丢弃可能不一致的 LLM 输出。"""
    # LLM 说 sentiment_score=85, sentiment_label="悲观" — 矛盾
    inconsistent = json.dumps(
        {
            "sentiment_score": 85,
            "sentiment_label": "悲观",  # 与 85 分不符，应被覆盖为"狂热"
            "implied_growth": 20.0,
            "key_narrative": "强烈乐观情绪",
            "key_worry": "估值过高",
            "key_hope": "AI 革命",
        }
    )
    result = ConsensusResult.from_dict(json.loads(inconsistent))
    assert result.sentiment_score == 85
    assert result.sentiment_label == "狂热"  # 由 score 强制推导
    assert result.validate() is True  # 一致性检查应通过

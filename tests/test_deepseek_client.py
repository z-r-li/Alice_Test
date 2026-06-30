"""DeepSeekClient §7 行为测试（LLM 模型 / thinking / effort 迁移）。

覆盖迁移计划 §7 待办 4 的客户端侧三条：
① 非 thinking 路径非零温度负例（应被拒）；
② thinking 路径 reasoning_effort 透传 + thinking enabled + 切 model_pro；
③ 确定性打分路径：非 thinking 分支显式 thinking disabled，且返回无 reasoning_content。

均用打桩的 ``chat.completions.create`` 捕获 kwargs，不触达真实网络。
"""
from types import SimpleNamespace

import pytest

from src.llm.deepseek_client import APICallError, DeepSeekClient


def _fake_response(content="{}", reasoning_content=None, model="deepseek-v4-flash"):
    """构造最小可用的 OpenAI 风格响应对象。"""
    message = SimpleNamespace(content=content, reasoning_content=reasoning_content)
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5)
    return SimpleNamespace(choices=[choice], model=model, usage=usage)


def _stub_create(client, monkeypatch, response):
    """打桩 client 的 create，返回捕获到的 kwargs dict（test 内可读）。"""
    captured: dict = {}

    def fake_create(**kwargs):
        captured.clear()
        captured.update(kwargs)
        return response

    monkeypatch.setattr(client._client.chat.completions, "create", fake_create)
    return captured


class TestNonThinkingTemperatureGuard:
    """① 非 thinking 关键路径（JSON 结构化）非零温度应被拒，且不发起调用。"""

    def test_json_non_thinking_nonzero_temp_rejected(self, monkeypatch):
        client = DeepSeekClient(api_key="test-key", temperature=0.0)
        captured = _stub_create(client, monkeypatch, _fake_response())

        with pytest.raises(APICallError) as exc_info:
            client.chat("sys", "user", json_mode=True, temperature=0.5)

        assert "temperature" in str(exc_info.value)
        # fail-fast：拒绝发生在真正调用之前，未触达 create
        assert captured == {}


class TestThinkingEffortPassthrough:
    """② thinking 路径：effort 透传 + thinking enabled + 用 model_pro + 不传 temperature。"""

    def test_thinking_passes_effort_and_enabled(self, monkeypatch):
        client = DeepSeekClient(
            api_key="test-key",
            model="deepseek-v4-flash",
            model_pro="deepseek-v4-pro",
            reasoning_effort="high",
        )
        captured = _stub_create(
            client, monkeypatch, _fake_response(reasoning_content="思考…")
        )

        client.chat("sys", "user", use_thinking=True)

        assert captured["model"] == "deepseek-v4-pro"
        # reasoning_effort 与 thinking 同走 extra_body（兼容老版 SDK，避免顶层 kwarg TypeError）
        assert captured["extra_body"] == {
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
        }
        assert "reasoning_effort" not in captured  # 不作为顶层 create() kwarg 透传
        # thinking 下 temperature 为 no-op，不应透传
        assert "temperature" not in captured

    def test_per_call_effort_override(self, monkeypatch):
        client = DeepSeekClient(api_key="test-key", reasoning_effort="high")
        captured = _stub_create(client, monkeypatch, _fake_response())

        client.chat("sys", "user", use_thinking=True, reasoning_effort="max")

        assert captured["extra_body"]["reasoning_effort"] == "max"
        assert "reasoning_effort" not in captured  # 仍只走 extra_body


class TestDeterministicPathExplicitDisabled:
    """③ 非 thinking 打分路径：显式 thinking disabled，返回无 reasoning_content。"""

    def test_non_thinking_sends_thinking_disabled(self, monkeypatch):
        client = DeepSeekClient(
            api_key="test-key", model="deepseek-v4-flash", temperature=0.0
        )
        # 显式 disabled 后服务端不再返回 reasoning_content（见 §2/待办 0 真调用核实）
        captured = _stub_create(
            client, monkeypatch, _fake_response(reasoning_content=None)
        )

        resp = client.chat("sys", "user", json_mode=True)

        assert captured["model"] == "deepseek-v4-flash"
        assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
        assert captured["temperature"] == 0.0
        # 确定性路径：无思维链
        assert resp.reasoning_content is None

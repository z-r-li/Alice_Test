"""
PR-A fail-closed no-fabrication 层负例（C1 / C2 / M10）——单元 / 引擎 / 客户端层。

口径：缺核心增长字段、内容审核拒绝、空文本 **绝不**被洗成可计算增长率 / gap，
而是抛错（触发重试 / 由调用方 fail-closed）。完全离线、确定性。
主流程（main）层的 fail-closed 行为见 test_main_pipeline_wiring.py。
"""
from datetime import datetime

import pytest

from src.data_ingestion.models import QuoteData, TextItem, TickerRawData
from src.engines.consensus_engine import ConsensusEngine, InsufficientDataError
from src.llm.deepseek_client import (
    ContentModerationError,
    DeepSeekClient,
    JSONParseError,
)
from src.llm.models import (
    ConsensusResult,
    ThesisProjection,
    ThesisProjectionResult,
)


# ============================================================
# C1：缺核心增长字段不得补 0.0
# ============================================================


class TestC1MissingCoreGrowthRaises:
    def test_consensus_missing_implied_growth_raises(self):
        with pytest.raises(ValueError):
            ConsensusResult.from_dict({
                "sentiment_score": 50, "sentiment_label": "中性",
                "key_narrative": "n", "key_worry": "w", "key_hope": "h",
            })

    def test_consensus_null_implied_growth_raises(self):
        with pytest.raises(ValueError):
            ConsensusResult.from_dict({
                "sentiment_score": 50, "sentiment_label": "中性",
                "implied_growth": None,
                "key_narrative": "n", "key_worry": "w", "key_hope": "h",
            })

    def test_consensus_explicit_zero_is_valid(self):
        """显式 0% 是有效值，不应被当成缺失而拒绝。"""
        r = ConsensusResult.from_dict({
            "sentiment_score": 50, "sentiment_label": "中性",
            "implied_growth": 0.0,
            "key_narrative": "n", "key_worry": "w", "key_hope": "h",
        })
        assert r.implied_growth == 0.0

    def test_consensus_alias_still_supported(self):
        """PRD 别名 implied_growth_rate 仍可映射（不回归 #）。"""
        r = ConsensusResult.from_dict({
            "sentiment_score": 50, "sentiment_label": "中性",
            "implied_growth_rate": 7.5,
            "key_narrative": "n", "key_worry": "w", "key_hope": "h",
        })
        assert r.implied_growth == 7.5

    def test_thesis_result_missing_our_growth_raises(self):
        with pytest.raises(ValueError):
            ThesisProjectionResult.from_dict({
                "thesis_aligned": True, "confidence": "中",
                "reasoning": "一段足够长的推理说明文本。",
            })

    def test_thesis_projection_missing_our_growth_raises(self):
        with pytest.raises(ValueError):
            ThesisProjection.from_dict({
                "thesis_aligned": True, "confidence": "中",
                "reasoning": "一段足够长的推理说明文本。",
            })

    def test_thesis_result_explicit_zero_is_valid(self):
        r = ThesisProjectionResult.from_dict({
            "thesis_aligned": True, "our_growth": 0.0, "confidence": "低",
            "reasoning": "一段足够长的推理说明文本。",
        })
        assert r.our_growth == 0.0


class TestC1ParseLayerFailsClosed:
    """解析层：缺字段 → JSONParseError（chat_with_json_output 据此重试 / 最终 fail-closed）。"""

    def test_parse_consensus_missing_field_raises_jsonparseerror(self):
        client = DeepSeekClient(api_key="dummy")
        bad = (
            '{"sentiment_score": 50, "sentiment_label": "中性", '
            '"key_narrative": "n", "key_worry": "w", "key_hope": "h"}'
        )
        with pytest.raises(JSONParseError):
            client._parse_json_response(bad, ConsensusResult)

    def test_parse_thesis_missing_field_raises_jsonparseerror(self):
        client = DeepSeekClient(api_key="dummy")
        bad = '{"thesis_aligned": true, "confidence": "中", "reasoning": "够长的推理说明文本。"}'
        with pytest.raises(JSONParseError):
            client._parse_json_response(bad, ThesisProjectionResult)


# ============================================================
# C2a：内容审核失败 fail-closed（不编造 5.0）
# ============================================================


class TestC2ContentModerationFailsClosed:
    def _client_raising(self, monkeypatch):
        client = DeepSeekClient(api_key="dummy")

        def _raise(*a, **k):
            raise ContentModerationError("Content Exists Risk")

        monkeypatch.setattr(client, "chat", _raise)
        return client

    def test_get_consensus_raises_instead_of_fabricating(self, monkeypatch):
        client = self._client_raising(monkeypatch)
        with pytest.raises(ContentModerationError):
            client.get_consensus("X", "N", 10.0, 18.0, 2.0, "外部资讯")

    def test_get_thesis_projection_raises_instead_of_fabricating(self, monkeypatch):
        client = self._client_raising(monkeypatch)
        with pytest.raises(ContentModerationError):
            client.get_thesis_projection("X", "N", "信念")


# ============================================================
# C2b：空文本 / 全空摘要 fail-closed（不以占位符调用 LLM）
# ============================================================


class _SpyLLM:
    """记录是否被调用的假 LLM；get_consensus 一旦被调用即判失败。"""

    def __init__(self):
        self.called = False

    def get_consensus(self, **kwargs):
        self.called = True
        raise AssertionError("空文本路径不应调用 LLM")


def _raw(texts):
    return TickerRawData(
        date=datetime(2026, 6, 27),
        ticker="601985.SH",
        name="中国核电",
        quote=QuoteData(
            date=datetime(2026, 6, 27), ticker="601985.SH",
            price_close=10.0, pe_ttm=18.0, pb=2.0,
        ),
        texts=texts,
        status="ok",
    )


class TestC2EmptyTextFailsClosed:
    def test_no_texts_raises_and_skips_llm(self):
        spy = _SpyLLM()
        engine = ConsensusEngine(spy)
        with pytest.raises(InsufficientDataError):
            engine.analyze(_raw([]))
        assert spy.called is False

    def test_all_blank_summaries_raises_and_skips_llm(self):
        spy = _SpyLLM()
        engine = ConsensusEngine(spy)
        texts = [
            TextItem(
                source="s", type="news", title="t", summary="   ",
                url="u", published_at=datetime(2026, 6, 27),
            )
        ]
        with pytest.raises(InsufficientDataError):
            engine.analyze(_raw(texts))
        assert spy.called is False

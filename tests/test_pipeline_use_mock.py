"""验证 `crawler.use_mock=True` 实际生效（跳过外部数据源）。"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from src.config.models import AppConfig, TargetConfig
from src.engines.gap_calculator import AuditSignal
from src.llm.models import ConsensusResult, ThesisProjectionResult


def _stub_llm(consensus_payload: ConsensusResult, thesis_payload: ThesisProjectionResult) -> MagicMock:
    """构造一个绕过 OpenAI 的 LLM 客户端，按方法返回预设结果。"""
    client = MagicMock()
    client.get_consensus.return_value = consensus_payload
    client.get_thesis_projection.return_value = thesis_payload
    return client


def test_use_mock_skips_external_quote_and_text_sources():
    """use_mock=True 应使用 MockTextProvider 数据，并跳过真实行情源调用。"""
    from src.main import AliceTestPipeline

    config = AppConfig.model_validate(
        {
            "llm_api": {"api_key": "test"},
            "data_sources": {
                "crawler": {"use_mock": True, "lookback_hours": 48, "max_items_per_ticker": 5},
            },
            "targets": [
                {
                    "ticker": "601985.SH",  # MockTextProvider 有该 ticker 数据
                    "name": "中国核电",
                    "thesis": "AI 算力需要稳定基荷",
                }
            ],
        }
    )

    consensus = ConsensusResult(
        sentiment_score=50,
        sentiment_label="中性",
        implied_growth=5.0,
        key_narrative="market narrative ok",
        key_worry="worry text",
        key_hope="hope text",
    )
    thesis = ThesisProjectionResult(
        thesis_aligned=True,
        our_growth=10.0,
        confidence="中",
        reasoning="充足理由长度通过验证",
    )

    # 拦截真实 DeepSeek 客户端构造 + 真实 quotes provider 选择
    fake_llm = _stub_llm(consensus, thesis)
    with patch.object(AliceTestPipeline, "_create_llm_client", return_value=fake_llm):
        pipeline = AliceTestPipeline(config=config, ticker_filter="601985.SH")

        # 替换 quotes_provider 选择器为永远抛错的桩：use_mock 路径不应触达它
        def _explode(*_a, **_kw):
            raise AssertionError("use_mock=True 时不应调用真实行情源")

        pipeline._select_quotes_provider = _explode  # type: ignore[assignment]

        result = pipeline._process_single_target(config.targets[0])

    # use_mock 提供的固定 quote
    assert result.price == 100.0
    assert result.pe_ttm == 15.0
    # 流水线完整跑通，未触发 data_error
    assert result.status == "ok"
    assert result.signal in (AuditSignal.OPPORTUNITY, AuditSignal.WAIT, AuditSignal.OVERHEATED)
    # LLM 收到了非空的 consensus 输入（说明 MockTextProvider 返回了文本）
    fake_llm.get_consensus.assert_called_once()

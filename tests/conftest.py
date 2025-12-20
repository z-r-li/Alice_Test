"""
pytest fixtures for Alice Test

提供测试所需的共享 fixtures，包括：
- 配置对象
- 审计结果样例
- LLM 响应样例
- 临时文件路径
"""
import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from src.config.models import (
    AppConfig,
    GapThresholdConfig,
    LLMConfig,
    TargetConfig,
)
from src.engines.gap_calculator import AuditResult, AuditSignal
from src.llm.models import ConsensusResult, ThesisProjectionResult


# ============================================
# 配置相关 Fixtures
# ============================================


@pytest.fixture
def sample_target_config() -> TargetConfig:
    """示例标的配置"""
    return TargetConfig(
        ticker="601985.SH",
        name="中国核电",
        thesis="AI算力需要稳定基荷电力，核电是物理刚需",
        industry="电力",
    )


@pytest.fixture
def sample_gap_thresholds() -> GapThresholdConfig:
    """示例 Gap 阈值配置（默认值）"""
    return GapThresholdConfig(
        opportunity_gap_min=10.0,
        opportunity_sentiment_max=40,
        overheated_sentiment_min=80,
    )


@pytest.fixture
def sample_app_config(sample_target_config: TargetConfig) -> AppConfig:
    """示例应用配置"""
    return AppConfig(
        llm_api=LLMConfig(
            provider="deepseek",
            api_key="test-api-key",
            model="deepseek-chat",
            temperature=0.0,
        ),
        targets=[sample_target_config],
        gap_thresholds=GapThresholdConfig(),
    )


@pytest.fixture
def sample_config_dict() -> dict:
    """示例配置字典（用于 load_config_from_dict 测试）"""
    return {
        "llm_api": {
            "provider": "deepseek",
            "api_key": "test-key",
            "model": "deepseek-chat",
            "temperature": 0,
        },
        "targets": [
            {
                "ticker": "601985.SH",
                "name": "中国核电",
                "thesis": "核电是清洁能源的未来",
            }
        ],
        "gap_thresholds": {
            "opportunity_gap_min": 10.0,
            "opportunity_sentiment_max": 40,
            "overheated_sentiment_min": 80,
        },
    }


# ============================================
# LLM 模型相关 Fixtures
# ============================================


@pytest.fixture
def sample_consensus_result() -> ConsensusResult:
    """示例市场共识结果"""
    return ConsensusResult(
        sentiment_score=35,
        sentiment_label="悲观",
        implied_growth=5.0,
        key_narrative="市场担忧钢价上涨侵蚀利润",
        key_worry="钢材成本压力",
        key_hope="新船订单增长",
    )


@pytest.fixture
def sample_thesis_projection() -> ThesisProjectionResult:
    """示例信念投影结果"""
    return ThesisProjectionResult(
        thesis_aligned=True,
        our_growth=20.0,
        confidence="高",
        reasoning="在全球供应链重构与高端制造国产替代的背景下，船舶制造业将迎来长周期成长",
    )


@pytest.fixture
def sample_consensus_dict() -> dict:
    """示例 LLM 返回的共识结果字典"""
    return {
        "sentiment_score": 35,
        "sentiment_label": "悲观",
        "implied_growth_rate": 5.0,  # LLM 响应使用的字段名
        "key_narrative": "市场担忧钢价上涨侵蚀利润",
        "key_worry": "钢材成本压力",
        "key_hope": "新船订单增长",
    }


@pytest.fixture
def sample_thesis_dict() -> dict:
    """示例 LLM 返回的信念投影结果字典"""
    return {
        "thesis_aligned": True,
        "expected_growth_rate": 20.0,  # LLM 响应使用的字段名
        "confidence": "高",
        "reasoning": "在全球供应链重构与高端制造国产替代的背景下，船舶制造业将迎来长周期成长",
    }


# ============================================
# 审计结果相关 Fixtures
# ============================================


@pytest.fixture
def sample_audit_result(
    sample_consensus_result: ConsensusResult,
    sample_thesis_projection: ThesisProjectionResult,
) -> AuditResult:
    """示例审计结果"""
    return AuditResult(
        date=datetime(2024, 1, 15),
        ticker="600150.SH",
        name="中国船舶",
        price=35.50,
        pe_ttm=25.5,
        sentiment_score=sample_consensus_result.sentiment_score,
        sentiment_label=sample_consensus_result.sentiment_label,
        implied_growth=sample_consensus_result.implied_growth,
        key_narrative=sample_consensus_result.key_narrative,
        key_worry=sample_consensus_result.key_worry,
        key_hope=sample_consensus_result.key_hope,
        thesis_aligned=sample_thesis_projection.thesis_aligned,
        our_growth=sample_thesis_projection.our_growth,
        confidence=sample_thesis_projection.confidence,
        reasoning=sample_thesis_projection.reasoning,
        gap=15.0,  # 20.0 - 5.0
        signal=AuditSignal.OPPORTUNITY,
    )


@pytest.fixture
def sample_audit_result_overheated() -> AuditResult:
    """示例过热信号审计结果"""
    return AuditResult(
        date=datetime(2024, 1, 16),
        ticker="NVDA",
        name="英伟达",
        price=550.00,
        pe_ttm=65.0,
        sentiment_score=85,
        sentiment_label="狂热",
        implied_growth=30.0,
        key_narrative="AI 芯片需求爆发",
        key_worry="估值过高",
        key_hope="AI 长期增长",
        thesis_aligned=True,
        our_growth=25.0,
        confidence="中",
        reasoning="AI 芯片领导者但估值已反映预期",
        gap=-5.0,
        signal=AuditSignal.OVERHEATED,
    )


@pytest.fixture
def sample_audit_result_wait() -> AuditResult:
    """示例观望信号审计结果"""
    return AuditResult(
        date=datetime(2024, 1, 17),
        ticker="0700.HK",
        name="腾讯控股",
        price=320.00,
        pe_ttm=18.0,
        sentiment_score=50,
        sentiment_label="中性",
        implied_growth=12.0,
        key_narrative="游戏和广告业务稳定",
        key_worry="监管不确定性",
        key_hope="海外游戏增长",
        thesis_aligned=True,
        our_growth=15.0,
        confidence="中",
        reasoning="基本盘稳固但缺乏明显催化剂",
        gap=3.0,
        signal=AuditSignal.WAIT,
    )


# ============================================
# 文件系统相关 Fixtures
# ============================================


@pytest.fixture
def temp_dir() -> Path:
    """创建临时目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_csv_path(temp_dir: Path) -> Path:
    """临时 CSV 文件路径"""
    return temp_dir / "test_audit_report.csv"


@pytest.fixture
def temp_config_path(temp_dir: Path) -> Path:
    """临时配置文件路径"""
    return temp_dir / "test_config.yaml"


@pytest.fixture
def sample_config_yaml_content() -> str:
    """示例配置文件 YAML 内容"""
    return """
llm_api:
  provider: "deepseek"
  api_key: "test-api-key"
  model: "deepseek-chat"
  temperature: 0

targets:
  - ticker: "601985.SH"
    name: "中国核电"
    thesis: "核电是清洁能源的未来"

gap_thresholds:
  opportunity_gap_min: 10.0
  opportunity_sentiment_max: 40
  overheated_sentiment_min: 80
"""


# ============================================
# 环境变量相关 Fixtures
# ============================================


@pytest.fixture
def env_with_api_key(monkeypatch):
    """设置 DEEPSEEK_API_KEY 环境变量"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-test-api-key")
    yield
    # monkeypatch 会自动清理


@pytest.fixture
def env_with_tushare_token(monkeypatch):
    """设置 TUSHARE_TOKEN 环境变量"""
    monkeypatch.setenv("TUSHARE_TOKEN", "env-test-tushare-token")
    yield


@pytest.fixture
def clean_env(monkeypatch):
    """清理环境变量"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    yield

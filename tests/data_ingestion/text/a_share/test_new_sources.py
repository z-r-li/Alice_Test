"""
#65/#66 新增共识数据源测试：公告 (AnnouncementFetcher) + 财联社 (CLSNewsFetcher)

通过 monkeypatch.setattr 替换 akshare 接口（不污染 sys.modules，顺序无关），
验证解析 / 时间窗过滤 / 相关性过滤 / 优雅降级，以及协调器对新源的配额与聚合。
"""
from datetime import datetime, timedelta

import pandas as pd
import pytest

from src.config.models import AShareTextSourceConfig
from src.data_ingestion.models import TextItem
from src.data_ingestion.text.a_share.announcement_fetcher import AnnouncementFetcher
from src.data_ingestion.text.a_share.cls_news_fetcher import CLSNewsFetcher
from src.data_ingestion.text.a_share.coordinator import AShareTextCoordinator
from src.data_ingestion.text.a_share.profit_forecast_fetcher import (
    ProfitForecastFetcher,
)
from src.data_ingestion.text.models import SourceReachability


def _dt(hours_ago: int) -> str:
    return (datetime.now() - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")


def _patch_ak(monkeypatch, func_name: str, fn) -> None:
    """通过字符串目标 patch akshare 接口。

    用字符串目标让 pytest 在 patch 时解析当前 sys.modules["akshare"]，
    与 fetcher 内部「调用时 import akshare」解析到的是同一对象——
    即使其他测试把 akshare 替换成了 MagicMock，也能可靠生效（顺序无关）。
    """
    monkeypatch.setattr(f"akshare.{func_name}", fn, raising=False)


class TestAnnouncementFetcher:
    def test_parses_and_filters_window(self, monkeypatch):
        df = pd.DataFrame({
            "公告标题": ["关于核电项目核准的公告", "年度报告披露", "过期公告"],
            "公告时间": [_dt(5), _dt(20), _dt(500)],
            "公告类型": ["重大事项", "定期报告", "其他"],
            "公告链接": ["http://a", "http://b", "http://c"],
        })
        _patch_ak(monkeypatch, "stock_zh_a_disclosure_report_cninfo", lambda **k: df)
        items = AnnouncementFetcher().fetch_texts(
            "601985.SH", "中国核电", lookback_hours=48, max_items=10
        )
        assert len(items) == 2  # 500h 前的过期公告被过滤
        assert all(i.type == "news" and i.source == "巨潮公告" for i in items)
        assert items[0].published_at >= items[1].published_at  # 倒序

    def test_graceful_failure_returns_empty(self, monkeypatch):
        def boom(**k):
            raise RuntimeError("network down")

        _patch_ak(monkeypatch, "stock_zh_a_disclosure_report_cninfo", boom)
        assert AnnouncementFetcher().fetch_texts("601985.SH", "中国核电") == []

    def test_non_a_share_returns_empty(self):
        assert AnnouncementFetcher().fetch_texts("AAPL", "Apple") == []


class TestCLSNewsFetcher:
    def test_filters_by_name_or_symbol(self, monkeypatch):
        df = pd.DataFrame({
            "标题": ["中国核电签订大单", "某无关公司新闻", "601985 项目进展"],
            "内容": ["中国核电...", "无关...", "601985 核电..."],
            "发布时间": [_dt(2), _dt(3), _dt(4)],
        })
        _patch_ak(monkeypatch, "stock_info_global_cls", lambda: df)
        items = CLSNewsFetcher().fetch_texts(
            "601985.SH", "中国核电", lookback_hours=48, max_items=10
        )
        titles = [i.title for i in items]
        assert len(items) == 2  # 仅保留提及名称/代码的两条
        assert any("中国核电" in t for t in titles)
        assert all("无关公司" not in t for t in titles)
        assert all(i.source == "财联社" and i.type == "news" for i in items)

    def test_graceful_failure_returns_empty(self, monkeypatch):
        def boom():
            raise RuntimeError("cls down")

        _patch_ak(monkeypatch, "stock_info_global_cls", boom)
        assert CLSNewsFetcher().fetch_texts("601985.SH", "中国核电") == []

    def test_legacy_function_name_fallback(self, monkeypatch):
        # akshare 旧版只有 stock_telegraph_cls：新名缺失时应回退到旧名
        df = pd.DataFrame({
            "标题": ["中国核电电报"],
            "内容": ["中国核电..."],
            "发布时间": [_dt(2)],
        })
        monkeypatch.delattr("akshare.stock_info_global_cls", raising=False)
        _patch_ak(monkeypatch, "stock_telegraph_cls", lambda: df)
        items = CLSNewsFetcher().fetch_texts(
            "601985.SH", "中国核电", lookback_hours=48, max_items=10
        )
        assert len(items) == 1
        assert items[0].source == "财联社"

    def test_hanging_endpoint_times_out_and_degrades(self, monkeypatch):
        # 端点挂起（实测部分网络 >5min 无响应）→ 硬超时 → 优雅降级为空列表
        import time as _time

        def hang():
            _time.sleep(1.0)
            return pd.DataFrame()

        _patch_ak(monkeypatch, "stock_info_global_cls", hang)
        monkeypatch.setattr(CLSNewsFetcher, "FETCH_TIMEOUT_S", 0.1)
        assert CLSNewsFetcher().fetch_texts("601985.SH", "中国核电") == []


class TestProfitForecastFetcher:
    """#65：东财机构盈利预测获取器（可达，喂 implied_growth 素材）。"""

    def test_parses_forecast_rows(self, monkeypatch):
        df = pd.DataFrame({
            "机构": ["中信证券", "华泰证券"],
            "研究员": ["张三", "李四"],
            "报告日期": [
                (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d"),
                (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d"),
            ],
            "评级": ["买入", "增持"],
            "2025预测每股收益": ["0.45", "0.50"],
            "2026预测每股收益": ["0.55", "0.62"],
        })
        _patch_ak(monkeypatch, "stock_profit_forecast_em", lambda **k: df)
        items = ProfitForecastFetcher().fetch_texts(
            "601985.SH", "中国核电", lookback_hours=48, max_items=10
        )
        assert len(items) == 2
        assert all(i.source == "东财盈利预测" and i.type == "research" for i in items)
        # 不做 48h 硬过滤：盈利预测是一致预期，>48h 仍保留
        assert items[0].published_at >= items[1].published_at  # 倒序，最新在前
        assert "中信证券" in items[0].title or "中信证券" in items[0].summary
        assert "2025预测每股收益" in items[0].summary
        # 评级不带「评级:」冒号写法（避免被协调器误判为评级变动）
        assert "评级:" not in items[0].summary

    def test_market_table_cached_across_calls(self, monkeypatch):
        """全市场一致预期表整轮复用：多次 fetch 仅拉一次（symbol 为板块名，须取全表过滤）。"""
        calls = {"n": 0}
        df = pd.DataFrame({
            "代码": ["601985"], "名称": ["中国核电"],
            "研报数": ["5"], "2025预测每股收益": ["0.45"],
        })

        def fake(**k):
            calls["n"] += 1
            return df

        _patch_ak(monkeypatch, "stock_profit_forecast_em", fake)
        f = ProfitForecastFetcher()
        items1 = f.fetch_texts("601985.SH", "中国核电")
        items2 = f.fetch_texts("601985.SH", "中国核电")
        assert calls["n"] == 1  # 整表仅拉一次
        assert len(items1) == 1 and len(items2) == 1
        assert "研报数 5" in items1[0].summary

    def test_filters_market_wide_table_to_target(self, monkeypatch):
        df = pd.DataFrame({
            "股票代码": ["601985", "600000"],
            "股票简称": ["中国核电", "浦发银行"],
            "机构": ["甲", "乙"],
            "2025预测净利润": ["100", "200"],
        })
        _patch_ak(monkeypatch, "stock_profit_forecast_em", lambda **k: df)
        items = ProfitForecastFetcher().fetch_texts("601985.SH", "中国核电")
        assert len(items) == 1  # 仅保留本标的，避免串标的
        assert "甲" in items[0].summary

    def test_filter_code_authoritative_ignores_name_substring(self, monkeypatch):
        """代码列权威：精确匹配代码，名称子串（如「中国核电」⊂「中国核电建」）不串入。"""
        df = pd.DataFrame({
            "代码": ["601985", "601986"],
            "名称": ["中国核电", "中国核电建"],  # 第二行名称含目标名作为子串
            "机构": ["甲", "乙"],
            "2025预测每股收益": ["1", "2"],
        })
        _patch_ak(monkeypatch, "stock_profit_forecast_em", lambda **k: df)
        items = ProfitForecastFetcher().fetch_texts("601985.SH", "中国核电")
        assert len(items) == 1  # 仅精确代码匹配，不被名称子串串标的
        assert "甲" in items[0].summary

    def test_non_a_share_returns_empty(self):
        assert ProfitForecastFetcher().fetch_texts("AAPL", "Apple") == []

    def test_graceful_failure_returns_empty(self, monkeypatch):
        def boom(**k):
            raise RuntimeError("forecast endpoint down")

        _patch_ak(monkeypatch, "stock_profit_forecast_em", boom)
        assert ProfitForecastFetcher().fetch_texts("601985.SH", "中国核电") == []

    def test_empty_df_returns_empty(self, monkeypatch):
        _patch_ak(monkeypatch, "stock_profit_forecast_em", lambda **k: pd.DataFrame())
        assert ProfitForecastFetcher().fetch_texts("601985.SH", "中国核电") == []


class TestCoordinatorForecastSource:
    """#65：协调器接入盈利预测源（可达、计入覆盖度）。"""

    def test_default_config_enables_forecast(self):
        cfg = AShareTextSourceConfig()
        assert "forecast" in cfg.enabled_sources
        assert cfg.quota_weights["forecast"] == 3

    def test_forecast_aggregated_and_marked_reachable(self, monkeypatch):
        cfg = AShareTextSourceConfig(
            enabled_sources=["forecast"], quota_weights={"forecast": 3}
        )
        coord = AShareTextCoordinator(config=cfg)
        fc = TextItem(source="东财盈利预测", type="research", title="盈利预测 · 中信",
                      summary="机构 中信｜预测评级 买入", published_at=datetime.now(),
                      url=None)
        monkeypatch.setattr(coord._forecast_fetcher, "fetch_texts", lambda **k: [fc])

        items = coord.fetch_texts("601985.SH", "中国核电", max_items=10)
        assert any(i.source == "东财盈利预测" for i in items)
        cov = coord.get_last_coverage()
        assert "forecast" in cov.covered_sources
        frow = next(c for c in cov.per_source if c.source == "forecast")
        assert frow.reachability == SourceReachability.REACHABLE
        assert frow.attempted is True and frow.hit_count == 1


class TestCoordinatorNewSources:
    def test_default_config_enables_new_sources(self):
        cfg = AShareTextSourceConfig()
        assert "announcement" in cfg.enabled_sources
        assert "cls" in cfg.enabled_sources
        assert cfg.quota_weights["announcement"] == 2
        assert cfg.quota_weights["cls"] == 2

    def test_quota_allocates_to_new_sources(self):
        coord = AShareTextCoordinator(config=AShareTextSourceConfig())
        quotas = coord._calculate_quotas(16)
        assert "announcement" in quotas and quotas["announcement"] > 0
        assert "cls" in quotas and quotas["cls"] > 0

    def test_lookback_override_applied(self, monkeypatch):
        # 公告(cninfo)在 #65 reachability 下被判不可达；本测验证 lookback 透传机制，
        # 故关掉「不可达跳过」让其照常抓取（等价 P2 可达机器路径）。
        cfg = AShareTextSourceConfig(
            enabled_sources=["announcement"], quota_weights={"announcement": 1},
            lookback_hours=336, skip_unreachable_sources=False,
        )
        coord = AShareTextCoordinator(config=cfg)
        captured = {}

        def fake_fetch(**kwargs):
            captured["lookback_hours"] = kwargs.get("lookback_hours")
            return []

        monkeypatch.setattr(coord._announcement_fetcher, "fetch_texts", fake_fetch)
        coord.fetch_texts("601985.SH", "中国核电", lookback_hours=48, max_items=10)
        assert captured["lookback_hours"] == 336  # 配置覆盖了传入的 48

    def test_aggregates_new_source_items(self, monkeypatch):
        # 验证协调器能聚合新源的 items；公告(cninfo)默认被判不可达跳过，
        # 这里关掉跳过以测「两源都被聚合」的机制（P2 可达机器路径）。
        cfg = AShareTextSourceConfig(
            enabled_sources=["announcement", "cls"],
            quota_weights={"announcement": 1, "cls": 1},
            skip_unreachable_sources=False,
        )
        coord = AShareTextCoordinator(config=cfg)
        ann = TextItem(source="巨潮公告", type="news", title="公告A",
                       summary="s1", published_at=datetime.now(), url=None)
        cls = TextItem(source="财联社", type="news", title="电报B",
                       summary="s2", published_at=datetime.now(), url=None)
        monkeypatch.setattr(coord._announcement_fetcher, "fetch_texts", lambda **k: [ann])
        monkeypatch.setattr(coord._cls_fetcher, "fetch_texts", lambda **k: [cls])

        items = coord.fetch_texts("601985.SH", "中国核电", max_items=10)
        sources = {i.source for i in items}
        assert "巨潮公告" in sources
        assert "财联社" in sources

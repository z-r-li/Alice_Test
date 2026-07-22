"""特征窗**上界**护栏测试（look-ahead 泄露，CogAlpha 借鉴①·L1）

各 fetcher 的时间过滤只有下界（``published_at < cutoff → continue``，只挡太旧、零上界），
源时钟偏移或日期解析错产生的未来戳条目会直接进入 S2/S3 的 LLM 上下文。
护栏 ``TextProvider.drop_future_items`` 装在**两个并列聚合口**上：

- ``TextProviderFactory.fetch_texts``（mock 路径 + 港美股生产路径 + 直接调工厂的调用方）
- ``AShareTextCoordinator._collect``（A 股**生产**路径 —— ``main.py:940`` 直接调协调器，
  绕过工厂，故工厂单点无法覆盖）

不变量：``published_at > now`` 丢弃（闭边界：``== now`` 保留）、必留 WARNING、不 fail 整跑。

时区：naive ``published_at`` 的时区语义由**源站**决定 —— A 股 fetcher 用
``strptime`` 解析源站字符串，得到的是**北京墙上时间**；MockTextProvider 用本地
``datetime.now()``；HK/US 直接产出 aware UTC。护栏据 ``source_tz_for_market`` 归一成
绝对时刻再比较，故结果与部署机时区无关。本文件用**显式北京时**构造 A 股条目，
这样在任意时区的机器上跑都必须给出同样结论（曾经的真实缺陷：拿本地 naive now
直接比北京戳，UTC-4 机器上最近 12 小时的 A 股素材被整批误杀）。

全部离线、确定性。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from src.config.models import AShareTextSourceConfig
from src.data_ingestion.models import TextItem
from src.data_ingestion.text import TextProviderFactory
from src.data_ingestion.text.a_share.coordinator import AShareTextCoordinator
from src.data_ingestion.text.a_share.provider import AShareTextProvider
from src.data_ingestion.text.base import CHINA_TZ, TextProvider
from src.data_ingestion.text.models import FetchResult, TextSourceType

TICKER = "601985.SH"       # A 股：naive 戳按北京时解释
US_TICKER = "AAPL"         # 美股：naive 戳按部署机本地解释


def _item(title: str, published_at: datetime, source: str = "测试源") -> TextItem:
    return TextItem(
        source=source,
        type="news",
        title=title,
        summary="护栏测试用摘要",
        published_at=published_at,
        url="https://guard.example.com/x",
    )


def _beijing_now() -> datetime:
    """A 股 fetcher 的真实形态：naive 的**北京墙上时间**（strptime 解析源站字符串所得）。"""
    return datetime.now(CHINA_TZ).replace(tzinfo=None)


class _StubProvider(TextProvider):
    """返回固定条目的 stub provider（不触网），用于验证工厂聚合口的上界过滤。"""

    def __init__(self, items: list[TextItem]):
        self._items = items

    def fetch_texts(self, ticker, name, lookback_hours=48, max_items=10,
                    source_types=None) -> list[TextItem]:
        return list(self._items)

    def get_source_name(self) -> str:
        return "stub"

    def supports_market(self, ticker: str) -> bool:
        return True

    def get_supported_source_types(self) -> list[TextSourceType]:
        return []


@pytest.fixture(autouse=True)
def _reset_factory():
    TextProviderFactory.reset()
    yield
    TextProviderFactory.reset()


def _stub_factory(monkeypatch, items: list[TextItem]) -> None:
    """把工厂的 provider 解析替换为返回 items 的 stub。"""
    stub = _StubProvider(items)
    monkeypatch.setattr(
        TextProviderFactory, "get_provider", classmethod(lambda cls, *a, **kw: stub)
    )


class TestFactoryUpperBound:
    """聚合口①：TextProviderFactory.fetch_texts（A 股条目按北京时构造）"""

    def test_future_item_dropped_past_item_kept(self, monkeypatch):
        """未来戳被拦：北京时 now + 2h 的条目不返回，正常过去戳条目原样保留。"""
        now = _beijing_now()
        past = _item("正常过去戳研报", now - timedelta(hours=3))
        future = _item("未来戳条目", now + timedelta(hours=2))
        _stub_factory(monkeypatch, [past, future])

        texts = TextProviderFactory.fetch_texts(ticker=TICKER, name="中国核电")

        assert [t.title for t in texts] == ["正常过去戳研报"]
        # 保留的条目必须原样（未被改写时间戳 —— 拒收 ≠ 编造）
        assert texts[0].published_at == past.published_at

    def test_boundary_is_closed_not_killed(self, monkeypatch):
        """边界不误杀：published_at ≈ now（now − 1s）保留。"""
        now = _beijing_now()
        _stub_factory(monkeypatch, [
            _item("刚刚发布", now - timedelta(seconds=1)),
            _item("一分钟前", now - timedelta(minutes=1)),
        ])

        texts = TextProviderFactory.fetch_texts(ticker=TICKER, name="中国核电")

        assert [t.title for t in texts] == ["刚刚发布", "一分钟前"]

    def test_drop_emits_warning_with_count_and_ticker(self, monkeypatch, caplog):
        """丢弃必留告警（含丢弃条数与 ticker），绝不静默。"""
        now = _beijing_now()
        _stub_factory(monkeypatch, [
            _item("未来戳 A", now + timedelta(hours=2)),
            _item("未来戳 B", now + timedelta(days=400)),
            _item("正常", now - timedelta(hours=1)),
        ])

        with caplog.at_level(logging.WARNING, logger="alice_test"):
            texts = TextProviderFactory.fetch_texts(ticker=TICKER, name="中国核电")

        assert [t.title for t in texts] == ["正常"]
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any(f"[{TICKER}]" in m and "丢弃 2 条未来戳文本" in m for m in warnings), warnings

    def test_no_warning_when_nothing_dropped(self, monkeypatch, caplog):
        """全是过去戳时不得产生噪音告警。"""
        now = _beijing_now()
        _stub_factory(monkeypatch, [_item("正常", now - timedelta(hours=1))])

        with caplog.at_level(logging.WARNING, logger="alice_test"):
            texts = TextProviderFactory.fetch_texts(ticker=TICKER, name="中国核电")

        assert len(texts) == 1
        assert not [r for r in caplog.records if "未来戳" in r.getMessage()]

    def test_does_not_fail_the_run(self, monkeypatch):
        """不 fail 整跑：全部条目都是未来戳时返回空列表而非抛错。"""
        now = _beijing_now()
        _stub_factory(monkeypatch, [_item("未来戳", now + timedelta(hours=5))])

        assert TextProviderFactory.fetch_texts(ticker=TICKER, name="中国核电") == []

    def test_mock_path_reads_naive_stamps_as_local(self, monkeypatch):
        """use_mock 下 MockTextProvider 用本地 datetime.now() 盖戳，须按**本地**解释。

        若误按北京时解释，在 UTC+8 以东的机器上本地戳会被当成未来戳丢弃。
        """
        local_now = datetime.now()
        _stub_factory(monkeypatch, [
            _item("mock 本地过去戳", local_now - timedelta(hours=2)),
            _item("mock 本地未来戳", local_now + timedelta(hours=2)),
        ])

        texts = TextProviderFactory.fetch_texts(
            ticker=TICKER, name="中国核电", use_mock=True
        )

        assert [t.title for t in texts] == ["mock 本地过去戳"]

    def test_real_mock_provider_items_all_survive(self):
        """真实 MockTextProvider 的条目（本地 now − N 小时）不得被护栏误杀。"""
        texts = TextProviderFactory.fetch_texts(
            ticker=TICKER, name="中国核电", use_mock=True
        )

        assert len(texts) > 0
        assert all("mock.example.com" in (t.url or "") for t in texts)


class TestSourceTimezone:
    """naive 戳的时区语义由源站决定 —— 护栏结果必须与部署机时区无关。"""

    def test_fresh_a_share_item_survives_on_any_host_timezone(self, monkeypatch):
        """回归（曾经的 blocker）：北京时 5 分钟前发布的 A 股条目必须保留。

        缺陷形态：护栏拿 naive **本地** now 直接比 naive **北京** 戳。在 UTC-4 主机上
        北京戳比本地 now 大 12h，于是「最近 12 小时内发布」的最新素材（今日公告 / 财联社
        电报 / 当日评级）被整批判为未来戳丢弃，只剩 12–48h 的陈旧尾部。
        本用例不传 now，走护栏默认时钟，故只有「按源时区归一成绝对时刻」的实现才能通过。
        """
        beijing_now = _beijing_now()
        _stub_factory(monkeypatch, [
            _item("北京时 5 分钟前", beijing_now - timedelta(minutes=5)),
            _item("北京时 6 小时前", beijing_now - timedelta(hours=6)),
            _item("北京时 30 小时前", beijing_now - timedelta(hours=30)),
        ])

        texts = TextProviderFactory.fetch_texts(ticker=TICKER, name="中国核电")

        assert [t.title for t in texts] == [
            "北京时 5 分钟前", "北京时 6 小时前", "北京时 30 小时前"
        ]

    def test_a_share_future_still_caught_on_any_host_timezone(self, monkeypatch):
        """反向（鉴别力）：真·未来戳（北京时明天 / 年份 typo）仍必须被拦。"""
        beijing_now = _beijing_now()
        _stub_factory(monkeypatch, [
            _item("北京时明天", beijing_now + timedelta(days=1)),
            _item("年份 typo 成明年", beijing_now.replace(year=beijing_now.year + 1)),
            _item("北京时 1 小时前", beijing_now - timedelta(hours=1)),
        ])

        texts = TextProviderFactory.fetch_texts(ticker=TICKER, name="中国核电")

        assert [t.title for t in texts] == ["北京时 1 小时前"]

    def test_source_tz_for_market_mapping(self):
        """A 股 → 北京时；港美股 / 其他 → None（按本地，且其 provider 本就产出 aware UTC）。"""
        assert TextProvider.source_tz_for_market("601985.SH") == CHINA_TZ
        assert TextProvider.source_tz_for_market("000001.SZ") == CHINA_TZ
        assert TextProvider.source_tz_for_market("0700.HK") is None
        assert TextProvider.source_tz_for_market(US_TICKER) is None

    def test_source_tz_defaults_to_inference_from_ticker(self):
        """默认即安全：不传 source_tz 时按 ticker 推断，直接调护栏也不会误杀 A 股素材。

        默认值若退回「按本地解释」，直接调用方（绕开工厂/协调器接线）会静默重现该缺陷。
        """
        beijing_now = _beijing_now()
        fresh = _item("北京时 5 分钟前", beijing_now - timedelta(minutes=5))
        future = _item("北京时 5 小时后", beijing_now + timedelta(hours=5))

        # A 股 ticker：推断为北京时
        assert TextProvider.drop_future_items([fresh, future], TICKER) == [fresh]
        # 显式 None 仍可要求「按本地解释」（mock 路径用）
        local_fresh = _item("本地 5 分钟前", datetime.now() - timedelta(minutes=5))
        assert TextProvider.drop_future_items(
            [local_fresh], TICKER, source_tz=None) == [local_fresh]

    def test_naive_stamp_interpreted_in_declared_source_tz(self):
        """同一 naive 戳在不同 source_tz 下给出不同判定 —— 证明 source_tz 真正生效。"""
        now = datetime(2026, 7, 20, 10, 0, tzinfo=CHINA_TZ)   # 北京 10:00
        # naive 09:55：按北京时读 = now 前 5 分钟（保留）；按 UTC 读 = now 后 约 7h55m（丢弃）
        item = _item("09:55", datetime(2026, 7, 20, 9, 55))

        assert TextProvider.drop_future_items(
            [item], TICKER, now=now, source_tz=CHINA_TZ) == [item]
        assert TextProvider.drop_future_items(
            [item], TICKER, now=now, source_tz=timezone.utc) == []

    def test_comparison_is_on_instants_not_wall_clocks(self):
        """跨时区比较按绝对时刻：早 45 分钟发布的条目不因墙上时间回拨而被判未来。

        夏令时回拨那一小时里，「归一成本地 naive 再比」会把 01:45 EDT（更早）判成
        晚于 01:30 EST（更晚），从而误杀。按绝对时刻比则不会。
        """
        published = datetime(2026, 11, 1, 5, 45, tzinfo=timezone.utc)   # 01:45 EDT
        now = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)         # 01:30 EST，实际晚 45 分钟
        item = _item("回拨小时内发布", published)

        assert TextProvider.drop_future_items([item], US_TICKER, now=now) == [item]


class TestTimezoneMixedComparison:
    """naive / aware 混存不得抛 TypeError（HKUSTextProvider 用 datetime.now(timezone.utc)）。"""

    def test_aware_future_item_dropped_without_typeerror(self, monkeypatch):
        """aware(UTC) 的未来戳被丢弃，且不触发 naive-vs-aware 比较异常。"""
        aware_future = datetime.now(timezone.utc) + timedelta(hours=6)
        aware_past = datetime.now(timezone.utc) - timedelta(hours=6)
        _stub_factory(monkeypatch, [
            _item("aware 未来戳", aware_future, source="serper"),
            _item("aware 过去戳", aware_past, source="serper"),
        ])

        texts = TextProviderFactory.fetch_texts(ticker=US_TICKER, name="Apple")

        assert [t.title for t in texts] == ["aware 过去戳"]

    def test_aware_now_stamped_item_survives(self, monkeypatch):
        """HK/US 真实形态回归：搜索结果以 datetime.now(timezone.utc) 盖戳，不得被误杀。

        这是 hk_us_provider.py:186/:216 的实际写法。
        """
        _stub_factory(monkeypatch, [
            _item("搜索结果", datetime.now(timezone.utc), source="serper")
        ])

        texts = TextProviderFactory.fetch_texts(ticker=US_TICKER, name="Apple")

        assert [t.title for t in texts] == ["搜索结果"]

    def test_aware_and_naive_items_in_one_batch(self, monkeypatch):
        """同一批里混 naive 与 aware：各按各的语义判定，互不影响、不抛错。"""
        beijing_now = _beijing_now()
        _stub_factory(monkeypatch, [
            _item("naive 北京·过去", beijing_now - timedelta(hours=1)),
            _item("aware UTC·未来", datetime.now(timezone.utc) + timedelta(hours=5)),
            _item("aware UTC·过去", datetime.now(timezone.utc) - timedelta(hours=1)),
            _item("naive 北京·未来", beijing_now + timedelta(hours=5)),
        ])

        texts = TextProviderFactory.fetch_texts(ticker=TICKER, name="中国核电")

        assert [t.title for t in texts] == ["naive 北京·过去", "aware UTC·过去"]


class TestCoordinatorUpperBound:
    """聚合口②：A 股生产路径（main.py 直调协调器，绕过工厂）。"""

    @pytest.fixture
    def coordinator(self) -> AShareTextCoordinator:
        return AShareTextCoordinator(
            config=AShareTextSourceConfig(
                enabled_sources=["rating"],
                quota_weights={"rating": 1},
                skip_unreachable_sources=False,
            )
        )

    def test_future_item_dropped_on_a_share_path(self, coordinator, monkeypatch):
        """协调器聚合口同样拦未来戳——工厂单点覆盖不到 A 股生产路径。"""
        now = _beijing_now()
        monkeypatch.setattr(
            coordinator._rating_fetcher, "fetch_texts",
            lambda **kw: [
                _item("评级·未来戳", now + timedelta(hours=3), source="机构评级"),
                _item("评级·正常", now - timedelta(hours=3), source="机构评级"),
            ],
        )

        texts = coordinator.fetch_texts(ticker=TICKER, name="中国核电", max_items=10)

        assert [t.title for t in texts] == ["评级·正常"]

    def test_fresh_item_survives_on_a_share_path(self, coordinator, monkeypatch):
        """回归：协调器路径上北京时刚发布的条目不得被误杀（与工厂路径同一缺陷）。"""
        now = _beijing_now()
        monkeypatch.setattr(
            coordinator._rating_fetcher, "fetch_texts",
            lambda **kw: [_item("评级·5 分钟前", now - timedelta(minutes=5), source="机构评级")],
        )

        texts = coordinator.fetch_texts(ticker=TICKER, name="中国核电", max_items=10)

        assert [t.title for t in texts] == ["评级·5 分钟前"]

    def test_coverage_counts_exclude_dropped_items(self, coordinator, monkeypatch):
        """覆盖度统计在过滤之后：只抓到未来戳的源应记 empty / hit_count=0，而非 ok。

        否则「素材过薄」降级判断会被未来戳虚高，掩盖真实的素材不足。
        """
        now = _beijing_now()
        monkeypatch.setattr(
            coordinator._rating_fetcher, "fetch_texts",
            lambda **kw: [_item("评级·全是未来戳", now + timedelta(hours=3), source="机构评级")],
        )

        texts = coordinator.fetch_texts(ticker=TICKER, name="中国核电", max_items=10)

        assert texts == []
        coverage = coordinator.get_last_coverage()
        rating_row = next(r for r in coverage.per_source if r.source == "rating")
        assert rating_row.hit_count == 0
        assert rating_row.status == "empty"

    def test_future_rows_do_not_crowd_out_valid_rows_within_quota(
        self, coordinator, monkeypatch
    ):
        """Codex P2 回归：未来戳排在有效行之前时，不得因 fetcher 内部按 quota 截断而挤掉有效行。

        fetcher 内部先按 max_items 截断（含未来戳），再由本护栏丢弃未来戳——若不给配额余量，
        「未来戳 + 有效老行」在 quota=1 时会先被截成「只剩未来戳」，drop_future 后该源虚报 empty，
        窗内本有的有效素材凭空消失。本 fake 忠实模拟真实 fetcher 的 `results[:max_items]` 行为。
        """
        now = _beijing_now()
        # 源站按自报时间倒序：年份 typo 的未来戳排最前，两条有效老行在后
        full_response = [
            _item("未来戳(typo)", now + timedelta(days=365), source="机构评级"),
            _item("有效·2h前", now - timedelta(hours=2), source="机构评级"),
            _item("有效·5h前", now - timedelta(hours=5), source="机构评级"),
        ]
        # 忠实模拟 fetcher 内部截断：只返回前 max_items 条（含未来戳占位）
        monkeypatch.setattr(
            coordinator._rating_fetcher, "fetch_texts",
            lambda *, max_items, **kw: full_response[:max_items],
        )

        # 单源 quota=1：修复前 fetcher 只回未来戳→drop 后 empty；修复后多取余量→回有效行
        texts = coordinator.fetch_texts(ticker=TICKER, name="中国核电", max_items=1)

        assert [t.title for t in texts] == ["有效·2h前"]
        coverage = coordinator.get_last_coverage()
        rating_row = next(r for r in coverage.per_source if r.source == "rating")
        assert rating_row.hit_count == 1
        assert rating_row.status == "ok"

    def test_per_source_quota_still_capped_after_headroom(self, coordinator, monkeypatch):
        """配额语义不被余量破坏：多取只为吸收未来戳，最终每源仍截回真实 quota。"""
        now = _beijing_now()
        # 标题、摘要各不相同，避开协调器去重（标题相似>0.8 或 summary 相同即视为重复）
        specs = [
            ("券商研报速评", "结论：装机加速，看多", 1),
            ("重大合同公告", "中标核电主设备订单", 2),
            ("上证e互动问答", "回应产能扩张进度", 3),
            ("财联社电报", "签署长期供货协议", 4),
        ]
        full_response = [
            TextItem(source="机构评级", type="news", title=t, summary=s,
                     published_at=now - timedelta(hours=h), url="https://x/y")
            for t, s, h in specs
        ]
        monkeypatch.setattr(
            coordinator._rating_fetcher, "fetch_texts",
            lambda *, max_items, **kw: full_response[:max_items],
        )

        texts = coordinator.fetch_texts(ticker=TICKER, name="中国核电", max_items=2)

        # 单源 quota=2（唯一启用源，全额）：即便多取了余量，也只保留最新 2 条
        assert [t.title for t in texts] == ["券商研报速评", "重大合同公告"]


class TestFactoryAShareProviderPath:
    """工厂 A 股分支（AShareTextProvider）：与协调器同构的逐源配额，须同样加余量。

    生产上 A 股走协调器、不经工厂（main.py:940）；但 TextProviderFactory.fetch_texts 是
    文档化的公开便捷入口（其 docstring 即以 601985.SH 为例），直接调用方会命中
    AShareTextProvider —— 后者同样逐源分配 quota、各 fetcher 内部先截断，故同一挤占缺陷成立。
    """

    def _fake_fetch(self, full_response):
        """忠实模拟 fetcher.fetch 内部按 max_items 截断（含未来戳占位）。"""
        def fetch(*, max_items, **kw):
            return FetchResult(
                items=full_response[:max_items],
                source_type=TextSourceType.NEWS,
                success=True,
            )
        return fetch

    def test_future_rows_do_not_crowd_out_on_factory_a_share_path(self, monkeypatch):
        """回归（Codex 二次指出）：工厂 A 股路径同样不得因逐源截断挤掉窗内有效行。"""
        provider = TextProviderFactory.get_provider(TICKER)   # 真实 AShareTextProvider
        assert isinstance(provider, AShareTextProvider)
        now = _beijing_now()
        full_response = [
            _item("未来戳(typo)", now + timedelta(days=365)),
            _item("有效·2h前", now - timedelta(hours=2)),
            _item("有效·5h前", now - timedelta(hours=5)),
        ]
        monkeypatch.setattr(
            provider._news_fetcher, "fetch", self._fake_fetch(full_response)
        )

        # 只启用 news → quota=max_items=1；未来戳排最前，修复前该源被截成「只剩未来戳」→空
        texts = TextProviderFactory.fetch_texts(
            ticker=TICKER, name="中国核电", max_items=1,
            source_types=[TextSourceType.NEWS],
        )

        assert [t.title for t in texts] == ["有效·2h前"]

    def test_fresh_item_survives_on_factory_a_share_path(self, monkeypatch):
        """回归：工厂 A 股路径上北京时刚发布的条目不得被误杀。"""
        provider = TextProviderFactory.get_provider(TICKER)
        now = _beijing_now()
        monkeypatch.setattr(
            provider._news_fetcher, "fetch",
            self._fake_fetch([_item("刚发布·北京时", now - timedelta(minutes=5))]),
        )

        texts = TextProviderFactory.fetch_texts(
            ticker=TICKER, name="中国核电", max_items=1,
            source_types=[TextSourceType.NEWS],
        )

        assert [t.title for t in texts] == ["刚发布·北京时"]


class TestDropFutureItemsUnit:
    """护栏本体的直接单测（与聚合口接线解耦）。

    用美股 ticker：``source_tz_for_market`` 返回 None，naive 锚点与 naive 条目同按本地
    解释，边界断言因而与部署机时区无关。
    """

    def test_explicit_now_is_honored_and_boundary_is_closed(self):
        """显式 now 为上界，且 `<= now` 是**闭**边界：恰好等于 now 的条目保留。"""
        anchor = datetime(2026, 7, 19, 12, 0, 0)
        items = [
            _item("早于锚点", anchor - timedelta(seconds=1)),
            _item("等于锚点", anchor),
            _item("晚于锚点", anchor + timedelta(seconds=1)),
        ]

        kept = TextProvider.drop_future_items(items, US_TICKER, now=anchor)

        assert [t.title for t in kept] == ["早于锚点", "等于锚点"]

    def test_order_is_preserved(self):
        """保持原有顺序（护栏不得重排相关性/时间排序结果）。"""
        anchor = datetime(2026, 7, 19, 12, 0, 0)
        items = [
            _item("第三早", anchor - timedelta(hours=1)),
            _item("最早", anchor - timedelta(hours=9)),
            _item("被丢", anchor + timedelta(hours=1)),
            _item("居中", anchor - timedelta(hours=5)),
        ]

        kept = TextProvider.drop_future_items(items, US_TICKER, now=anchor)

        assert [t.title for t in kept] == ["第三早", "最早", "居中"]

    def test_empty_input_is_noop(self):
        assert TextProvider.drop_future_items([], TICKER) == []

    @pytest.mark.parametrize("ticker", [TICKER, US_TICKER])
    @pytest.mark.parametrize("published_at", [
        datetime(1, 1, 1),                              # datetime.min
        datetime(1900, 1, 1),
        datetime(1969, 12, 31),                         # 1970 年前：Windows 上的雷区
        datetime(1970, 1, 1),
        datetime(9999, 12, 31, 23, 59, 59),             # datetime.max
        datetime(1, 1, 1, tzinfo=timezone.utc),
        datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
    ])
    def test_extreme_timestamps_never_raise(self, published_at, ticker):
        """畸形/极端戳不得抛错 —— 「不 fail 整跑」是硬不变量。

        曾经的缺陷：naive 分支用 ``moment.astimezone()``，Windows 上对 1970 年前或
        超范围的 naive 值抛 ``OSError: [Errno 22]``（``datetime(1970,1,1).astimezone()``
        即抛）。护栏在协调器里位于 ``_fetch_with_fallback`` 的 try 之外，异常会一路冒到
        ``main._fetch_texts``，把该标的的**全部**文本清空。改为纯 ``replace(tzinfo=...)``
        后不再触平台 localtime。
        """
        item = _item("极端戳", published_at)

        kept = TextProvider.drop_future_items([item], ticker)

        # 只要求不抛错且判定确定：远古保留、远未来丢弃
        assert kept == ([] if published_at.year == 9999 else [item])

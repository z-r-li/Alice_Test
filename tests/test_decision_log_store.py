"""S7 决策日志 SQLite 存储测试（离线、确定性）。

三部分：
1. ``TestDecisionLogStore`` —— 自 Cowork 原型逐字迁入的 10 条决策日志单测
   （roundtrip/NULL 不编造、幂等 upsert、批量+过滤、point-in-time、结果 append-only、
   open 决策剔除、命中率默认剔 WAIT、IC 符号、外键拒孤儿、非法 action 抛错）。
2. ``TestSQLiteReportStore`` —— audit_reports SQLite 后端 roundtrip（替换原 NotImplementedError 桩）。
3. ``TestDecisionLogPipeline`` —— backend=sqlite 端到端 mock 流水线：每个标的（含 WAIT /
   fail-closed）在 decision_log 留一行可追溯记录（CDX-2 / P0-5）。
"""
from datetime import datetime

import pytest

from src.config import load_config_from_dict
from src.data_ingestion.models import QuoteData
from src.data_ingestion.text import TextProviderFactory
from src.engines.gap_calculator import AuditResult, AuditSignal
from src.persistence.sqlite_store import (
    SQLiteStore,
    SQLiteReportStore,
    DecisionEntry,
    OutcomeEntry,
    DEFAULT_CONFIDENCE_BASIS,
    DEFAULT_IC_OUTCOME_DEF,
)
from tests.fakes import FakeLLMClient


def _entry(**kw):
    base = dict(decision_id="601985-2026-06-29", asof_date="2026-06-29",
                ticker="601985", action="BUY")
    base.update(kw)
    return DecisionEntry(**base)


class TestDecisionLogStore:
    """决策日志 v0.1（原型 10 条单测逐字迁入，import 改指仓库内 store）。"""

    def test_roundtrip_and_nulls_not_fabricated(self):
        with SQLiteStore() as s:
            s.save_decision(_entry(our_growth=3.0, implied_growth=5.0, gap=-2.0,
                                   thesis_summary="核电装机加速", confidence_pct=60.0))
            r = s.get_decision("601985-2026-06-29")
            assert r["gap"] == -2.0
            assert r["confidence_basis"] == DEFAULT_CONFIDENCE_BASIS
            assert r["ic_outcome_def"] == DEFAULT_IC_OUTCOME_DEF
            # unknown fields must stay NULL, never coerced to 0.0
            assert r["our_alpha"] is None
            assert r["catalyst"] is None
            assert r["created_at"]  # auto-stamped

    def test_idempotent_upsert_by_decision_id(self):
        with SQLiteStore() as s:
            s.save_decision(_entry(action="WAIT"))
            s.save_decision(_entry(action="BUY", notes="re-run same day"))
            rows = s.get_decisions()
            assert len(rows) == 1               # not duplicated
            assert rows[0]["action"] == "BUY"   # updated in place
            assert rows[0]["notes"] == "re-run same day"

    def test_batch_and_filters(self):
        with SQLiteStore() as s:
            s.save_decisions([
                _entry(decision_id="a", ticker="601985", asof_date="2026-06-20"),
                _entry(decision_id="b", ticker="600150", asof_date="2026-06-29"),
                _entry(decision_id="c", ticker="601985", asof_date="2026-06-29"),
            ])
            assert len(s.get_decisions()) == 3
            assert len(s.get_decisions(ticker="601985")) == 2
            assert len(s.get_decisions(since="2026-06-25")) == 2
            assert len(s.get_decisions(until="2026-06-25")) == 1

    def test_point_in_time_by_created_at(self):
        with SQLiteStore() as s:
            s.save_decision(_entry(decision_id="early", created_at="2026-06-20T10:00:00Z"))
            s.save_decision(_entry(decision_id="late", created_at="2026-06-29T10:00:00Z"))
            # as of 2026-06-25 we had only logged "early"
            asof = s.get_decisions(asof="2026-06-25")
            assert [r["decision_id"] for r in asof] == ["early"]
            assert len(s.get_decisions(asof="2026-06-29")) == 2

    def test_outcomes_append_only_and_final(self):
        with SQLiteStore() as s:
            s.save_decision(_entry())
            s.record_outcome(OutcomeEntry(decision_id="601985-2026-06-29",
                                          horizon_label="30d", hit=1, excess_return=0.04))
            s.record_outcome(OutcomeEntry(decision_id="601985-2026-06-29",
                                          horizon_label="final", hit=1,
                                          excess_return=0.07, is_final=1))
            outs = s.get_outcomes("601985-2026-06-29")
            assert len(outs) == 2                     # both snapshots kept (append-only)
            assert sum(o["is_final"] for o in outs) == 1

    def test_open_decisions_excludes_resolved(self):
        with SQLiteStore() as s:
            s.save_decisions([_entry(decision_id="x"), _entry(decision_id="y")])
            s.record_outcome(OutcomeEntry(decision_id="x", is_final=1, hit=1))
            open_ids = [r["decision_id"] for r in s.get_open_decisions()]
            assert open_ids == ["y"]

    def test_hit_rate_excludes_wait_by_default(self):
        with SQLiteStore() as s:
            s.save_decision(_entry(decision_id="w", action="WAIT"))
            s.save_decision(_entry(decision_id="b1", action="BUY"))
            s.save_decision(_entry(decision_id="b2", action="BUY"))
            for did, hit in [("w", 0), ("b1", 1), ("b2", 0)]:
                s.record_outcome(OutcomeEntry(decision_id=did, is_final=1, hit=hit))
            assert s.hit_rate() == pytest.approx(0.5)            # only b1,b2 -> 1/2
            assert s.hit_rate(include_wait=True) == pytest.approx(1 / 3)

    def test_information_coefficient_sign(self):
        with SQLiteStore() as s:
            # gap perfectly rank-aligned with realized excess return -> IC = +1
            data = [(-2.0, -0.01), (1.0, 0.02), (5.0, 0.06), (8.0, 0.09)]
            for i, (gap, exc) in enumerate(data):
                did = f"t{i}"
                s.save_decision(_entry(decision_id=did, gap=gap))
                s.record_outcome(OutcomeEntry(decision_id=did, is_final=1, excess_return=exc))
            assert s.information_coefficient("gap") == pytest.approx(1.0)

    def test_foreign_key_blocks_orphan_outcome(self):
        with SQLiteStore() as s:
            with pytest.raises(Exception):
                s.record_outcome(OutcomeEntry(decision_id="does-not-exist", hit=1))

    def test_invalid_action_rejected(self):
        with SQLiteStore() as s:
            with pytest.raises(ValueError):
                s.save_decision(_entry(action="YOLO"))

    def test_upsert_preserves_original_created_at(self):
        # 同 decision_id 重跑：created_at 是 point-in-time 锚，必须保留首次入账时刻，
        # 否则旧决策会在「原入账 ~ 重跑」之间从历史快照里凭空消失。
        with SQLiteStore() as s:
            s.save_decision(_entry(created_at="2026-06-20T10:00:00Z"))
            s.save_decision(_entry(action="WAIT", notes="rerun later"))  # created_at 自动盖戳
            r = s.get_decision("601985-2026-06-29")
            assert r["created_at"] == "2026-06-20T10:00:00Z"   # 保留首次
            assert r["action"] == "WAIT"                       # 其余列照常更新
            # 截至 2026-06-25 的快照仍包含它（不因重跑而消失）
            assert len(s.get_decisions(asof="2026-06-25")) == 1

    def test_hit_rate_honors_date_window(self):
        with SQLiteStore() as s:
            s.save_decision(_entry(decision_id="old", action="BUY", asof_date="2026-05-01"))
            s.save_decision(_entry(decision_id="new", action="BUY", asof_date="2026-06-29"))
            s.record_outcome(OutcomeEntry(decision_id="old", is_final=1, hit=0))
            s.record_outcome(OutcomeEntry(decision_id="new", is_final=1, hit=1))
            assert s.hit_rate() == pytest.approx(0.5)                       # 全样本
            assert s.hit_rate(since="2026-06-01") == pytest.approx(1.0)     # 只剩 new
            assert s.hit_rate(until="2026-05-31") == pytest.approx(0.0)     # 只剩 old

    def test_open_decisions_excludes_future_with_asof(self):
        with SQLiteStore() as s:
            s.save_decision(_entry(decision_id="early", created_at="2026-06-20T10:00:00Z"))
            s.save_decision(_entry(decision_id="late", created_at="2026-06-29T10:00:00Z"))
            # 截至 2026-06-25：late 尚未入账，不应作为当时的 open 决策返回
            open_ids = [r["decision_id"] for r in s.get_open_decisions(asof="2026-06-25")]
            assert open_ids == ["early"]

    @pytest.mark.parametrize("bad", [
        dict(hit=2), dict(is_final=3), dict(realized_direction=5),
    ])
    def test_record_outcome_rejects_out_of_range(self, bad):
        with SQLiteStore() as s:
            s.save_decision(_entry())
            with pytest.raises(ValueError):
                s.record_outcome(OutcomeEntry(decision_id="601985-2026-06-29", **bad))

    def test_hit_rate_dedups_rescored_final(self):
        # append-only：同一决策被 re-score 留两条 is_final=1（hit=0 → backfill hit=1）。
        # 只能按最新 final 计一次 → 1.0；旧 SQL 会两条都计入得 0.5（污染）。
        with SQLiteStore() as s:
            s.save_decision(_entry(decision_id="b", action="BUY"))
            s.record_outcome(OutcomeEntry(decision_id="b", is_final=1, hit=0))
            s.record_outcome(OutcomeEntry(decision_id="b", is_final=1, hit=1))  # 修正
            assert s.hit_rate() == pytest.approx(1.0)

    def test_ic_dedups_rescored_final(self):
        # 两决策、其一被 re-score。去重后 (gap,-) 完美正序对齐 → IC=+1；
        # 不去重则混入旧 final 的反向 excess，IC 被污染。
        with SQLiteStore() as s:
            s.save_decision(_entry(decision_id="t0", gap=-2.0))
            s.save_decision(_entry(decision_id="t1", gap=5.0))
            s.record_outcome(OutcomeEntry(decision_id="t0", is_final=1, excess_return=0.01))
            s.record_outcome(OutcomeEntry(decision_id="t1", is_final=1, excess_return=-0.50))  # 错值
            s.record_outcome(OutcomeEntry(decision_id="t1", is_final=1, excess_return=0.09))   # 修正
            assert s.information_coefficient("gap") == pytest.approx(1.0)

    def test_hit_rate_latest_final_null_drops_decision(self):
        # 决策 A 最新 final 的 hit=NULL → 整条剔除，**不回退**到更早 final 的 hit=0；
        # 只剩 B(hit=1) → 1.0。若错误回退则 hits=[0,1]→0.5。
        with SQLiteStore() as s:
            s.save_decision(_entry(decision_id="A", action="BUY"))
            s.save_decision(_entry(decision_id="B", action="BUY"))
            s.record_outcome(OutcomeEntry(decision_id="A", is_final=1, hit=0))
            s.record_outcome(OutcomeEntry(decision_id="A", is_final=1, hit=None))  # 最新无值
            s.record_outcome(OutcomeEntry(decision_id="B", is_final=1, hit=1))
            assert s.hit_rate() == pytest.approx(1.0)

    def test_dedup_picks_max_outcome_id_not_observed_at(self):
        # 锁死去重轴 = max(outcome_id)（写入顺序），而非 observed_at（可乱序）。
        # 较早写入(outcome_id 小)的 final 带较晚 observed_at、hit=0；较晚写入的 hit=1。
        with SQLiteStore() as s:
            s.save_decision(_entry(decision_id="b", action="BUY"))
            s.record_outcome(OutcomeEntry(decision_id="b", is_final=1, hit=0,
                                          observed_at="2026-12-31T00:00:00Z"))
            s.record_outcome(OutcomeEntry(decision_id="b", is_final=1, hit=1,
                                          observed_at="2026-01-01T00:00:00Z"))
            assert s.hit_rate() == pytest.approx(1.0)   # 取后写入(hit=1)，不被 observed_at 误导


class TestSQLiteReportStore:
    """audit_reports SQLite 后端（原 NotImplementedError 桩 → 可用实现）。"""

    def test_save_and_get_roundtrip(self, sample_audit_result):
        with SQLiteReportStore(":memory:") as store:
            store.save(sample_audit_result)
            got = store.get_by_ticker(sample_audit_result.ticker)
            assert len(got) == 1
            r = got[0]
            assert r.ticker == sample_audit_result.ticker
            assert r.gap == pytest.approx(sample_audit_result.gap)
            assert r.signal is AuditSignal.OPPORTUNITY
            assert r.date.date() == sample_audit_result.date.date()

    def test_idempotent_upsert_by_date_ticker(self, sample_audit_result):
        with SQLiteReportStore(":memory:") as store:
            store.save(sample_audit_result)
            sample_audit_result.our_growth = 99.0  # 同 (date,ticker) 重写
            store.save(sample_audit_result)
            got = store.get_by_ticker(sample_audit_result.ticker)
            assert len(got) == 1                       # 未重复
            assert got[0].our_growth == pytest.approx(99.0)  # 覆盖更新

    def test_get_by_date_and_signal(self, sample_audit_result, sample_audit_result_wait):
        with SQLiteReportStore(":memory:") as store:
            store.save_batch([sample_audit_result, sample_audit_result_wait])
            assert len(store.get_by_signal("OPPORTUNITY")) == 1
            assert len(store.get_by_signal("WAIT")) == 1
            day = store.get_by_date(sample_audit_result.date)
            assert [r.ticker for r in day] == [sample_audit_result.ticker]

    def test_get_latest(self, sample_audit_result):
        with SQLiteReportStore(":memory:") as store:
            store.save(sample_audit_result)
            later = AuditResult(**{**sample_audit_result.__dict__,
                                   "date": datetime(2024, 6, 1), "our_growth": 30.0})
            store.save(later)
            latest = store.get_latest(sample_audit_result.ticker)
            assert latest.date.date() == datetime(2024, 6, 1).date()
            assert latest.our_growth == pytest.approx(30.0)

    def test_nan_normalized_to_null_and_list_fields_preserved(self, sample_audit_result):
        # fail-closed 行的 NaN 增长率：SQLite 在底层把 IEEE NaN 归一为 NULL（读回 None）——
        # 这是诚实的「未知」，绝非被造成 0.0；与 fail-closed 纪律一致。list 字段 JSON roundtrip。
        sample_audit_result.our_growth = float("nan")
        sample_audit_result.gap = float("nan")
        sample_audit_result.correlation_flags = ["600150.SH", "601985.SH"]
        sample_audit_result.structural_exit = ["核心政策逆转"]
        with SQLiteReportStore(":memory:") as store:
            store.save(sample_audit_result)
            r = store.get_by_ticker(sample_audit_result.ticker)[0]
            assert r.our_growth is None        # NaN → NULL（不编造 0.0）
            assert r.gap is None
            assert r.correlation_flags == ["600150.SH", "601985.SH"]
            assert r.structural_exit == ["核心政策逆转"]

    def test_decision_log_and_report_coexist_same_db(self, tmp_path, sample_audit_result):
        # D-20260629-1：决策日志与审计报告共用同一 DB 文件，互不干扰。
        db = str(tmp_path / "alice.db")
        with SQLiteReportStore(db) as report_store:
            report_store.save(sample_audit_result)
        with SQLiteStore(db) as dec_store:
            dec_store.save_decision(_entry())
            assert len(dec_store.get_decisions()) == 1
        with SQLiteReportStore(db) as report_store:
            assert len(report_store.get_by_ticker(sample_audit_result.ticker)) == 1


# ---- 端到端：backend=sqlite mock 流水线（待办 5） ---------------------------
class _FakeQuotesProvider:
    def get_quote(self, ticker, date=None):
        return QuoteData(
            date=datetime(2026, 6, 4), ticker=ticker,
            price_close=10.0, pe_ttm=18.0, pb=2.0,
        )

    def get_historical_quotes(self, ticker, start_date, end_date):
        return []

    def is_market_supported(self, ticker):
        return True


class _FailingQuotesProvider:
    def get_quote(self, ticker, date=None):
        raise RuntimeError("all quote sources down")

    def get_historical_quotes(self, ticker, start_date, end_date):
        return []

    def is_market_supported(self, ticker):
        return True


def _make_sqlite_pipeline(monkeypatch, tmp_path, *, our_growth=25.0,
                          implied_growth=8.0, targets=None):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    from src.main import AliceTestPipeline

    TextProviderFactory.reset()
    monkeypatch.setattr(
        AliceTestPipeline,
        "_create_llm_client",
        lambda self: FakeLLMClient(
            our_growth=our_growth, implied_growth=implied_growth, n_links=3,
        ),
    )
    db_path = tmp_path / "alice.db"
    config = load_config_from_dict({
        "data_sources": {"crawler": {"use_mock": True}},
        "financial_analysis": {"use_mock": True},
        "pipeline": {"enabled": True},
        "risk": {"enabled": True},
        "output": {
            "path": str(tmp_path / "out.csv"),
            "artifacts_dir": str(tmp_path / "artifacts"),
        },
        "persistence": {"backend": "sqlite", "sqlite_path": str(db_path)},
        "targets": targets if targets is not None else [
            {"ticker": "601985.SH", "name": "中国核电",
             "thesis": "AI算力需要稳定基荷电力，核电是物理刚需。", "industry": "电力"}
        ],
    })
    pipeline = AliceTestPipeline(config=config, output_path=tmp_path / "out.csv")
    monkeypatch.setattr(
        pipeline, "_select_quotes_provider", lambda ticker: _FakeQuotesProvider()
    )
    return pipeline, config, db_path


class TestDecisionLogPipeline:
    def test_opportunity_target_logs_buy_row(self, monkeypatch, tmp_path):
        pipeline, _config, db_path = _make_sqlite_pipeline(monkeypatch, tmp_path)
        results = pipeline.run()
        assert len(results) == 1
        assert results[0].signal is AuditSignal.OPPORTUNITY

        with SQLiteStore(str(db_path)) as store:
            rows = store.get_decisions()
        assert len(rows) == 1
        row = rows[0]
        assert row["decision_id"] == "601985.SH-" + results[0].date.strftime("%Y-%m-%d")
        assert row["action"] == "BUY"            # OPPORTUNITY → BUY 占位
        assert row["signal"] == "OPPORTUNITY"
        assert row["ticker"] == "601985.SH"
        assert row["market"] == "CN"
        assert row["benchmark"] == "沪深300"
        assert row["gap"] == pytest.approx(25.0 - 8.0)
        assert row["our_growth"] == pytest.approx(25.0)
        # 证伪条件来自 S1 kill_criteria（FakeLLMClient 固定值），经 structural_exit 落地
        assert row["falsification"] and "核心政策逆转" in row["falsification"]
        # thesis + 复现锚
        assert row["thesis_summary"]
        assert row["model_version"] == "deepseek-v4-flash"

    def test_wait_target_is_logged_too(self, monkeypatch, tmp_path):
        # gap=18-8=10，不 >10 → WAIT；WAIT 也必须留一行（广度 / 校准需要「看过即记」）。
        pipeline, _config, db_path = _make_sqlite_pipeline(
            monkeypatch, tmp_path, our_growth=18.0, implied_growth=8.0
        )
        results = pipeline.run()
        assert results[0].signal is AuditSignal.WAIT
        with SQLiteStore(str(db_path)) as store:
            rows = store.get_decisions()
        assert len(rows) == 1
        assert rows[0]["action"] == "WAIT"

    def test_fail_closed_row_logged_with_null_growth(self, monkeypatch, tmp_path):
        # 无文本 → fail-closed WAIT 行：our_growth/implied/gap 为 NaN → 决策日志存 NULL（不编造）。
        pipeline, _config, db_path = _make_sqlite_pipeline(monkeypatch, tmp_path)
        monkeypatch.setattr(pipeline, "_fetch_texts", lambda target: [])
        results = pipeline.run()
        assert results[0].status == "data_partial"
        with SQLiteStore(str(db_path)) as store:
            rows = store.get_decisions()
        assert len(rows) == 1
        assert rows[0]["action"] == "WAIT"
        assert rows[0]["our_growth"] is None       # NaN 不落库
        assert rows[0]["gap"] is None

    def test_idempotent_across_reruns(self, monkeypatch, tmp_path):
        pipeline, _config, db_path = _make_sqlite_pipeline(monkeypatch, tmp_path)
        pipeline.run()
        pipeline.run()  # 同交易日重跑
        with SQLiteStore(str(db_path)) as store:
            rows = store.get_decisions()
        assert len(rows) == 1                       # 幂等：未重复

    def test_multi_target_one_row_each(self, monkeypatch, tmp_path):
        targets = [
            {"ticker": "601985.SH", "name": "中国核电", "thesis": "核电刚需。", "industry": "电力"},
            {"ticker": "0700.HK", "name": "腾讯控股", "thesis": "社交基本盘稳。", "industry": "互联网"},
        ]
        pipeline, _config, db_path = _make_sqlite_pipeline(
            monkeypatch, tmp_path, targets=targets
        )
        results = pipeline.run()
        assert len(results) == 2
        with SQLiteStore(str(db_path)) as store:
            rows = store.get_decisions()
        assert {r["ticker"] for r in rows} == {"601985.SH", "0700.HK"}
        hk = next(r for r in rows if r["ticker"] == "0700.HK")
        assert hk["market"] == "HK"
        assert hk["benchmark"] == "HSI"

    def test_csv_backend_writes_no_decision_db(self, monkeypatch, tmp_path):
        # 默认 backend=csv：不创建决策日志 DB（开关关闭时零副作用）。
        pipeline, config, db_path = _make_sqlite_pipeline(monkeypatch, tmp_path)
        # 切回 csv 后端
        config.persistence.backend = "csv"
        pipeline.run()
        assert not db_path.exists()

    def test_degraded_opportunity_logged_wait_with_null_predictors(self, monkeypatch, tmp_path):
        # 行情全失败 → status=data_error，占位 price=0.0；gap/sentiment 仍判为 OPPORTUNITY。
        # 决策日志绝不能记 BUY（与审计「不可操作」矛盾），且预测子不得进 IC 样本 → 置 NULL。
        pipeline, _config, db_path = _make_sqlite_pipeline(monkeypatch, tmp_path)
        monkeypatch.setattr(
            pipeline, "_select_quotes_provider",
            lambda ticker: _FailingQuotesProvider(),
        )
        results = pipeline.run()
        assert results[0].status == "data_error"
        assert results[0].signal is AuditSignal.OPPORTUNITY  # 信号本身不被否决
        with SQLiteStore(str(db_path)) as store:
            rows = store.get_decisions()
            assert len(rows) == 1
            assert rows[0]["action"] == "WAIT"          # 降级行不记 BUY
            assert rows[0]["our_growth"] is None        # 非 ok → 预测子 NULL（不进 IC）
            assert rows[0]["implied_growth"] is None
            assert rows[0]["gap"] is None
            # 决策行仍留底（可追溯），但 gap=NULL → 不进 IC 样本（未被污染）
            assert store.information_coefficient("gap") is None

"""
Alice Test - Streamlit GUI

启动方式：
    streamlit run gui.py
或：
    streamlit run src/gui/app.py
"""
from __future__ import annotations

import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

# 支持 `streamlit run src/gui/app.py` 直接执行
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd
import streamlit as st
import yaml

from src.config import ConfigManager
from src.config.models import AppConfig, TargetConfig
from src.engines.gap_calculator import AuditResult, AuditSignal
from src.main import AliceTestPipeline
from src.persistence import CSVReportWriter
from src.utils import setup_logger


# =============================================================================
# 常量
# =============================================================================

KNOWN_DEEPSEEK_MODELS = [
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "deepseek-chat",      # 兼容别名 (将于 2026/07/24 弃用)
    "deepseek-reasoner",  # 兼容别名 (将于 2026/07/24 弃用)
]

SIGNAL_COLORS = {
    "OPPORTUNITY": "#16a34a",  # 绿
    "OVERHEATED": "#dc2626",   # 红
    "WAIT": "#6b7280",         # 灰
}

SIGNAL_EMOJI = {
    "OPPORTUNITY": "🟢",
    "OVERHEATED": "🔴",
    "WAIT": "⚪",
}


# =============================================================================
# 页面配置 + 会话状态
# =============================================================================

st.set_page_config(
    page_title="Alice Test · 认知差审计",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _init_session_state() -> None:
    defaults: dict = {
        "config": None,
        "config_path": "config.yaml",
        "config_dirty": False,
        "last_results": [],
        "run_log": [],
        "is_running": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# =============================================================================
# 配置加载 / 保存
# =============================================================================

def _load_config(path: str) -> AppConfig | None:
    try:
        return ConfigManager(path).load()
    except Exception as e:
        st.sidebar.error(f"加载失败: {e}")
        return None


def _save_config(config: AppConfig, path: str) -> bool:
    """将配置序列化回 YAML，保留示例文件的注释结构（简化版：覆盖写入）。"""
    try:
        data = config.model_dump(mode="json", exclude_defaults=False)
        # 写入前确保目录存在
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                data,
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=120,
            )
        return True
    except Exception as e:
        st.error(f"保存配置失败: {e}")
        return False


# =============================================================================
# 侧边栏
# =============================================================================

def render_sidebar() -> None:
    st.sidebar.title("📈 Alice Test")
    st.sidebar.caption("市场隐含预期与认知差自动审计")

    st.sidebar.divider()
    st.sidebar.subheader("📂 配置文件")
    st.session_state.config_path = st.sidebar.text_input(
        "config.yaml 路径",
        value=st.session_state.config_path,
        label_visibility="collapsed",
    )

    col1, col2 = st.sidebar.columns(2)
    if col1.button("🔄 加载", width="stretch"):
        cfg = _load_config(st.session_state.config_path)
        if cfg is not None:
            st.session_state.config = cfg
            st.session_state.config_dirty = False
            st.sidebar.success(f"已加载 {len(cfg.targets)} 个标的")

    if col2.button(
        "💾 保存",
        width="stretch",
        disabled=st.session_state.config is None,
    ):
        if _save_config(st.session_state.config, st.session_state.config_path):
            st.session_state.config_dirty = False
            st.sidebar.success("配置已保存")

    # API key status
    st.sidebar.divider()
    st.sidebar.subheader("🔑 凭据状态")
    has_key = bool(os.environ.get("DEEPSEEK_API_KEY"))
    if has_key:
        st.sidebar.success("DEEPSEEK_API_KEY ✓")
    else:
        st.sidebar.error("DEEPSEEK_API_KEY 未设置")
        st.sidebar.caption("可在下方设置（仅当前进程内生效）")
        key_input = st.sidebar.text_input(
            "临时设置 API Key",
            type="password",
            key="_apikey_input",
        )
        if st.sidebar.button("应用 API Key"):
            if key_input:
                os.environ["DEEPSEEK_API_KEY"] = key_input
                st.sidebar.success("已设置（仅当前会话）")
                st.rerun()

    tushare_ok = bool(os.environ.get("TUSHARE_TOKEN"))
    serper_ok = bool(os.environ.get("SERPER_API_KEY"))
    st.sidebar.caption(
        f"{'✓' if tushare_ok else '○'} TUSHARE_TOKEN · "
        f"{'✓' if serper_ok else '○'} SERPER_API_KEY"
    )

    if st.session_state.config_dirty:
        st.sidebar.warning("⚠️ 配置已修改但未保存")


# =============================================================================
# Tab 1: 监控标的
# =============================================================================

def render_targets_tab(config: AppConfig) -> None:
    st.subheader("📋 监控标的")
    st.caption("增删/编辑投资标的、宏观信念和预期增长率。修改后点击 **应用变更**。")

    if not config.targets:
        st.info("当前配置中没有标的，请在下方添加。")

    # 构造 DataFrame
    df = pd.DataFrame(
        [
            {
                "ticker": t.ticker,
                "name": t.name,
                "industry": t.industry,
                "thesis": t.thesis,
            }
            for t in config.targets
        ],
        columns=["ticker", "name", "industry", "thesis"],
    )

    edited = st.data_editor(
        df,
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        column_config={
            "ticker": st.column_config.TextColumn(
                "Ticker",
                help="A 股: 601985.SH / 港股: 0700.HK / 美股: AAPL",
                width="small",
                required=True,
            ),
            "name": st.column_config.TextColumn("名称", width="small", required=True),
            "industry": st.column_config.TextColumn(
                "行业", width="small", required=False
            ),
            "thesis": st.column_config.TextColumn(
                "投资信念 (Thesis)",
                help="多行文本：你对该标的的宏观/产业判断",
                width="large",
                required=True,
            ),
        },
        key="_targets_editor",
    )

    col1, col2, _ = st.columns([1, 1, 4])
    if col1.button("✅ 应用变更", type="primary"):
        try:
            new_targets: list[TargetConfig] = []
            for _, row in edited.iterrows():
                ticker = str(row["ticker"]).strip()
                name = str(row["name"]).strip()
                thesis = str(row["thesis"]).strip()
                if not ticker or not name or not thesis:
                    continue  # 跳过空行
                new_targets.append(
                    TargetConfig(
                        ticker=ticker,
                        name=name,
                        industry=str(row.get("industry") or "未知").strip() or "未知",
                        thesis=thesis,
                    )
                )
            config.targets = new_targets
            st.session_state.config_dirty = True
            st.success(f"已应用 {len(new_targets)} 个标的（点侧边栏 💾 保存到磁盘）")
        except Exception as e:
            st.error(f"应用变更失败: {e}")

    if col2.button("↺ 撤销"):
        st.rerun()


# =============================================================================
# Tab 2: LLM 与数据源设置
# =============================================================================

def render_settings_tab(config: AppConfig) -> None:
    st.subheader("⚙️ LLM 与阈值设置")

    llm = config.llm_api
    with st.expander("🤖 LLM 模型配置", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            current_model = llm.model
            model_options = list(dict.fromkeys([current_model, *KNOWN_DEEPSEEK_MODELS]))
            llm.model = st.selectbox(
                "Module A 模型 (市场共识)",
                options=model_options,
                index=model_options.index(current_model),
                help="处理新闻/研报情绪与隐含增长。推荐 deepseek-v4-flash。",
            )
        with col2:
            thesis_current = llm.thesis_model or llm.model
            thesis_options = list(dict.fromkeys([thesis_current, "", *KNOWN_DEEPSEEK_MODELS]))
            thesis_options_display = [
                "(同 Module A)" if o == "" else o for o in thesis_options
            ]
            selected_thesis_idx = st.selectbox(
                "Module B 模型 (信念投影)",
                options=range(len(thesis_options)),
                format_func=lambda i: thesis_options_display[i],
                index=thesis_options.index(llm.thesis_model)
                if llm.thesis_model in thesis_options
                else 0,
                help="可设为 deepseek-v4-pro 以获得更强推理能力。",
            )
            llm.thesis_model = thesis_options[selected_thesis_idx]

        col3, col4 = st.columns(2)
        llm.temperature = col3.number_input(
            "Temperature",
            min_value=0.0,
            max_value=2.0,
            value=float(llm.temperature),
            step=0.1,
            help="PRD 要求 0，保证评分稳定。",
        )
        llm.max_tokens = col4.number_input(
            "Max tokens",
            min_value=256,
            max_value=65536,
            value=int(llm.max_tokens),
            step=256,
        )

        col5, col6 = st.columns(2)
        llm.thesis_thinking_enabled = col5.checkbox(
            "Module B 启用思考模式",
            value=llm.thesis_thinking_enabled,
            help="启用后 token 消耗增加 2-3 倍，但推理更深入。",
        )
        llm.thesis_thinking_max_tokens = col6.number_input(
            "思考模式 max tokens",
            min_value=1024,
            max_value=65536,
            value=int(llm.thesis_thinking_max_tokens),
            step=1024,
            disabled=not llm.thesis_thinking_enabled,
        )

    with st.expander("📏 Gap 信号阈值", expanded=False):
        gt = config.gap_thresholds
        col1, col2, col3 = st.columns(3)
        gt.opportunity_gap_min = col1.number_input(
            "OPPORTUNITY: Gap 下限 (%)",
            value=float(gt.opportunity_gap_min),
            step=1.0,
        )
        gt.opportunity_sentiment_max = col2.number_input(
            "OPPORTUNITY: 情绪上限",
            min_value=0,
            max_value=100,
            value=int(gt.opportunity_sentiment_max),
            step=5,
        )
        gt.overheated_sentiment_min = col3.number_input(
            "OVERHEATED: 情绪下限",
            min_value=0,
            max_value=100,
            value=int(gt.overheated_sentiment_min),
            step=5,
        )

    with st.expander("📰 数据源", expanded=False):
        ds = config.data_sources
        col1, col2 = st.columns(2)
        ds.a_shares.provider = col1.selectbox(
            "A 股行情源",
            options=["akshare", "tushare"],
            index=["akshare", "tushare"].index(ds.a_shares.provider),
        )
        ds.crawler.lookback_hours = col2.number_input(
            "文本回溯时间 (小时)",
            min_value=1,
            max_value=8760,
            value=int(ds.crawler.lookback_hours),
            step=12,
        )
        ds.crawler.max_items_per_ticker = st.number_input(
            "每个标的最大文本数",
            min_value=1,
            max_value=200,
            value=int(ds.crawler.max_items_per_ticker),
            step=1,
        )
        ds.crawler.use_mock = st.checkbox(
            "开发模式 (Mock 数据)",
            value=ds.crawler.use_mock,
            help="启用后使用假数据，跳过真实 API 调用。",
        )

    if st.button("✅ 应用设置", type="primary"):
        st.session_state.config_dirty = True
        st.success("设置已应用（点侧边栏 💾 保存到磁盘）")


# =============================================================================
# Tab 3: 运行审计
# =============================================================================

def _result_to_row(r: AuditResult) -> dict:
    return {
        "信号": f"{SIGNAL_EMOJI.get(r.signal.value, '')} {r.signal.value}",
        "Ticker": r.ticker,
        "名称": r.name,
        "价格": round(r.price, 2),
        "PE(TTM)": round(r.pe_ttm, 2) if r.pe_ttm is not None else None,
        "情绪": r.sentiment_score,
        "情绪标签": r.sentiment_label,
        "隐含增长%": round(r.implied_growth, 1),
        "我们的预期%": round(r.our_growth, 1),
        "Gap%": round(r.gap, 1),
        "置信度": r.confidence,
        "市场叙事": r.key_narrative,
        "主要担忧": r.key_worry,
        "主要期待": r.key_hope,
        "推理": r.reasoning,
        "状态": r.status,
    }


def render_run_tab(config: AppConfig) -> None:
    st.subheader("▶️ 运行审计")

    if not config.targets:
        st.warning("当前没有可审计的标的，请先在 **监控标的** 标签页添加。")
        return

    col1, col2, col3 = st.columns([2, 1, 1])
    ticker_options = ["(全部)"] + [t.ticker for t in config.targets]
    selected = col1.selectbox("选择标的", options=ticker_options, index=0)
    output_path = col2.text_input("输出 CSV 路径", value=config.output.path)
    verbose = col3.checkbox("Verbose", value=False, help="打印 LLM 详细日志")

    if st.button(
        "🚀 开始审计",
        type="primary",
        disabled=st.session_state.is_running,
    ):
        st.session_state.is_running = True
        st.session_state.run_log = []
        try:
            _run_pipeline(config, selected, output_path, verbose)
        finally:
            st.session_state.is_running = False

    # 显示上一轮结果
    if st.session_state.last_results:
        st.divider()
        _render_results(st.session_state.last_results)


def _run_pipeline(
    config: AppConfig,
    selected_ticker: str,
    output_path: str,
    verbose: bool,
) -> None:
    """同步执行审计流水线，按标的更新进度。"""
    setup_logger(level=logging.DEBUG if verbose else logging.INFO)

    # 过滤目标
    if selected_ticker == "(全部)":
        targets = list(config.targets)
    else:
        targets = [t for t in config.targets if t.ticker == selected_ticker]

    if not targets:
        st.error(f"未找到标的 {selected_ticker}")
        return

    # 创建流水线
    try:
        pipeline = AliceTestPipeline(
            config=config,
            ticker_filter=selected_ticker if selected_ticker != "(全部)" else None,
            output_path=output_path,
            verbose=verbose,
        )
    except ValueError as e:
        st.error(f"流水线初始化失败: {e}")
        return

    # 进度条 + 状态
    progress = st.progress(0.0, text="准备中...")
    status_container = st.empty()
    results: list[AuditResult] = []

    for i, target in enumerate(targets, 1):
        progress.progress(
            (i - 1) / len(targets),
            text=f"[{i}/{len(targets)}] 处理 {target.ticker} ({target.name})...",
        )
        try:
            # 复用 AliceTestPipeline._process_single_target；它是稳定的内部接口
            result = pipeline._process_single_target(target)  # noqa: SLF001
            results.append(result)
            sig = result.signal.value
            status_container.success(
                f"✓ {target.ticker} → {SIGNAL_EMOJI.get(sig)} {sig} "
                f"(Gap {result.gap:+.1f}%, 情绪 {result.sentiment_score})"
            )
        except Exception as e:
            status_container.error(f"✗ {target.ticker}: {e}")
            if verbose:
                st.code(traceback.format_exc(), language="python")

    progress.progress(1.0, text=f"完成 {len(results)}/{len(targets)} 个标的")

    # 保存
    if results:
        try:
            writer = CSVReportWriter(output_path)
            writer.save_batch(results)
            st.toast(f"✅ 已保存到 {output_path}", icon="💾")
        except Exception as e:
            st.error(f"保存报告失败: {e}")

    st.session_state.last_results = results


def _render_results(results: list[AuditResult]) -> None:
    st.subheader("📊 本次结果")

    # 信号汇总
    counts: dict[str, int] = {"OPPORTUNITY": 0, "OVERHEATED": 0, "WAIT": 0}
    for r in results:
        counts[r.signal.value] = counts.get(r.signal.value, 0) + 1

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("总计", len(results))
    col2.metric("🟢 OPPORTUNITY", counts["OPPORTUNITY"])
    col3.metric("🔴 OVERHEATED", counts["OVERHEATED"])
    col4.metric("⚪ WAIT", counts["WAIT"])

    # 详细表格
    df = pd.DataFrame([_result_to_row(r) for r in results])
    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config={
            "情绪": st.column_config.ProgressColumn(
                "情绪",
                min_value=0,
                max_value=100,
                format="%d",
            ),
            "Gap%": st.column_config.NumberColumn("Gap%", format="%+.1f"),
        },
    )

    # 详情卡片
    with st.expander("🔍 详情（按标的）"):
        for r in results:
            sig = r.signal.value
            color = SIGNAL_COLORS.get(sig, "#6b7280")
            st.markdown(
                f"### {SIGNAL_EMOJI.get(sig)} `{r.ticker}` {r.name} "
                f"<span style='color:{color}'>{sig}</span>",
                unsafe_allow_html=True,
            )
            c1, c2, c3 = st.columns(3)
            c1.metric("Gap", f"{r.gap:+.1f}%")
            c2.metric("情绪", r.sentiment_score, r.sentiment_label)
            c3.metric("隐含 vs 我们", f"{r.implied_growth:.1f}% / {r.our_growth:.1f}%")
            st.markdown(f"**市场叙事：** {r.key_narrative}")
            st.markdown(f"**担忧：** {r.key_worry}")
            st.markdown(f"**期待：** {r.key_hope}")
            st.markdown(f"**Module B 推理 (置信 {r.confidence})：** {r.reasoning}")
            st.divider()


# =============================================================================
# Tab 4: 历史报告
# =============================================================================

def render_history_tab(config: AppConfig) -> None:
    st.subheader("📚 历史审计报告")

    csv_path = st.text_input("CSV 报告路径", value=config.output.path)
    if not Path(csv_path).exists():
        st.info(f"文件不存在: {csv_path}")
        return

    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        st.error(f"读取失败: {e}")
        return

    if df.empty:
        st.info("CSV 文件为空")
        return

    # 过滤器
    col1, col2 = st.columns(2)
    tickers = ["(全部)"] + sorted(df["ticker"].astype(str).unique().tolist())
    selected_ticker = col1.selectbox("Ticker", options=tickers)
    signals = ["(全部)"] + sorted(df["signal"].astype(str).unique().tolist())
    selected_signal = col2.selectbox("信号", options=signals)

    filtered = df
    if selected_ticker != "(全部)":
        filtered = filtered[filtered["ticker"] == selected_ticker]
    if selected_signal != "(全部)":
        filtered = filtered[filtered["signal"] == selected_signal]

    st.caption(f"共 {len(filtered)} 条记录")
    st.dataframe(filtered, width="stretch", hide_index=True)

    if selected_ticker != "(全部)" and "date" in filtered.columns:
        st.divider()
        st.subheader(f"📈 {selected_ticker} 趋势")
        try:
            trend = filtered.copy()
            trend["date"] = pd.to_datetime(trend["date"])
            trend = trend.sort_values("date")
            chart_cols = [
                c for c in ("sentiment_score", "implied_growth", "gap")
                if c in trend.columns
            ]
            if chart_cols:
                st.line_chart(trend.set_index("date")[chart_cols])
        except Exception as e:
            st.warning(f"绘图失败: {e}")


# =============================================================================
# 主入口
# =============================================================================

def main() -> None:
    _init_session_state()
    render_sidebar()

    st.title("📈 Alice Test")
    st.caption("市场隐含预期与认知差自动审计系统 · 配置 / 运行 / 查看历史")

    cfg: AppConfig | None = st.session_state.config
    if cfg is None:
        st.info(
            "👈 请在侧边栏点击 **加载** 读取 config.yaml，或先复制 "
            "`config.example.yaml` 为 `config.yaml`。"
        )
        with st.expander("快速上手"):
            st.markdown(
                """
                1. 在项目根目录复制示例配置：`cp config.example.yaml config.yaml`
                2. 设置环境变量：`export DEEPSEEK_API_KEY=sk-...`
                3. 在侧边栏点击 **🔄 加载**
                4. 进入 **▶️ 运行审计** 标签页，点击开始
                """
            )
        return

    tab1, tab2, tab3, tab4 = st.tabs(
        ["📋 监控标的", "⚙️ 设置", "▶️ 运行审计", "📚 历史报告"]
    )
    with tab1:
        render_targets_tab(cfg)
    with tab2:
        render_settings_tab(cfg)
    with tab3:
        render_run_tab(cfg)
    with tab4:
        render_history_tab(cfg)


if __name__ == "__main__":
    main()

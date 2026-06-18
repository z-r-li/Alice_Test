"""
Alice Test - 主程序入口

市场隐含预期与逻辑偏差自动审计系统
"""
import sys
from pathlib import Path

# 支持直接运行: python src/main.py
if __name__ == "__main__" and __package__ is None:
    # 将项目根目录添加到 Python 路径
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "src"

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal

from .config import ConfigManager, AppConfig, TargetConfig
from .data_ingestion import TickerRawData, QuoteData, TextItem
from .data_ingestion.quotes import (
    QuotesProvider,
    TushareQuotesProvider,
    AkShareQuotesProvider,
    YFinanceQuotesProvider,
    AShareYFinanceQuotesProvider,
    FallbackQuotesProvider,
)
from .data_ingestion.text import TextProviderFactory, TextSourceType
from .data_ingestion.text.a_share.coordinator import AShareTextCoordinator
from .data_ingestion.preprocessor import TextPreprocessor
from .data_ingestion.financials import get_financials_provider
from .engines import (
    ConsensusEngine,
    ThesisProjector,
    GapCalculator,
    AuditResult,
    FinancialAnalysisEngine,
    ThesisPipeline,
)
from .engines.thesis_pipeline import PipelineResult
from .llm import DeepSeekClient
from .persistence import CSVReportWriter, AuditReportStore, ArtifactStore
from .utils import setup_logger, AuditLogger, TextSanitizer


def _reconfigure_stdio() -> None:
    """将 stdout/stderr 切到 UTF-8（errors='replace'）。

    在 Windows GBK/cp936 等非 UTF-8 控制台下，打印 '✓'/'✗'(U+2713/U+2717) 等字符
    会触发 UnicodeEncodeError。该错误发生在审计完成、CSV 已落盘之后，却会把异常上抛、
    污染进程退出码，使每日 cron 把成功的运行误报为失败。

    Python 3.7+ 的 TextIOWrapper 提供 reconfigure；不可用或被重定向/包装的流则跳过，
    交由 _safe_print 兜底。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # 流不支持重配置（已分离/非真实 TextIO）：忽略
            pass


def _safe_print(*args, **kwargs) -> None:
    """print 包装：非 UTF-8 控制台下打印不可编码字符时退化为 errors='replace'。

    确保摘要打印永不抛 UnicodeEncodeError、不污染退出码——退出码只应反映审计结果。
    """
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_args = [
            a.encode(enc, "replace").decode(enc, "replace") if isinstance(a, str) else a
            for a in args
        ]
        print(*safe_args, **kwargs)


class AliceTestPipeline:
    """Alice Test 主流水线"""

    def __init__(
        self,
        config: AppConfig,
        ticker_filter: str | None = None,
        output_path: str | Path | None = None,
        verbose: bool = False,
    ):
        """
        初始化流水线

        Args:
            config: 应用配置
            ticker_filter: 指定单个标的（可选），仅处理该标的
            output_path: 输出文件路径（可选），覆盖配置中的路径
            verbose: 是否启用详细输出模式
        """
        self._config = config
        self._ticker_filter = ticker_filter.upper() if ticker_filter else None
        self._verbose = verbose
        self._logger = AuditLogger()
        self._py_logger = logging.getLogger("alice_test")

        # 输出路径
        if output_path:
            self._output_path = Path(output_path)
        else:
            self._output_path = Path(config.output.path)

        # 初始化组件
        self._llm_client = self._create_llm_client()
        self._sanitizer = TextSanitizer()
        self._consensus_engine = ConsensusEngine(
            self._llm_client, sanitizer=self._sanitizer
        )
        self._thesis_projector = ThesisProjector(
            self._llm_client, sanitizer=self._sanitizer
        )
        self._gap_calculator = GapCalculator(config.gap_thresholds)
        self._report_writer: AuditReportStore = CSVReportWriter(self._output_path)
        self._text_preprocessor = TextPreprocessor()

        # 初始化 A 股文本协调器
        self._text_coordinator = AShareTextCoordinator(
            config=self._config.data_sources.text.a_share,
            logger=self._py_logger,
        )

        # P1: S1–S5 多阶段流水线 + S4 财报分析 + 阶段产物持久化
        self._artifact_store = ArtifactStore(self._config.output.artifacts_dir)
        self._thesis_pipeline = self._build_thesis_pipeline()

    def _build_thesis_pipeline(self) -> ThesisPipeline | None:
        """构建多阶段信念流水线（pipeline.enabled=False 时回退单次 ThesisProjector）"""
        if not self._config.pipeline.enabled:
            return None

        a_cfg = self._config.data_sources.a_shares
        fin_cfg = self._config.financial_analysis

        fin_factory = None
        if fin_cfg.enabled:
            def fin_factory(ticker: str):
                return get_financials_provider(
                    ticker,
                    use_mock=fin_cfg.use_mock,
                    a_share_provider=a_cfg.provider,
                    tushare_token=(a_cfg.token or None),
                )

        return ThesisPipeline(
            self._llm_client,
            financials_provider_factory=fin_factory,
            financial_engine=FinancialAnalysisEngine(),
            sanitizer=self._sanitizer,
            artifact_store=self._artifact_store,
            logger=self._py_logger,
        )

    def _create_llm_client(self) -> DeepSeekClient:
        """创建 LLM 客户端"""
        llm_config = self._config.llm_api
        return DeepSeekClient(
            api_key=llm_config.get_api_key(),
            model=llm_config.model,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
            thinking_enabled=llm_config.thesis_thinking_enabled,
            thinking_max_tokens=llm_config.thesis_thinking_max_tokens,
        )

    def run(self) -> list[AuditResult]:
        """
        执行完整审计流程

        Returns:
            list[AuditResult]: 所有标的的审计结果
        """
        # 根据 ticker_filter 过滤标的
        targets = self._get_filtered_targets()

        if not targets:
            if self._ticker_filter:
                self._py_logger.error(
                    f"未找到标的 {self._ticker_filter}，请检查配置文件"
                )
            else:
                self._py_logger.warning("配置中没有标的可供审计")
            return []

        self._logger.start_run(len(targets))
        self._py_logger.info(f"开始审计 {len(targets)} 个标的...")

        if self._verbose:
            tickers = [t.ticker for t in targets]
            self._py_logger.debug(f"标的列表: {tickers}")

        results: list[AuditResult] = []
        success_count = 0
        error_count = 0

        for i, target in enumerate(targets, 1):
            self._py_logger.info(
                f"[{i}/{len(targets)}] 处理标的: {target.ticker} ({target.name})"
            )

            try:
                result = self._process_single_target(target)
                results.append(result)

                if result.status == "ok":
                    self._logger.log_success(target.ticker)
                    success_count += 1
                    if self._verbose:
                        self._py_logger.info(
                            f"  ✓ {target.ticker}: {result.signal.value}, "
                            f"Gap={result.gap:+.1f}%, "
                            f"Sentiment={result.sentiment_score}"
                        )
                else:
                    self._logger.log_data_error(target.ticker, result.status)
                    error_count += 1

            except Exception as e:
                error_count += 1
                self._logger.log_llm_error(target.ticker, str(e))
                self._py_logger.error(f"  ✗ {target.ticker}: {e}")

                if self._verbose:
                    import traceback
                    self._py_logger.debug(traceback.format_exc())

        # 保存结果
        if results:
            try:
                self._report_writer.save_batch(results)
                self._py_logger.info(f"审计报告已保存至: {self._output_path}")
            except Exception as e:
                self._py_logger.error(f"保存报告失败: {e}")

        # 输出统计信息
        stats = self._logger.end_run()
        self._print_summary(results, success_count, error_count)

        return results

    def _get_filtered_targets(self) -> list[TargetConfig]:
        """
        获取过滤后的标的列表

        Returns:
            list[TargetConfig]: 过滤后的标的列表
        """
        if self._ticker_filter:
            target = self._config.get_target_by_ticker(self._ticker_filter)
            return [target] if target else []
        return self._config.targets

    def _print_summary(
        self,
        results: list[AuditResult],
        success_count: int,
        error_count: int,
    ) -> None:
        """
        打印审计摘要

        Args:
            results: 审计结果列表
            success_count: 成功数量
            error_count: 错误数量
        """
        _safe_print("\n" + "=" * 60)
        _safe_print("审计摘要")
        _safe_print("=" * 60)
        _safe_print(f"总计: {len(results)} 个标的")
        _safe_print(f"成功: {success_count} | 错误: {error_count}")
        _safe_print("-" * 60)

        # 按信号分类统计
        signal_counts: dict[str, int] = {}
        for r in results:
            signal = r.signal.value
            signal_counts[signal] = signal_counts.get(signal, 0) + 1

        if signal_counts:
            _safe_print("信号分布:")
            for signal, count in sorted(signal_counts.items()):
                _safe_print(f"  {signal}: {count}")
            _safe_print("-" * 60)

        # 显示每个标的结果
        _safe_print("详细结果:")
        for r in results:
            status_icon = "✓" if r.status == "ok" else "✗"
            _safe_print(
                f"  {status_icon} {r.ticker:12} {r.name:10} | "
                f"{r.signal.value:12} | Gap: {r.gap:+6.1f}% | "
                f"Sentiment: {r.sentiment_score:3}"
            )

        _safe_print("=" * 60)

    def _process_single_target(self, target: TargetConfig) -> AuditResult:
        """
        处理单个标的的完整流程

        Args:
            target: 标的配置

        Returns:
            AuditResult: 审计结果
        """
        # Step 1: 数据摄入
        raw_data = self._ingest_data(target)

        # 检查是否有有效的文本数据，避免无意义的 LLM 调用
        if not raw_data.texts:
            self._py_logger.warning(
                f"[{target.ticker}] 无有效文本数据，跳过 LLM 分析"
            )
            # 记录为数据错误，但仍继续处理（使用默认值）

        # Step 2: Module A - 市场共识分析
        consensus = self._consensus_engine.analyze(raw_data)

        # Step 3: Module B - 信念投影
        # 默认走 S1–S5 多阶段流水线（ThesisPipeline），任一阶段失败其内部回退单次投影；
        # pipeline.enabled=False 时直接用单次 ThesisProjector。
        pipeline_result: PipelineResult | None = None
        if self._thesis_pipeline is not None:
            pipeline_result = self._thesis_pipeline.run(
                target,
                quote=raw_data.quote,
                texts=raw_data.texts,
                audit_date=raw_data.date,
            )
            thesis_projection = pipeline_result.to_projection_result()
        else:
            thesis_projection = self._thesis_projector.project(target)

        # Step 4: Gap 计算与信号判定（脊柱 gap = our_growth − implied_growth 不变）
        result = self._gap_calculator.compute_audit_result(
            ticker=target.ticker,
            name=target.name,
            price=raw_data.quote.price_close,
            pe_ttm=raw_data.quote.pe_ttm,
            consensus=consensus,
            thesis_projection=thesis_projection,
            audit_date=raw_data.date,
        )

        # 数据摄入降级（如行情全失败时的占位 price_close=0.0）必须传播到结果状态，
        # 否则基于占位数据的运行会被统计与落盘为 status="ok"
        if raw_data.status != "ok":
            result.status = "data_error"

        # P1: 附带多阶段流水线产物引用（向后兼容字段，不影响原 CSV 14 列）
        if pipeline_result is not None:
            result.artifact_dir = pipeline_result.artifact_dir
            result.evidence_summary = self._summarize_evidence(pipeline_result)
            if self._verbose and pipeline_result.due_diligence_queue:
                self._py_logger.info(
                    f"  [{target.ticker}] 尽调队列 {len(pipeline_result.due_diligence_queue)} 项"
                )

        return result

    @staticmethod
    def _summarize_evidence(pr: PipelineResult) -> str:
        """证据链 / 尽调队列一句话摘要（写入 AuditResult.evidence_summary）"""
        if not pr.used_pipeline:
            return "单次投影（流水线回退）"
        n = len(pr.evidence)
        supported = sum(1 for e in pr.evidence if e.supports)
        dd = len(pr.due_diligence_queue)
        summary = f"证据链 {n} 环节（支持 {supported}）；尽调队列 {dd} 项"
        # #8：thesis 无引擎可验证驱动时显式标注 our_growth 无定量锚（受限于 thesis，非数据缺失）
        if pr.no_quantitative_anchor:
            summary += "；our_growth 无定量锚（thesis 无引擎可验证驱动，经 S2 重试仍 n_quant=0）"
        return summary

    def _ingest_data(self, target: TargetConfig) -> TickerRawData:
        """
        数据摄入

        Args:
            target: 标的配置

        Returns:
            TickerRawData: 原始数据
        """
        ticker = target.ticker
        now = datetime.now()

        # 1. 获取行情数据
        quotes_provider = self._select_quotes_provider(ticker)
        try:
            quote = quotes_provider.get_quote(ticker)
            data_status: Literal["ok", "data_error", "partial"] = "ok"
            error_message = None
        except NotImplementedError:
            # 数据源未实现时，生成占位行情数据（开发阶段）
            self._py_logger.warning(
                f"[{ticker}] QuotesProvider 未实现，使用占位数据"
            )
            quote = QuoteData(
                date=now,
                ticker=ticker,
                price_close=0.0,
                pe_ttm=None,
                pb=None,
            )
            data_status = "data_error"
            error_message = "QuotesProvider 未实现"
        except Exception as e:
            self._py_logger.error(
                f"[{ticker}] 获取行情数据失败: {e}"
            )
            quote = QuoteData(
                date=now,
                ticker=ticker,
                price_close=0.0,
                pe_ttm=None,
                pb=None,
            )
            data_status = "data_error"
            error_message = str(e)

        # 2. 获取文本数据
        texts = self._fetch_texts(target)

        # 3. 组装返回
        return TickerRawData(
            date=now,
            ticker=ticker,
            name=target.name,
            quote=quote,
            texts=texts,
            status=data_status,
            error_message=error_message,
        )

    def _fetch_texts(self, target: TargetConfig) -> list[TextItem]:
        """
        获取文本数据

        对于 A 股使用 AShareTextCoordinator，其他市场使用 TextProviderFactory。

        Args:
            target: 标的配置

        Returns:
            list[TextItem]: 文本数据列表
        """
        try:
            # 从配置获取参数
            crawler_config = self._config.data_sources.crawler

            # 判断市场类型
            market = target.get_market()

            if crawler_config.use_mock:
                # 开发/离线模式：统一使用 Mock 文本数据，跳过真实数据源
                texts = TextProviderFactory.fetch_texts(
                    ticker=target.ticker,
                    name=target.name,
                    lookback_hours=crawler_config.lookback_hours,
                    max_items=crawler_config.max_items_per_ticker,
                    use_mock=True,
                )
            elif market == "a_share":
                # A 股使用协调器
                texts = self._text_coordinator.fetch_texts(
                    ticker=target.ticker,
                    name=target.name,
                    lookback_hours=crawler_config.lookback_hours,
                    max_items=crawler_config.max_items_per_ticker,
                )
                # #65 / §五 #9：素材覆盖度元数据可见——过薄时显式降级标注，供共识可信度判断
                get_cov = getattr(self._text_coordinator, "get_last_coverage", None)
                cov = get_cov() if callable(get_cov) else None
                if cov is not None and cov.is_thin:
                    self._py_logger.warning(
                        f"[{target.ticker}] A股共识素材覆盖度过薄: {cov.thin_reason}"
                        f"（覆盖源 {cov.covered_sources or '无'}, 未覆盖 {cov.uncovered_sources}）"
                    )
            else:
                # 港美股使用原有工厂方法
                texts = TextProviderFactory.fetch_texts(
                    ticker=target.ticker,
                    name=target.name,
                    lookback_hours=crawler_config.lookback_hours,
                    max_items=crawler_config.max_items_per_ticker,
                )

            if self._verbose:
                self._py_logger.debug(
                    f"[{target.ticker}] 获取 {len(texts)} 条文本"
                )

            return texts

        except Exception as e:
            self._py_logger.warning(
                f"[{target.ticker}] 文本获取失败: {e}"
            )
            return []

    def _select_quotes_provider(self, ticker: str) -> QuotesProvider:
        """
        根据 ticker 后缀选择合适的行情数据提供者

        Args:
            ticker: 证券代码

        Returns:
            QuotesProvider: 行情数据提供者实例

        规则：
            - .SH/.SZ 后缀 → A股，使用 TushareQuotesProvider 或 AkShareQuotesProvider
            - .HK 后缀 → 港股，使用 YFinanceQuotesProvider
            - 无后缀或其他 → 美股，使用 YFinanceQuotesProvider
        """
        ticker_upper = ticker.upper()

        if ticker_upper.endswith((".SH", ".SZ")):
            # A股市场
            a_share_provider = self._config.data_sources.a_shares.provider
            if a_share_provider == "tushare":
                token = self._config.data_sources.a_shares.get_token()
                return TushareQuotesProvider(api_token=token)
            else:
                # 东财行情在部分网络不可达（连接被远端重置），降级走
                # Yahoo A 股镜像（601985.SH→601985.SS，带 PE/PB），均为真实数据
                return FallbackQuotesProvider(
                    AkShareQuotesProvider(),
                    AShareYFinanceQuotesProvider(),
                )
        else:
            # 港股 (.HK) 或美股 (无后缀)
            return YFinanceQuotesProvider()


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Alice Test - 市场隐含预期与逻辑偏差自动审计系统"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="配置文件路径 (默认: config.yaml)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="audit_report.csv",
        help="输出报告路径 (默认: audit_report.csv)",
    )
    parser.add_argument(
        "--ticker",
        type=str,
        help="只处理指定标的 (可选)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="详细输出模式",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="启用 DEBUG 级别日志（显示 LLM 原始响应等调试信息）",
    )
    return parser.parse_args()


def main() -> None:
    """主入口函数"""
    # 优先把控制台切到 UTF-8，避免摘要里的 '✓'/'✗' 在 Windows GBK 控制台炸退出码
    _reconfigure_stdio()

    args = parse_args()

    # 配置日志（--debug 优先于 --verbose）
    if args.debug:
        log_level = logging.DEBUG
    elif args.verbose:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO
    setup_logger(level=log_level)
    logger = logging.getLogger("alice_test")

    if args.debug:
        logger.debug("DEBUG 模式已启用，将输出 LLM 原始响应等详细调试信息")

    logger.info("Alice Test - 市场隐含预期与逻辑偏差自动审计系统")
    logger.info(f"配置文件: {args.config}")

    # 加载配置
    try:
        config_manager = ConfigManager(args.config)
        config = config_manager.load()
        logger.info(f"已加载 {len(config.targets)} 个标的配置")
    except FileNotFoundError:
        logger.error(f"配置文件不存在: {args.config}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"加载配置失败: {e}")
        sys.exit(1)

    # 参数校验
    if args.ticker:
        logger.info(f"仅处理指定标的: {args.ticker}")
        if not config.get_target_by_ticker(args.ticker):
            logger.error(f"未在配置中找到标的: {args.ticker}")
            logger.info(f"可用标的: {config.get_tickers()}")
            sys.exit(1)

    # 运行流水线
    try:
        pipeline = AliceTestPipeline(
            config=config,
            ticker_filter=args.ticker,
            output_path=args.output,
            verbose=args.verbose,
        )
        results = pipeline.run()
    except KeyboardInterrupt:
        logger.warning("用户中断执行")
        sys.exit(130)
    except Exception as e:
        logger.error(f"流水线执行失败: {e}")
        if args.verbose:
            import traceback
            logger.debug(traceback.format_exc())
        sys.exit(1)

    # 返回适当的退出码
    if not results:
        sys.exit(1)

    # 检查是否有错误
    error_results = [r for r in results if r.status != "ok"]
    if error_results:
        sys.exit(2)  # 部分成功


if __name__ == "__main__":
    main()

"""
Alice Test - 主程序入口

市场隐含预期与逻辑偏差自动审计系统
"""
import argparse
from datetime import datetime
from pathlib import Path

from .config import ConfigManager, AppConfig, TargetConfig
from .data_ingestion import TickerRawData
from .data_ingestion.quotes import TushareQuotesProvider, YFinanceQuotesProvider
from .data_ingestion.text import ResearchCrawler, NewsCrawler
from .data_ingestion.preprocessor import TextPreprocessor
from .engines import ConsensusEngine, ThesisProjector, GapCalculator, AuditResult
from .llm import DeepSeekClient
from .persistence import CSVReportWriter, AuditReportStore
from .utils import setup_logger, AuditLogger


class AliceTestPipeline:
    """Alice Test 主流水线"""

    def __init__(self, config: AppConfig):
        """
        初始化流水线

        Args:
            config: 应用配置
        """
        self._config = config
        self._logger = AuditLogger()

        # 初始化组件
        self._llm_client = self._create_llm_client()
        self._consensus_engine = ConsensusEngine(self._llm_client)
        self._thesis_projector = ThesisProjector(self._llm_client)
        self._gap_calculator = GapCalculator(config.gap_thresholds)
        self._report_writer: AuditReportStore = CSVReportWriter()
        self._text_preprocessor = TextPreprocessor()

    def _create_llm_client(self) -> DeepSeekClient:
        """创建 LLM 客户端"""
        llm_config = self._config.llm_api
        return DeepSeekClient(
            api_key=llm_config.api_key,
            model=llm_config.model,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
        )

    def run(self) -> list[AuditResult]:
        """
        执行完整审计流程

        Returns:
            list[AuditResult]: 所有标的的审计结果
        """
        targets = self._config.targets
        self._logger.start_run(len(targets))

        results: list[AuditResult] = []

        for target in targets:
            try:
                result = self._process_single_target(target)
                results.append(result)
                self._logger.log_success(target.ticker)
            except Exception as e:
                self._logger.log_llm_error(target.ticker, str(e))

        # 保存结果
        self._report_writer.save_batch(results)
        self._logger.end_run()

        return results

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

        # Step 2: Module A - 市场共识分析
        consensus = self._consensus_engine.analyze(raw_data)

        # Step 3: Module B - 信念投影
        thesis_projection = self._thesis_projector.project(target)

        # Step 4: Gap 计算与信号判定
        result = self._gap_calculator.compute_audit_result(
            ticker=target.ticker,
            name=target.name,
            price=raw_data.quote.price_close,
            pe_ttm=raw_data.quote.pe_ttm,
            consensus=consensus,
            thesis_projection=thesis_projection,
        )

        return result

    def _ingest_data(self, target: TargetConfig) -> TickerRawData:
        """
        数据摄入

        Args:
            target: 标的配置

        Returns:
            TickerRawData: 原始数据
        """
        # TODO: 实现数据摄入逻辑
        # 1. 根据 ticker 后缀选择行情数据源
        # 2. 获取行情数据
        # 3. 获取文本数据（研报 + 新闻）
        # 4. 文本预处理
        # 5. 组装 TickerRawData
        raise NotImplementedError


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
    return parser.parse_args()


def main() -> None:
    """主入口函数"""
    args = parse_args()

    # 配置日志
    setup_logger(level=10 if args.verbose else 20)

    # 加载配置
    config_manager = ConfigManager(args.config)
    config = config_manager.load()

    # 运行流水线
    pipeline = AliceTestPipeline(config)
    results = pipeline.run()

    # 输出摘要
    print(f"\n审计完成，共处理 {len(results)} 个标的")
    for r in results:
        print(f"  {r.ticker} ({r.name}): {r.signal.value}, Gap={r.gap:.1f}%")


if __name__ == "__main__":
    main()

"""
AkShare 研报获取器
接口: stock_research_report_em
数据源: 东方财富
"""
from datetime import datetime, timedelta, date
from typing import List, Optional
import logging

from ...models import TextItem
from .pdf_extractor import PDFExtractor

logger = logging.getLogger("alice_test")


class AkShareResearchFetcher:
    """AkShare A股研报获取器"""

    def __init__(
        self,
        pdf_extractor: PDFExtractor | None = None,
        extract_pdf: bool = True,
        max_retries: int = 2,
    ):
        """
        初始化研报获取器

        Args:
            pdf_extractor: PDF 提取器实例
            extract_pdf: 是否下载并解析 PDF 内容
            max_retries: 最大重试次数
        """
        self._pdf_extractor = pdf_extractor
        self._extract_pdf = extract_pdf and pdf_extractor is not None
        self._max_retries = max_retries

    def fetch(
        self,
        symbol: str,
        lookback_hours: int = 48,
        max_items: int = 10,
    ) -> List[TextItem]:
        """
        获取个股研报

        Args:
            symbol: 股票代码（不带后缀），如 "601985"
            lookback_hours: 回溯小时数
            max_items: 最大返回条数

        Returns:
            List[TextItem]: 研报列表
        """
        import akshare as ak

        try:
            df = ak.stock_research_report_em(symbol=symbol)
        except Exception as e:
            logger.warning(f"[{symbol}] AkShare 研报获取失败: {e}")
            return []

        if df is None or df.empty:
            logger.debug(f"[{symbol}] 无研报数据")
            return []

        # 时间过滤
        cutoff_date = (datetime.now() - timedelta(hours=lookback_hours)).date()
        results: List[TextItem] = []

        for _, row in df.iterrows():
            try:
                # 解析日期
                report_date = self._parse_date(row.get("日期", ""))
                if report_date is None or report_date < cutoff_date:
                    continue

                # 基础信息
                title = str(row.get("报告名称", ""))
                source = str(row.get("机构", "未知机构"))
                pdf_url = str(row.get("报告PDF链接", "")) or None

                # 构建摘要：元数据 + PDF 内容
                summary = self._build_summary(row, pdf_url)

                item = TextItem(
                    source=source,
                    type="research",
                    title=title,
                    summary=summary,
                    published_at=datetime.combine(report_date, datetime.min.time()),
                    url=pdf_url,
                )
                results.append(item)

                if len(results) >= max_items:
                    break

            except Exception as e:
                logger.debug(f"[{symbol}] 解析研报行失败: {e}")
                continue

        logger.info(f"[{symbol}] 获取 {len(results)} 条研报")
        return results

    def _build_summary(self, row, pdf_url: str | None) -> str:
        """
        构建研报摘要

        优先级：
        1. PDF 提取的关键观点（如果启用）
        2. 元数据组合（评级+盈利预测）
        """
        # 尝试 PDF 提取
        if self._extract_pdf and pdf_url and self._pdf_extractor:
            try:
                pdf_summary = self._pdf_extractor.extract_summary(pdf_url)
                if pdf_summary:
                    return pdf_summary
            except Exception as e:
                logger.debug(f"PDF 提取失败: {e}")

        # 回退到元数据
        parts = []

        rating = row.get("东财评级", "")
        if rating:
            parts.append(f"评级: {rating}")

        # 盈利预测
        for year in ["2024", "2025", "2026"]:
            eps = row.get(f"{year}-盈利预测-收益")
            pe = row.get(f"{year}-盈利预测-市盈率")
            if eps is not None and pe is not None:
                try:
                    parts.append(f"{year}E EPS:{float(eps):.2f} PE:{float(pe):.1f}")
                    break  # 只取最近一年
                except (ValueError, TypeError):
                    continue

        industry = row.get("行业", "")
        if industry:
            parts.append(f"行业: {industry}")

        return " | ".join(parts) if parts else "暂无摘要"

    def _parse_date(self, date_str: str) -> date | None:
        """解析日期字符串"""
        if not date_str:
            return None

        formats = ["%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"]
        for fmt in formats:
            try:
                return datetime.strptime(str(date_str), fmt).date()
            except ValueError:
                continue
        return None

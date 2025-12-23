"""
AkShare 数据提供者

使用 AkShare 免费 API 获取 A 股新闻和研报数据。
"""
import logging
import re
from datetime import datetime, timedelta
from typing import Literal

import akshare as ak
import pandas as pd

from .base import DataProvider, ProviderRegistry, ProviderType
from ...models import TextItem
from ...preprocessor import TextPreprocessor

logger = logging.getLogger("alice_test")


@ProviderRegistry.register(ProviderType.AKSHARE)
class AkShareProvider(DataProvider):
    """AkShare 数据提供者（A股市场）"""

    provider_type = ProviderType.AKSHARE
    supported_markets: list[Literal["a_share", "hk", "us"]] = ["a_share"]

    def __init__(self):
        """初始化 AkShare 提供者"""
        self._preprocessor = TextPreprocessor()
        self._available: bool | None = None  # 缓存可用性检查结果

    def fetch_news(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
    ) -> list[TextItem]:
        """
        使用 AkShare 获取 A 股个股新闻

        AkShare 接口：ak.stock_news_em(symbol)
        返回 DataFrame 列：
        - 新闻标题
        - 新闻内容
        - 发布时间
        - 文章来源
        - 新闻链接
        """
        # 1. 转换 ticker 格式：601985.SH → 601985
        symbol = self._convert_ticker(ticker)

        try:
            # 2. 调用 AkShare 接口
            df = ak.stock_news_em(symbol=symbol)

            if df is None or df.empty:
                logger.warning(f"[{ticker}] AkShare 返回空数据")
                return []

            # 3. 转换为 TextItem 列表
            texts = self._convert_news_dataframe(df, ticker, lookback_hours)

            # 4. 过滤噪声内容
            texts = [t for t in texts if not self._preprocessor.is_noise(t)]

            # 5. 返回 top N
            return texts[:max_items]

        except Exception as e:
            logger.error(f"[{ticker}] AkShare 获取新闻失败: {e}")
            return []

    def _convert_ticker(self, ticker: str) -> str:
        """转换 ticker 格式"""
        # 601985.SH → 601985
        # 000001.SZ → 000001
        return ticker.split(".")[0]

    def _convert_news_dataframe(
        self,
        df: pd.DataFrame,
        ticker: str,
        lookback_hours: int,
    ) -> list[TextItem]:
        """将 DataFrame 转换为 TextItem 列表"""
        texts = []
        cutoff_time = datetime.now() - timedelta(hours=lookback_hours)

        for _, row in df.iterrows():
            try:
                # 解析发布时间
                published_at = self._parse_datetime(row.get("发布时间", ""))

                # 过滤超出时间窗口的新闻
                if published_at and published_at < cutoff_time:
                    continue

                # 提取字段
                title = str(row.get("新闻标题", "")).strip()
                content = str(row.get("新闻内容", "")).strip()
                source = str(row.get("文章来源", "未知")).strip()
                url = str(row.get("新闻链接", "")).strip()

                # 跳过无标题的记录
                if not title:
                    continue

                # 截取摘要（最多 500 字）
                summary = content[:500] if content else title

                texts.append(
                    TextItem(
                        source=source,
                        type="news",
                        title=title,
                        summary=summary,
                        published_at=published_at or datetime.now(),
                        url=url if url else None,
                    )
                )

            except Exception as e:
                logger.debug(f"[{ticker}] 解析新闻记录失败: {e}")
                continue

        # 按时间排序（最新在前）
        texts.sort(key=lambda x: x.published_at, reverse=True)

        return texts

    def _parse_datetime(self, time_str: str) -> datetime | None:
        """解析时间字符串"""
        if not time_str:
            return None

        # 尝试多种时间格式
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%Y年%m月%d日 %H:%M",
            "%Y年%m月%d日",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(str(time_str).strip(), fmt)
            except ValueError:
                continue

        # 处理相对时间（如 "2小时前"）
        return self._parse_relative_time(time_str)

    def _parse_relative_time(self, time_str: str) -> datetime | None:
        """解析相对时间表达式"""
        now = datetime.now()
        time_str = str(time_str).strip()

        # 匹配 "X分钟前"、"X小时前"、"X天前"
        patterns = [
            (r"(\d+)\s*分钟前", lambda m: now - timedelta(minutes=int(m.group(1)))),
            (r"(\d+)\s*小时前", lambda m: now - timedelta(hours=int(m.group(1)))),
            (r"(\d+)\s*天前", lambda m: now - timedelta(days=int(m.group(1)))),
            (r"刚刚", lambda m: now),
            (r"今天", lambda m: now.replace(hour=12, minute=0, second=0)),
            (r"昨天", lambda m: now - timedelta(days=1)),
        ]

        for pattern, handler in patterns:
            match = re.search(pattern, time_str)
            if match:
                return handler(match)

        return None

    def fetch_research(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
    ) -> list[TextItem]:
        """
        获取研报数据

        注意：AkShare 的研报接口可能需要探索，
        这里提供一个基于新闻筛选的备选方案
        """
        symbol = self._convert_ticker(ticker)

        try:
            # 方案 1：尝试使用研报接口（如果可用）
            # df = ak.stock_research_report_em(symbol=symbol)

            # 方案 2：从新闻中筛选研报相关内容
            df = ak.stock_news_em(symbol=symbol)

            if df is None or df.empty:
                return []

            texts = []
            cutoff_time = datetime.now() - timedelta(hours=lookback_hours)

            # 研报关键词
            research_keywords = [
                "研报",
                "研究报告",
                "深度报告",
                "投资建议",
                "评级",
                "目标价",
                "买入",
                "增持",
                "中性",
                "减持",
                "首次覆盖",
                "跟踪报告",
                "点评",
            ]

            for _, row in df.iterrows():
                title = str(row.get("新闻标题", ""))
                content = str(row.get("新闻内容", ""))

                # 检查是否包含研报关键词
                combined = title + content
                if not any(kw in combined for kw in research_keywords):
                    continue

                # 解析时间
                published_at = self._parse_datetime(row.get("发布时间", ""))
                if published_at and published_at < cutoff_time:
                    continue

                # 尝试提取券商来源
                source = self._extract_research_provider(title, content)

                texts.append(
                    TextItem(
                        source=source,
                        type="research",
                        title=title.strip(),
                        summary=content[:500] if content else title,
                        published_at=published_at or datetime.now(),
                        url=str(row.get("新闻链接", "")) or None,
                    )
                )

            texts.sort(key=lambda x: x.published_at, reverse=True)
            return texts[:max_items]

        except Exception as e:
            logger.error(f"[{ticker}] AkShare 获取研报失败: {e}")
            return []

    def _extract_research_provider(self, title: str, content: str) -> str:
        """从标题或内容中提取券商来源"""
        providers = [
            "中信证券",
            "华泰证券",
            "海通证券",
            "国泰君安",
            "招商证券",
            "广发证券",
            "申万宏源",
            "中金公司",
            "兴业证券",
            "东方证券",
            "光大证券",
            "平安证券",
            "浙商证券",
            "中泰证券",
            "天风证券",
        ]

        combined = title + content

        for provider in providers:
            if provider in combined:
                return provider

        return "未知券商"

    def is_available(self) -> bool:
        """检查 AkShare 是否可用"""
        # 使用缓存结果
        if self._available is not None:
            return self._available

        try:
            # 尝试获取一个简单的接口验证连通性
            df = ak.stock_news_em(symbol="000001")
            self._available = df is not None
        except Exception as e:
            logger.warning(f"AkShare 不可用: {e}")
            self._available = False

        return self._available


if __name__ == "__main__":
    provider = AkShareProvider()

    print(f"AkShare 可用性: {provider.is_available()}")
    print()

    print("=" * 60)
    print("测试获取新闻：中国核电 (601985.SH)")
    print("=" * 60)

    news = provider.fetch_news("601985.SH", "中国核电", max_items=5)

    for i, item in enumerate(news, 1):
        print(f"{i}. [{item.source}] {item.title}")
        print(f"   时间: {item.published_at}")
        print(f"   摘要: {item.summary[:80]}...")
        print()

    print("=" * 60)
    print("测试获取研报")
    print("=" * 60)

    research = provider.fetch_research("601985.SH", "中国核电", max_items=3)

    for i, item in enumerate(research, 1):
        print(f"{i}. [{item.source}] {item.title}")
        print(f"   摘要: {item.summary[:80]}...")
        print()

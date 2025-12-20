"""
文本预处理器 - 去噪与过滤
"""
import re

from .models import TextItem


class TextPreprocessor:
    """文本去噪与过滤处理器"""

    # 需要过滤的无关内容模式
    NOISE_PATTERNS: list[str] = [
        r"融资融券",
        r"大宗交易",
        r"股东减持",
        r"限售股解禁",
        r"交易公开信息",
        r"龙虎榜",
    ]

    # 需要保留的有价值内容标记
    VALUE_MARKERS: list[str] = [
        "摘要",
        "投资建议",
        "风险提示",
        "结论",
        "核心观点",
        "investment thesis",
        "key takeaways",
        "risk factors",
    ]

    # 权威来源列表（用于评分加权）
    AUTHORITATIVE_SOURCES: list[str] = [
        "中信证券",
        "中金公司",
        "国泰君安",
        "华泰证券",
        "招商证券",
        "广发证券",
        "海通证券",
        "申万宏源",
        "兴业证券",
        "中信建投",
        "东方证券",
        "光大证券",
        "平安证券",
        "浙商证券",
        "国信证券",
        "财新",
        "第一财经",
        "证券时报",
        "上海证券报",
        "中国证券报",
    ]

    def __init__(self, custom_noise_patterns: list[str] | None = None):
        """
        初始化预处理器

        Args:
            custom_noise_patterns: 自定义噪声模式列表
        """
        self._noise_patterns = self.NOISE_PATTERNS + (custom_noise_patterns or [])
        self._noise_regex = re.compile("|".join(self._noise_patterns), re.IGNORECASE)

    def filter_texts(
        self,
        texts: list[TextItem],
        max_items: int = 10,
    ) -> list[TextItem]:
        """
        过滤并排序文本列表

        Args:
            texts: 原始文本列表
            max_items: 最大保留条数

        Returns:
            list[TextItem]: 过滤后的文本列表，按观点密度排序
        """
        if not texts:
            return []

        # 1. 移除匹配噪声模式的文本
        filtered = [text for text in texts if not self.is_noise(text)]

        # 2. 按观点密度评分排序（降序）
        scored_texts = [(text, self.calculate_opinion_density(text)) for text in filtered]
        scored_texts.sort(key=lambda x: x[1], reverse=True)

        # 3. 返回 top N
        result = [text for text, _ in scored_texts[:max_items]]

        return result

    def is_noise(self, text: TextItem) -> bool:
        """
        判断文本是否为噪声

        Args:
            text: 文本项

        Returns:
            bool: 是否为噪声
        """
        content = f"{text.title} {text.summary}"
        return bool(self._noise_regex.search(content))

    def extract_key_content(self, raw_text: str) -> str:
        """
        从原始文本中提取关键内容（摘要/结论等）

        Args:
            raw_text: 原始文本

        Returns:
            str: 提取的关键内容
        """
        if not raw_text:
            return ""

        extracted_parts: list[str] = []

        # 构建匹配 VALUE_MARKERS 附近段落的正则模式
        # 匹配格式：标记词后跟冒号或换行，然后是内容段落
        for marker in self.VALUE_MARKERS:
            # 匹配模式：标记词 + 可选的冒号/：+ 后续内容（到下一个换行或段落结束）
            pattern = rf"(?:{marker})[：:\s]*([^\n]+(?:\n(?![一二三四五六七八九十\d]+[、.])(?!{marker})[^\n]+)*)"
            matches = re.findall(pattern, raw_text, re.IGNORECASE)
            for match in matches:
                content = match.strip()
                if content and len(content) >= 10:
                    extracted_parts.append(content)

        # 如果没有匹配到任何标记，尝试提取开头段落作为摘要
        if not extracted_parts:
            # 提取第一段非空内容（限制长度）
            paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
            if paragraphs:
                first_para = paragraphs[0]
                if len(first_para) >= 20:
                    extracted_parts.append(first_para[:500])

        # 合并提取的内容，去除重复
        seen: set[str] = set()
        unique_parts: list[str] = []
        for part in extracted_parts:
            # 使用前50个字符作为去重标识
            key = part[:50]
            if key not in seen:
                seen.add(key)
                unique_parts.append(part)

        return "\n\n".join(unique_parts)

    def calculate_opinion_density(self, text: TextItem) -> float:
        """
        计算文本的观点密度评分

        Args:
            text: 文本项

        Returns:
            float: 观点密度评分 (0.0 - 1.0)
        """
        score = 0.0
        content = f"{text.title} {text.summary}".lower()

        # 1. VALUE_MARKERS 匹配得分 (最高 0.5 分)
        marker_count = 0
        for marker in self.VALUE_MARKERS:
            if marker.lower() in content:
                marker_count += 1
        # 每个标记贡献 0.1 分，最多 0.5 分
        score += min(marker_count * 0.1, 0.5)

        # 2. 文本长度适中得分 (最高 0.3 分)
        # 太短可能信息不足，太长可能是噪声或冗余
        summary_len = len(text.summary)
        if 50 <= summary_len <= 500:
            # 最佳长度范围，满分
            score += 0.3
        elif 20 <= summary_len < 50 or 500 < summary_len <= 1000:
            # 次优长度范围
            score += 0.2
        elif 10 <= summary_len < 20 or 1000 < summary_len <= 2000:
            # 一般长度范围
            score += 0.1
        # 太短或太长不加分

        # 3. 来源权威性得分 (最高 0.2 分)
        for source in self.AUTHORITATIVE_SOURCES:
            if source in text.source:
                score += 0.2
                break

        return min(score, 1.0)

    def deduplicate(self, texts: list[TextItem], similarity_threshold: float = 0.8) -> list[TextItem]:
        """
        文本去重

        Args:
            texts: 文本列表
            similarity_threshold: 相似度阈值

        Returns:
            list[TextItem]: 去重后的列表
        """
        if not texts:
            return []

        result: list[TextItem] = []

        for text in texts:
            is_duplicate = False
            for existing in result:
                similarity = self._calculate_title_similarity(text.title, existing.title)
                if similarity >= similarity_threshold:
                    is_duplicate = True
                    break
            if not is_duplicate:
                result.append(text)

        return result

    def _calculate_title_similarity(self, title1: str, title2: str) -> float:
        """
        计算两个标题的相似度

        使用基于字符集合的 Jaccard 相似度算法

        Args:
            title1: 第一个标题
            title2: 第二个标题

        Returns:
            float: 相似度 (0.0 - 1.0)
        """
        if not title1 or not title2:
            return 0.0

        # 移除空白字符并转小写
        t1 = title1.replace(" ", "").lower()
        t2 = title2.replace(" ", "").lower()

        # 完全相同
        if t1 == t2:
            return 1.0

        # 使用 2-gram 计算 Jaccard 相似度
        def get_ngrams(text: str, n: int = 2) -> set[str]:
            """获取 n-gram 集合"""
            if len(text) < n:
                return {text}
            return {text[i : i + n] for i in range(len(text) - n + 1)}

        set1 = get_ngrams(t1)
        set2 = get_ngrams(t2)

        intersection = len(set1 & set2)
        union = len(set1 | set2)

        if union == 0:
            return 0.0

        return intersection / union

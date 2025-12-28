"""
PDF 研报提取器

职责：
1. 下载 PDF 文件
2. 提取文本内容
3. 使用 LLM 提取关键观点
"""
import tempfile
import logging
from typing import Optional

import httpx

logger = logging.getLogger("alice_test")


class PDFExtractor:
    """PDF 研报内容提取器"""

    # 研报中需要重点提取的段落标记
    KEY_SECTIONS = [
        "投资要点",
        "核心观点",
        "投资建议",
        "风险提示",
        "摘要",
        "结论",
        "事件",
        "点评",
    ]

    def __init__(
        self,
        llm_client=None,
        use_llm: bool = True,
        max_pages: int = 5,
        timeout: float = 15.0,
    ):
        """
        初始化 PDF 提取器

        Args:
            llm_client: DeepSeekClient 实例（用于摘要提取）
            use_llm: 是否使用 LLM 提炼摘要
            max_pages: 最大解析页数（研报通常前几页是摘要）
            timeout: 下载超时时间
        """
        self._llm_client = llm_client
        self._use_llm = use_llm and llm_client is not None
        self._max_pages = max_pages
        self._timeout = timeout

    def extract_summary(self, pdf_url: str) -> str | None:
        """
        从 PDF URL 提取研报摘要

        Args:
            pdf_url: PDF 文件 URL

        Returns:
            str | None: 提取的摘要，失败返回 None
        """
        # 1. 下载 PDF
        pdf_content = self._download_pdf(pdf_url)
        if not pdf_content:
            return None

        # 2. 提取文本
        raw_text = self._extract_text(pdf_content)
        if not raw_text:
            return None

        # 3. 提取关键段落
        key_content = self._extract_key_sections(raw_text)

        # 4. LLM 精炼（可选）
        if self._use_llm and len(key_content) > 200:
            return self._llm_summarize(key_content)

        return key_content[:1000] if key_content else None

    def _download_pdf(self, url: str) -> bytes | None:
        """下载 PDF 文件"""
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(url, follow_redirects=True)
                response.raise_for_status()

                # 验证是 PDF
                content_type = response.headers.get("content-type", "")
                if "pdf" not in content_type.lower() and not url.endswith(".pdf"):
                    logger.warning(f"非 PDF 内容: {content_type}")
                    return None

                return response.content

        except httpx.TimeoutException:
            logger.warning(f"PDF 下载超时: {url}")
            return None
        except Exception as e:
            logger.warning(f"PDF 下载失败: {e}")
            return None

    def _extract_text(self, pdf_content: bytes) -> str | None:
        """从 PDF 内容提取文本"""
        import pdfplumber

        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
                tmp.write(pdf_content)
                tmp.flush()

                text_parts = []
                with pdfplumber.open(tmp.name) as pdf:
                    for i, page in enumerate(pdf.pages):
                        if i >= self._max_pages:
                            break
                        page_text = page.extract_text()
                        if page_text:
                            text_parts.append(page_text)

                return "\n\n".join(text_parts)

        except Exception as e:
            logger.warning(f"PDF 文本提取失败: {e}")
            return None

    def _extract_key_sections(self, raw_text: str) -> str:
        """
        提取关键段落

        使用正则匹配研报中的重要章节
        """
        import re

        # 尝试按标记提取
        extracted = []
        for marker in self.KEY_SECTIONS:
            # 匹配 "投资要点：xxx" 或 "【投资要点】xxx" 等格式
            patterns = [
                rf"{marker}[：:]\s*(.{{50,500}}?)(?=\n\n|\n[一二三四五六七八九十\d]|$)",
                rf"【{marker}】\s*(.{{50,500}}?)(?=\n\n|\n【|$)",
                rf"^{marker}\n(.{{50,500}}?)(?=\n\n|^[一二三四五六七八九十])",
            ]
            for pattern in patterns:
                matches = re.findall(pattern, raw_text, re.MULTILINE | re.DOTALL)
                for match in matches:
                    cleaned = self._clean_text(match)
                    if len(cleaned) > 30:
                        extracted.append(f"【{marker}】{cleaned}")

        if extracted:
            return "\n".join(extracted[:5])  # 最多取 5 段

        # 回退：返回开头内容（通常是摘要）
        return self._clean_text(raw_text[:2000])

    def _clean_text(self, text: str) -> str:
        """清理文本"""
        import re

        # 移除多余空白
        text = re.sub(r"\s+", " ", text)
        # 移除页码等噪声
        text = re.sub(r"第\s*\d+\s*页", "", text)
        text = re.sub(r"\d+\s*/\s*\d+", "", text)
        # 移除特殊字符
        text = re.sub(r"[■●◆▲△▼▽○◇□★☆]", "", text)

        return text.strip()

    def _llm_summarize(self, content: str) -> str:
        """使用 LLM 提炼摘要"""
        if not self._llm_client:
            return content[:500]

        system_prompt = """你是一位专业的证券研究助理。请从以下研报内容中提取核心观点。

要求：
1. 提取投资评级和目标价（如有）
2. 总结 1-2 个核心观点
3. 列出主要风险点（如有）
4. 输出控制在 200 字以内
5. 使用简洁的中文表述

直接输出摘要内容，不要有额外说明。"""

        user_prompt = f"研报内容：\n{content[:4000]}"

        try:
            response = self._llm_client.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0,
            )
            return response.content.strip()
        except Exception as e:
            logger.warning(f"LLM 摘要提取失败: {e}")
            return content[:500]

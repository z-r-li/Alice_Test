"""
网页内容抓取器

职责：
1. 抓取网页 HTML 内容
2. 提取正文文本（去除导航、广告等）
3. 提取页面中的链接
4. 处理反爬和超时
"""
import logging
import random
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("alice_test")


@dataclass
class PageContent:
    """页面内容"""
    url: str
    title: str
    text: str  # 提取的正文文本
    links: list[str]  # 页面中发现的链接
    fetch_success: bool
    error_message: str | None = None


class WebFetcher:
    """
    网页内容抓取器

    特点：
    - 使用 httpx 直接抓取，不消耗搜索 API 额度
    - 内置 User-Agent 轮换
    - 支持从 HTML 提取正文和链接
    """

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
    ]

    # 需要移除的 HTML 标签（不包含正文内容）
    REMOVE_TAGS = [
        "script", "style", "nav", "footer", "aside", "header",
        "noscript", "iframe", "form", "button", "input", "select",
        "textarea", "svg", "canvas", "audio", "video",
    ]

    # 正文容器的优先选择器（按优先级排序）
    CONTENT_SELECTORS = [
        "article",
        "main",
        "[role='main']",
        ".article-content",
        ".post-content",
        ".entry-content",
        ".content",
        "#content",
        ".article-body",
        ".post-body",
        "#article",
        "#main-content",
    ]

    def __init__(
        self,
        timeout: float = 15.0,
        max_content_length: int = 500_000,  # 500KB
    ):
        """
        初始化抓取器

        Args:
            timeout: 请求超时时间（秒）
            max_content_length: 最大内容长度（字节）
        """
        self._timeout = timeout
        self._max_content_length = max_content_length

    def fetch(self, url: str) -> PageContent:
        """
        抓取单个页面

        Args:
            url: 页面 URL

        Returns:
            PageContent: 页面内容
        """
        logger.debug(f"Fetching URL: {url}")

        try:
            headers = self._get_random_headers()

            with httpx.Client(
                timeout=self._timeout,
                follow_redirects=True,
                headers=headers,
            ) as client:
                response = client.get(url)
                response.raise_for_status()

                # 检查 Content-Type
                content_type = response.headers.get("content-type", "")
                if not self._is_html_content(content_type):
                    return PageContent(
                        url=url,
                        title="",
                        text="",
                        links=[],
                        fetch_success=False,
                        error_message=f"Non-HTML content type: {content_type}",
                    )

                # 检查内容长度
                content_length = len(response.content)
                if content_length > self._max_content_length:
                    return PageContent(
                        url=url,
                        title="",
                        text="",
                        links=[],
                        fetch_success=False,
                        error_message=f"Content too large: {content_length} bytes",
                    )

                # 解析 HTML
                # 尝试使用 lxml 解析器（更快），如果不可用则使用 html.parser
                try:
                    soup = BeautifulSoup(response.text, "lxml")
                except Exception:
                    soup = BeautifulSoup(response.text, "html.parser")

                # 提取标题
                title = self._extract_title(soup)

                # 提取正文文本
                text = self._extract_text(soup)

                # 提取链接
                links = self._extract_links(soup, url)

                logger.info(
                    f"Fetched successfully: url={url}, "
                    f"title_len={len(title)}, text_len={len(text)}, links={len(links)}"
                )

                return PageContent(
                    url=url,
                    title=title,
                    text=text,
                    links=links,
                    fetch_success=True,
                )

        except httpx.TimeoutException as e:
            logger.warning(f"Timeout fetching {url}: {e}")
            return PageContent(
                url=url,
                title="",
                text="",
                links=[],
                fetch_success=False,
                error_message=f"Timeout: {e}",
            )

        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP error fetching {url}: {e.response.status_code}")
            return PageContent(
                url=url,
                title="",
                text="",
                links=[],
                fetch_success=False,
                error_message=f"HTTP {e.response.status_code}",
            )

        except httpx.RequestError as e:
            logger.warning(f"Request error fetching {url}: {e}")
            return PageContent(
                url=url,
                title="",
                text="",
                links=[],
                fetch_success=False,
                error_message=f"Request error: {e}",
            )

        except Exception as e:
            logger.error(f"Unexpected error fetching {url}: {e}")
            return PageContent(
                url=url,
                title="",
                text="",
                links=[],
                fetch_success=False,
                error_message=f"Unexpected error: {e}",
            )

    def fetch_batch(
        self,
        urls: list[str],
        delay: float = 1.0,
    ) -> list[PageContent]:
        """
        批量抓取页面

        Args:
            urls: URL 列表
            delay: 请求间隔（秒），避免被封

        Returns:
            list[PageContent]: 页面内容列表
        """
        results = []
        for i, url in enumerate(urls):
            results.append(self.fetch(url))
            # 最后一个 URL 不需要延迟
            if delay > 0 and i < len(urls) - 1:
                sleep_time = delay + random.uniform(0, 0.5)
                time.sleep(sleep_time)
        return results

    def _extract_title(self, soup: BeautifulSoup) -> str:
        """
        从 HTML 提取页面标题

        Args:
            soup: BeautifulSoup 对象

        Returns:
            str: 页面标题
        """
        # 优先使用 og:title
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return og_title["content"].strip()

        # 使用 <title> 标签
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            return title_tag.string.strip()

        # 使用 h1 标签
        h1_tag = soup.find("h1")
        if h1_tag:
            return h1_tag.get_text(strip=True)

        return ""

    def _extract_text(self, soup: BeautifulSoup) -> str:
        """
        从 HTML 提取正文文本

        策略：
        1. 移除 script, style, nav, footer, aside 等标签
        2. 优先查找 article, main, .content, #content 等容器
        3. 提取文本并清理空白
        """
        # 克隆 soup 以避免修改原始对象
        soup = BeautifulSoup(str(soup), soup.builder.NAME if soup.builder else "html.parser")

        # 移除不需要的标签
        for tag in soup.find_all(self.REMOVE_TAGS):
            tag.decompose()

        # 尝试查找主要内容容器
        content_element = None
        for selector in self.CONTENT_SELECTORS:
            content_element = soup.select_one(selector)
            if content_element:
                break

        # 如果找到内容容器，使用它；否则使用 body
        if content_element:
            target = content_element
        else:
            target = soup.find("body") or soup

        # 提取文本
        text = target.get_text(separator="\n", strip=True)

        # 清理多余的空白行
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        text = "\n".join(lines)

        return text

    def _extract_links(
        self,
        soup: BeautifulSoup,
        base_url: str,
        trusted_domains: list[str] | None = None,
    ) -> list[str]:
        """
        从页面提取链接

        Args:
            soup: BeautifulSoup 对象
            base_url: 基础 URL（用于解析相对链接）
            trusted_domains: 可信域名白名单，None 表示不过滤

        Returns:
            list[str]: 链接列表
        """
        links = set()
        base_parsed = urlparse(base_url)

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()

            # 跳过空链接和锚点链接
            if not href or href.startswith("#"):
                continue

            # 跳过 javascript: 和 mailto: 等特殊链接
            if href.startswith(("javascript:", "mailto:", "tel:", "data:")):
                continue

            # 解析相对链接为绝对链接
            absolute_url = urljoin(base_url, href)

            # 解析 URL
            parsed = urlparse(absolute_url)

            # 只保留 http/https 链接
            if parsed.scheme not in ("http", "https"):
                continue

            # 移除锚点部分
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.query:
                clean_url += f"?{parsed.query}"

            # 如果指定了可信域名，进行过滤
            if trusted_domains is not None:
                domain = parsed.netloc.replace("www.", "")
                if not any(domain.endswith(d) for d in trusted_domains):
                    continue

            links.add(clean_url)

        return list(links)

    def _is_html_content(self, content_type: str) -> bool:
        """
        检查 Content-Type 是否为 HTML

        Args:
            content_type: Content-Type 头部值

        Returns:
            bool: 是否为 HTML 内容
        """
        html_types = ["text/html", "application/xhtml+xml"]
        return any(ht in content_type.lower() for ht in html_types)

    def _get_random_headers(self) -> dict:
        """生成随机请求头"""
        return {
            "User-Agent": random.choice(self.USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
        }

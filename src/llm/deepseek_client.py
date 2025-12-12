"""
DeepSeek API 客户端封装

职责：
1. 封装 DeepSeek API 调用
2. 实现重试机制
3. JSON 响应解析与校验
"""
import json
import time
from typing import TypeVar, Type

from .models import LLMResponse, ConsensusResult, ThesisProjectionResult
from .prompts import PromptTemplates

T = TypeVar("T", ConsensusResult, ThesisProjectionResult)


class DeepSeekClientError(Exception):
    """DeepSeek 客户端错误基类"""
    pass


class JSONParseError(DeepSeekClientError):
    """JSON 解析错误"""
    pass


class APICallError(DeepSeekClientError):
    """API 调用错误"""
    pass


class DeepSeekClient:
    """DeepSeek API 客户端"""

    DEFAULT_MODEL = "deepseek-chat"
    DEFAULT_TEMPERATURE = 0.0  # 必须为 0，保证评分稳定
    DEFAULT_MAX_TOKENS = 4096
    MAX_RETRIES = 2  # 最大重试次数

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        base_url: str = "https://api.deepseek.com",
    ):
        """
        初始化 DeepSeek 客户端

        Args:
            api_key: API Key
            model: 模型名称，默认 "deepseek-chat"
            temperature: 温度参数，默认 0.0
            max_tokens: 最大 token 数，默认 4096
            base_url: API 基础 URL
        """
        self._api_key = api_key
        self._model = model or self.DEFAULT_MODEL
        self._temperature = temperature if temperature is not None else self.DEFAULT_TEMPERATURE
        self._max_tokens = max_tokens or self.DEFAULT_MAX_TOKENS
        self._base_url = base_url
        # TODO: 初始化 HTTP 客户端 (httpx/requests)

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
    ) -> LLMResponse:
        """
        发送聊天请求

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户消息
            temperature: 可选覆盖温度参数

        Returns:
            LLMResponse: 响应对象

        Raises:
            APICallError: API 调用失败
        """
        # TODO: 实现 API 调用
        # 1. 构建请求 body
        # 2. 发送 POST 请求到 /v1/chat/completions
        # 3. 解析响应
        # 4. 返回 LLMResponse
        raise NotImplementedError

    def chat_with_json_output(
        self,
        system_prompt: str,
        user_prompt: str,
        result_class: Type[T],
        max_retries: int | None = None,
    ) -> T:
        """
        发送聊天请求并解析 JSON 响应

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户消息
            result_class: 结果数据类 (ConsensusResult 或 ThesisProjectionResult)
            max_retries: 最大重试次数

        Returns:
            T: 解析后的结果对象

        Raises:
            JSONParseError: JSON 解析失败（重试后仍失败）
            APICallError: API 调用失败
        """
        retries = max_retries if max_retries is not None else self.MAX_RETRIES

        for attempt in range(retries + 1):
            try:
                # 重试时添加 JSON 修复提示
                effective_system = system_prompt
                if attempt > 0:
                    effective_system += PromptTemplates.JSON_REPAIR_SUFFIX

                response = self.chat(effective_system, user_prompt)
                result = self._parse_json_response(response.content, result_class)

                if result.validate():
                    return result
                else:
                    raise JSONParseError("Response validation failed")

            except JSONParseError as e:
                if attempt < retries:
                    time.sleep(1)  # 重试前等待
                    continue
                raise

        raise JSONParseError(f"Failed to parse JSON after {retries + 1} attempts")

    def _parse_json_response(self, content: str, result_class: Type[T]) -> T:
        """
        解析 JSON 响应

        Args:
            content: 响应内容
            result_class: 结果数据类

        Returns:
            T: 解析后的结果对象

        Raises:
            JSONParseError: 解析失败
        """
        # TODO: 实现 JSON 解析
        # 1. 清理 markdown 代码块标记
        # 2. json.loads 解析
        # 3. 构造 result_class 实例
        raise NotImplementedError

    def get_consensus(
        self,
        ticker: str,
        ticker_name: str,
        price_close: float,
        pe_ttm: float | None,
        pb: float | None,
        texts_content: str,
    ) -> ConsensusResult:
        """
        获取市场共识分析结果 (Module A)

        Args:
            ticker: 证券代码
            ticker_name: 标的名称
            price_close: 收盘价
            pe_ttm: 市盈率
            pb: 市净率
            texts_content: 格式化后的文本内容

        Returns:
            ConsensusResult: 市场共识分析结果
        """
        system, user = PromptTemplates.format_consensus_prompt(
            ticker=ticker,
            ticker_name=ticker_name,
            price_close=price_close,
            pe_ttm=pe_ttm,
            pb=pb,
            texts_content=texts_content,
        )
        return self.chat_with_json_output(system, user, ConsensusResult)

    def get_thesis_projection(
        self,
        ticker: str,
        ticker_name: str,
        user_thesis: str,
        industry: str = "未知",
    ) -> ThesisProjectionResult:
        """
        获取信念投影结果 (Module B)

        Args:
            ticker: 证券代码
            ticker_name: 标的名称
            user_thesis: 用户宏观信念
            industry: 行业

        Returns:
            ThesisProjectionResult: 信念投影结果
        """
        system, user = PromptTemplates.format_thesis_prompt(
            ticker=ticker,
            ticker_name=ticker_name,
            user_thesis=user_thesis,
            industry=industry,
        )
        return self.chat_with_json_output(system, user, ThesisProjectionResult)

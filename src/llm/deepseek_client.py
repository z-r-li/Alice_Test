"""
DeepSeek API 客户端封装

使用 OpenAI 官方 Python SDK 调用 DeepSeek API
"""
import logging
import os
import json
import time
from typing import Literal, TypeVar, Type

from openai import OpenAI

from .models import LLMResponse, ConsensusResult, ThesisProjectionResult
from .prompts import PromptTemplates

T = TypeVar("T", ConsensusResult, ThesisProjectionResult)

# 默认配置
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TEMPERATURE = 0
DEFAULT_BASE_URL = "https://api.deepseek.com"


def _get_client() -> OpenAI:
    """获取 OpenAI 客户端实例"""
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("环境变量 DEEPSEEK_API_KEY 未设置")
    return OpenAI(api_key=api_key, base_url=DEFAULT_BASE_URL)


def call_chat(
    messages: list[dict],
    *,
    response_format: Literal["json", "text"] = "text",
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
) -> str:
    """
    调用 DeepSeek Chat API

    Args:
        messages: 消息列表，格式为 [{"role": "user", "content": "..."}]
        response_format: 响应格式，"json" 或 "text"，默认 "text"
        model: 模型名称，默认 "deepseek-chat"
        temperature: 温度参数，默认 0

    Returns:
        str: 模型响应内容

    Raises:
        ValueError: 环境变量未设置
        openai.APIError: API 调用失败
    """
    client = _get_client()

    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }

    # 若 response_format="json"，启用 JSON 输出模式
    if response_format == "json":
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)

    return response.choices[0].message.content or ""


# =============================================================================
# 以下为兼容现有代码的类实现
# =============================================================================


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
    DEFAULT_TEMPERATURE = 0.0
    DEFAULT_MAX_TOKENS = 4096
    DEFAULT_THINKING_MAX_TOKENS = 16384
    MAX_RETRIES = 2

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        base_url: str = "https://api.deepseek.com",
        thinking_enabled: bool = False,
        thinking_max_tokens: int | None = None,
    ):
        """
        初始化 DeepSeek 客户端

        Args:
            api_key: API Key
            model: 模型名称，默认 "deepseek-chat"
            temperature: 温度参数，默认 0.0
            max_tokens: 最大 token 数，默认 4096
            base_url: API 基础 URL
            thinking_enabled: 是否启用思考模式（用于 Module B）
            thinking_max_tokens: 思考模式下的最大 token 数
        """
        self._api_key = api_key
        self._model = model or self.DEFAULT_MODEL
        self._temperature = temperature if temperature is not None else self.DEFAULT_TEMPERATURE
        self._max_tokens = max_tokens or self.DEFAULT_MAX_TOKENS
        self._base_url = base_url
        self._thinking_enabled = thinking_enabled
        self._thinking_max_tokens = thinking_max_tokens or self.DEFAULT_THINKING_MAX_TOKENS
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        json_mode: bool = False,
        use_thinking: bool = False,
    ) -> LLMResponse:
        """
        发送聊天请求

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户消息
            temperature: 可选覆盖温度参数
            json_mode: 是否启用 JSON 输出模式
            use_thinking: 是否启用思考模式（仅对当前请求生效）

        Returns:
            LLMResponse: 响应对象

        Raises:
            APICallError: API 调用失败
        """
        try:
            # 构建请求参数
            kwargs: dict = {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }

            # 思考模式处理
            if use_thinking:
                # 思考模式下不支持 temperature 参数，使用 extra_body 启用
                kwargs["max_tokens"] = self._thinking_max_tokens
                kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
                # 注意：思考模式下 temperature 参数不会生效
            else:
                kwargs["temperature"] = temperature if temperature is not None else self._temperature
                kwargs["max_tokens"] = self._max_tokens

            # 启用 JSON 输出模式（PRD 4.2, 4.3 要求）
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            response = self._client.chat.completions.create(**kwargs)

            content = response.choices[0].message.content or ""

            # 提取思维链内容（如果有）
            reasoning_content = getattr(
                response.choices[0].message,
                "reasoning_content",
                None,
            )

            usage = response.usage

            return LLMResponse(
                content=content,
                model=response.model,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                reasoning_content=reasoning_content,
            )
        except Exception as e:
            raise APICallError(f"API 调用失败: {e}") from e

    def chat_with_json_output(
        self,
        system_prompt: str,
        user_prompt: str,
        result_class: Type[T],
        max_retries: int | None = None,
        use_thinking: bool = False,
    ) -> T:
        """
        发送聊天请求并解析 JSON 响应

        使用 DeepSeek 的 JSON 模式确保输出格式正确（PRD 4.2, 4.3 要求）。
        实现重试机制：失败时追加 JSON_REPAIR_SUFFIX 提示并重试。

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户消息
            result_class: 结果数据类 (ConsensusResult 或 ThesisProjectionResult)
            max_retries: 最大重试次数，默认为 MAX_RETRIES (2)
            use_thinking: 是否启用思考模式（仅对当前请求生效）

        Returns:
            T: 解析后的结果对象

        Raises:
            JSONParseError: JSON 解析失败（重试后仍失败）
            APICallError: API 调用失败
        """
        logger = logging.getLogger("alice_test")
        retries = max_retries if max_retries is not None else self.MAX_RETRIES
        last_error: Exception | None = None
        attempt_details: list[str] = []  # 记录每次尝试的详情

        for attempt in range(retries + 1):
            try:
                # 重试时追加 JSON 修复提示（PRD 7.2 要求）
                effective_system = system_prompt
                if attempt > 0:
                    logger.warning(
                        f"JSON 解析重试 (第 {attempt + 1}/{retries + 1} 次): "
                        f"原因 - {last_error}"
                    )
                    effective_system += PromptTemplates.JSON_REPAIR_SUFFIX

                # 启用 JSON 模式调用 API（PRD 4.2, 4.3 要求）
                response = self.chat(
                    effective_system,
                    user_prompt,
                    json_mode=True,  # 启用 response_format={"type": "json_object"}
                    use_thinking=use_thinking,  # 传递思考模式开关
                )

                # 解析并验证响应
                result = self._parse_json_response(response.content, result_class)

                if result.validate():
                    logger.debug(f"JSON 解析成功 (第 {attempt + 1} 次尝试)")
                    return result
                else:
                    error_msg = "响应验证失败：字段值不符合约束条件"
                    attempt_details.append(f"第 {attempt + 1} 次: {error_msg}")
                    raise JSONParseError(error_msg)

            except JSONParseError as e:
                last_error = e
                attempt_details.append(f"第 {attempt + 1} 次: {e}")
                if attempt < retries:
                    time.sleep(1)  # 重试前等待 1 秒
                    continue
                # 最终失败，记录所有尝试信息
                logger.error(
                    f"JSON 解析最终失败 (共尝试 {retries + 1} 次):\n"
                    + "\n".join(f"  - {detail}" for detail in attempt_details)
                )
                raise

            except APICallError:
                # API 调用失败直接抛出，不重试
                raise

        # 理论上不会到达这里，但为了类型完整性
        raise JSONParseError(
            f"JSON 解析失败（已重试 {retries} 次）: {last_error}"
        )

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
        logger = logging.getLogger("alice_test")

        # 记录原始响应（debug 级别，限制长度）
        content_preview = content[:500] if len(content) > 500 else content
        logger.debug(f"LLM 原始响应 (前500字符): {content_preview}")

        # 检查空响应
        if not content or not content.strip():
            logger.error("LLM 返回空响应")
            raise JSONParseError("LLM 返回空响应")

        try:
            # 清理 markdown 代码块标记
            cleaned = content.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            # 解析 JSON
            data = json.loads(cleaned)

            # 构造结果对象
            logger.debug(f"JSON 解析成功，字段: {list(data.keys())}")
            return result_class.from_dict(data)
        except json.JSONDecodeError as e:
            # 记录完整的原始响应用于调试
            logger.error(
                f"JSON 解析失败，原始响应:\n{content[:1000]}"
                + ("..." if len(content) > 1000 else "")
            )
            # 异常信息中包含响应内容摘要
            content_summary = content[:200] + ("..." if len(content) > 200 else "")
            raise JSONParseError(
                f"JSON 解析失败: {e}\n响应内容预览: {content_summary}"
            ) from e
        except Exception as e:
            logger.error(
                f"结果构造失败，原始响应:\n{content[:1000]}"
                + ("..." if len(content) > 1000 else "")
            )
            content_summary = content[:200] + ("..." if len(content) > 200 else "")
            raise JSONParseError(
                f"结果构造失败: {e}\n响应内容预览: {content_summary}"
            ) from e

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

        自动根据配置决定是否使用思考模式。

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
        return self.chat_with_json_output(
            system,
            user,
            ThesisProjectionResult,
            use_thinking=self._thinking_enabled,  # 使用配置的思考模式开关
        )


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    # 简单测试 call_chat 函数
    messages = [
        {"role": "system", "content": "你是一个有帮助的助手。"},
        {"role": "user", "content": "你好，请用一句话介绍自己。"},
    ]

    print("测试 text 格式:")
    result = call_chat(messages, response_format="text")
    print(f"响应: {result}\n")

    print("测试 json 格式:")
    messages_json = [
        {"role": "system", "content": "你是一个返回 JSON 格式数据的助手。"},
        {"role": "user", "content": "请返回一个包含 name 和 greeting 字段的 JSON 对象。"},
    ]
    result_json = call_chat(messages_json, response_format="json")
    print(f"响应: {result_json}")

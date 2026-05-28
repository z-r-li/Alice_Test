"""
DeepSeek API 客户端封装

使用 OpenAI 官方 Python SDK 调用 DeepSeek API
"""
import logging
import os
import json
import time
from typing import TypeVar, Type

from openai import OpenAI

from .models import LLMResponse, ConsensusResult, ThesisProjectionResult
from .prompts import PromptTemplates

T = TypeVar("T", ConsensusResult, ThesisProjectionResult)

# 默认配置 (2026)
# deepseek-chat / deepseek-reasoner 已成为 v4-flash 的兼容别名，计划于 2026/07/24 弃用。
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_THESIS_MODEL = "deepseek-v4-pro"
DEFAULT_TEMPERATURE = 0
DEFAULT_BASE_URL = "https://api.deepseek.com"

# 不支持思考模式的兼容别名。命中后会自动切换到对应 thinking 模型。
_NON_THINKING_ALIAS_TO_THINKING = {
    "deepseek-chat": "deepseek-reasoner",
}


class DeepSeekClientError(Exception):
    """DeepSeek 客户端错误基类"""
    pass


class JSONParseError(DeepSeekClientError):
    """JSON 解析错误（格式问题，可通过 JSON 修复提示重试）"""
    pass


class JSONValidationError(DeepSeekClientError):
    """JSON 内容验证错误（格式正确但字段值不合规）"""
    pass


class APICallError(DeepSeekClientError):
    """API 调用错误"""
    pass


class ContentModerationError(APICallError):
    """内容审核错误 - API 拒绝处理内容"""
    pass


class DeepSeekClient:
    """DeepSeek API 客户端"""

    DEFAULT_MODEL = "deepseek-v4-flash"
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
        thesis_model: str | None = None,
        client: OpenAI | None = None,
    ):
        """
        初始化 DeepSeek 客户端

        Args:
            api_key: API Key
            model: Module A 默认模型，默认 "deepseek-v4-flash"
            temperature: 温度参数，默认 0.0
            max_tokens: 最大 token 数，默认 4096
            base_url: API 基础 URL
            thinking_enabled: 是否启用思考模式（用于 Module B）
            thinking_max_tokens: 思考模式下的最大 token 数
            thesis_model: Module B 专用模型；留空则复用 model。
                常用值为 "deepseek-v4-pro" 以获得更强推理能力。
            client: 可选的 OpenAI 客户端实例，便于测试注入。
        """
        self._api_key = api_key
        self._model = model or self.DEFAULT_MODEL
        self._thesis_model = thesis_model or self._model
        self._temperature = temperature if temperature is not None else self.DEFAULT_TEMPERATURE
        self._max_tokens = max_tokens or self.DEFAULT_MAX_TOKENS
        self._base_url = base_url
        self._thinking_enabled = thinking_enabled
        self._thinking_max_tokens = thinking_max_tokens or self.DEFAULT_THINKING_MAX_TOKENS
        self._client = client if client is not None else OpenAI(api_key=api_key, base_url=base_url)

    @staticmethod
    def _resolve_thinking_model(model: str) -> str:
        """思考模式下，将非思考别名自动切换到对应的思考模型。"""
        return _NON_THINKING_ALIAS_TO_THINKING.get(model, model)

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        json_mode: bool = False,
        use_thinking: bool = False,
        model: str | None = None,
    ) -> LLMResponse:
        """
        发送聊天请求

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户消息
            temperature: 可选覆盖温度参数
            json_mode: 是否启用 JSON 输出模式
            use_thinking: 是否启用思考模式（仅对当前请求生效）
            model: 可选覆盖模型名称（仅对当前请求生效）

        Returns:
            LLMResponse: 响应对象

        Raises:
            APICallError: API 调用失败
        """
        logger = logging.getLogger("alice_test")
        try:
            resolved_model = model or self._model

            # 思考模式下自动切换非思考别名 (deepseek-chat → deepseek-reasoner)
            if use_thinking:
                switched = self._resolve_thinking_model(resolved_model)
                if switched != resolved_model:
                    logger.info(
                        f"思考模式：自动将模型 {resolved_model} 切换为 {switched}"
                    )
                    resolved_model = switched

            kwargs: dict = {
                "model": resolved_model,
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
            error_msg = str(e)
            # 检测内容审核错误
            if "Content Exists Risk" in error_msg or "content_filter" in error_msg.lower():
                raise ContentModerationError(f"内容审核失败: {e}") from e
            raise APICallError(f"API 调用失败: {e}") from e

    def chat_with_json_output(
        self,
        system_prompt: str,
        user_prompt: str,
        result_class: Type[T],
        max_retries: int | None = None,
        use_thinking: bool = False,
        model: str | None = None,
    ) -> T:
        """
        发送聊天请求并解析 JSON 响应

        使用 DeepSeek 的 JSON 模式确保输出格式正确（PRD 4.2, 4.3 要求）。

        重试策略：
        - JSONParseError (格式问题): 追加 JSON_REPAIR_SUFFIX 重试
        - JSONValidationError (字段值不合规): 不追加修复提示，直接重试

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户消息
            result_class: 结果数据类 (ConsensusResult 或 ThesisProjectionResult)
            max_retries: 最大重试次数，默认为 MAX_RETRIES (2)
            use_thinking: 是否启用思考模式（仅对当前请求生效）
            model: 可选覆盖模型名称（仅对当前请求生效）

        Returns:
            T: 解析后的结果对象

        Raises:
            JSONParseError | JSONValidationError: 重试后仍失败
            APICallError: API 调用失败
        """
        logger = logging.getLogger("alice_test")
        retries = max_retries if max_retries is not None else self.MAX_RETRIES
        last_error: Exception | None = None
        attempt_details: list[str] = []

        for attempt in range(retries + 1):
            try:
                effective_system = system_prompt
                # 只有上一轮是 JSONParseError (格式问题) 时才追加修复提示
                if attempt > 0:
                    logger.warning(
                        f"JSON 解析重试 (第 {attempt + 1}/{retries + 1} 次): "
                        f"原因 - {last_error}"
                    )
                    if isinstance(last_error, JSONParseError):
                        effective_system += PromptTemplates.JSON_REPAIR_SUFFIX

                response = self.chat(
                    effective_system,
                    user_prompt,
                    json_mode=True,
                    use_thinking=use_thinking,
                    model=model,
                )

                result = self._parse_json_response(response.content, result_class)

                if result.validate():
                    logger.debug(f"JSON 解析成功 (第 {attempt + 1} 次尝试)")
                    return result

                # 字段验证失败：不是格式问题，避免误用 JSON 修复提示
                raise JSONValidationError(
                    "响应验证失败：字段值不符合约束条件"
                )

            except (JSONParseError, JSONValidationError) as e:
                last_error = e
                attempt_details.append(f"第 {attempt + 1} 次 ({type(e).__name__}): {e}")
                if attempt < retries:
                    time.sleep(1)
                    continue
                logger.error(
                    f"JSON 解析最终失败 (共尝试 {retries + 1} 次):\n"
                    + "\n".join(f"  - {detail}" for detail in attempt_details)
                )
                raise

            except ContentModerationError:
                raise

            except APICallError:
                raise

        # 防御性兜底
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

            data = json.loads(cleaned)

            logger.debug(f"JSON 解析成功，字段: {list(data.keys())}")
            return result_class.from_dict(data)
        except json.JSONDecodeError as e:
            logger.error(
                f"JSON 解析失败，原始响应:\n{content[:1000]}"
                + ("..." if len(content) > 1000 else "")
            )
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
        logger = logging.getLogger("alice_test")
        system, user = PromptTemplates.format_consensus_prompt(
            ticker=ticker,
            ticker_name=ticker_name,
            price_close=price_close,
            pe_ttm=pe_ttm,
            pb=pb,
            texts_content=texts_content,
        )

        try:
            return self.chat_with_json_output(system, user, ConsensusResult)
        except ContentModerationError as e:
            logger.warning(
                f"[{ticker}] 内容审核触发，使用默认中性结果: {e}"
            )
            return ConsensusResult(
                sentiment_score=50,
                sentiment_label="中性",
                implied_growth=5.0,
                key_narrative="内容审核限制，无法分析市场情绪",
                key_worry="无法获取（内容审核限制）",
                key_hope="无法获取（内容审核限制）",
            )

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
        logger = logging.getLogger("alice_test")
        system, user = PromptTemplates.format_thesis_prompt(
            ticker=ticker,
            ticker_name=ticker_name,
            user_thesis=user_thesis,
            industry=industry,
        )

        try:
            return self.chat_with_json_output(
                system,
                user,
                ThesisProjectionResult,
                use_thinking=self._thinking_enabled,
                model=self._thesis_model,
            )
        except ContentModerationError as e:
            logger.warning(
                f"[{ticker}] 信念投影内容审核触发，使用默认结果: {e}"
            )
            return ThesisProjectionResult(
                thesis_aligned=True,
                our_growth=5.0,
                confidence="低",
                reasoning="内容审核限制，无法进行信念投影分析，使用保守默认值",
            )

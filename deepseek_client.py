"""
DeepSeek Client - 使用 OpenAI SDK 调用 DeepSeek API
"""

import os
from typing import Literal

from openai import OpenAI


# 初始化客户端
_client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

# 默认模型
DEFAULT_MODEL = "deepseek-chat"


def call_chat(
    messages: list[dict],
    *,
    response_format: Literal["json", "text"] = "text",
    model: str = DEFAULT_MODEL,
    temperature: float = 0,
) -> str:
    """
    调用 DeepSeek Chat API

    Args:
        messages: 消息列表，格式为 [{"role": "user", "content": "..."}, ...]
        response_format: 响应格式，"json" 或 "text"，默认 "text"
        model: 模型名称，默认 "deepseek-chat"
        temperature: 温度参数，默认 0

    Returns:
        模型返回的文本内容
    """
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }

    # 如果需要 JSON 输出，设置 response_format
    if response_format == "json":
        kwargs["response_format"] = {"type": "json_object"}

    response = _client.chat.completions.create(**kwargs)

    return response.choices[0].message.content


if __name__ == "__main__":
    # 简单测试
    test_messages = [
        {"role": "user", "content": "请用 JSON 格式返回：{\"greeting\": \"你好\"}"}
    ]

    # 测试 text 格式
    print("=== Text 格式测试 ===")
    result = call_chat([{"role": "user", "content": "你好，请简短介绍一下自己"}])
    print(result)

    # 测试 JSON 格式
    print("\n=== JSON 格式测试 ===")
    result = call_chat(test_messages, response_format="json")
    print(result)

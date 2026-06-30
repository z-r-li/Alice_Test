"""配置值 ``${ENV}`` 占位解析（CDX-5 / D-20260629-2 B 案）。

允许配置文件用 ``${VAR}`` 占位，load 时把**非密钥字段**的占位解析为环境变量值。

三条不变量（验收硬性）：

1. **插值**：对字符串值做 ``${VAR}`` 替换，支持一个值里出现多次、与普通文本混排
   （如 ``${HOME}/data``）。
2. **缺失即错**：被引用的环境变量未设置 → 抛 :class:`EnvPlaceholderError`
   （:meth:`ConfigManager.load` 在 load 阶段包成 ``ConfigError``），报文明确指出缺失的
   ``VAR``；绝不静默置空 / 置 None。
3. **密钥不驻留**：密钥类字段（``api_key`` / ``token`` / ``secret`` …）的 ``${VAR}``
   **不在 load 时解析**（:func:`interpolate_config` 跳过这些键），占位原样留在配置里；
   解析只在运行期 getter（``get_api_key`` / ``get_token``）读取时即时发生，解析值绝不
   写回 ``AppConfig`` / 进 ``__repr__`` / ``dict()`` / yaml dump / 日志。

语法只支持 ``${VAR}`` 一种（KISS）。``${VAR:-default}``、字面 ``$`` 转义等暂不实现
（除非团队明确要）。
"""
from __future__ import annotations

import os
import re
from typing import Any

# ${VAR}：VAR 为环境变量名（标识符：字母 / 下划线开头，后续字母 / 数字 / 下划线）。
_ENV_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# 密钥类字段名识别：
# - 按分隔符（_ - 空白）切段后，任一段精确命中下列词即视为密钥字段；
#   段精确匹配避免误伤（如 ``max_tokens`` 的 "tokens" ≠ "token"，不算密钥）。
# - 另对无分隔的强密钥词做整名子串兜底（如 camelCase ``clientSecret``）。
_SECRET_SEGMENTS = frozenset(
    {
        "key",
        "token",
        "secret",
        "secrets",
        "password",
        "passwd",
        "credential",
        "credentials",
        "apikey",
    }
)
_SECRET_STRONG_SUBSTRINGS = ("secret", "password", "credential", "apikey")
_SEGMENT_SPLIT_RE = re.compile(r"[_\-\s]+")


class EnvPlaceholderError(ValueError):
    """配置 ``${ENV}`` 占位解析失败（引用的环境变量缺失）。

    继承 ``ValueError``：与既有 getter「未配置即抛 ValueError」契约一致；
    :meth:`ConfigManager.load` 会在 load 阶段把它包成 ``ConfigError``。
    """


def is_secret_key(name: str) -> bool:
    """字段名是否属于密钥类（大小写不敏感）。

    分隔符切段后任一段精确命中密钥词（``key`` / ``token`` / ``secret`` …）即为密钥；
    段精确匹配避免误伤 ``max_tokens`` 等普通字段。另对 camelCase 等无分隔强密钥词
    （``clientSecret``）做整名子串兜底。
    """
    lowered = name.lower()
    segments = _SEGMENT_SPLIT_RE.split(lowered)
    if any(seg in _SECRET_SEGMENTS for seg in segments):
        return True
    return any(word in lowered for word in _SECRET_STRONG_SUBSTRINGS)


def is_env_placeholder(value: Any) -> bool:
    """字符串里是否含 ``${VAR}`` 占位。"""
    return isinstance(value, str) and bool(_ENV_PLACEHOLDER_RE.search(value))


def resolve_env_placeholders(value: str) -> str:
    """把字符串中所有 ``${VAR}`` 替换为对应环境变量值。

    支持一个值里出现多次、与普通文本混排。任一被引用的环境变量未设置即 fail-closed
    抛 :class:`EnvPlaceholderError`（绝不静默置空）。无占位则原样返回。

    Args:
        value: 可能含 ``${VAR}`` 占位的字符串

    Returns:
        str: 替换后的字符串

    Raises:
        EnvPlaceholderError: 引用的环境变量缺失，报文含该 ``VAR`` 名
    """

    def _sub(match: re.Match[str]) -> str:
        var = match.group(1)
        env_val = os.environ.get(var)
        if env_val is None:
            raise EnvPlaceholderError(
                f"配置引用的环境变量 ${{{var}}} 未设置；"
                "fail-closed 拒绝静默置空，请设置该环境变量或修正配置占位。"
            )
        return env_val

    return _ENV_PLACEHOLDER_RE.sub(_sub, value)


def interpolate_config(obj: Any, *, _sensitive: bool = False) -> Any:
    """递归对配置结构做 ``${VAR}`` 插值，但跳过密钥类字段（密钥不驻留不变量）。

    - ``dict``：逐键递归；键名命中密钥类 token 时，其整棵子树标记为 sensitive、不解析。
    - ``list``：逐元素递归，继承父级 sensitive 标记。
    - ``str``：非 sensitive 才解析；sensitive（密钥字段）原样保留 ``${VAR}`` 占位，
      留待运行期 getter 即时解析。
    - 其它标量：原样返回。

    Args:
        obj: 原始配置（dict / list / 标量）
        _sensitive: 内部递归用——父级是否为密钥子树

    Returns:
        Any: 占位解析后的同构结构（密钥字段原样保留占位）
    """
    if isinstance(obj, dict):
        return {
            k: interpolate_config(
                v,
                _sensitive=_sensitive or (isinstance(k, str) and is_secret_key(k)),
            )
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [interpolate_config(x, _sensitive=_sensitive) for x in obj]
    if isinstance(obj, str):
        return obj if _sensitive else resolve_env_placeholders(obj)
    return obj

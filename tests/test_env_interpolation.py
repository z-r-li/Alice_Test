"""CDX-5 配置 ``${ENV}`` 占位解析测试（D-20260629-2 B 案，守三条不变量）。

三条不变量：
1. **插值**：``${VAR}`` 替换，支持一值多次出现、与普通文本混排。
2. **缺失即错**：被引用的 env 未设置 → 抛错（load 层包成 ConfigError），报文含 VAR 名；
   绝不静默置空。
3. **密钥不驻留**：密钥字段（api_key/token/…）的 ``${VAR}`` 不在 load 时解析、不进 dump /
   repr / 日志；getter 运行期即时解析、解析值不写回 AppConfig。
"""
import pytest

from src.config.env_interpolation import (
    EnvPlaceholderError,
    interpolate_config,
    is_env_placeholder,
    is_secret_key,
    resolve_env_placeholders,
)
from src.config.manager import ConfigError, load_config


class TestResolveEnvPlaceholders:
    """不变量 1 + 2：解析器单元行为。"""

    def test_single_placeholder(self, monkeypatch):
        monkeypatch.setenv("ALICE_X", "value-x")
        assert resolve_env_placeholders("${ALICE_X}") == "value-x"

    def test_mixed_and_repeated(self, monkeypatch):
        """同值多次出现 + 与普通文本混排。"""
        monkeypatch.setenv("ALICE_DIR", "/data")
        monkeypatch.setenv("ALICE_NAME", "alice")
        result = resolve_env_placeholders("${ALICE_DIR}/${ALICE_NAME}/${ALICE_NAME}.db")
        assert result == "/data/alice/alice.db"

    def test_no_placeholder_passthrough(self):
        assert resolve_env_placeholders("plain-text") == "plain-text"

    def test_missing_raises_with_var_name(self, monkeypatch):
        """缺失即错：报文必须含缺失的 VAR 名，绝不静默置空。"""
        monkeypatch.delenv("ALICE_MISSING", raising=False)
        with pytest.raises(EnvPlaceholderError) as exc_info:
            resolve_env_placeholders("${ALICE_MISSING}/x")
        assert "ALICE_MISSING" in str(exc_info.value)

    def test_is_env_placeholder(self):
        assert is_env_placeholder("${X}") is True
        assert is_env_placeholder("a${X}b") is True
        assert is_env_placeholder("plain") is False
        assert is_env_placeholder("") is False
        assert is_env_placeholder(None) is False


class TestInterpolateConfigSkipsSecrets:
    """不变量 3（load 层）：密钥键的占位被跳过、不解析。"""

    def test_secret_key_classification(self):
        for name in ("api_key", "token", "search_api_key", "SECRET", "DbPassword"):
            assert is_secret_key(name) is True
        for name in ("model", "path", "provider", "max_tokens"):
            assert is_secret_key(name) is False

    def test_skips_secret_keys(self, monkeypatch):
        monkeypatch.setenv("ALICE_SECRET", "should-not-resolve")
        out = interpolate_config(
            {"llm_api": {"api_key": "${ALICE_SECRET}", "model": "m"}}
        )
        # 密钥字段占位原样保留（不解析、不驻留）
        assert out["llm_api"]["api_key"] == "${ALICE_SECRET}"

    def test_secret_subtree_inherits_skip(self, monkeypatch):
        """密钥键下的嵌套结构整棵不解析。"""
        monkeypatch.setenv("ALICE_SECRET", "nope")
        out = interpolate_config({"token": {"nested": "${ALICE_SECRET}"}})
        assert out["token"]["nested"] == "${ALICE_SECRET}"

    def test_resolves_non_secret(self, monkeypatch):
        monkeypatch.setenv("ALICE_PATH", "/out")
        out = interpolate_config({"output": {"path": "${ALICE_PATH}/a.csv"}})
        assert out["output"]["path"] == "/out/a.csv"


_MINIMAL_TARGET = (
    "targets:\n"
    '  - ticker: "TEST.SH"\n'
    '    name: "测试"\n'
    '    thesis: "测试信念"\n'
)


class TestConfigLoadEnvInterpolation:
    """三条不变量在真实 load 流程上的端到端验收。"""

    def test_non_secret_interpolated_on_load(self, tmp_path, monkeypatch):
        """不变量 1：非密钥字段 ${VAR} 在 load 时被解析。"""
        monkeypatch.setenv("ALICE_OUT_DIR", "/tmp/aliceout")
        cfg = tmp_path / "c.yaml"
        cfg.write_text(
            "output:\n"
            '  path: "${ALICE_OUT_DIR}/audit.csv"\n' + _MINIMAL_TARGET,
            encoding="utf-8",
        )
        config = load_config(cfg)
        assert config.output.path == "/tmp/aliceout/audit.csv"

    def test_missing_env_raises_configerror_with_var(self, tmp_path, monkeypatch):
        """不变量 2：非密钥字段引用缺失 env → ConfigError，报文含 VAR 名。"""
        monkeypatch.delenv("ALICE_NOPE", raising=False)
        cfg = tmp_path / "c.yaml"
        cfg.write_text(
            "output:\n  path: \"${ALICE_NOPE}/x.csv\"\n" + _MINIMAL_TARGET,
            encoding="utf-8",
        )
        with pytest.raises(ConfigError) as exc_info:
            load_config(cfg)
        assert "ALICE_NOPE" in str(exc_info.value)

    def test_secret_not_resident_but_getter_resolves(self, tmp_path, monkeypatch):
        """不变量 3：api_key 写成 ${ENV} → (a) getter 取到值；(b) dump/repr 无明文/解析值。"""
        secret = "super-secret-xyz-9999"
        monkeypatch.setenv("ALICE_LLM_KEY", secret)
        # 故意不设 DEEPSEEK_API_KEY：证明 getter 解析的是占位指向的自定义 env
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        cfg = tmp_path / "c.yaml"
        cfg.write_text(
            "llm_api:\n"
            '  api_key: "${ALICE_LLM_KEY}"\n'
            '  model: "deepseek-v4-flash"\n'
            "  temperature: 0\n" + _MINIMAL_TARGET,
            encoding="utf-8",
        )
        config = load_config(cfg)

        # (a) getter 运行期即时解析，能取到值
        assert config.llm_api.get_api_key() == secret

        # (b) 明文密钥 / 解析后的值绝不出现在 dump / repr
        assert secret not in repr(config)
        assert secret not in config.model_dump_json()
        assert secret not in str(config.model_dump())

        # 配置对象里只驻留无害的占位引用，不驻留解析值
        assert config.llm_api.api_key == "${ALICE_LLM_KEY}"

    def test_secret_token_getter_resolves(self, tmp_path, monkeypatch):
        """密钥不驻留同样适用于 tushare token 的 ${ENV} 占位。"""
        secret = "tk-secret-12345"
        monkeypatch.setenv("ALICE_TS_TOKEN", secret)
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
        cfg = tmp_path / "c.yaml"
        cfg.write_text(
            "data_sources:\n"
            "  a_shares:\n"
            '    provider: "tushare"\n'
            '    token: "${ALICE_TS_TOKEN}"\n' + _MINIMAL_TARGET,
            encoding="utf-8",
        )
        config = load_config(cfg)

        assert config.data_sources.a_shares.get_token() == secret
        assert secret not in repr(config)
        assert secret not in config.model_dump_json()
        assert config.data_sources.a_shares.token == "${ALICE_TS_TOKEN}"

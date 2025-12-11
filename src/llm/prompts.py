"""
Prompt 模板管理
"""
from string import Template


class PromptTemplates:
    """Prompt 模板集合"""

    # Module A: 市场共识引擎的 System Prompt
    CONSENSUS_ENGINE_SYSTEM: str = """你是一个客观的"市场情绪审计师"。
现在给你一组关于【{ticker_name}】的最新市场资讯（包括研报摘要和新闻标题），以及该标的当前估值信息。

你的任务是：
1. 提炼出市场当前的主要叙事（最担忧什么？最期待什么？）。
2. 根据下述量表，对市场情绪进行打分（整数 0–100）：
   - 0–20：提及崩盘、危机、不可持续；
   - 21–40：关注成本风险、汇率风险、增长不及预期；
   - 41–60：多空平衡，价格已 Price-in；
   - 61–80：强调增长逻辑，弱化风险；
   - 81–100：使用"无限空间"、"新纪元"等极度乐观用语。
3. 基于当前估值与上述情绪，保守估计市场隐含的未来 3 年年化增长率 g（单位：百分比）。

请严格输出 JSON，字段包括：
- sentiment_score: int (0–100)
- implied_growth: float (百分数，例如 5 表示 5%)
- key_narrative: string (一段话描述市场主要叙事)"""

    # Module A: 用户消息模板
    CONSENSUS_ENGINE_USER: str = """标的：{ticker_name} ({ticker})

当前估值信息：
- 收盘价：{price_close}
- PE (TTM)：{pe_ttm}
- PB：{pb}

最新市场资讯（过去48小时）：
{texts_content}

请分析并输出 JSON 结果。"""

    # Module B: 信念投影器的 System Prompt
    THESIS_PROJECTOR_SYSTEM: str = """你是一个基于第一性原理的长期投资审计师。
已知投资人的核心信念为：
{user_thesis}

请忽略短期市场情绪和价格波动，只基于上述信念与产业逻辑，评估该标的在未来 3 年的"合理年化增长率 g"（单位：百分比）。

请考虑：行业空间、竞争格局、资本开支周期、政策约束等关键因素，但不需要给出过于细致的估值模型。

输出格式必须为 JSON，字段包括：
- our_growth: float (百分数，例如 15 表示 15%)
- reasoning: string (你得出该增长率的逻辑说明，简明扼要)"""

    # Module B: 用户消息模板
    THESIS_PROJECTOR_USER: str = """标的：{ticker_name} ({ticker})
行业：{industry}

请基于投资人信念，评估合理增长率并输出 JSON 结果。"""

    # JSON 修复提示（重试时使用）
    JSON_REPAIR_SUFFIX: str = """

注意：你的上一次回复无法解析为有效 JSON。
请严格按照要求的 JSON 格式输出，不要包含任何额外的自然语言解释或 markdown 代码块标记。
直接输出纯 JSON 对象。"""

    @classmethod
    def format_consensus_prompt(
        cls,
        ticker: str,
        ticker_name: str,
        price_close: float,
        pe_ttm: float | None,
        pb: float | None,
        texts_content: str,
    ) -> tuple[str, str]:
        """
        格式化市场共识引擎的 Prompt

        Args:
            ticker: 证券代码
            ticker_name: 标的名称
            price_close: 收盘价
            pe_ttm: 市盈率
            pb: 市净率
            texts_content: 格式化后的文本内容

        Returns:
            tuple[str, str]: (system_prompt, user_prompt)
        """
        system = cls.CONSENSUS_ENGINE_SYSTEM.format(ticker_name=ticker_name)
        user = cls.CONSENSUS_ENGINE_USER.format(
            ticker_name=ticker_name,
            ticker=ticker,
            price_close=price_close,
            pe_ttm=pe_ttm if pe_ttm else "N/A",
            pb=pb if pb else "N/A",
            texts_content=texts_content,
        )
        return system, user

    @classmethod
    def format_thesis_prompt(
        cls,
        ticker: str,
        ticker_name: str,
        user_thesis: str,
        industry: str = "未知",
    ) -> tuple[str, str]:
        """
        格式化信念投影器的 Prompt

        Args:
            ticker: 证券代码
            ticker_name: 标的名称
            user_thesis: 用户宏观信念
            industry: 行业（可选）

        Returns:
            tuple[str, str]: (system_prompt, user_prompt)
        """
        system = cls.THESIS_PROJECTOR_SYSTEM.format(user_thesis=user_thesis)
        user = cls.THESIS_PROJECTOR_USER.format(
            ticker_name=ticker_name,
            ticker=ticker,
            industry=industry,
        )
        return system, user

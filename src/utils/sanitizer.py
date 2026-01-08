"""
文本脱敏模块 (Text Sanitizer)

用于在调用 LLM API 前对敏感内容进行脱敏处理，
避免触发内容审核（如 DeepSeek 的 "Content Exists Risk" 错误）。
"""
import re
import logging
import json
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("alice_test")


@dataclass
class SensitiveWord:
    """敏感词条目"""
    word: str
    replacement: str
    category: str = "general"
    is_regex: bool = False
    priority: int = 0


class SensitiveWordDict:
    """敏感词词典"""

    # 军工/国防类
    MILITARY_WORDS: dict[str, str] = {
        "军舰": "大型船舶", "战舰": "特种船舶", "航母": "大型舰船",
        "航空母舰": "大型舰船", "驱逐舰": "护卫船舶", "护卫舰": "护卫船舶",
        "潜艇": "水下船舶", "潜水艇": "水下船舶", "核潜艇": "特种水下船舶",
        "导弹": "特种装备", "火箭": "航天器", "战斗机": "特种飞行器",
        "歼击机": "特种飞行器", "轰炸机": "特种飞行器", "武器": "特种产品",
        "军火": "特种产品", "弹药": "特种物资", "炸弹": "特种物资",
        "坦克": "特种车辆", "装甲车": "特种车辆",
        "军工": "特种装备制造", "国防": "特定领域", "军事": "特定领域",
        "军方": "特定机构", "军队": "特定机构", "解放军": "特定机构",
        "部队": "特定机构", "国防科工": "特种制造", "军品": "特种产品",
        "军用": "特种用途", "军民融合": "产业融合",
        "核武器": "特种能源装备", "核弹": "特种能源装备",
        "原子弹": "特种能源装备", "氢弹": "特种能源装备",
        "核技术": "特种能源技术", "铀浓缩": "特种材料加工",
        "雷达": "探测设备", "电子战": "电子对抗",
    }

    # 政治敏感类
    POLITICAL_WORDS: dict[str, str] = {
        "台海": "区域形势", "台湾问题": "区域问题", "两岸关系": "区域关系",
        "统一": "整合", "南海": "南部海域", "东海": "东部海域",
        "钓鱼岛": "争议岛屿", "领土争端": "区域争议",
        "制裁": "贸易限制", "贸易战": "贸易摩擦", "科技战": "技术竞争",
        "脱钩": "供应链调整", "封锁": "贸易限制", "禁运": "出口管制",
        "实体清单": "出口管制名单", "黑名单": "受限名单",
        "反腐": "合规整顿", "巡视": "内部检查", "纪检": "合规部门",
    }

    # 敏感公司名称
    COMPANY_WORDS: dict[str, str] = {
        "中国船舶": "该船舶制造企业", "中船重工": "该船舶制造企业",
        "中船集团": "该船舶制造企业",
        "中国航天": "该航天企业", "航天科技": "该航天企业",
        "航天科工": "该航天企业", "中航工业": "该航空企业",
        "中国航空": "该航空企业",
        "中国兵器": "该特种装备企业", "兵器工业": "该特种装备企业",
        "北方工业": "该特种装备企业",
        "中国核电": "该能源企业", "中核集团": "该能源企业",
        "中广核": "该能源企业",
        "中国电子": "该电子企业", "中国电科": "该电子企业",
        "中国烟草": "该消费品企业",
    }

    # 金融敏感类
    FINANCIAL_WORDS: dict[str, str] = {
        "暴涨": "大幅上涨", "暴跌": "大幅下跌", "崩盘": "显著回调",
        "割韭菜": "市场波动", "庄家": "主力资金", "操纵": "异常波动",
        "内幕": "非公开信息", "黑幕": "违规行为", "爆雷": "风险暴露",
        "跑路": "经营异常",
    }

    def __init__(self):
        self._words: list[SensitiveWord] = []
        self._load_builtin_words()

    def _load_builtin_words(self) -> None:
        word_sets = [
            (self.MILITARY_WORDS, "military", 100),
            (self.POLITICAL_WORDS, "political", 80),
            (self.COMPANY_WORDS, "company", 60),
            (self.FINANCIAL_WORDS, "financial", 40),
        ]
        for word_dict, category, priority in word_sets:
            for word, replacement in word_dict.items():
                self._words.append(SensitiveWord(
                    word=word, replacement=replacement,
                    category=category, priority=priority,
                ))
        self._words.sort(key=lambda w: (-len(w.word), -w.priority))

    def load_from_json(self, filepath: str | Path) -> int:
        filepath = Path(filepath)
        if not filepath.exists():
            logger.warning(f"敏感词词典文件不存在: {filepath}")
            return 0
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            count = 0
            for item in data.get("words", []):
                self.add_word(
                    word=item["word"], replacement=item["replacement"],
                    category=item.get("category", "custom"),
                    is_regex=item.get("is_regex", False),
                    priority=item.get("priority", 50),
                )
                count += 1
            logger.info(f"从 {filepath} 加载了 {count} 条自定义敏感词")
            return count
        except Exception as e:
            logger.error(f"加载敏感词词典失败: {e}")
            return 0

    def add_word(self, word: str, replacement: str, category: str = "custom",
                 is_regex: bool = False, priority: int = 50) -> None:
        self._words.append(SensitiveWord(
            word=word, replacement=replacement, category=category,
            is_regex=is_regex, priority=priority,
        ))
        self._words.sort(key=lambda w: (-len(w.word), -w.priority))

    def get_words(self, category: str | None = None) -> list[SensitiveWord]:
        if category is None:
            return self._words.copy()
        return [w for w in self._words if w.category == category]


class TextSanitizer:
    """文本脱敏器"""

    def __init__(self, custom_dict_path: str | Path | None = None,
                 enabled_categories: list[str] | None = None):
        self._dict = SensitiveWordDict()
        self._enabled_categories = enabled_categories
        self._sanitize_log: list[tuple[str, str]] = []
        if custom_dict_path:
            self._dict.load_from_json(custom_dict_path)

    def sanitize(self, text: str, log_replacements: bool = False) -> str:
        if not text:
            return text
        if log_replacements:
            self._sanitize_log.clear()
        result = text
        for sw in self._dict.get_words():
            if self._enabled_categories and sw.category not in self._enabled_categories:
                continue
            if sw.is_regex:
                pattern = re.compile(sw.word)
                if pattern.search(result):
                    result = pattern.sub(sw.replacement, result)
                    if log_replacements:
                        self._sanitize_log.append((sw.word, sw.replacement))
            else:
                if sw.word in result:
                    result = result.replace(sw.word, sw.replacement)
                    if log_replacements:
                        self._sanitize_log.append((sw.word, sw.replacement))
        return result

    def get_replacement_log(self) -> list[tuple[str, str]]:
        return self._sanitize_log.copy()

    def add_sensitive_word(self, word: str, replacement: str,
                           category: str = "custom") -> None:
        self._dict.add_word(word, replacement, category)


# 全局单例
_default_sanitizer: TextSanitizer | None = None

def get_sanitizer() -> TextSanitizer:
    global _default_sanitizer
    if _default_sanitizer is None:
        _default_sanitizer = TextSanitizer()
    return _default_sanitizer

def sanitize_text(text: str) -> str:
    return get_sanitizer().sanitize(text)

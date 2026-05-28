"""
CSV 写入测试

测试用例：
- test_save_single_result: 保存单条审计结果
- test_save_batch: 批量保存
- test_comma_escaping: 逗号转义
- test_query_methods: 查询方法测试
- test_file_creation: 文件创建和表头写入
"""
import csv
from datetime import datetime
from pathlib import Path

import pytest

from src.engines.gap_calculator import AuditResult, AuditSignal
from src.persistence.csv_writer import CSVReportWriter


class TestCSVReportWriterSave:
    """CSV 保存功能测试类"""

    def test_save_single_result(
        self,
        temp_csv_path: Path,
        sample_audit_result: AuditResult,
    ):
        """测试保存单条审计结果"""
        writer = CSVReportWriter(temp_csv_path)
        writer.save(sample_audit_result)

        # 验证文件存在
        assert temp_csv_path.exists()

        # 读取并验证内容
        with open(temp_csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        # 应该有表头和一条数据
        assert len(rows) == 2
        assert rows[0] == CSVReportWriter.CSV_COLUMNS
        assert rows[1][0] == "2024-01-15"  # date
        assert rows[1][1] == "600150.SH"  # ticker
        assert rows[1][2] == "中国船舶"  # name

    def test_save_batch(
        self,
        temp_csv_path: Path,
        sample_audit_result: AuditResult,
        sample_audit_result_overheated: AuditResult,
        sample_audit_result_wait: AuditResult,
    ):
        """测试批量保存审计结果"""
        writer = CSVReportWriter(temp_csv_path)
        results = [
            sample_audit_result,
            sample_audit_result_overheated,
            sample_audit_result_wait,
        ]
        writer.save_batch(results)

        # 读取并验证内容
        with open(temp_csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        # 应该有表头和三条数据
        assert len(rows) == 4
        assert rows[1][1] == "600150.SH"
        assert rows[2][1] == "NVDA"
        assert rows[3][1] == "0700.HK"

    def test_save_append_mode(
        self,
        temp_csv_path: Path,
        sample_audit_result: AuditResult,
        sample_audit_result_overheated: AuditResult,
    ):
        """测试追加模式保存"""
        writer = CSVReportWriter(temp_csv_path)

        # 分两次保存
        writer.save(sample_audit_result)
        writer.save(sample_audit_result_overheated)

        # 读取并验证内容
        with open(temp_csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        # 应该有表头和两条数据
        assert len(rows) == 3
        assert rows[1][1] == "600150.SH"
        assert rows[2][1] == "NVDA"


class TestCSVCommaEscaping:
    """逗号转义测试类"""

    def test_comma_escaping_in_text_fields(self, temp_csv_path: Path):
        """测试文本字段中的逗号转义"""
        result = AuditResult(
            date=datetime(2024, 1, 15),
            ticker="TEST.SH",
            name="测试公司,子公司",  # 包含逗号
            price=10.0,
            pe_ttm=15.0,
            sentiment_score=50,
            sentiment_label="中性",
            implied_growth=10.0,
            key_narrative="叙事包含,逗号",  # 包含逗号
            key_worry="担忧,也有逗号",  # 包含逗号
            key_hope="期望,同样有逗号",  # 包含逗号
            thesis_aligned=True,
            our_growth=15.0,
            confidence="中",
            reasoning="测试推理",
            gap=5.0,
            signal=AuditSignal.WAIT,
        )

        writer = CSVReportWriter(temp_csv_path)
        writer.save(result)

        # 读取并验证逗号保留（由 csv.writer 处理引号转义，不替换为中文逗号）
        with open(temp_csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        data_row = rows[1]
        assert "," in data_row[2]  # name: 测试公司,子公司 - 逗号保留
        assert "，" not in data_row[2]
        assert "," in data_row[11]  # key_narrative
        assert "," in data_row[12]  # key_worry
        assert "," in data_row[13]  # key_hope

    def test_no_comma_no_escaping(self, temp_csv_path: Path):
        """测试没有逗号时不进行转义"""
        result = AuditResult(
            date=datetime(2024, 1, 15),
            ticker="TEST.SH",
            name="测试公司",  # 无逗号
            price=10.0,
            pe_ttm=15.0,
            sentiment_score=50,
            sentiment_label="中性",
            implied_growth=10.0,
            key_narrative="正常叙事",
            key_worry="正常担忧",
            key_hope="正常期望",
            thesis_aligned=True,
            our_growth=15.0,
            confidence="中",
            reasoning="测试推理",
            gap=5.0,
            signal=AuditSignal.WAIT,
        )

        writer = CSVReportWriter(temp_csv_path)
        writer.save(result)

        with open(temp_csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        data_row = rows[1]
        assert data_row[2] == "测试公司"
        assert "，" not in data_row[2]


class TestCSVQueryMethods:
    """CSV 查询方法测试类"""

    @pytest.fixture
    def writer_with_data(
        self,
        temp_csv_path: Path,
        sample_audit_result: AuditResult,
        sample_audit_result_overheated: AuditResult,
        sample_audit_result_wait: AuditResult,
    ) -> CSVReportWriter:
        """创建包含测试数据的 writer"""
        writer = CSVReportWriter(temp_csv_path)
        writer.save_batch([
            sample_audit_result,
            sample_audit_result_overheated,
            sample_audit_result_wait,
        ])
        return writer

    def test_get_by_ticker(self, writer_with_data: CSVReportWriter):
        """测试按 ticker 查询"""
        results = writer_with_data.get_by_ticker("600150.SH")

        assert len(results) == 1
        assert results[0].ticker == "600150.SH"
        assert results[0].name == "中国船舶"

    def test_get_by_ticker_not_found(self, writer_with_data: CSVReportWriter):
        """测试 ticker 不存在"""
        results = writer_with_data.get_by_ticker("UNKNOWN")

        assert len(results) == 0

    def test_get_by_ticker_with_date_range(self, writer_with_data: CSVReportWriter):
        """测试带日期范围的 ticker 查询"""
        start = datetime(2024, 1, 14)
        end = datetime(2024, 1, 16)

        results = writer_with_data.get_by_ticker(
            "600150.SH",
            start_date=start,
            end_date=end,
        )

        assert len(results) == 1

    def test_get_by_date(self, writer_with_data: CSVReportWriter):
        """测试按日期查询"""
        results = writer_with_data.get_by_date(datetime(2024, 1, 15))

        assert len(results) == 1
        assert results[0].ticker == "600150.SH"

    def test_get_by_date_no_results(self, writer_with_data: CSVReportWriter):
        """测试日期无结果"""
        results = writer_with_data.get_by_date(datetime(2024, 12, 31))

        assert len(results) == 0

    def test_get_by_signal_opportunity(self, writer_with_data: CSVReportWriter):
        """测试按 OPPORTUNITY 信号查询"""
        results = writer_with_data.get_by_signal("OPPORTUNITY")

        assert len(results) == 1
        assert results[0].signal == AuditSignal.OPPORTUNITY

    def test_get_by_signal_overheated(self, writer_with_data: CSVReportWriter):
        """测试按 OVERHEATED 信号查询"""
        results = writer_with_data.get_by_signal("OVERHEATED")

        assert len(results) == 1
        assert results[0].signal == AuditSignal.OVERHEATED

    def test_get_by_signal_wait(self, writer_with_data: CSVReportWriter):
        """测试按 WAIT 信号查询"""
        results = writer_with_data.get_by_signal("WAIT")

        assert len(results) == 1
        assert results[0].signal == AuditSignal.WAIT

    def test_get_latest(self, temp_csv_path: Path):
        """测试获取最新结果"""
        # 创建同一 ticker 的多个结果
        results = [
            AuditResult(
                date=datetime(2024, 1, 10),
                ticker="TEST.SH",
                name="测试",
                price=10.0,
                pe_ttm=15.0,
                sentiment_score=50,
                sentiment_label="中性",
                implied_growth=10.0,
                key_narrative="旧数据",
                key_worry="担忧",
                key_hope="期望",
                thesis_aligned=True,
                our_growth=15.0,
                confidence="中",
                reasoning="测试推理",
                gap=5.0,
                signal=AuditSignal.WAIT,
            ),
            AuditResult(
                date=datetime(2024, 1, 20),  # 更新的日期
                ticker="TEST.SH",
                name="测试",
                price=12.0,
                pe_ttm=16.0,
                sentiment_score=55,
                sentiment_label="中性",
                implied_growth=12.0,
                key_narrative="新数据",
                key_worry="担忧",
                key_hope="期望",
                thesis_aligned=True,
                our_growth=18.0,
                confidence="高",
                reasoning="测试推理",
                gap=6.0,
                signal=AuditSignal.WAIT,
            ),
        ]

        writer = CSVReportWriter(temp_csv_path)
        writer.save_batch(results)

        latest = writer.get_latest("TEST.SH")

        assert latest is not None
        assert latest.date == datetime(2024, 1, 20)
        assert latest.key_narrative == "新数据"

    def test_get_latest_not_found(self, writer_with_data: CSVReportWriter):
        """测试获取不存在 ticker 的最新结果"""
        latest = writer_with_data.get_latest("UNKNOWN")

        assert latest is None


class TestCSVFileCreation:
    """CSV 文件创建测试类"""

    def test_ensure_file_exists_creates_file(self, temp_csv_path: Path):
        """测试文件不存在时创建文件"""
        assert not temp_csv_path.exists()

        writer = CSVReportWriter(temp_csv_path)
        writer._ensure_file_exists()

        assert temp_csv_path.exists()

    def test_ensure_file_exists_writes_header(self, temp_csv_path: Path):
        """测试创建文件时写入表头"""
        writer = CSVReportWriter(temp_csv_path)
        writer._ensure_file_exists()

        with open(temp_csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)

        assert header == CSVReportWriter.CSV_COLUMNS

    def test_ensure_file_exists_creates_parent_dirs(self, temp_dir: Path):
        """测试创建父目录"""
        nested_path = temp_dir / "nested" / "dir" / "report.csv"

        writer = CSVReportWriter(nested_path)
        writer._ensure_file_exists()

        assert nested_path.exists()
        assert nested_path.parent.exists()

    def test_ensure_file_exists_no_duplicate_header(self, temp_csv_path: Path):
        """测试文件已存在时不重复写入表头"""
        writer = CSVReportWriter(temp_csv_path)

        # 第一次创建
        writer._ensure_file_exists()

        # 第二次调用
        writer._ensure_file_exists()

        with open(temp_csv_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # 只应有一行（表头）
        assert len(lines) == 1


class TestCSVRowConversion:
    """CSV 行转换测试类"""

    def test_result_to_row(
        self,
        temp_csv_path: Path,
        sample_audit_result: AuditResult,
    ):
        """测试 AuditResult 转 CSV 行"""
        writer = CSVReportWriter(temp_csv_path)
        row = writer._result_to_row(sample_audit_result)

        assert row[0] == "2024-01-15"  # date
        assert row[1] == "600150.SH"  # ticker
        assert row[2] == "中国船舶"  # name
        assert row[3] == "35.5"  # price
        assert row[4] == "25.5"  # pe_ttm
        assert row[5] == "35"  # sentiment_score
        assert row[6] == "悲观"  # sentiment_label
        assert row[10] == "OPPORTUNITY"  # signal

    def test_result_to_row_none_pe(self, temp_csv_path: Path):
        """测试 PE 为 None 时的转换"""
        result = AuditResult(
            date=datetime(2024, 1, 15),
            ticker="TEST.SH",
            name="测试",
            price=10.0,
            pe_ttm=None,  # PE 为空
            sentiment_score=50,
            sentiment_label="中性",
            implied_growth=10.0,
            key_narrative="测试",
            key_worry="担忧",
            key_hope="期望",
            thesis_aligned=True,
            our_growth=15.0,
            confidence="中",
            reasoning="测试推理",
            gap=5.0,
            signal=AuditSignal.WAIT,
        )

        writer = CSVReportWriter(temp_csv_path)
        row = writer._result_to_row(result)

        assert row[4] == ""  # pe_ttm 为空字符串

    def test_row_to_result(self, temp_csv_path: Path):
        """测试 CSV 行转 AuditResult"""
        row = {
            "date": "2024-01-15",
            "ticker": "TEST.SH",
            "name": "测试公司",
            "price": "10.0",
            "pe_ttm": "15.0",
            "sentiment_score": "50",
            "sentiment_label": "中性",
            "implied_growth": "10.0",
            "our_growth": "15.0",
            "gap": "5.0",
            "signal": "WAIT",
            "key_narrative": "测试叙事",
            "key_worry": "测试担忧",
            "key_hope": "测试期望",
            "thesis_aligned": "1",
            "confidence": "中",
            "reasoning": "测试推理",
            "status": "ok",
        }

        writer = CSVReportWriter(temp_csv_path)
        result = writer._row_to_result(row)

        assert result.date == datetime(2024, 1, 15)
        assert result.ticker == "TEST.SH"
        assert result.name == "测试公司"
        assert result.price == 10.0
        assert result.pe_ttm == 15.0
        assert result.sentiment_score == 50
        assert result.signal == AuditSignal.WAIT
        # 新增字段在回读时保留
        assert result.thesis_aligned is True
        assert result.confidence == "中"
        assert result.reasoning == "测试推理"

    def test_row_to_result_empty_pe(self, temp_csv_path: Path):
        """测试空 PE 的行转换"""
        row = {
            "date": "2024-01-15",
            "ticker": "TEST.SH",
            "name": "测试公司",
            "price": "10.0",
            "pe_ttm": "",  # 空 PE
            "sentiment_score": "50",
            "sentiment_label": "中性",
            "implied_growth": "10.0",
            "our_growth": "15.0",
            "gap": "5.0",
            "signal": "WAIT",
            "key_narrative": "测试叙事",
            "key_worry": "测试担忧",
            "key_hope": "测试期望",
        }

        writer = CSVReportWriter(temp_csv_path)
        result = writer._row_to_result(row)

        assert result.pe_ttm is None


class TestCSVReadAllResults:
    """读取全部结果测试类"""

    def test_read_all_results_empty_file(self, temp_csv_path: Path):
        """测试文件为空时返回空列表"""
        writer = CSVReportWriter(temp_csv_path)
        # 不创建文件

        results = writer._read_all_results()

        assert results == []

    def test_read_all_results_header_only(self, temp_csv_path: Path):
        """测试只有表头时返回空列表"""
        writer = CSVReportWriter(temp_csv_path)
        writer._ensure_file_exists()

        results = writer._read_all_results()

        assert results == []

    def test_read_all_results_with_data(
        self,
        temp_csv_path: Path,
        sample_audit_result: AuditResult,
        sample_audit_result_overheated: AuditResult,
    ):
        """测试读取所有数据"""
        writer = CSVReportWriter(temp_csv_path)
        writer.save_batch([sample_audit_result, sample_audit_result_overheated])

        results = writer._read_all_results()

        assert len(results) == 2
        assert results[0].ticker == "600150.SH"
        assert results[1].ticker == "NVDA"

    def test_read_all_results_skips_incomplete_rows(self, temp_csv_path: Path):
        """测试跳过缺少 date 的行（DictReader 模式下，缺列会填 None / 空字符串）"""
        # 写入表头和一个 date 为空的行
        with open(temp_csv_path, "w", newline="", encoding="utf-8") as f:
            csvwriter = csv.writer(f)
            csvwriter.writerow(CSVReportWriter.CSV_COLUMNS)
            csvwriter.writerow([""] * len(CSVReportWriter.CSV_COLUMNS))

        writer = CSVReportWriter(temp_csv_path)
        results = writer._read_all_results()

        assert results == []  # 缺少 date 的行被跳过

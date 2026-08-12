from __future__ import annotations

import base64
import binascii
import json
import csv
import io
import posixpath
import re
import uuid
import zipfile
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen
from xml.etree import ElementTree

from data_engine import DataWorkspaceStore


HOST = "127.0.0.6"
PORT = 8006
STATIC_DIR = Path(__file__).parent / "static"
RECORDS_FILE = Path(__file__).parent / "data" / "analysis_records.json"
ACTIVITY_FILE = Path(__file__).parent / "data" / "collaboration_record_actions.json"
WORKSPACES_DIR = Path(__file__).parent / "data" / "workspaces"
PROJECT_ID = "ai-data-workbench"
PROJECT_NAME = "AI 数据工作台"
PROJECT_PATH = str(Path(__file__).resolve().parent)
APS_EXECUTIONS_URL = "http://127.0.0.5:8005/api/executions"
HANDLING_STATUSES = {"pending", "processing", "done"}
DATA_ACTIONS = {"upload_data", "connect_source", "use_existing_data"}
PROJECT_ROOT = Path(__file__).parent.resolve()
SUPPORTED_DATA_SUFFIXES = {".csv", ".tsv", ".json", ".xlsx"}
MAX_DATA_BYTES = 5 * 1024 * 1024
MAX_XLSX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_XLSX_ROWS = 100_000
MAX_XLSX_COLUMNS = 1_000

SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOCUMENT_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

DRAFT_FIELDS = (
    "targetRestatement",
    "metrics",
    "dimensions",
    "scope",
    "requiredData",
    "clarifyingQuestions",
)


def _matches(goal: str, words: tuple[str, ...]) -> bool:
    return any(word in goal for word in words)


def build_draft(goal: str) -> dict[str, Any]:
    """Use deterministic rules to create an editable Phase 1 draft."""
    normalized = re.sub(r"\s+", " ", goal).strip()
    if not normalized:
        raise ValueError("请输入自然语言分析目标")

    metrics: list[str] = []
    required_data: list[dict[str, str]] = []
    dimensions: list[str] = []

    metric_rules = (
        (("利润", "毛利"), ("收入", "成本", "利润"), "交易或业务明细", "用于确认收入、成本和利润口径"),
        (("销售", "销量", "营收"), ("销售额", "销量"), "销售明细", "用于计算销售规模和变化"),
        (("采购", "供应商"), ("采购金额", "采购数量"), "采购明细", "用于计算采购规模和成本"),
        (("支付", "回款", "账期"), ("支付金额", "支付时长"), "支付明细", "用于分析支付进度和周期"),
        (("订单",), ("订单数",), "订单明细", "用于统计订单规模和状态"),
    )
    for words, suggested_metrics, data_name, reason in metric_rules:
        if _matches(normalized, words):
            metrics.extend(item for item in suggested_metrics if item not in metrics)
            if not any(item["name"] == data_name for item in required_data):
                required_data.append({"name": data_name, "reason": reason})

    dimension_rules = (
        (("渠道",), "渠道"),
        (("客户",), "客户"),
        (("地区", "区域"), "地区"),
        (("产品", "商品"), "产品"),
        (("供应商",), "供应商"),
        (("月份", "季度", "年度", "同比", "环比", "趋势"), "时间"),
    )
    for words, dimension in dimension_rules:
        if _matches(normalized, words):
            dimensions.append(dimension)

    if not metrics:
        metrics.append("待确认的核心指标")
    if not required_data:
        required_data.append({"name": "与分析目标相关的业务明细", "reason": "用于确认指标来源和计算范围"})
    if not dimensions:
        dimensions.append("整体")

    time_scope_match = re.search(
        r"(今年第[一二三四1234]季度|今年[一二三四1234]季度|本季度|上季度|"
        r"去年同期|今年|去年|\d{4}\s*年(?:第?[一二三四1234]季度)?|"
        r"近\d+\s*(?:天|个月|季度|年)|过去\d+\s*(?:天|个月|季度|年))",
        normalized,
    )
    has_time_scope = bool(time_scope_match)
    has_change_intent = bool(re.search(r"下降|增长|变化|波动|异常|趋势", normalized))
    has_comparison_baseline = bool(re.search(r"同比|环比|去年同期|上一季度|上季度|上期|同期", normalized))
    questions: list[str] = []
    if not has_time_scope:
        questions.append("本次分析的时间范围是什么？")
    if has_change_intent and not has_comparison_baseline:
        questions.append("变化应与哪个基准周期比较，例如上一季度还是去年同期？")
    if metrics == ["待确认的核心指标"]:
        questions.append("最需要衡量的核心指标及其口径是什么？")

    return {
        "targetRestatement": normalized,
        "metrics": metrics,
        "dimensions": dimensions,
        "scope": time_scope_match.group(0) if time_scope_match else "具体时间与业务范围待确认。",
        "requiredData": required_data,
        "clarifyingQuestions": questions,
    }


def validate_draft(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("草案格式无效")

    target = str(payload.get("targetRestatement", "")).strip()
    scope = str(payload.get("scope", "")).strip()
    metrics = payload.get("metrics")
    dimensions = payload.get("dimensions")
    required_data = payload.get("requiredData")
    questions = payload.get("clarifyingQuestions")

    if not target or not scope:
        raise ValueError("目标重述和范围不能为空")
    if not isinstance(metrics, list) or not metrics or not all(str(item).strip() for item in metrics):
        raise ValueError("至少需要一个有效指标")
    if not isinstance(dimensions, list) or not dimensions or not all(str(item).strip() for item in dimensions):
        raise ValueError("至少需要一个有效维度")
    if not isinstance(questions, list) or not all(str(item).strip() for item in questions):
        raise ValueError("澄清问题格式无效")
    if not isinstance(required_data, list) or not required_data:
        raise ValueError("至少需要一项所需数据")
    for item in required_data:
        if not isinstance(item, dict) or not str(item.get("name", "")).strip() or not str(item.get("reason", "")).strip():
            raise ValueError("每项所需数据都必须包含名称和原因")

    return {
        "targetRestatement": target,
        "metrics": [str(item).strip() for item in metrics],
        "dimensions": [str(item).strip() for item in dimensions],
        "scope": scope,
        "requiredData": [
            {"name": str(item["name"]).strip(), "reason": str(item["reason"]).strip()}
            for item in required_data
        ],
        "clarifyingQuestions": [str(item).strip() for item in questions],
    }


def _xlsx_column_index(reference: str) -> int:
    match = re.match(r"([A-Z]+)", reference.upper())
    if not match:
        raise ValueError("Excel 单元格位置无效")
    index = 0
    for character in match.group(1):
        index = index * 26 + ord(character) - ord("A") + 1
    return index - 1


def _xlsx_text(element: ElementTree.Element) -> str:
    return "".join(node.text or "" for node in element.iter(f"{{{SPREADSHEET_NS}}}t"))


def _xlsx_cell_value(
    cell: ElementTree.Element,
    shared_strings: list[str],
) -> Any:
    cell_type = cell.get("t", "")
    if cell_type == "inlineStr":
        inline = cell.find(f"{{{SPREADSHEET_NS}}}is")
        return _xlsx_text(inline) if inline is not None else ""

    value_node = cell.find(f"{{{SPREADSHEET_NS}}}v")
    if value_node is None or value_node.text is None:
        return ""
    value = value_node.text
    if cell_type == "s":
        try:
            return shared_strings[int(value)]
        except (IndexError, ValueError) as error:
            raise ValueError("Excel 共享字符串索引无效") from error
    if cell_type == "b":
        return value == "1"
    if cell_type in {"str", "e", "d"}:
        return value
    try:
        number = float(value)
    except ValueError:
        return value
    return int(number) if number.is_integer() else number


def _parse_xlsx(binary: bytes) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    try:
        with zipfile.ZipFile(io.BytesIO(binary)) as workbook:
            if sum(item.file_size for item in workbook.infolist()) > MAX_XLSX_UNCOMPRESSED_BYTES:
                raise ValueError("Excel 解压后数据量超过 50 MB")

            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in workbook.namelist():
                shared_root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
                shared_strings = [
                    _xlsx_text(item)
                    for item in shared_root.findall(f"{{{SPREADSHEET_NS}}}si")
                ]

            workbook_root = ElementTree.fromstring(workbook.read("xl/workbook.xml"))
            relationships_root = ElementTree.fromstring(
                workbook.read("xl/_rels/workbook.xml.rels")
            )
            relationship_targets = {
                item.get("Id"): item.get("Target")
                for item in relationships_root.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
            }
            sheets = workbook_root.find(f"{{{SPREADSHEET_NS}}}sheets")
            if sheets is None:
                raise ValueError("Excel 文件没有工作表")

            sheet_entries: list[tuple[str, str]] = []
            for sheet in sheets.findall(f"{{{SPREADSHEET_NS}}}sheet"):
                relationship_id = sheet.get(f"{{{DOCUMENT_REL_NS}}}id")
                target = relationship_targets.get(relationship_id)
                if not target:
                    continue
                normalized_target = target.lstrip("/")
                if not normalized_target.startswith("xl/"):
                    normalized_target = posixpath.normpath(posixpath.join("xl", normalized_target))
                sheet_entries.append((sheet.get("name", "未命名工作表"), normalized_target))
            if not sheet_entries:
                raise ValueError("Excel 文件没有可读取的工作表")

            for sheet_name, sheet_path in sheet_entries:
                sheet_root = ElementTree.fromstring(workbook.read(sheet_path))
                parsed_rows: list[list[Any]] = []
                for row in sheet_root.findall(f".//{{{SPREADSHEET_NS}}}row"):
                    values: list[Any] = []
                    for cell in row.findall(f"{{{SPREADSHEET_NS}}}c"):
                        index = _xlsx_column_index(cell.get("r", ""))
                        if index >= MAX_XLSX_COLUMNS:
                            raise ValueError("Excel 列数不能超过 1000")
                        while len(values) <= index:
                            values.append("")
                        values[index] = _xlsx_cell_value(cell, shared_strings)
                    if any(value not in (None, "") for value in values):
                        parsed_rows.append(values)
                    if len(parsed_rows) > MAX_XLSX_ROWS + 1:
                        raise ValueError("Excel 数据行不能超过 100000")
                if not parsed_rows:
                    continue

                columns = [str(value).strip() for value in parsed_rows[0]]
                while columns and not columns[-1]:
                    columns.pop()
                if not columns or not all(columns):
                    raise ValueError(f"工作表“{sheet_name}”包含空表头")
                if len(set(columns)) != len(columns):
                    raise ValueError(f"工作表“{sheet_name}”包含重复表头")
                rows = [
                    {
                        column: row[index] if index < len(row) else ""
                        for index, column in enumerate(columns)
                    }
                    for row in parsed_rows[1:]
                    if any(
                        index < len(row) and row[index] not in (None, "")
                        for index in range(len(columns))
                    )
                ]
                if not rows:
                    raise ValueError(f"工作表“{sheet_name}”没有可解析的数据行")
                return rows, columns, {
                    "sheetNames": [name for name, _ in sheet_entries],
                    "selectedSheet": sheet_name,
                }
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as error:
        raise ValueError("Excel 文件损坏或不是有效的 .xlsx 文件") from error
    raise ValueError("Excel 文件没有可解析的数据工作表")


def parse_data(
    filename: str,
    content: str | bytes,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_DATA_SUFFIXES:
        raise ValueError("仅支持 CSV、TSV、JSON 和 XLSX 文件")
    binary = content if isinstance(content, bytes) else content.encode("utf-8")
    if len(binary) > MAX_DATA_BYTES:
        raise ValueError("数据文件不能超过 5 MB")
    if suffix == ".xlsx":
        return _parse_xlsx(binary)
    if not isinstance(content, str):
        try:
            content = content.decode("utf-8-sig")
        except UnicodeError as error:
            raise ValueError("文本数据文件必须使用 UTF-8 编码") from error

    if suffix == ".json":
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as error:
            raise ValueError("JSON 文件格式无效") from error
        if isinstance(payload, dict):
            payload = payload.get("records")
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise ValueError("JSON 数据必须是对象数组，或包含 records 对象数组")
        rows = payload
        columns = list(dict.fromkeys(str(key) for row in rows for key in row))
    else:
        delimiter = "\t" if suffix == ".tsv" else ","
        reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
        if not reader.fieldnames:
            raise ValueError("数据文件缺少表头")
        columns = [str(field).strip() for field in reader.fieldnames]
        if not all(columns):
            raise ValueError("数据文件包含空表头")
        rows = [{str(key).strip(): value for key, value in row.items()} for row in reader]
    if not rows:
        raise ValueError("数据文件没有可解析的数据行")
    return rows, columns, {"sheetNames": [], "selectedSheet": None}


def _number(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def _field_meaning(column: str) -> str:
    rules = (
        (("编号", "编码", "单号", "票号", "订单号", "流水号", "ID", "id", "SKU", "PNR"), "标识字段"),
        (("日期", "时间", "月份", "季度", "年度"), "时间字段"),
        (("率", "比例", "折扣", "扣率", "占比"), "比例指标"),
        (("金额", "销售额", "收入", "成本", "利润", "价格"), "金额或经营指标"),
        (("数量", "销量", "订单数"), "数量指标"),
        (("客户",), "客户维度"),
        (("渠道",), "渠道维度"),
        (("地区", "区域"), "地区维度"),
        (("产品", "商品"), "产品维度"),
        (("供应商",), "供应商维度"),
    )
    for words, meaning in rules:
        if any(word in column for word in words):
            return meaning
    return "通用业务字段"


def understand_data(rows: list[dict[str, Any]], columns: list[str], table_name: str) -> dict[str, Any]:
    fields = []
    for column in columns:
        values = [row.get(column) for row in rows if row.get(column) not in (None, "")]
        numeric_count = sum(_number(value) is not None for value in values)
        date_count = sum(
            bool(re.fullmatch(r"\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?", str(value).strip()))
            for value in values
        )
        meaning = _field_meaning(column)
        if meaning == "标识字段":
            field_type = "identifier"
        elif meaning == "时间字段":
            field_type = "date"
        elif values and numeric_count == len(values):
            field_type = "number"
        elif values and date_count == len(values):
            field_type = "date"
        elif numeric_count:
            field_type = "mixed"
        else:
            field_type = "text"
        fields.append({
            "name": column,
            "type": field_type,
            "meaning": meaning,
            "nonEmptyCount": len(values),
            "emptyCount": len(rows) - len(values),
            "uniqueCount": len({str(value).strip() for value in values}),
        })

    dimensions = [field["name"] for field in fields if "维度" in field["meaning"] or field["type"] in {"date", "text"}]
    measures = [field["name"] for field in fields if field["type"] == "number" and field["meaning"] not in {"标识字段", "时间字段"}]
    relationships = [
        {"from": dimension, "to": measure, "relation": "可按维度汇总指标"}
        for dimension in dimensions[:4]
        for measure in measures[:4]
    ]
    return {
        "tables": [{
            "name": table_name,
            "rowCount": len(rows),
            "columnCount": len(columns),
            "fields": fields,
        }],
        "relationships": relationships,
    }


def clean_and_detect(rows: list[dict[str, Any]], columns: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cleaned_rows = []
    seen = set()
    duplicate_count = 0
    trimmed_count = 0
    normalized_empty_count = 0
    empty_markers = {"", "-", "--", "null", "none", "n/a", "na"}
    for row in rows:
        cleaned = {}
        for column in columns:
            original = row.get(column)
            value = original.strip() if isinstance(original, str) else original
            if isinstance(original, str) and value != original:
                trimmed_count += 1
            if value is None or str(value).strip().lower() in empty_markers:
                if value not in (None, ""):
                    normalized_empty_count += 1
                value = None
            cleaned[column] = value
        signature = tuple(str(cleaned.get(column)) for column in columns)
        if signature in seen:
            duplicate_count += 1
            continue
        seen.add(signature)
        cleaned_rows.append(cleaned)

    missing = [
        {"field": column, "count": sum(row.get(column) is None for row in cleaned_rows)}
        for column in columns
    ]
    missing = [item for item in missing if item["count"]]
    mixed_types = []
    outliers = []
    for column in columns:
        values = [row.get(column) for row in cleaned_rows if row.get(column) is not None]
        numbers = [_number(value) for value in values]
        numeric_values = [value for value in numbers if value is not None]
        if numeric_values and len(numeric_values) != len(values):
            mixed_types.append({"field": column, "numericCount": len(numeric_values), "otherCount": len(values) - len(numeric_values)})
        if len(numeric_values) >= 4:
            ordered = sorted(numeric_values)
            lower = ordered[len(ordered) // 4]
            upper = ordered[(len(ordered) * 3) // 4]
            spread = upper - lower
            low_limit, high_limit = lower - 1.5 * spread, upper + 1.5 * spread
            count = sum(value < low_limit or value > high_limit for value in numeric_values)
            if count:
                outliers.append({"field": column, "count": count, "rule": "IQR 1.5 倍"})

    return cleaned_rows, {
        "sourceRowCount": len(rows),
        "cleanedRowCount": len(cleaned_rows),
        "actions": {
            "trimmedValues": trimmed_count,
            "normalizedEmptyValues": normalized_empty_count,
            "removedDuplicateRows": duplicate_count,
        },
        "anomalies": {
            "missingValues": missing,
            "mixedTypes": mixed_types,
            "numericOutliers": outliers,
        },
    }


def _match_field(item: str, columns: list[str]) -> str | None:
    normalized = re.sub(r"\s+", "", item).lower()
    for column in columns:
        candidate = re.sub(r"\s+", "", column).lower()
        if normalized == candidate or normalized in candidate or candidate in normalized:
            return column
    return None


def prepare_for_analysis(draft: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    metrics = [{"item": item, "field": _match_field(item, columns)} for item in draft["metrics"]]
    dimensions = [{"item": item, "field": _match_field(item, columns)} for item in draft["dimensions"]]
    requirements = [
        {"name": item["name"], "reason": item["reason"], "available": bool(columns)}
        for item in draft["requiredData"]
    ]
    missing = [item["item"] for item in metrics + dimensions if not item["field"] and item["item"] != "整体"]
    computations = [
        {"metric": item["item"], "field": item["field"], "operation": "汇总、均值、最小值、最大值", "ready": bool(item["field"])}
        for item in metrics
    ]
    return {
        "goal": draft["targetRestatement"],
        "metricMappings": metrics,
        "dimensionMappings": dimensions,
        "requiredDataAssessment": requirements,
        "computationItems": computations,
        "missingItems": missing,
        "ready": not missing,
    }


def build_adjustment_focus(
    draft: dict[str, Any],
    numeric_summaries: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    review = draft.get("customerReview") or {}
    feedback = str(review.get("feedback", "")).strip()
    if review.get("action") != "adjust" or not feedback:
        return None, numeric_summaries

    price_summary = next(
        (
            item
            for item in numeric_summaries
            if any(word in item["field"] for word in ("票价", "售价", "销售价", "价格"))
        ),
        None,
    )
    if not price_summary:
        return {
            "feedback": feedback,
            "sourceField": None,
            "items": [],
            "missingItems": ["没有找到可用于票价和利润计算的价格字段"],
        }, numeric_summaries

    items = []
    missing_items = []
    if "利润" in feedback:
        cost_text = " ".join([
            draft.get("targetRestatement", ""),
            *[str(item) for item in draft.get("metrics", [])],
        ])
        cost_match = re.search(r"成本\s*[:：为是]?\s*(\d+(?:\.\d+)?)", cost_text)
        if cost_match:
            unit_cost = float(cost_match.group(1))
            profit = price_summary["sum"] - unit_cost * price_summary["count"]
            items.append({
                "label": "利润",
                "value": round(profit, 4),
                "basis": (
                    f"{price_summary['field']}合计 - 单票成本 {unit_cost:g}"
                    f" × {price_summary['count']}"
                ),
            })
        else:
            missing_items.append("利润：缺少可识别的单票成本")
    if "平均" in feedback:
        items.append({
            "label": "平均票价",
            "value": price_summary["average"],
            "basis": price_summary["field"],
        })
    if "最高" in feedback:
        items.append({
            "label": "最高价",
            "value": price_summary["max"],
            "basis": price_summary["field"],
        })
    if "最低" in feedback:
        items.append({
            "label": "最低价",
            "value": price_summary["min"],
            "basis": price_summary["field"],
        })
    return {
        "feedback": feedback,
        "sourceField": price_summary["field"],
        "items": items,
        "missingItems": missing_items,
    }, [price_summary]


def build_analysis_result(
    draft: dict[str, Any],
    rows: list[dict[str, Any]],
    columns: list[str],
    table_name: str,
) -> dict[str, Any]:
    understanding = understand_data(rows, columns, table_name)
    cleaned_rows, processing = clean_and_detect(rows, columns)
    preparation = prepare_for_analysis(draft, columns)
    numeric_summaries = []
    for column in columns:
        if _field_meaning(column) in {"标识字段", "时间字段"}:
            continue
        values = [_number(row.get(column)) for row in cleaned_rows]
        values = [value for value in values if value is not None]
        if values:
            numeric_summaries.append({
                "field": column,
                "count": len(values),
                "sum": round(sum(values), 4),
                "average": round(sum(values) / len(values), 4),
                "min": min(values),
                "max": max(values),
            })
    adjustment_focus, numeric_summaries = build_adjustment_focus(draft, numeric_summaries)

    dimension_summaries = []
    for dimension in draft["dimensions"]:
        if dimension not in columns:
            continue
        counts: dict[str, int] = {}
        for row in cleaned_rows:
            value = str(row.get(dimension, "")).strip() or "（空）"
            counts[value] = counts.get(value, 0) + 1
        dimension_summaries.append({
            "field": dimension,
            "values": [
                {"value": value, "count": count}
                for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10]
            ],
        })

    return {
        "goal": draft["targetRestatement"],
        "confirmedMetrics": draft["metrics"],
        "confirmedDimensions": draft["dimensions"],
        "rowCount": len(cleaned_rows),
        "sourceRowCount": len(rows),
        "columns": columns,
        "dataUnderstanding": understanding,
        "dataProcessing": processing,
        "analysisPreparation": preparation,
        "adjustmentFocus": adjustment_focus,
        "numericSummaries": numeric_summaries,
        "dimensionSummaries": dimension_summaries,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }


class DraftStore:
    def __init__(self, records_file: Path | None = None) -> None:
        self._records_file = records_file
        self._drafts: dict[str, dict[str, dict[str, Any]]] = {}
        self._lock = Lock()
        if records_file and records_file.exists():
            stored = json.loads(records_file.read_text(encoding="utf-8"))
            self._drafts = stored.get("projects", {})

    @staticmethod
    def _project_id(project_id: str) -> str:
        normalized = project_id.strip()
        if not re.fullmatch(r"[a-z0-9-]{1,64}", normalized):
            raise ValueError("项目标识无效")
        return normalized

    def _save_locked(self) -> None:
        if not self._records_file:
            return
        self._records_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_file = self._records_file.with_suffix(".tmp")
        temporary_file.write_text(
            json.dumps({"projects": self._drafts}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_file.replace(self._records_file)

    def create(self, goal: str, project_id: str = PROJECT_ID) -> dict[str, Any]:
        project_id = self._project_id(project_id)
        draft_id = uuid.uuid4().hex
        draft = {
            "id": draft_id,
            "projectId": project_id,
            "originalGoal": goal.strip(),
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "status": "draft",
            "nextAllowed": False,
            "timeline": [{"stage": "requirement_created", "at": datetime.now(timezone.utc).isoformat()}],
            **build_draft(goal),
        }
        with self._lock:
            self._drafts.setdefault(project_id, {})[draft_id] = draft
            self._save_locked()
        return dict(draft)

    def list(self, project_id: str = PROJECT_ID) -> list[dict[str, Any]]:
        project_id = self._project_id(project_id)
        with self._lock:
            records = self._drafts.get(project_id, {}).values()
            return [dict(record) for record in sorted(records, key=lambda item: item["createdAt"], reverse=True)]

    def get(self, draft_id: str, project_id: str = PROJECT_ID) -> dict[str, Any] | None:
        project_id = self._project_id(project_id)
        with self._lock:
            draft = self._drafts.get(project_id, {}).get(draft_id)
            return dict(draft) if draft else None

    def update(self, draft_id: str, payload: Any, project_id: str = PROJECT_ID) -> tuple[HTTPStatus, dict[str, Any]]:
        project_id = self._project_id(project_id)
        with self._lock:
            draft = self._drafts.get(project_id, {}).get(draft_id)
            if not draft:
                return HTTPStatus.NOT_FOUND, {"error": "草案不存在"}
            if draft["status"] != "draft":
                return HTTPStatus.CONFLICT, {"error": "已确认草案不可再编辑"}
            try:
                changes = validate_draft(payload)
            except ValueError as error:
                return HTTPStatus.BAD_REQUEST, {"error": str(error)}
            draft.update(changes)
            self._save_locked()
            return HTTPStatus.OK, dict(draft)

    def confirm(self, draft_id: str, project_id: str = PROJECT_ID) -> tuple[HTTPStatus, dict[str, Any]]:
        project_id = self._project_id(project_id)
        with self._lock:
            draft = self._drafts.get(project_id, {}).get(draft_id)
            if not draft:
                return HTTPStatus.NOT_FOUND, {"error": "草案不存在"}
            if draft["status"] != "draft":
                return HTTPStatus.CONFLICT, {"error": "当前状态不可重复确认"}
            draft["status"] = "confirmed"
            draft["nextAllowed"] = True
            draft["confirmedAt"] = datetime.now(timezone.utc).isoformat()
            draft.setdefault("timeline", []).append({"stage": "requirement_confirmed", "at": draft["confirmedAt"]})
            self._save_locked()
            return HTTPStatus.OK, dict(draft)

    def delete(self, draft_id: str, project_id: str = PROJECT_ID) -> tuple[HTTPStatus, dict[str, Any]]:
        project_id = self._project_id(project_id)
        with self._lock:
            project_records = self._drafts.get(project_id, {})
            if draft_id not in project_records:
                return HTTPStatus.NOT_FOUND, {"error": "记录不存在"}
            del project_records[draft_id]
            self._save_locked()
            return HTTPStatus.OK, {"deleted": draft_id}

    def advance(self, draft_id: str, project_id: str = PROJECT_ID) -> tuple[HTTPStatus, dict[str, Any]]:
        project_id = self._project_id(project_id)
        with self._lock:
            draft = self._drafts.get(project_id, {}).get(draft_id)
            if not draft:
                return HTTPStatus.NOT_FOUND, {"error": "草案不存在"}
            if draft["status"] != "confirmed":
                return HTTPStatus.CONFLICT, {"error": "草案尚未确认，后续流程已阻断"}
            draft["status"] = "data_preparation"
            draft["dataPreparationStatus"] = "selecting_source"
            draft["nextAction"] = None
            draft.setdefault("timeline", []).append({
                "stage": "data_preparation_started",
                "at": datetime.now(timezone.utc).isoformat(),
            })
            self._save_locked()
            return HTTPStatus.OK, dict(draft)

    def import_data(
        self,
        draft_id: str,
        payload: Any,
        project_id: str = PROJECT_ID,
    ) -> tuple[HTTPStatus, dict[str, Any]]:
        project_id = self._project_id(project_id)
        if not isinstance(payload, dict):
            return HTTPStatus.BAD_REQUEST, {"error": "数据导入请求无效"}
        with self._lock:
            draft = self._drafts.get(project_id, {}).get(draft_id)
            if not draft:
                return HTTPStatus.NOT_FOUND, {"error": "草案不存在"}
            if draft["status"] not in {"data_preparation", "adjustment_requested"}:
                return HTTPStatus.CONFLICT, {"error": "任务尚未进入可导入数据阶段"}
        method = str(payload.get("method", ""))
        try:
            if method == "path":
                raw_path = str(payload.get("path", "")).strip()
                if not raw_path:
                    raise ValueError("请输入数据文件路径")
                source_path = Path(raw_path)
                if not source_path.is_absolute():
                    source_path = PROJECT_ROOT / source_path
                source_path = source_path.resolve()
                if not source_path.is_relative_to(PROJECT_ROOT):
                    raise ValueError("数据路径必须位于当前项目目录内")
                if not source_path.is_file():
                    raise ValueError("数据文件不存在")
                if source_path.stat().st_size > MAX_DATA_BYTES:
                    raise ValueError("数据文件不能超过 5 MB")
                filename = source_path.name
                content = (
                    source_path.read_bytes()
                    if source_path.suffix.lower() == ".xlsx"
                    else source_path.read_text(encoding="utf-8-sig")
                )
                source_label = str(source_path.relative_to(PROJECT_ROOT))
            elif method in {"file", "connector"}:
                filename = Path(str(payload.get("filename", ""))).name
                content = payload.get("content")
                if not filename or not isinstance(content, str):
                    raise ValueError("请提供有效的数据文件")
                if Path(filename).suffix.lower() == ".xlsx":
                    if payload.get("contentEncoding") != "base64":
                        raise ValueError("Excel 文件必须使用 Base64 二进制编码上传")
                    try:
                        content = base64.b64decode(content, validate=True)
                    except (binascii.Error, ValueError) as error:
                        raise ValueError("Excel 文件编码无效") from error
                if method == "connector":
                    system_name = str(payload.get("systemName", "")).strip()
                    if not system_name:
                        raise ValueError("请输入业务系统名称")
                    source_label = f"{system_name}（安全导出快照）/{filename}"
                else:
                    source_label = filename
            else:
                raise ValueError("请选择上传数据、连接业务系统或使用已有数据")
            rows, columns, workbook_metadata = parse_data(filename, content)
        except (OSError, UnicodeError, ValueError) as error:
            return HTTPStatus.BAD_REQUEST, {"error": str(error)}

        with self._lock:
            draft = self._drafts.get(project_id, {}).get(draft_id)
            if not draft:
                return HTTPStatus.NOT_FOUND, {"error": "草案不存在"}
            if draft["status"] not in {"data_preparation", "adjustment_requested"}:
                return HTTPStatus.CONFLICT, {"error": "任务尚未进入可导入数据阶段"}
            imported_at = datetime.now(timezone.utc).isoformat()
            draft["dataImport"] = {
                "method": method,
                "source": source_label,
                "filename": filename,
                "rowCount": len(rows),
                "columns": columns,
                **workbook_metadata,
                "importedAt": imported_at,
            }
            draft["status"] = "result_ready"
            draft["dataPreparationStatus"] = "analysis_ready"
            table_name = workbook_metadata.get("selectedSheet") or Path(filename).stem
            draft["analysisResult"] = build_analysis_result(draft, rows, columns, table_name)
            draft.setdefault("timeline", []).extend([
                {"stage": "data_imported", "at": imported_at, "source": source_label},
                {"stage": "data_understood", "at": draft["analysisResult"]["generatedAt"]},
                {"stage": "data_processed", "at": draft["analysisResult"]["generatedAt"]},
                {"stage": "analysis_prepared", "at": draft["analysisResult"]["generatedAt"]},
            ])
            self._save_locked()
            return HTTPStatus.OK, dict(draft)

    def review_result(
        self,
        draft_id: str,
        action: str,
        feedback: str,
        project_id: str = PROJECT_ID,
    ) -> tuple[HTTPStatus, dict[str, Any]]:
        project_id = self._project_id(project_id)
        if action not in {"accept", "adjust"}:
            return HTTPStatus.BAD_REQUEST, {"error": "验收操作无效"}
        feedback = feedback.strip()
        if action == "adjust" and not feedback:
            return HTTPStatus.BAD_REQUEST, {"error": "提出调整时请填写调整意见"}
        with self._lock:
            draft = self._drafts.get(project_id, {}).get(draft_id)
            if not draft:
                return HTTPStatus.NOT_FOUND, {"error": "草案不存在"}
            if draft["status"] != "result_ready":
                return HTTPStatus.CONFLICT, {"error": "当前没有待验收的分析结果"}
            reviewed_at = datetime.now(timezone.utc).isoformat()
            draft["status"] = "accepted" if action == "accept" else "adjustment_requested"
            draft["customerReview"] = {"action": action, "feedback": feedback, "reviewedAt": reviewed_at}
            draft.setdefault("timeline", []).append({
                "stage": "customer_accepted" if action == "accept" else "adjustment_requested",
                "at": reviewed_at,
                "feedback": feedback,
            })
            self._save_locked()
            return HTTPStatus.OK, dict(draft)

    def choose_data_action(
        self,
        draft_id: str,
        action: str,
        project_id: str = PROJECT_ID,
    ) -> tuple[HTTPStatus, dict[str, Any]]:
        project_id = self._project_id(project_id)
        if action not in DATA_ACTIONS:
            return HTTPStatus.BAD_REQUEST, {"error": "数据准备选择无效"}
        with self._lock:
            draft = self._drafts.get(project_id, {}).get(draft_id)
            if not draft:
                return HTTPStatus.NOT_FOUND, {"error": "草案不存在"}
            if draft["status"] != "data_preparation":
                return HTTPStatus.CONFLICT, {"error": "任务尚未进入数据准备阶段"}
            draft["nextAction"] = action
            draft["nextActionUpdatedAt"] = datetime.now(timezone.utc).isoformat()
            self._save_locked()
            return HTTPStatus.OK, dict(draft)


DRAFT_STORE = DraftStore(RECORDS_FILE)
WORKSPACE_STORE = DataWorkspaceStore(WORKSPACES_DIR)


class ActivityStore:
    def __init__(self, records_file: Path | None = None) -> None:
        self._records_file = records_file
        self._records: dict[str, dict[str, Any]] = {}
        self._lock = Lock()
        if records_file and records_file.exists():
            stored = json.loads(records_file.read_text(encoding="utf-8"))
            self._records = stored.get("records", {})

    def _save_locked(self) -> None:
        if not self._records_file:
            return
        self._records_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_file = self._records_file.with_suffix(".tmp")
        temporary_file.write_text(
            json.dumps({"records": self._records}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_file.replace(self._records_file)

    def state_for(self, execution_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._records.get(execution_id, {}))

    def update(self, execution_id: str, handling_status: str) -> tuple[HTTPStatus, dict[str, Any]]:
        if handling_status not in HANDLING_STATUSES:
            return HTTPStatus.BAD_REQUEST, {"error": "处理状态无效"}
        with self._lock:
            state = self._records.setdefault(execution_id, {})
            state.update({
                "handlingStatus": handling_status,
                "deleted": False,
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            })
            self._save_locked()
            return HTTPStatus.OK, {"id": execution_id, **state}

    def delete(self, execution_id: str) -> tuple[HTTPStatus, dict[str, Any]]:
        with self._lock:
            state = self._records.setdefault(execution_id, {})
            state.update({
                "deleted": True,
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            })
            self._save_locked()
            return HTTPStatus.OK, {"deleted": execution_id}


def load_aps_executions() -> list[dict[str, Any]]:
    try:
        with urlopen(APS_EXECUTIONS_URL, timeout=3) as response:
            payload = json.loads(response.read())
    except (OSError, URLError, json.JSONDecodeError) as error:
        raise RuntimeError("APS 执行记录暂时不可读取") from error
    executions = payload.get("executions", []) if isinstance(payload, dict) else []
    return executions if isinstance(executions, list) else []


def project_execution_records(
    executions: list[dict[str, Any]],
    activity_store: ActivityStore,
) -> list[dict[str, Any]]:
    records = []
    for execution in executions:
        if not isinstance(execution, dict):
            continue
        workspace = str(execution.get("workspacePath", ""))
        project = str(execution.get("project", ""))
        if workspace:
            if workspace != PROJECT_PATH:
                continue
        elif project != PROJECT_NAME:
            continue
        execution_id = str(execution.get("id", "")).strip()
        if not execution_id:
            continue
        local_state = activity_store.state_for(execution_id)
        if local_state.get("deleted"):
            continue
        records.append({
            "id": execution_id,
            "promptNumber": execution.get("promptNumber"),
            "title": str(execution.get("title", "未命名任务")),
            "executionStatus": str(execution.get("status", "unknown")),
            "handlingStatus": local_state.get("handlingStatus", "pending"),
            "createdAt": execution.get("createdAt"),
            "startedAt": execution.get("startedAt"),
            "completedAt": execution.get("completedAt"),
            "exitCode": execution.get("exitCode"),
            "error": execution.get("error"),
            "result": str(execution.get("result", ""))[:12000],
            "changedFiles": execution.get("changedFiles", []) if isinstance(execution.get("changedFiles"), list) else [],
            "statusHistory": execution.get("statusHistory", []) if isinstance(execution.get("statusHistory"), list) else [],
        })
    return sorted(records, key=lambda item: str(item.get("createdAt") or ""), reverse=True)


ACTIVITY_STORE = ActivityStore(ACTIVITY_FILE)


class WorkbenchHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Any:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 28 * 1024 * 1024:
            raise ValueError("请求内容不能超过 28 MB")
        return json.loads(self.rfile.read(length))

    def _send_file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _draft_route(self) -> tuple[str, str] | None:
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) >= 3 and parts[:2] == ["api", "drafts"]:
            return parts[2], parts[3] if len(parts) == 4 else ""
        return None

    def _project_id(self, payload: Any = None) -> str:
        query = parse_qs(urlparse(self.path).query)
        value = query.get("projectId", [None])[0]
        if value is None and isinstance(payload, dict):
            value = payload.get("projectId")
        return DraftStore._project_id(str(value or PROJECT_ID))

    def _record_id(self) -> str | None:
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) == 3 and parts[:2] == ["api", "records"]:
            return parts[2]
        return None

    def _activity_id(self) -> str | None:
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) == 3 and parts[:2] == ["api", "collaboration-records"]:
            return parts[2]
        return None

    def _workspace_route(self) -> tuple[str, str, str] | None:
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) >= 3 and parts[:2] == ["api", "workspaces"]:
            return parts[2], parts[3] if len(parts) >= 4 else "", parts[4] if len(parts) >= 5 else ""
        return None

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/health", "/api/health"}:
            self._send_json(HTTPStatus.OK, {
                "status": "ok",
                "product": "AI 数据工作台",
                "host": HOST,
                "port": PORT,
                "processingEngine": "pandas+openpyxl",
                "workspaceStore": "ok" if WORKSPACES_DIR.is_dir() else "missing",
            })
            return
        if path == "/api/workspaces":
            self._send_json(HTTPStatus.OK, {"workspaces": WORKSPACE_STORE.list()})
            return
        if path == "/api/records":
            try:
                records = DRAFT_STORE.list(self._project_id())
            except ValueError as error:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return
            self._send_json(HTTPStatus.OK, {"records": records})
            return
        if path == "/api/collaboration-records":
            try:
                records = project_execution_records(load_aps_executions(), ACTIVITY_STORE)
            except RuntimeError as error:
                self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(error)})
                return
            self._send_json(HTTPStatus.OK, {"records": records})
            return
        route = self._draft_route()
        if route and not route[1]:
            try:
                draft = DRAFT_STORE.get(route[0], self._project_id())
            except ValueError as error:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return
            self._send_json(HTTPStatus.OK, draft) if draft else self._send_json(HTTPStatus.NOT_FOUND, {"error": "草案不存在"})
            return
        workspace_route = self._workspace_route()
        if workspace_route:
            workspace_id, action, detail = workspace_route
            if action == "exports" and detail:
                try:
                    export_path = WORKSPACE_STORE.export_path(workspace_id, detail)
                except ValueError as error:
                    self._send_json(HTTPStatus.CONFLICT, {"error": str(error)})
                    return
                content_type = "text/csv; charset=utf-8" if detail == "csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                self._send_file(export_path, content_type)
                return
            if action:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
                return
            workspace = WORKSPACE_STORE.get(workspace_id)
            self._send_json(HTTPStatus.OK, workspace) if workspace else self._send_json(HTTPStatus.NOT_FOUND, {"error": "数据任务不存在"})
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
        except (ValueError, json.JSONDecodeError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "请求格式无效"})
            return

        if path == "/api/workspaces":
            if not isinstance(payload, dict):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "请求格式无效"})
                return
            workspace = WORKSPACE_STORE.create(str(payload.get("name", "")), str(payload.get("instructions", "")))
            self._send_json(HTTPStatus.CREATED, workspace)
            return

        workspace_route = self._workspace_route()
        if workspace_route:
            workspace_id, action, _detail = workspace_route
            try:
                if action == "datasets":
                    result = WORKSPACE_STORE.upload(workspace_id, str(payload.get("filename", "")), str(payload.get("content", "")))
                elif action == "suggest-plan":
                    result = WORKSPACE_STORE.suggest_plan(workspace_id, str(payload.get("instructions", "")))
                elif action == "preview":
                    result = WORKSPACE_STORE.preview(workspace_id)
                elif action == "execute":
                    result = WORKSPACE_STORE.execute(workspace_id, str(payload.get("previewId", "")), payload.get("outputModes"))
                elif action == "auto-run":
                    result = WORKSPACE_STORE.auto_run(
                        workspace_id,
                        str(payload.get("instructions", "")),
                        payload.get("outputModes"),
                        payload.get("decisions"),
                    )
                else:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
                    return
            except KeyError as error:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": str(error).strip("'")})
                return
            except ValueError as error:
                self._send_json(HTTPStatus.CONFLICT, {"error": str(error)})
                return
            self._send_json(HTTPStatus.OK, result)
            return

        if path == "/api/drafts":
            if not isinstance(payload, dict):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "请求格式无效"})
                return
            try:
                draft = DRAFT_STORE.create(str(payload.get("goal", "")), self._project_id(payload))
            except ValueError as error:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return
            self._send_json(HTTPStatus.CREATED, draft)
            return

        route = self._draft_route()
        if route and route[1] == "confirm":
            status, result = DRAFT_STORE.confirm(route[0], self._project_id(payload))
            self._send_json(status, result)
            return
        if route and route[1] == "advance":
            status, result = DRAFT_STORE.advance(route[0], self._project_id(payload))
            self._send_json(status, result)
            return
        if route and route[1] == "data-action":
            action = str(payload.get("action", "")) if isinstance(payload, dict) else ""
            status, result = DRAFT_STORE.choose_data_action(route[0], action, self._project_id(payload))
            self._send_json(status, result)
            return
        if route and route[1] == "import":
            status, result = DRAFT_STORE.import_data(route[0], payload, self._project_id(payload))
            self._send_json(status, result)
            return
        if route and route[1] == "review":
            action = str(payload.get("action", "")) if isinstance(payload, dict) else ""
            feedback = str(payload.get("feedback", "")) if isinstance(payload, dict) else ""
            status, result = DRAFT_STORE.review_result(
                route[0], action, feedback, self._project_id(payload)
            )
            self._send_json(status, result)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})

    def do_PUT(self) -> None:
        workspace_route = self._workspace_route()
        if workspace_route and workspace_route[1] == "plan":
            try:
                payload = self._read_json()
                result = WORKSPACE_STORE.save_plan(workspace_route[0], payload)
            except (ValueError, json.JSONDecodeError) as error:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return
            except KeyError as error:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": str(error).strip("'")})
                return
            self._send_json(HTTPStatus.OK, result)
            return
        activity_id = self._activity_id()
        if activity_id:
            try:
                payload = self._read_json()
            except (ValueError, json.JSONDecodeError):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "请求格式无效"})
                return
            status, result = ACTIVITY_STORE.update(activity_id, str(payload.get("handlingStatus", "")))
            self._send_json(status, result)
            return
        route = self._draft_route()
        if not route or route[1]:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
            return
        try:
            payload = self._read_json()
        except (ValueError, json.JSONDecodeError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "请求格式无效"})
            return
        try:
            status, result = DRAFT_STORE.update(route[0], payload, self._project_id(payload))
        except ValueError as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        self._send_json(status, result)

    def do_DELETE(self) -> None:
        workspace_route = self._workspace_route()
        if workspace_route and not workspace_route[1]:
            try:
                result = WORKSPACE_STORE.delete(workspace_route[0])
            except KeyError as error:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": str(error).strip("'")})
                return
            self._send_json(HTTPStatus.OK, result)
            return
        activity_id = self._activity_id()
        if activity_id:
            status, result = ACTIVITY_STORE.delete(activity_id)
            self._send_json(status, result)
            return
        record_id = self._record_id()
        if not record_id:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
            return
        try:
            status, result = DRAFT_STORE.delete(record_id, self._project_id())
        except ValueError as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        self._send_json(status, result)

    def log_message(self, format: str, *args: Any) -> None:
        return


def create_server() -> ThreadingHTTPServer:
    return ThreadingHTTPServer((HOST, PORT), WorkbenchHandler)


if __name__ == "__main__":
    print(f"AI 数据工作台运行于 http://{HOST}:{PORT}")
    create_server().serve_forever()

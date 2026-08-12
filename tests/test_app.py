import base64
import io
import json
import socket
import tempfile
import unittest
import zipfile
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch

import app


def make_xlsx_bytes() -> bytes:
    files = {
        "[Content_Types].xml": """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>""",
        "_rels/.rels": """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
        "xl/workbook.xml": """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="空表" sheetId="1" r:id="rId1"/>
    <sheet name="销售明细" sheetId="2" r:id="rId2"/>
  </sheets>
</workbook>""",
        "xl/_rels/workbook.xml.rels": """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
</Relationships>""",
        "xl/worksheets/sheet1.xml": """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData/>
</worksheet>""",
        "xl/worksheets/sheet2.xml": """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="inlineStr"><is><t>渠道</t></is></c>
      <c r="B1" t="inlineStr"><is><t>销售额</t></is></c>
    </row>
    <row r="2">
      <c r="A2" t="inlineStr"><is><t>官网</t></is></c>
      <c r="B2"><v>100</v></c>
    </row>
    <row r="3">
      <c r="A3" t="inlineStr"><is><t>门店</t></is></c>
      <c r="B3"><v>200</v></c>
    </row>
  </sheetData>
</worksheet>""",
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as workbook:
        for filename, content in files.items():
            workbook.writestr(filename, content)
    return output.getvalue()


class PhaseOneTest(unittest.TestCase):
    def setUp(self):
        self.store = app.DraftStore()

    def test_natural_language_goal_creates_complete_editable_draft(self):
        draft = self.store.create("分析本季度各渠道利润变化")

        self.assertEqual(draft["status"], "draft")
        self.assertFalse(draft["nextAllowed"])
        self.assertEqual(draft["targetRestatement"], "分析本季度各渠道利润变化")
        self.assertIn("利润", draft["metrics"])
        self.assertIn("渠道", draft["dimensions"])
        self.assertTrue(draft["scope"])
        self.assertTrue(all(item["name"] and item["reason"] for item in draft["requiredData"]))
        self.assertIsInstance(draft["clarifyingQuestions"], list)

    def test_decline_goal_asks_for_missing_comparison_baseline(self):
        draft = self.store.create(
            "我想分析今年第一季度销售额下降的原因，希望知道哪些产品、区域、渠道导致下降。"
        )

        self.assertEqual(draft["scope"], "今年第一季度")
        self.assertIn("销售额", draft["metrics"])
        self.assertEqual(draft["dimensions"], ["渠道", "地区", "产品", "时间"])
        self.assertEqual(
            draft["clarifyingQuestions"],
            ["变化应与哪个基准周期比较，例如上一季度还是去年同期？"],
        )

    def test_draft_can_be_edited_before_confirmation(self):
        draft = self.store.create("分析订单变化")
        edited = app.validate_draft(
            {
                "targetRestatement": "比较订单变化",
                "metrics": ["订单数"],
                "dimensions": ["月份"],
                "scope": "2026 年",
                "requiredData": [{"name": "订单明细", "reason": "统计订单数"}],
                "clarifyingQuestions": [],
            }
        )

        status, result = self.store.update(draft["id"], edited)

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(result["scope"], "2026 年")

    def test_advance_is_blocked_until_explicit_confirmation(self):
        draft = self.store.create("分析销售趋势")

        blocked_status, blocked = self.store.advance(draft["id"])
        confirm_status, confirmed = self.store.confirm(draft["id"])
        after_status, after = self.store.advance(draft["id"])

        self.assertEqual(blocked_status, HTTPStatus.CONFLICT)
        self.assertIn("尚未确认", blocked["error"])
        self.assertEqual(confirm_status, HTTPStatus.OK)
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertTrue(confirmed["nextAllowed"])
        self.assertEqual(after_status, HTTPStatus.OK)
        self.assertEqual(after["status"], "data_preparation")
        self.assertEqual(after["dataPreparationStatus"], "selecting_source")
        self.assertIsNone(after["nextAction"])

    def test_data_is_not_parsed_before_requirement_confirmation(self):
        draft = self.store.create("分析销售趋势")

        status, result = self.store.import_data(draft["id"], {
            "method": "file", "filename": "invalid.csv", "content": ""
        })

        self.assertEqual(status, HTTPStatus.CONFLICT)
        self.assertIn("尚未进入", result["error"])

    def test_data_preparation_action_is_recorded_and_persisted(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            records_file = Path(temporary_directory) / "records.json"
            store = app.DraftStore(records_file)
            draft = store.create("分析采购成本")
            store.confirm(draft["id"])
            store.advance(draft["id"])

            status, updated = store.choose_data_action(draft["id"], "connect_source")
            reloaded = app.DraftStore(records_file).get(draft["id"])

            self.assertEqual(status, HTTPStatus.OK)
            self.assertEqual(updated["nextAction"], "connect_source")
            self.assertEqual(reloaded["status"], "data_preparation")
            self.assertEqual(reloaded["nextAction"], "connect_source")

    def test_confirmed_draft_is_locked_against_edits(self):
        draft = self.store.create("分析采购成本")
        self.store.confirm(draft["id"])

        status, result = self.store.update(draft["id"], app.build_draft("改写目标"))

        self.assertEqual(status, HTTPStatus.CONFLICT)
        self.assertIn("不可再编辑", result["error"])

    def test_complete_loop_imports_parses_analyzes_and_accepts(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            records_file = Path(temporary_directory) / "records.json"
            store = app.DraftStore(records_file)
            draft = store.create("分析各渠道销售额")
            store.confirm(draft["id"])
            store.advance(draft["id"])

            import_status, result = store.import_data(draft["id"], {
                "method": "file",
                "filename": "sales.csv",
                "content": "渠道,销售额\n官网,100\n门店,200\n官网,50\n",
            })
            review_status, accepted = store.review_result(draft["id"], "accept", "结果符合需求")
            reloaded = app.DraftStore(records_file).get(draft["id"])

            self.assertEqual(import_status, HTTPStatus.OK)
            self.assertEqual(result["status"], "result_ready")
            self.assertEqual(result["analysisResult"]["rowCount"], 3)
            self.assertEqual(result["analysisResult"]["numericSummaries"][0]["sum"], 350.0)
            self.assertEqual(result["analysisResult"]["dimensionSummaries"][0]["values"][0], {"value": "官网", "count": 2})
            self.assertEqual(result["analysisResult"]["dataUnderstanding"]["tables"][0]["columnCount"], 2)
            self.assertFalse(result["analysisResult"]["analysisPreparation"]["ready"])
            self.assertEqual(result["analysisResult"]["analysisPreparation"]["missingItems"], ["销量"])
            self.assertEqual(review_status, HTTPStatus.OK)
            self.assertEqual(accepted["status"], "accepted")
            self.assertEqual(reloaded["customerReview"]["feedback"], "结果符合需求")
            self.assertEqual(
                [event["stage"] for event in reloaded["timeline"]],
                ["requirement_created", "requirement_confirmed", "data_preparation_started", "data_imported", "data_understood", "data_processed", "analysis_prepared", "customer_accepted"],
            )

    def test_xlsx_upload_uses_first_non_empty_sheet(self):
        draft = self.store.create("分析各渠道销售额")
        self.store.confirm(draft["id"])
        self.store.advance(draft["id"])

        status, result = self.store.import_data(draft["id"], {
            "method": "file",
            "filename": "sales.xlsx",
            "content": base64.b64encode(make_xlsx_bytes()).decode("ascii"),
            "contentEncoding": "base64",
        })

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(result["dataImport"]["rowCount"], 2)
        self.assertEqual(result["dataImport"]["columns"], ["渠道", "销售额"])
        self.assertEqual(result["dataImport"]["sheetNames"], ["空表", "销售明细"])
        self.assertEqual(result["dataImport"]["selectedSheet"], "销售明细")
        self.assertEqual(
            result["analysisResult"]["dataUnderstanding"]["tables"][0]["name"],
            "销售明细",
        )
        self.assertEqual(result["analysisResult"]["numericSummaries"][0]["sum"], 300.0)

    def test_xlsx_upload_rejects_invalid_encoding_and_corrupt_workbook(self):
        draft = self.store.create("分析各渠道销售额")
        self.store.confirm(draft["id"])
        self.store.advance(draft["id"])

        invalid_status, invalid = self.store.import_data(draft["id"], {
            "method": "file",
            "filename": "sales.xlsx",
            "content": "not-base64!",
            "contentEncoding": "base64",
        })
        corrupt_status, corrupt = self.store.import_data(draft["id"], {
            "method": "file",
            "filename": "sales.xlsx",
            "content": base64.b64encode(b"not an xlsx workbook").decode("ascii"),
            "contentEncoding": "base64",
        })

        self.assertEqual(invalid_status, HTTPStatus.BAD_REQUEST)
        self.assertIn("编码无效", invalid["error"])
        self.assertEqual(corrupt_status, HTTPStatus.BAD_REQUEST)
        self.assertIn("损坏", corrupt["error"])

    def test_phase_two_cleans_data_and_identifies_anomalies(self):
        draft = self.store.create("分析各渠道销售额")
        self.store.confirm(draft["id"])
        self.store.advance(draft["id"])

        status, result = self.store.import_data(draft["id"], {
            "method": "file",
            "filename": "sales.csv",
            "content": "渠道,销售额\n 官网 ,100\n官网,100\n门店,\n批发,异常\n",
        })

        processing = result["analysisResult"]["dataProcessing"]
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(processing["sourceRowCount"], 4)
        self.assertEqual(processing["cleanedRowCount"], 3)
        self.assertEqual(processing["actions"]["removedDuplicateRows"], 1)
        self.assertEqual(processing["actions"]["trimmedValues"], 1)
        self.assertEqual(processing["anomalies"]["missingValues"], [{"field": "销售额", "count": 1}])
        self.assertEqual(processing["anomalies"]["mixedTypes"][0]["field"], "销售额")

    def test_business_system_entry_uses_export_snapshot_without_credentials(self):
        draft = self.store.create("分析订单数")
        self.store.confirm(draft["id"])
        self.store.advance(draft["id"])

        invalid_status, _ = self.store.import_data(draft["id"], {
            "method": "connector", "filename": "orders.csv", "content": "订单数\n2\n"
        })
        status, result = self.store.import_data(draft["id"], {
            "method": "connector",
            "systemName": "ERP",
            "filename": "orders.csv",
            "content": "订单数\n2\n3\n",
        })

        self.assertEqual(invalid_status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(result["dataImport"]["source"], "ERP（安全导出快照）/orders.csv")

    def test_adjustment_requires_feedback_and_returns_to_importable_state(self):
        store = self.store
        draft = store.create("分析订单")
        store.confirm(draft["id"])
        store.advance(draft["id"])
        store.import_data(draft["id"], {
            "method": "file", "filename": "orders.json", "content": '[{"订单数": 3}]'
        })

        invalid_status, _ = store.review_result(draft["id"], "adjust", "")
        status, adjusted = store.review_result(draft["id"], "adjust", "增加客户维度")

        self.assertEqual(invalid_status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(adjusted["status"], "adjustment_requested")

    def test_adjustment_reuses_data_and_returns_focused_result(self):
        draft = self.store.create("分析利润和票价")
        edited = app.validate_draft({
            "targetRestatement": "分析利润和票价",
            "metrics": ["成本850", "利润"],
            "dimensions": ["整体"],
            "scope": "全部数据",
            "requiredData": [{"name": "票价明细", "reason": "计算票价和利润"}],
            "clarifyingQuestions": [],
        })
        self.store.update(draft["id"], edited)
        self.store.confirm(draft["id"])
        self.store.advance(draft["id"])
        payload = {
            "method": "file",
            "filename": "sales.csv",
            "content": "航司售价\n1000\n900\n800\n",
        }
        self.store.import_data(draft["id"], payload)
        self.store.review_result(
            draft["id"],
            "adjust",
            "只要利润和平均票价、最高价、最低价",
        )

        status, adjusted = self.store.import_data(draft["id"], payload)

        focus = adjusted["analysisResult"]["adjustmentFocus"]
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(adjusted["status"], "result_ready")
        self.assertEqual(adjusted["analysisResult"]["numericSummaries"][0]["field"], "航司售价")
        self.assertEqual(
            {item["label"]: item["value"] for item in focus["items"]},
            {"利润": 150.0, "平均票价": 900.0, "最高价": 1000.0, "最低价": 800.0},
        )
        self.assertEqual(focus["missingItems"], [])

    def test_records_persist_and_are_isolated_by_project(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            records_file = Path(temporary_directory) / "records.json"
            store = app.DraftStore(records_file)
            current = store.create("分析当前项目销售", "ai-data-workbench")
            other = store.create("分析其他项目采购", "other-project")

            reloaded = app.DraftStore(records_file)
            self.assertEqual([record["id"] for record in reloaded.list("ai-data-workbench")], [current["id"]])
            self.assertEqual([record["id"] for record in reloaded.list("other-project")], [other["id"]])

            wrong_project_status, _ = reloaded.delete(other["id"], "ai-data-workbench")
            delete_status, _ = reloaded.delete(current["id"], "ai-data-workbench")
            self.assertEqual(wrong_project_status, HTTPStatus.NOT_FOUND)
            self.assertEqual(delete_status, HTTPStatus.OK)
            self.assertEqual(reloaded.list("ai-data-workbench"), [])
            self.assertEqual(len(reloaded.list("other-project")), 1)

    def test_server_uses_only_required_host_and_port(self):
        with patch("app.ThreadingHTTPServer") as server_class:
            app.create_server()
        server_class.assert_called_once_with(("127.0.0.6", 8006), app.WorkbenchHandler)

    def test_collaboration_records_are_filtered_operable_and_deletable(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            activity_file = Path(temporary_directory) / "activity.json"
            store = app.ActivityStore(activity_file)
            executions = [
                {
                    "id": "execution-workbench",
                    "promptNumber": 303,
                    "title": "新增分析记录留痕与管理功能",
                    "status": "completed",
                    "project": "AI 数据工作台",
                    "workspacePath": app.PROJECT_PATH,
                    "createdAt": "2026-07-20T09:37:45Z",
                    "result": "测试通过",
                    "changedFiles": ["app.py"],
                },
                {
                    "id": "execution-other",
                    "title": "其他项目任务",
                    "status": "completed",
                    "project": "其他项目",
                    "workspacePath": "/private/tmp/other",
                },
            ]

            records = app.project_execution_records(executions, store)
            update_status, _ = store.update("execution-workbench", "processing")
            updated = app.project_execution_records(executions, store)
            delete_status, _ = store.delete("execution-workbench")
            deleted = app.project_execution_records(executions, app.ActivityStore(activity_file))

            self.assertEqual([record["id"] for record in records], ["execution-workbench"])
            self.assertEqual(update_status, HTTPStatus.OK)
            self.assertEqual(updated[0]["handlingStatus"], "processing")
            self.assertEqual(delete_status, HTTPStatus.OK)
            self.assertEqual(deleted, [])

    def test_collaboration_records_require_exact_workspace_and_keep_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = app.ActivityStore(Path(temporary_directory) / "activity.json")
            executions = [
                {
                    "id": "execution-current",
                    "project": "AI 数据工作台",
                    "workspacePath": app.PROJECT_PATH,
                },
                {
                    "id": "execution-same-name-other-workspace",
                    "project": "AI 数据工作台",
                    "workspacePath": "/private/tmp/other-workbench",
                },
                {
                    "id": "execution-legacy-without-workspace",
                    "project": "AI 数据工作台",
                },
            ]

            records = app.project_execution_records(executions, store)

            self.assertEqual(
                [record["id"] for record in records],
                ["execution-current", "execution-legacy-without-workspace"],
            )

    def test_page_exposes_goal_draft_and_confirmation_controls(self):
        static_dir = Path(app.STATIC_DIR)
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        css = (static_dir / "styles.css").read_text(encoding="utf-8")
        javascript = (static_dir / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="goal"', html)
        self.assertIn('id="target-restatement"', html)
        self.assertIn('id="required-data"', html)
        self.assertIn('id="save-draft-button"', html)
        self.assertIn('id="confirm-button"', html)
        self.assertIn('id="history-list"', html)
        self.assertIn('id="data-preparation-form"', html)
        self.assertIn('value="path"', html)
        self.assertIn('value="file"', html)
        self.assertIn('value="connector"', html)
        self.assertIn("上传数据", html)
        self.assertIn("连接业务系统", html)
        self.assertIn("使用已有数据", html)
        self.assertIn('id="file-drop-zone"', html)
        self.assertIn('accept=".xlsx,.csv,.tsv,.json"', html)
        self.assertIn('/app.js?v=20260809-1', html)
        self.assertIn('id="run-workspace-button"', html)
        self.assertIn('id="output-linked"', html)
        self.assertIn("/auto-run", javascript)
        self.assertIn('id="result-panel"', html)
        self.assertIn('id="accept-result-button"', html)
        self.assertIn('id="request-adjustment-button"', html)
        self.assertIn('id="collaboration-record-list"', html)
        self.assertIn('id="collaboration-search"', html)
        self.assertIn('id="collaboration-panel-toggle"', html)
        self.assertIn('id="collaboration-panel-content"', html)
        self.assertIn('data-section-toggle', html)
        self.assertIn("/confirm", javascript)
        self.assertIn("草案已保存，仍处于 draft 状态。", javascript)
        self.assertIn("window.confirm", javascript)
        self.assertIn("/api/records", javascript)
        self.assertIn("/api/collaboration-records", javascript)
        self.assertIn("/import", javascript)
        self.assertIn("/review", javascript)
        self.assertIn('addEventListener("drop"', javascript)
        self.assertIn('payload.contentEncoding = "base64"', javascript)
        self.assertIn("已按调整意见重新分析", javascript)
        self.assertIn("Cache-Control", app.WorkbenchHandler.end_headers.__code__.co_consts)
        self.assertIn('managementToggle.textContent = "管理操作"', javascript)
        self.assertIn('managementToggle.setAttribute("aria-expanded", "false")', javascript)
        self.assertIn("actions.hidden = true", javascript)
        self.assertIn('event.target.closest(".record-management-toggle")', javascript)
        self.assertIn("IntersectionObserver", javascript)
        self.assertIn('aria-current', javascript)
        self.assertIn('event.target.closest("[data-section-toggle]")', javascript)
        self.assertIn(".collaboration-record__actions[hidden]", css)
        self.assertIn("position: sticky", css)
        self.assertIn("height: calc(100vh - 68px)", css)
        self.assertIn(".section-content[hidden]", css)
        self.assertIn("position: fixed", css)
        self.assertIn("transform: translateX(-100%)", css)
        self.assertIn(".file-drop-zone", css)
        self.assertIn(".analysis-result table", css)
        self.assertIn('id="free-workspace-panel"', html)
        self.assertIn('id="workspace-files"', html)
        self.assertIn('id="operation-type"', html)
        self.assertIn('id="workspace-preview-before"', html)
        self.assertIn('id="execute-workspace-button"', html)
        self.assertIn('/api/workspaces', javascript)
        self.assertIn('data-workspace-step', html)
        self.assertIn('.workspace-step-content[hidden]', css)


class PhaseOneHttpContractTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        app.DRAFT_STORE = app.DraftStore(Path(self.temporary_directory.name) / "records.json")
        app.ACTIVITY_STORE = app.ActivityStore(Path(self.temporary_directory.name) / "activity.json")
        app.WORKSPACE_STORE = app.DataWorkspaceStore(Path(self.temporary_directory.name) / "workspaces")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def request(self, method, path, payload=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else b""
        request = (
            f"{method} {path} HTTP/1.1\r\n"
            "Host: 127.0.0.6:8006\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("utf-8") + body
        client, server_socket = socket.socketpair()
        try:
            client.sendall(request)
            client.shutdown(socket.SHUT_WR)
            server = type("TestServer", (), {"server_name": "127.0.0.6", "server_port": 8006})()
            app.WorkbenchHandler(server_socket, ("127.0.0.6", 0), server)
            server_socket.close()
            response = b""
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    break
                response += chunk
        finally:
            client.close()
            server_socket.close()
        head, response_body = response.split(b"\r\n\r\n", 1)
        status = int(head.split(b" ", 2)[1])
        return status, json.loads(response_body.decode("utf-8"))

    def test_api_create_edit_confirm_and_get_status(self):
        created_status, draft = self.request("POST", "/api/drafts", {"goal": "分析本季度各渠道利润"})
        self.assertEqual(created_status, HTTPStatus.CREATED)

        draft["scope"] = "2026 年第二季度"
        edited_status, edited = self.request("PUT", f"/api/drafts/{draft['id']}", draft)
        self.assertEqual(edited_status, HTTPStatus.OK)
        self.assertEqual(edited["scope"], "2026 年第二季度")

        blocked_status, _ = self.request("POST", f"/api/drafts/{draft['id']}/advance", {})
        self.assertEqual(blocked_status, HTTPStatus.CONFLICT)

        confirm_status, confirmed = self.request("POST", f"/api/drafts/{draft['id']}/confirm", {})
        self.assertEqual(confirm_status, HTTPStatus.OK)
        self.assertEqual(confirmed["status"], "confirmed")

        advance_status, waiting = self.request("POST", f"/api/drafts/{draft['id']}/advance", {})
        self.assertEqual(advance_status, HTTPStatus.OK)
        self.assertEqual(waiting["status"], "data_preparation")

        action_status, selected = self.request(
            "POST", f"/api/drafts/{draft['id']}/data-action", {"action": "upload_data"}
        )
        self.assertEqual(action_status, HTTPStatus.OK)
        self.assertEqual(selected["nextAction"], "upload_data")

        get_status, current = self.request("GET", f"/api/drafts/{draft['id']}")
        self.assertEqual(get_status, HTTPStatus.OK)
        self.assertEqual(current["status"], "data_preparation")
        self.assertEqual(current["nextAction"], "upload_data")

    def test_workspace_api_requires_preview_before_execution(self):
        health_status, health = self.request("GET", "/api/health")
        created_status, workspace = self.request("POST", "/api/workspaces", {
            "name": "订单筛选", "instructions": "清理空格并去重"
        })
        upload_status, uploaded = self.request("POST", f"/api/workspaces/{workspace['id']}/datasets", {
            "filename": "orders.csv",
            "content": base64.b64encode("订单号,状态\n1,已付\n1,已付\n2,待付\n".encode("utf-8-sig")).decode("ascii"),
        })
        table_id = uploaded["tables"][0]["id"]
        plan_status, _ = self.request("PUT", f"/api/workspaces/{workspace['id']}/plan", {
            "sourceTableIds": [table_id],
            "combineMode": "first",
            "operations": [
                {"type": "drop_duplicates", "columns": ["订单号"]},
                {"type": "filter", "column": "状态", "operator": "eq", "value": "已付"},
            ],
        })
        blocked_status, _ = self.request("POST", f"/api/workspaces/{workspace['id']}/execute", {"previewId": "none"})
        preview_status, preview = self.request("POST", f"/api/workspaces/{workspace['id']}/preview", {})
        execute_status, execution = self.request("POST", f"/api/workspaces/{workspace['id']}/execute", {"previewId": preview["id"]})

        self.assertEqual(health_status, HTTPStatus.OK)
        self.assertEqual(health["host"], "127.0.0.6")
        self.assertEqual(created_status, HTTPStatus.CREATED)
        self.assertEqual(upload_status, HTTPStatus.OK)
        self.assertEqual(plan_status, HTTPStatus.OK)
        self.assertEqual(blocked_status, HTTPStatus.CONFLICT)
        self.assertEqual(preview_status, HTTPStatus.OK)
        self.assertEqual(preview["result"]["profile"]["rowCount"], 1)
        self.assertEqual(execute_status, HTTPStatus.OK)
        self.assertEqual(execution["profile"]["rowCount"], 1)

    def test_api_lists_selects_and_deletes_only_current_project_record(self):
        _, current = self.request(
            "POST", "/api/drafts", {"goal": "分析当前项目利润", "projectId": "ai-data-workbench"}
        )
        _, other = self.request(
            "POST", "/api/drafts", {"goal": "分析其他项目利润", "projectId": "other-project"}
        )

        list_status, listed = self.request("GET", "/api/records?projectId=ai-data-workbench")
        select_status, selected = self.request(
            "GET", f"/api/drafts/{current['id']}?projectId=ai-data-workbench"
        )
        wrong_delete_status, _ = self.request(
            "DELETE", f"/api/records/{other['id']}?projectId=ai-data-workbench"
        )
        delete_status, _ = self.request(
            "DELETE", f"/api/records/{current['id']}?projectId=ai-data-workbench"
        )
        _, after_delete = self.request("GET", "/api/records?projectId=ai-data-workbench")
        _, other_records = self.request("GET", "/api/records?projectId=other-project")

        self.assertEqual(list_status, HTTPStatus.OK)
        self.assertEqual([record["id"] for record in listed["records"]], [current["id"]])
        self.assertEqual(select_status, HTTPStatus.OK)
        self.assertEqual(selected["originalGoal"], "分析当前项目利润")
        self.assertEqual(selected["targetRestatement"], "分析当前项目利润")
        self.assertEqual(wrong_delete_status, HTTPStatus.NOT_FOUND)
        self.assertEqual(delete_status, HTTPStatus.OK)
        self.assertEqual(after_delete["records"], [])
        self.assertEqual([record["id"] for record in other_records["records"]], [other["id"]])

    def test_api_completes_import_result_and_customer_acceptance(self):
        _, draft = self.request("POST", "/api/drafts", {"goal": "分析各渠道销售额"})
        self.request("POST", f"/api/drafts/{draft['id']}/confirm", {})
        self.request("POST", f"/api/drafts/{draft['id']}/advance", {})

        import_status, result = self.request("POST", f"/api/drafts/{draft['id']}/import", {
            "method": "file",
            "filename": "sales.csv",
            "content": "渠道,销售额\n官网,100\n门店,200\n",
        })
        review_status, accepted = self.request("POST", f"/api/drafts/{draft['id']}/review", {
            "action": "accept", "feedback": "通过"
        })

        self.assertEqual(import_status, HTTPStatus.OK)
        self.assertEqual(result["status"], "result_ready")
        self.assertEqual(result["analysisResult"]["rowCount"], 2)
        self.assertEqual(review_status, HTTPStatus.OK)
        self.assertEqual(accepted["status"], "accepted")

    def test_api_imports_xlsx_binary_payload(self):
        _, draft = self.request("POST", "/api/drafts", {"goal": "分析各渠道销售额"})
        self.request("POST", f"/api/drafts/{draft['id']}/confirm", {})
        self.request("POST", f"/api/drafts/{draft['id']}/advance", {})

        import_status, result = self.request("POST", f"/api/drafts/{draft['id']}/import", {
            "method": "file",
            "filename": "sales.xlsx",
            "content": base64.b64encode(make_xlsx_bytes()).decode("ascii"),
            "contentEncoding": "base64",
        })

        self.assertEqual(import_status, HTTPStatus.OK)
        self.assertEqual(result["dataImport"]["selectedSheet"], "销售明细")
        self.assertEqual(result["analysisResult"]["rowCount"], 2)

    def test_collaboration_record_api_lists_updates_and_deletes_page_trace(self):
        executions = [{
            "id": "execution-draft-prompt-303",
            "promptNumber": 303,
            "title": "新增分析记录留痕与管理功能",
            "status": "completed",
            "project": "AI 数据工作台",
            "workspacePath": app.PROJECT_PATH,
            "createdAt": "2026-07-20T09:37:45Z",
            "result": "10 项测试全部通过",
            "changedFiles": ["app.py", "static/app.js"],
        }]
        with patch("app.load_aps_executions", return_value=executions):
            list_status, listed = self.request("GET", "/api/collaboration-records")
            update_status, updated = self.request(
                "PUT",
                "/api/collaboration-records/execution-draft-prompt-303",
                {"handlingStatus": "done"},
            )
            _, after_update = self.request("GET", "/api/collaboration-records")
            delete_status, _ = self.request(
                "DELETE", "/api/collaboration-records/execution-draft-prompt-303"
            )
            _, after_delete = self.request("GET", "/api/collaboration-records")

        self.assertEqual(list_status, HTTPStatus.OK)
        self.assertEqual(listed["records"][0]["promptNumber"], 303)
        self.assertEqual(update_status, HTTPStatus.OK)
        self.assertEqual(updated["handlingStatus"], "done")
        self.assertEqual(after_update["records"][0]["handlingStatus"], "done")
        self.assertEqual(delete_status, HTTPStatus.OK)
        self.assertEqual(after_delete["records"], [])


if __name__ == "__main__":
    unittest.main()

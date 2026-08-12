const goalForm = document.querySelector("#goal-form");
const draftForm = document.querySelector("#draft-form");
const formMessage = document.querySelector("#form-message");
const draftMessage = document.querySelector("#draft-message");
const draftStatus = document.querySelector("#draft-status");
const saveDraftButton = document.querySelector("#save-draft-button");
const confirmButton = document.querySelector("#confirm-button");
const dataPreparationForm = document.querySelector("#data-preparation-form");
const dataPreparationMessage = document.querySelector("#data-preparation-message");
const resultPanel = document.querySelector("#result-panel");
const analysisResult = document.querySelector("#analysis-result");
const reviewMessage = document.querySelector("#review-message");
const pathImportPanel = document.querySelector("#path-import-panel");
const connectorImportPanel = document.querySelector("#connector-import-panel");
const fileImportPanel = document.querySelector("#file-import-panel");
const dataFileInput = document.querySelector("#data-file");
const fileDropZone = document.querySelector("#file-drop-zone");
const selectedFileLabel = document.querySelector("#selected-file");
const appLayout = document.querySelector("#app-layout");
const sidebarCollapse = document.querySelector("#sidebar-collapse");
const sidebarRestore = document.querySelector("#sidebar-restore");
const historyList = document.querySelector("#history-list");
const historyMessage = document.querySelector("#history-message");
const collaborationRecordList = document.querySelector("#collaboration-record-list");
const collaborationRecordMessage = document.querySelector("#collaboration-record-message");
const collaborationSearch = document.querySelector("#collaboration-search");
const collaborationStatusFilter = document.querySelector("#collaboration-status-filter");
const sidebarLinks = Array.from(document.querySelectorAll('.sidebar nav a[href^="#"]'));
const appViews = Array.from(document.querySelectorAll("[data-app-view]"));
const SIDEBAR_STORAGE_KEY = "ai-data-workbench-sidebar-collapsed";
const PROJECT_ID = "ai-data-workbench";
let activeDraftId = null;
let collaborationRecords = [];
let selectedDataFile = null;
const DATA_ACTION_LABELS = {
  upload_data: "上传数据",
  connect_source: "连接业务系统",
  use_existing_data: "使用已有数据",
};

function setSidebarCollapsed(collapsed) {
  appLayout.classList.toggle("sidebar-is-collapsed", collapsed);
  sidebarRestore.hidden = !collapsed;
  localStorage.setItem(SIDEBAR_STORAGE_KEY, String(collapsed));
}

sidebarCollapse.addEventListener("click", () => setSidebarCollapsed(true));
sidebarRestore.addEventListener("click", () => setSidebarCollapsed(false));
setSidebarCollapsed(localStorage.getItem(SIDEBAR_STORAGE_KEY) === "true");

function setActiveSidebarLink(sectionId) {
  sidebarLinks.forEach((link) => {
    if (link.getAttribute("href") === `#${sectionId}`) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  });
}

function setAppView(sectionId, updateHash = true) {
  const target = document.getElementById(sectionId);
  if (!target?.matches("[data-app-view]")) return;
  appViews.forEach((view) => {
    const isActive = view === target;
    view.hidden = !isActive;
    view.classList.toggle("is-active", isActive);
  });
  setActiveSidebarLink(sectionId);
  if (updateHash) history.replaceState(null, "", `#${sectionId}`);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setSectionCollapsed(toggle, collapsed) {
  const content = document.getElementById(toggle.getAttribute("aria-controls"));
  if (!content) return;
  toggle.setAttribute("aria-expanded", String(!collapsed));
  toggle.textContent = collapsed ? "展开功能区" : "收起功能区";
  content.hidden = collapsed;
  toggle.closest("[data-nav-section]")?.classList.toggle("is-collapsed", collapsed);
}

document.addEventListener("click", (event) => {
  const toggle = event.target.closest("[data-section-toggle]");
  if (!toggle) return;
  const collapsed = toggle.getAttribute("aria-expanded") === "true";
  setSectionCollapsed(toggle, collapsed);
  const section = toggle.closest("[data-nav-section]");
  if (section) setActiveSidebarLink(section.id);
});

document.querySelector("#sidebar nav").addEventListener("click", (event) => {
  const link = event.target.closest('a[href^="#"]');
  if (!link) return;
  const target = document.querySelector(link.getAttribute("href"));
  if (!target) return;
  event.preventDefault();
  setAppView(target.id);
  if (window.matchMedia("(max-width: 520px)").matches) setSidebarCollapsed(true);
});

// App views replace the old long-page scrolling model. The capability check is
// retained for browsers that expose IntersectionObserver to legacy panels.
const sectionObserver = "IntersectionObserver" in window ? new IntersectionObserver(() => {}) : null;
if (sectionObserver) document.querySelectorAll("[data-nav-section]").forEach((section) => sectionObserver.observe(section));
const initialView = location.hash.slice(1);
setAppView(appViews.some((view) => view.id === initialView) ? initialView : "start-view", false);

function lines(value) {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}

function showMessage(element, message, isError = false) {
  element.className = `form-message ${isError ? "error" : "success"}`;
  element.textContent = message;
}

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { hour12: false });
}

function handlingLabel(value) {
  return { pending: "待处理", processing: "处理中", done: "已处理" }[value] || "待处理";
}

function appendDetail(container, label, value) {
  const item = document.createElement("div");
  const small = document.createElement("small");
  small.textContent = label;
  const strong = document.createElement("strong");
  strong.textContent = value;
  item.append(small, strong);
  container.append(item);
}

function filteredCollaborationRecords() {
  const keyword = collaborationSearch.value.trim().toLowerCase();
  const handlingStatus = collaborationStatusFilter.value;
  return collaborationRecords.filter((record) => {
    const searchable = [record.promptNumber, record.title, record.result, record.error].join(" ").toLowerCase();
    return (!keyword || searchable.includes(keyword))
      && (handlingStatus === "all" || record.handlingStatus === handlingStatus);
  });
}

function renderCollaborationRecords() {
  const records = filteredCollaborationRecords();
  collaborationRecordList.replaceChildren();
  if (!records.length) {
    const empty = document.createElement("p");
    empty.className = "record-empty";
    empty.textContent = collaborationRecords.length ? "没有符合当前查询条件的记录。" : "暂无 GPT / Codex 执行记录。";
    collaborationRecordList.append(empty);
    return;
  }

  records.forEach((record, index) => {
    const item = document.createElement("article");
    item.className = "collaboration-record";
    item.dataset.recordId = record.id;

    const head = document.createElement("div");
    head.className = "collaboration-record__head";
    const title = document.createElement("div");
    title.className = "collaboration-record__title";
    const prompt = document.createElement("span");
    prompt.className = "record-prompt";
    prompt.textContent = record.promptNumber ? `Prompt ${record.promptNumber}` : record.id;
    const name = document.createElement("strong");
    name.textContent = record.title;
    const badges = document.createElement("div");
    badges.className = "record-badges";
    const executionBadge = document.createElement("span");
    executionBadge.className = `record-badge record-badge--${record.executionStatus}`;
    executionBadge.textContent = record.executionStatus === "completed" ? "执行完成" : record.executionStatus === "failed" ? "执行失败" : record.executionStatus;
    const handlingBadge = document.createElement("span");
    handlingBadge.className = "record-badge";
    handlingBadge.textContent = handlingLabel(record.handlingStatus);
    badges.append(executionBadge, handlingBadge);
    title.append(prompt, name, badges);

    const management = document.createElement("div");
    management.className = "collaboration-record__management";
    const managementToggle = document.createElement("button");
    managementToggle.type = "button";
    managementToggle.className = "record-management-toggle";
    managementToggle.setAttribute("aria-expanded", "false");
    managementToggle.setAttribute("aria-controls", `record-management-${index}`);
    managementToggle.textContent = "管理操作";
    const actions = document.createElement("div");
    actions.id = `record-management-${index}`;
    actions.className = "collaboration-record__actions";
    actions.hidden = true;
    const statusLabel = document.createElement("label");
    statusLabel.textContent = "处理状态";
    const statusSelect = document.createElement("select");
    statusSelect.className = "record-handling-status";
    statusSelect.dataset.recordId = record.id;
    [["pending", "待处理"], ["processing", "处理中"], ["done", "已处理"]].forEach(([value, text]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = text;
      option.selected = record.handlingStatus === value;
      statusSelect.append(option);
    });
    statusLabel.append(statusSelect);
    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "record-delete";
    deleteButton.dataset.recordId = record.id;
    deleteButton.dataset.recordTitle = record.title;
    deleteButton.textContent = "删除";
    actions.append(statusLabel, deleteButton);
    management.append(managementToggle, actions);
    head.append(title, management);

    const details = document.createElement("details");
    details.className = "record-details";
    const summary = document.createElement("summary");
    summary.textContent = "查看执行详情";
    const detailGrid = document.createElement("div");
    detailGrid.className = "record-detail-grid";
    appendDetail(detailGrid, "执行 ID", record.id);
    appendDetail(detailGrid, "开始时间", formatTime(record.startedAt || record.createdAt));
    appendDetail(detailGrid, "完成时间", formatTime(record.completedAt));
    appendDetail(detailGrid, "退出码", record.exitCode === null || record.exitCode === undefined ? "—" : String(record.exitCode));
    appendDetail(detailGrid, "执行状态", record.executionStatus);
    appendDetail(detailGrid, "处理状态", handlingLabel(record.handlingStatus));
    details.append(summary, detailGrid);
    if (record.result || record.error) {
      const result = document.createElement("pre");
      result.className = "record-result";
      result.textContent = record.error ? `错误：${record.error}\n\n${record.result || ""}` : record.result;
      details.append(result);
    }
    if (record.changedFiles.length) {
      const files = document.createElement("p");
      files.className = "record-files";
      files.textContent = `涉及文件：${record.changedFiles.join("、")}`;
      details.append(files);
    }
    item.append(head, details);
    collaborationRecordList.append(item);
  });
}

async function refreshCollaborationRecords() {
  const result = await request("/api/collaboration-records");
  collaborationRecords = result.records;
  renderCollaborationRecords();
}

function renderDraft(draft) {
  activeDraftId = draft.id;
  goalForm.goal.value = draft.originalGoal;
  document.querySelector("#target-restatement").value = draft.targetRestatement;
  document.querySelector("#metrics").value = draft.metrics.join("\n");
  document.querySelector("#dimensions").value = draft.dimensions.join("\n");
  document.querySelector("#scope").value = draft.scope;
  document.querySelector("#required-data").value = draft.requiredData.map((item) => `${item.name} | ${item.reason}`).join("\n");
  document.querySelector("#questions").value = draft.clarifyingQuestions.join("\n");
  draftStatus.textContent = `${draft.status} · ${draft.nextAllowed ? "确认门已通过" : "后续流程已阻断"}`;
  draftForm.hidden = false;
  const locked = draft.status !== "draft";
  draftForm.querySelectorAll("textarea").forEach((element) => { element.disabled = locked; });
  saveDraftButton.disabled = locked;
  saveDraftButton.textContent = locked ? "草案已锁定" : "保存草案";
  confirmButton.disabled = locked;
  confirmButton.textContent = locked ? "已明确确认" : "明确确认 →";
  renderDataPreparation(draft);
  renderResult(draft);
}

function renderDataPreparation(draft) {
  const isPreparing = ["data_preparation", "adjustment_requested"].includes(draft.status);
  dataPreparationForm.hidden = !isPreparing;
  if (!isPreparing) return;
  document.querySelector("#confirmed-target").textContent = draft.targetRestatement;
  const requiredDataList = document.querySelector("#confirmed-required-data");
  requiredDataList.replaceChildren();
  draft.requiredData.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = `${item.name}：${item.reason}`;
    requiredDataList.append(li);
  });
}

function addResultItem(container, label, value) {
  const item = document.createElement("div");
  const small = document.createElement("small");
  small.textContent = label;
  const strong = document.createElement("strong");
  strong.textContent = value;
  item.append(small, strong);
  container.append(item);
}

function renderResult(draft) {
  const result = draft.analysisResult;
  resultPanel.hidden = !result;
  if (!result) return;
  analysisResult.replaceChildren();
  const summary = document.createElement("div");
  summary.className = "result-summary-grid";
  addResultItem(summary, "已确认目标", result.goal);
  addResultItem(summary, "原始 / 清洗后行数", `${result.sourceRowCount} / ${result.rowCount}`);
  addResultItem(summary, "字段", result.columns.join("、"));
  addResultItem(summary, "数据来源", draft.dataImport?.source || "—");
  analysisResult.append(summary);

  if (result.adjustmentFocus) {
    const focusHeading = document.createElement("h3");
    focusHeading.textContent = "按调整意见重新计算";
    const focusNote = document.createElement("p");
    focusNote.className = "result-note";
    focusNote.textContent = `调整意见：${result.adjustmentFocus.feedback}`;
    const focusGrid = document.createElement("div");
    focusGrid.className = "result-summary-grid";
    result.adjustmentFocus.items.forEach((item) => {
      addResultItem(focusGrid, item.label, String(item.value));
    });
    const focusDetails = document.createElement("ul");
    result.adjustmentFocus.items.forEach((item) => {
      const detail = document.createElement("li");
      detail.textContent = `${item.label}口径：${item.basis}`;
      focusDetails.append(detail);
    });
    result.adjustmentFocus.missingItems.forEach((text) => {
      const detail = document.createElement("li");
      detail.textContent = text;
      focusDetails.append(detail);
    });
    analysisResult.append(focusHeading, focusNote, focusGrid, focusDetails);
  }

  const understandingHeading = document.createElement("h3");
  understandingHeading.textContent = "1. AI 数据理解";
  const structureTable = document.createElement("table");
  structureTable.innerHTML = "<thead><tr><th>字段</th><th>识别类型</th><th>字段含义</th><th>非空</th><th>唯一值</th></tr></thead>";
  const structureBody = document.createElement("tbody");
  result.dataUnderstanding.tables[0].fields.forEach((field) => {
    const row = document.createElement("tr");
    [field.name, field.type, field.meaning, field.nonEmptyCount, field.uniqueCount].forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = String(value);
      row.append(cell);
    });
    structureBody.append(row);
  });
  structureTable.append(structureBody);
  const relationshipText = document.createElement("p");
  relationshipText.className = "result-note";
  relationshipText.textContent = result.dataUnderstanding.relationships.length
    ? `基础关系：${result.dataUnderstanding.relationships.map((item) => `${item.from} → ${item.to}`).join("；")}`
    : "基础关系：当前字段未形成可识别的维度与指标关系。";
  analysisResult.append(understandingHeading, structureTable, relationshipText);

  const processingHeading = document.createElement("h3");
  processingHeading.textContent = "2. 数据整理、清洗与异常识别";
  const processingGrid = document.createElement("div");
  processingGrid.className = "result-summary-grid";
  addResultItem(processingGrid, "去除重复行", String(result.dataProcessing.actions.removedDuplicateRows));
  addResultItem(processingGrid, "清理首尾空格", String(result.dataProcessing.actions.trimmedValues));
  addResultItem(processingGrid, "统一空值", String(result.dataProcessing.actions.normalizedEmptyValues));
  const anomalyCount = Object.values(result.dataProcessing.anomalies).reduce((count, items) => count + items.length, 0);
  addResultItem(processingGrid, "异常类型项", String(anomalyCount));
  const anomalyList = document.createElement("ul");
  const anomalies = result.dataProcessing.anomalies;
  [
    ...anomalies.missingValues.map((item) => `${item.field}：缺失 ${item.count} 个`),
    ...anomalies.mixedTypes.map((item) => `${item.field}：混合类型（数值 ${item.numericCount} / 其他 ${item.otherCount}）`),
    ...anomalies.numericOutliers.map((item) => `${item.field}：${item.rule} 识别 ${item.count} 个离群值`),
  ].forEach((text) => {
    const item = document.createElement("li");
    item.textContent = text;
    anomalyList.append(item);
  });
  if (!anomalyList.children.length) {
    const item = document.createElement("li");
    item.textContent = "未识别到基础缺失、混合类型或数值离群异常。";
    anomalyList.append(item);
  }
  analysisResult.append(processingHeading, processingGrid, anomalyList);

  const preparationHeading = document.createElement("h3");
  preparationHeading.textContent = "3. 按已确认目标准备分析";
  const preparation = result.analysisPreparation;
  const preparationStatus = document.createElement("p");
  preparationStatus.className = `preparation-status ${preparation.ready ? "is-ready" : "has-gap"}`;
  preparationStatus.textContent = preparation.ready
    ? "分析准备已就绪：指标和维度均已找到对应字段。"
    : `分析准备存在缺口：${preparation.missingItems.join("、")}`;
  const mappingList = document.createElement("ul");
  [...preparation.metricMappings, ...preparation.dimensionMappings].forEach((item) => {
    const li = document.createElement("li");
    li.textContent = `${item.item} → ${item.field || "未找到对应字段"}`;
    mappingList.append(li);
  });
  analysisResult.append(preparationHeading, preparationStatus, mappingList);

  if (result.numericSummaries.length) {
    const heading = document.createElement("h3");
    heading.textContent = "4. 基础计算预览";
    const table = document.createElement("table");
    table.innerHTML = "<thead><tr><th>字段</th><th>有效数</th><th>合计</th><th>平均</th><th>最小</th><th>最大</th></tr></thead>";
    const body = document.createElement("tbody");
    result.numericSummaries.forEach((item) => {
      const row = document.createElement("tr");
      [item.field, item.count, item.sum, item.average, item.min, item.max].forEach((value) => {
        const cell = document.createElement("td");
        cell.textContent = String(value);
        row.append(cell);
      });
      body.append(row);
    });
    table.append(body);
    analysisResult.append(heading, table);
  }

  result.dimensionSummaries.forEach((item) => {
    const heading = document.createElement("h3");
    heading.textContent = `${item.field}分布`;
    const list = document.createElement("ul");
    item.values.forEach((entry) => {
      const li = document.createElement("li");
      li.textContent = `${entry.value}：${entry.count} 行`;
      list.append(li);
    });
    analysisResult.append(heading, list);
  });

  const canReview = draft.status === "result_ready";
  document.querySelector("#review-feedback").disabled = !canReview;
  document.querySelector("#request-adjustment-button").disabled = !canReview;
  document.querySelector("#accept-result-button").disabled = !canReview;
  if (draft.status === "accepted") {
    showMessage(reviewMessage, "客户已确认验收，完整流程已闭环。", false);
  } else if (draft.status === "adjustment_requested") {
    showMessage(reviewMessage, `已记录调整意见：${draft.customerReview.feedback}`, false);
  } else {
    reviewMessage.className = "form-message";
  }
}

function saveActiveDraft() {
  return request(`/api/drafts/${activeDraftId}?projectId=${encodeURIComponent(PROJECT_ID)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(collectDraft()),
  });
}

function renderHistory(records) {
  historyList.replaceChildren();
  if (!records.length) {
    const empty = document.createElement("p");
    empty.className = "history-empty";
    empty.textContent = "暂无分析记录。";
    historyList.append(empty);
    return;
  }
  records.forEach((record) => {
    const item = document.createElement("article");
    item.className = "history-item";

    const selectButton = document.createElement("button");
    selectButton.type = "button";
    selectButton.className = "history-select";
    selectButton.dataset.recordId = record.id;
    const goal = document.createElement("strong");
    goal.textContent = record.originalGoal;
    const understanding = document.createElement("span");
    understanding.textContent = `AI 理解：${record.targetRestatement}`;
    const status = document.createElement("small");
    const statusLabel = {
      draft: "需求待确认", confirmed: "需求已确认", data_preparation: "正在准备数据",
      result_ready: "结果待验收", adjustment_requested: "客户要求调整", accepted: "客户已验收",
    }[record.status] || record.status;
    status.textContent = `${statusLabel} · 留痕 ${record.timeline?.length || 0} 项`;
    selectButton.append(goal, understanding, status);

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "history-delete";
    deleteButton.dataset.recordId = record.id;
    deleteButton.dataset.recordGoal = record.originalGoal;
    deleteButton.textContent = "清除";
    item.append(selectButton, deleteButton);
    historyList.append(item);
  });
}

async function refreshHistory() {
  const result = await request(`/api/records?projectId=${encodeURIComponent(PROJECT_ID)}`);
  renderHistory(result.records);
}

function collectDraft() {
  return {
    targetRestatement: document.querySelector("#target-restatement").value,
    metrics: lines(document.querySelector("#metrics").value),
    dimensions: lines(document.querySelector("#dimensions").value),
    scope: document.querySelector("#scope").value,
    requiredData: lines(document.querySelector("#required-data").value).map((line) => {
      const separator = line.indexOf("|");
      return separator < 0
        ? { name: line, reason: "" }
        : { name: line.slice(0, separator).trim(), reason: line.slice(separator + 1).trim() };
    }),
    clarifyingQuestions: lines(document.querySelector("#questions").value),
  };
}

async function request(url, options) {
  const response = await fetch(url, options);
  const result = await response.json();
  if (!response.ok) {
    const error = new Error(result.error || "请求失败");
    error.payload = result;
    error.status = response.status;
    throw error;
  }
  return result;
}

goalForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  formMessage.className = "form-message";
  const button = goalForm.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    const draft = await request("/api/drafts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goal: goalForm.goal.value, projectId: PROJECT_ID }),
    });
    renderDraft(draft);
    await refreshHistory();
    showMessage(formMessage, "草案已生成，请编辑并明确确认。确认前后续流程保持阻断。", false);
    draftForm.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showMessage(formMessage, error.message, true);
  } finally {
    button.disabled = false;
  }
});

saveDraftButton.addEventListener("click", async () => {
  draftMessage.className = "form-message";
  saveDraftButton.disabled = true;
  confirmButton.disabled = true;
  try {
    const saved = await saveActiveDraft();
    renderDraft(saved);
    await refreshHistory();
    showMessage(draftMessage, "草案已保存，仍处于 draft 状态。", false);
  } catch (error) {
    saveDraftButton.disabled = false;
    confirmButton.disabled = false;
    showMessage(draftMessage, error.message, true);
  }
});

draftForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  draftMessage.className = "form-message";
  saveDraftButton.disabled = true;
  confirmButton.disabled = true;
  try {
    await saveActiveDraft();
    const confirmed = await request(`/api/drafts/${activeDraftId}/confirm?projectId=${encodeURIComponent(PROJECT_ID)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const dataPreparation = await request(`/api/drafts/${activeDraftId}/advance?projectId=${encodeURIComponent(PROJECT_ID)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    renderDraft(dataPreparation);
    await refreshHistory();
    showMessage(draftMessage, `草案已确认（${confirmed.status}），已主动进入数据准备阶段。`, false);
    dataPreparationForm.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    saveDraftButton.disabled = false;
    confirmButton.disabled = false;
    showMessage(draftMessage, error.message, true);
  }
});

async function buildImportPayload() {
  const method = dataPreparationForm.querySelector('input[name="import-method"]:checked').value;
  const payload = { method, projectId: PROJECT_ID };
  if (method === "path") {
    payload.path = document.querySelector("#data-path").value.trim();
  } else if (selectedDataFile) {
    payload.filename = selectedDataFile.name;
    if (selectedDataFile.name.toLowerCase().endsWith(".xlsx")) {
      const bytes = new Uint8Array(await selectedDataFile.arrayBuffer());
      let binary = "";
      for (let offset = 0; offset < bytes.length; offset += 32_768) {
        binary += String.fromCharCode(...bytes.subarray(offset, offset + 32_768));
      }
      payload.content = btoa(binary);
      payload.contentEncoding = "base64";
    } else {
      payload.content = await selectedDataFile.text();
    }
    if (method === "connector") payload.systemName = document.querySelector("#system-name").value.trim();
  }
  return payload;
}

async function importCurrentData() {
  const payload = await buildImportPayload();
  return request(`/api/drafts/${activeDraftId}/import?projectId=${encodeURIComponent(PROJECT_ID)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

dataPreparationForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.querySelector("#import-data-button");
  button.disabled = true;
  try {
    const updated = await importCurrentData();
    renderDraft(updated);
    await refreshHistory();
    showMessage(dataPreparationMessage, `已完成 ${updated.dataImport.rowCount} 行数据的理解、处理与分析准备。`, false);
    resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showMessage(dataPreparationMessage, error.message, true);
  } finally {
    button.disabled = false;
  }
});

dataPreparationForm.addEventListener("change", (event) => {
  if (event.target.matches('input[name="import-method"]')) {
    const method = event.target.value;
    pathImportPanel.hidden = method !== "path";
    connectorImportPanel.hidden = method !== "connector";
    fileImportPanel.hidden = method === "path";
  }
});

function selectDataFile(file) {
  selectedDataFile = file || null;
  selectedFileLabel.textContent = selectedDataFile ? `已选择：${selectedDataFile.name}` : "尚未选择文件";
}

dataFileInput.addEventListener("change", () => selectDataFile(dataFileInput.files[0]));
fileDropZone.addEventListener("click", (event) => {
  if (event.target !== dataFileInput) dataFileInput.click();
});
fileDropZone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") dataFileInput.click();
});
["dragenter", "dragover"].forEach((name) => fileDropZone.addEventListener(name, (event) => {
  event.preventDefault();
  fileDropZone.classList.add("is-dragging");
}));
["dragleave", "drop"].forEach((name) => fileDropZone.addEventListener(name, (event) => {
  event.preventDefault();
  fileDropZone.classList.remove("is-dragging");
}));
fileDropZone.addEventListener("drop", (event) => selectDataFile(event.dataTransfer.files[0]));

async function reviewResult(action) {
  const feedback = document.querySelector("#review-feedback").value;
  try {
    const updated = await request(`/api/drafts/${activeDraftId}/review?projectId=${encodeURIComponent(PROJECT_ID)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, feedback }),
    });
    renderDraft(updated);
    if (action === "adjust") {
      const method = dataPreparationForm.querySelector('input[name="import-method"]:checked').value;
      const canReuseData = method === "path"
        ? Boolean(document.querySelector("#data-path").value.trim())
        : Boolean(selectedDataFile);
      if (canReuseData) {
        const reanalyzed = await importCurrentData();
        renderDraft(reanalyzed);
        showMessage(reviewMessage, "已按调整意见重新分析，请核对新结果后确认验收。", false);
        resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
      } else {
        showMessage(dataPreparationMessage, "调整意见已记录。请重新选择原数据文件后继续处理。", false);
        dataPreparationForm.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }
    await refreshHistory();
  } catch (error) {
    showMessage(reviewMessage, error.message, true);
  }
}

document.querySelector("#accept-result-button").addEventListener("click", () => reviewResult("accept"));
document.querySelector("#request-adjustment-button").addEventListener("click", () => reviewResult("adjust"));

historyList.addEventListener("click", async (event) => {
  const selectButton = event.target.closest(".history-select");
  const deleteButton = event.target.closest(".history-delete");
  try {
    if (selectButton) {
      const draft = await request(`/api/drafts/${selectButton.dataset.recordId}?projectId=${encodeURIComponent(PROJECT_ID)}`);
      renderDraft(draft);
      showMessage(historyMessage, draft.status === "draft" ? "已恢复记录，可继续编辑并确认。" : "已打开历史记录。", false);
      draftForm.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    if (deleteButton) {
      const confirmed = window.confirm(`确认清除这条分析记录？\n\n${deleteButton.dataset.recordGoal}\n\n此操作仅影响当前项目。`);
      if (!confirmed) return;
      await request(`/api/records/${deleteButton.dataset.recordId}?projectId=${encodeURIComponent(PROJECT_ID)}`, { method: "DELETE" });
      if (activeDraftId === deleteButton.dataset.recordId) {
        activeDraftId = null;
        draftForm.hidden = true;
        dataPreparationForm.hidden = true;
        resultPanel.hidden = true;
      }
      await refreshHistory();
      showMessage(historyMessage, "指定记录已清除。", false);
    }
  } catch (error) {
    showMessage(historyMessage, error.message, true);
  }
});

collaborationSearch.addEventListener("input", renderCollaborationRecords);
collaborationStatusFilter.addEventListener("change", renderCollaborationRecords);

collaborationRecordList.addEventListener("change", async (event) => {
  const select = event.target.closest(".record-handling-status");
  if (!select) return;
  try {
    await request(`/api/collaboration-records/${select.dataset.recordId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ handlingStatus: select.value }),
    });
    await refreshCollaborationRecords();
    showMessage(collaborationRecordMessage, "处理状态已保存。", false);
  } catch (error) {
    showMessage(collaborationRecordMessage, error.message, true);
  }
});

collaborationRecordList.addEventListener("click", async (event) => {
  const managementToggle = event.target.closest(".record-management-toggle");
  if (managementToggle) {
    const actions = document.getElementById(managementToggle.getAttribute("aria-controls"));
    const expanded = managementToggle.getAttribute("aria-expanded") === "true";
    managementToggle.setAttribute("aria-expanded", String(!expanded));
    managementToggle.textContent = expanded ? "管理操作" : "收起管理操作";
    actions.hidden = expanded;
    return;
  }
  const deleteButton = event.target.closest(".record-delete");
  if (!deleteButton) return;
  const confirmed = window.confirm(`确认从 AI 数据工作台删除这条任务留痕？\n\n${deleteButton.dataset.recordTitle}\n\nAPS 原始审计记录会继续保留。`);
  if (!confirmed) return;
  try {
    await request(`/api/collaboration-records/${deleteButton.dataset.recordId}`, { method: "DELETE" });
    await refreshCollaborationRecords();
    showMessage(collaborationRecordMessage, "页面留痕已删除，APS 原始审计记录未删除。", false);
  } catch (error) {
    showMessage(collaborationRecordMessage, error.message, true);
  }
});

refreshHistory().catch((error) => showMessage(historyMessage, error.message, true));
refreshCollaborationRecords().catch((error) => showMessage(collaborationRecordMessage, error.message, true));

// 自由数据处理工作区。与原有“分析目标”闭环并存，不改写历史草案。
const workspaceSelector = document.querySelector("#workspace-selector");
const workspaceStatus = document.querySelector("#workspace-status");
const workspaceName = document.querySelector("#workspace-name");
const workspaceInstructions = document.querySelector("#workspace-instructions");
const workspaceFiles = document.querySelector("#workspace-files");
const workspaceMessage = document.querySelector("#workspace-message");
const workspaceTableList = document.querySelector("#workspace-table-list");
const workspaceSourceTables = document.querySelector("#workspace-source-tables");
const workspaceCombineMode = document.querySelector("#workspace-combine-mode");
const operationType = document.querySelector("#operation-type");
const operationFields = document.querySelector("#operation-fields");
const operationList = document.querySelector("#operation-list");
const workspacePreviewSummary = document.querySelector("#workspace-preview-summary");
const workspacePreviewBefore = document.querySelector("#workspace-preview-before");
const workspacePreviewAfter = document.querySelector("#workspace-preview-after");
const workspacePreviewAudit = document.querySelector("#workspace-preview-audit");
const workspaceExecutionSummary = document.querySelector("#workspace-execution-summary");
const executeWorkspaceButton = document.querySelector("#execute-workspace-button");
const downloadWorkspaceCsv = document.querySelector("#download-workspace-csv");
const downloadWorkspaceXlsx = document.querySelector("#download-workspace-xlsx");
const downloadWorkspaceLinked = document.querySelector("#download-workspace-linked");
const runWorkspaceButton = document.querySelector("#run-workspace-button");
const workspaceProgress = document.querySelector("#workspace-progress");
const workspaceDropZone = document.querySelector("#workspace-drop-zone");
const workspaceFileCount = document.querySelector("#workspace-file-count");
const workspaceFileSummary = document.querySelector("#workspace-file-summary");
const workspaceResolution = document.querySelector("#workspace-resolution");
const oneClickResult = document.querySelector("#workspace-one-click-result");
const oneClickResultSummary = document.querySelector("#one-click-result-summary");
const workspaceResultEmpty = document.querySelector("#workspace-result-empty");
const outputLinked = document.querySelector("#output-linked");
const outputStandalone = document.querySelector("#output-standalone");
let activeWorkspace = null;
let workspaceOperations = [];
let activeWorkspacePreview = null;
let pendingAutoRunDecisions = {};
let stagedWorkspaceFiles = [];

const WORKSPACE_STATUS_LABELS = {
  waiting_for_data: "等待数据",
  plan_draft: "待编辑处理计划",
  plan_saved: "处理计划已保存",
  preview_ready: "预览待确认",
  needs_input: "需要选择",
  running: "正在处理",
  completed: "执行完成",
};
const OPERATION_LABELS = {
  trim: "清理首尾空格", normalize_empty: "统一空值", drop_duplicates: "删除重复行",
  select_columns: "选择字段", rename_columns: "重命名字段", reorder_columns: "调整字段顺序",
  convert_type: "转换字段类型", filter: "条件筛选", sort: "排序", split_column: "拆分字段",
  merge_columns: "合并字段", calculate: "计算列", group: "分组汇总", join: "关联另一张表",
};

function switchWorkspaceStep(step) {
  document.querySelectorAll("[data-workspace-step]").forEach((button) => button.classList.toggle("is-active", button.dataset.workspaceStep === step));
  document.querySelectorAll("[data-workspace-content]").forEach((content) => { content.hidden = content.dataset.workspaceContent !== step; });
}

document.querySelectorAll("[data-workspace-step]").forEach((button) => {
  button.addEventListener("click", () => switchWorkspaceStep(button.dataset.workspaceStep));
});

function appendOption(select, value, label, selected = false) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  option.selected = selected;
  select.append(option);
}

function activeColumns() {
  if (!activeWorkspace?.tables?.length) return [];
  const selectedId = Array.from(workspaceSourceTables.selectedOptions)[0]?.value || activeWorkspace.tables[0].id;
  return activeWorkspace.tables.find((table) => table.id === selectedId)?.profile?.columns || [];
}

function renderSimpleTable(container, rows) {
  container.replaceChildren();
  if (!rows?.length) {
    const empty = document.createElement("p");
    empty.className = "empty-workspace";
    empty.textContent = "没有可预览的数据行。";
    container.append(empty);
    return;
  }
  const columns = Object.keys(rows[0]);
  const table = document.createElement("table");
  table.className = "data-table";
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  columns.forEach((column) => { const cell = document.createElement("th"); cell.textContent = column; headRow.append(cell); });
  head.append(headRow);
  const body = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((column) => { const cell = document.createElement("td"); cell.textContent = row[column] ?? "（空）"; tr.append(cell); });
    body.append(tr);
  });
  table.append(head, body);
  container.append(table);
}

function renderWorkspaceTables() {
  workspaceTableList.replaceChildren();
  workspaceSourceTables.replaceChildren();
  if (!activeWorkspace?.tables?.length) {
    const empty = document.createElement("p");
    empty.className = "empty-workspace";
    empty.textContent = "尚未上传数据。";
    workspaceTableList.append(empty);
    return;
  }
  const selectedIds = new Set(activeWorkspace.plan?.sourceTableIds || [activeWorkspace.tables[0].id]);
  activeWorkspace.tables.forEach((tableRecord) => {
    appendOption(workspaceSourceTables, tableRecord.id, `${tableRecord.name} · ${tableRecord.profile.rowCount}行`, selectedIds.has(tableRecord.id));
    const card = document.createElement("article");
    card.className = "workspace-table-card";
    const title = document.createElement("strong");
    title.textContent = tableRecord.name;
    const meta = document.createElement("span");
    meta.textContent = `${tableRecord.profile.rowCount} 行 × ${tableRecord.profile.columnCount} 列 · ${tableRecord.profile.columns.join("、")}`;
    const details = document.createElement("details");
    details.className = "workspace-table-sample";
    const summary = document.createElement("summary");
    summary.textContent = "查看字段画像与样例";
    const profile = document.createElement("p");
    profile.className = "hint";
    profile.textContent = tableRecord.profile.fields.map((field) => `${field.name}：${field.type}，空值${field.emptyCount}，唯一值${field.uniqueCount}`).join("；");
    const tableBox = document.createElement("div");
    tableBox.className = "table-scroll";
    renderSimpleTable(tableBox, tableRecord.sample);
    details.append(summary, profile, tableBox);
    card.append(title, meta, details);
    workspaceTableList.append(card);
  });
}

function operationSummary(operation) {
  const copy = { ...operation };
  delete copy.type;
  return Object.keys(copy).length ? JSON.stringify(copy, null, 0) : "全部适用字段";
}

function renderOperations() {
  operationList.replaceChildren();
  if (!workspaceOperations.length) {
    const empty = document.createElement("p");
    empty.className = "empty-workspace";
    empty.textContent = "尚未添加处理步骤。没有步骤时，预览会原样保留数据。";
    operationList.append(empty);
    return;
  }
  workspaceOperations.forEach((operation, index) => {
    const card = document.createElement("article");
    card.className = "operation-card";
    const number = document.createElement("span");
    number.className = "operation-index";
    number.textContent = String(index + 1);
    const content = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = OPERATION_LABELS[operation.type] || operation.type;
    const summary = document.createElement("small");
    summary.textContent = operationSummary(operation);
    content.append(title, summary);
    const actions = document.createElement("div");
    actions.className = "operation-actions";
    [["↑", -1], ["↓", 1]].forEach(([label, move]) => {
      const button = document.createElement("button"); button.type = "button"; button.textContent = label; button.dataset.operationMove = move; button.dataset.operationIndex = index; actions.append(button);
    });
    const remove = document.createElement("button");
    remove.type = "button"; remove.textContent = "删除"; remove.className = "danger"; remove.dataset.operationDelete = index; actions.append(remove);
    card.append(number, content, actions);
    operationList.append(card);
  });
}

function fieldSelect(id, label, columns = activeColumns()) {
  const wrapper = document.createElement("label");
  wrapper.htmlFor = id;
  wrapper.textContent = label;
  const select = document.createElement("select");
  select.id = id;
  columns.forEach((column) => appendOption(select, column, column));
  wrapper.append(select);
  return wrapper;
}

function textField(id, label, placeholder = "") {
  const wrapper = document.createElement("label");
  wrapper.htmlFor = id;
  wrapper.textContent = label;
  const input = document.createElement("input");
  input.id = id; input.type = "text"; input.placeholder = placeholder;
  wrapper.append(input);
  return wrapper;
}

function staticSelect(id, label, choices) {
  const wrapper = document.createElement("label"); wrapper.htmlFor = id; wrapper.textContent = label;
  const select = document.createElement("select"); select.id = id;
  choices.forEach(([value, text]) => appendOption(select, value, text));
  wrapper.append(select); return wrapper;
}

function renderOperationFields() {
  operationFields.replaceChildren();
  const grid = document.createElement("div");
  grid.className = "field-grid";
  const kind = operationType.value;
  if (["trim", "normalize_empty", "drop_duplicates", "select_columns", "reorder_columns"].includes(kind)) {
    grid.append(textField("operation-columns", "字段（逗号分隔，可留空表示全部）", "例如：订单号,金额"));
  } else if (kind === "rename_columns") {
    grid.append(textField("operation-mapping", "重命名规则", "原字段=新字段,金额=销售额"));
  } else if (kind === "convert_type") {
    grid.append(fieldSelect("operation-column", "字段"), staticSelect("operation-target-type", "目标类型", [["number", "数值"], ["date", "日期"], ["text", "文本"], ["boolean", "布尔"]]));
  } else if (kind === "filter") {
    grid.append(fieldSelect("operation-column", "字段"), staticSelect("operation-operator", "条件", [["eq", "等于"], ["ne", "不等于"], ["contains", "包含"], ["starts_with", "开头是"], ["gt", "大于"], ["gte", "大于等于"], ["lt", "小于"], ["lte", "小于等于"], ["is_empty", "为空"], ["not_empty", "不为空"]]), textField("operation-value", "比较值"));
  } else if (kind === "sort") {
    grid.append(fieldSelect("operation-column", "字段"), staticSelect("operation-direction", "顺序", [["asc", "升序"], ["desc", "降序"]]));
  } else if (kind === "split_column") {
    grid.append(fieldSelect("operation-column", "来源字段"), textField("operation-separator", "分隔符", "例如：-"), textField("operation-new-columns", "新字段（逗号分隔）", "地区,渠道"));
  } else if (kind === "merge_columns") {
    grid.append(textField("operation-columns", "来源字段（逗号分隔）", "省,市"), textField("operation-new-column", "新字段", "地区"), textField("operation-separator", "连接符", "/"));
  } else if (kind === "calculate") {
    grid.append(textField("operation-new-column", "新字段", "利润"), fieldSelect("operation-left", "左侧字段"), staticSelect("operation-calc-operator", "运算", [["add", "加"], ["subtract", "减"], ["multiply", "乘"], ["divide", "除"]]), fieldSelect("operation-right", "右侧字段"));
  } else if (kind === "group") {
    grid.append(textField("operation-group-by", "分组字段（逗号分隔）", "渠道"), fieldSelect("operation-column", "汇总字段"), staticSelect("operation-aggregation", "汇总方式", [["sum", "合计"], ["mean", "平均"], ["min", "最小"], ["max", "最大"], ["count", "计数"], ["nunique", "去重计数"]]), textField("operation-output-column", "结果字段", "销售合计"));
  } else if (kind === "join") {
    const tables = activeWorkspace?.tables || [];
    grid.append(staticSelect("operation-right-table", "右侧数据表", tables.map((table) => [table.id, table.name])), textField("operation-left-on", "左表关联字段（逗号分隔）", "订单号"), textField("operation-right-on", "右表关联字段（逗号分隔）", "订单号"), staticSelect("operation-join-how", "关联方式", [["left", "保留左表全部"], ["inner", "仅保留匹配"], ["outer", "保留两侧全部"], ["right", "保留右表全部"]]));
  }
  operationFields.append(grid);
}

function csvValues(id) { return (document.querySelector(`#${id}`)?.value || "").split(",").map((item) => item.trim()).filter(Boolean); }
function fieldValue(id) { return document.querySelector(`#${id}`)?.value || ""; }

function collectOperation() {
  const kind = operationType.value;
  if (["trim", "normalize_empty", "drop_duplicates", "select_columns", "reorder_columns"].includes(kind)) return { type: kind, columns: csvValues("operation-columns") };
  if (kind === "rename_columns") {
    const mapping = {};
    csvValues("operation-mapping").forEach((entry) => { const [left, ...right] = entry.split("="); if (left?.trim() && right.join("=").trim()) mapping[left.trim()] = right.join("=").trim(); });
    return { type: kind, mapping };
  }
  if (kind === "convert_type") return { type: kind, column: fieldValue("operation-column"), targetType: fieldValue("operation-target-type") };
  if (kind === "filter") return { type: kind, column: fieldValue("operation-column"), operator: fieldValue("operation-operator"), value: fieldValue("operation-value") };
  if (kind === "sort") return { type: kind, columns: [{ column: fieldValue("operation-column"), ascending: fieldValue("operation-direction") === "asc" }] };
  if (kind === "split_column") return { type: kind, column: fieldValue("operation-column"), separator: fieldValue("operation-separator"), newColumns: csvValues("operation-new-columns") };
  if (kind === "merge_columns") return { type: kind, columns: csvValues("operation-columns"), newColumn: fieldValue("operation-new-column"), separator: fieldValue("operation-separator") };
  if (kind === "calculate") return { type: kind, newColumn: fieldValue("operation-new-column"), left: { column: fieldValue("operation-left") }, operator: fieldValue("operation-calc-operator"), right: { column: fieldValue("operation-right") } };
  if (kind === "group") return { type: kind, by: csvValues("operation-group-by"), aggregations: [{ column: fieldValue("operation-column"), operation: fieldValue("operation-aggregation"), outputColumn: fieldValue("operation-output-column") }] };
  if (kind === "join") return { type: kind, rightTableId: fieldValue("operation-right-table"), leftOn: csvValues("operation-left-on"), rightOn: csvValues("operation-right-on"), how: fieldValue("operation-join-how") };
  throw new Error("无法识别处理步骤");
}

function renderWorkspace(workspace) {
  activeWorkspace = workspace;
  activeWorkspacePreview = workspace?.preview || null;
  workspaceOperations = workspace?.plan?.operations ? workspace.plan.operations.map((item) => ({ ...item })) : [];
  workspaceStatus.textContent = workspace ? (WORKSPACE_STATUS_LABELS[workspace.status] || workspace.status) : "尚未创建";
  document.querySelector("#delete-workspace-button").hidden = !workspace;
  workspaceName.value = workspace?.name || "";
  workspaceInstructions.value = workspace?.instructions || workspace?.plan?.instructions || "";
  workspaceCombineMode.value = workspace?.plan?.combineMode || "first";
  document.querySelector("#upload-workspace-files-button").disabled = !workspace;
  executeWorkspaceButton.disabled = !activeWorkspacePreview || workspace?.status === "completed";
  const exports = workspace?.execution?.exports || {};
  downloadWorkspaceCsv.hidden = !exports.csv;
  downloadWorkspaceXlsx.hidden = !exports.xlsx;
  downloadWorkspaceLinked.hidden = !exports.linked;
  oneClickResult.hidden = workspace?.status !== "completed";
  if (workspace?.status === "completed") {
    if (exports.csv) downloadWorkspaceCsv.href = `/api/workspaces/${workspace.id}/exports/csv`;
    if (exports.xlsx) downloadWorkspaceXlsx.href = `/api/workspaces/${workspace.id}/exports/xlsx`;
    if (exports.linked) downloadWorkspaceLinked.href = `/api/workspaces/${workspace.id}/exports/linked`;
    oneClickResultSummary.textContent = `${workspace.execution.profile.rowCount} 行 · ${workspace.execution.profile.columnCount} 个字段`;
  }
  if (workspace?.pendingResolution) renderWorkspaceResolution(workspace.pendingResolution);
  else workspaceResolution.hidden = true;
  if (workspaceResultEmpty) workspaceResultEmpty.hidden = workspace?.status === "completed";
  renderWorkspaceFileSummary();
  syncWorkspaceProgress();
  renderWorkspaceTables();
  renderOperations();
  renderOperationFields();
}

function setWorkspaceProgress(step) {
  Array.from(workspaceProgress.children).forEach((item, index) => {
    item.classList.toggle("is-done", index < step);
    item.classList.toggle("is-active", index === step);
  });
}

function selectedWorkspaceFiles() {
  return stagedWorkspaceFiles.length ? stagedWorkspaceFiles : Array.from(workspaceFiles.files || []);
}

function renderWorkspaceFileSummary() {
  const selectedFiles = selectedWorkspaceFiles();
  const savedFiles = activeWorkspace?.datasets || [];
  const files = selectedFiles.length ? selectedFiles : savedFiles;
  const values = workspaceFileSummary.querySelectorAll("dd");
  const filenames = files.map((file) => file.name || file.filename).filter(Boolean);
  workspaceFileCount.textContent = files.length ? `${files.length} 个文件` : "未上传";
  values[0].textContent = filenames.length ? filenames.join("、") : "-";
  values[1].textContent = files.length ? String(files.length) : "-";
  values[2].textContent = selectedFiles.length ? "已选择，等待生成" : savedFiles.length ? "已安全读取" : "等待添加文件";
}

function syncWorkspaceProgress() {
  const hasFile = selectedWorkspaceFiles().length > 0 || Boolean(activeWorkspace?.datasets?.length);
  const hasInstructions = Boolean(workspaceInstructions.value.trim());
  const hasNewSelection = selectedWorkspaceFiles().length > 0;
  setWorkspaceProgress(!hasNewSelection && activeWorkspace?.status === "completed" ? 3 : hasFile ? (hasInstructions ? 2 : 1) : 0);
}

workspaceFiles.addEventListener("change", () => {
  stagedWorkspaceFiles = Array.from(workspaceFiles.files || []);
  renderWorkspaceFileSummary();
  syncWorkspaceProgress();
});

workspaceInstructions.addEventListener("input", syncWorkspaceProgress);

workspaceDropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  workspaceDropZone.classList.add("is-dragging");
});
workspaceDropZone.addEventListener("dragleave", () => workspaceDropZone.classList.remove("is-dragging"));
workspaceDropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  workspaceDropZone.classList.remove("is-dragging");
  stagedWorkspaceFiles = Array.from(event.dataTransfer?.files || []);
  renderWorkspaceFileSummary();
  syncWorkspaceProgress();
});

document.querySelectorAll("[data-workspace-example]").forEach((button) => {
  button.addEventListener("click", () => {
    workspaceInstructions.value = button.dataset.workspaceExample;
    workspaceInstructions.focus();
    syncWorkspaceProgress();
  });
});

function selectedOutputModes() {
  return [outputLinked.checked ? "linked" : null, outputStandalone.checked ? "standalone" : null].filter(Boolean);
}

function renderWorkspaceResolution(resolution) {
  workspaceResolution.replaceChildren();
  workspaceResolution.hidden = false;
  const title = document.createElement("strong");
  title.textContent = resolution.title;
  const reason = document.createElement("p");
  reason.textContent = resolution.reason;
  workspaceResolution.append(title, reason);
  if (resolution.type === "information") {
    const open = document.createElement("button");
    open.type = "button";
    open.textContent = "打开高级设置";
    open.addEventListener("click", () => {
      document.querySelector(".advanced-workspace").open = true;
      switchWorkspaceStep("plan");
    });
    workspaceResolution.append(open);
    return;
  }
  const choices = document.createElement("div");
  choices.className = "resolution-choices";
  resolution.choices.forEach((choice) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = choice.label;
    button.addEventListener("click", async () => {
      pendingAutoRunDecisions = { ...(resolution.decisions || pendingAutoRunDecisions), [resolution.field]: choice.value };
      await runActiveWorkspace(pendingAutoRunDecisions);
    });
    choices.append(button);
  });
  workspaceResolution.append(choices);
}

async function runActiveWorkspace(decisions = {}) {
  setWorkspaceProgress(2);
  const result = await request(`/api/workspaces/${activeWorkspace.id}/auto-run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instructions: workspaceInstructions.value.trim(), outputModes: selectedOutputModes(), decisions }),
  });
  if (result.status === "needs_input") {
    activeWorkspace = result.workspace;
    renderWorkspace(result.workspace);
    renderWorkspaceResolution(result.resolution);
    setWorkspaceProgress(2);
    showMessage(workspaceMessage, "为了避免生成错误结果，请完成上方这一项选择。", false);
    return;
  }
  pendingAutoRunDecisions = {};
  stagedWorkspaceFiles = [];
  workspaceFiles.value = "";
  await refreshWorkspaces(result.workspace.id);
  setWorkspaceProgress(3);
  setAppView("results-view");
  showMessage(workspaceMessage, "结果已生成。原始文件未被覆盖，处理记录已保存。", false);
}

runWorkspaceButton.addEventListener("click", async () => {
  const instructions = workspaceInstructions.value.trim();
  const files = selectedWorkspaceFiles();
  if (!instructions) return showMessage(workspaceMessage, "请先说明最终想得到什么结果。", true);
  if (!selectedOutputModes().length) return showMessage(workspaceMessage, "请至少选择一种结果形式。", true);
  if (!files.length && !activeWorkspace?.datasets?.length) return showMessage(workspaceMessage, "请先上传原始文件。", true);
  runWorkspaceButton.disabled = true;
  runWorkspaceButton.textContent = "正在生成…";
  oneClickResult.hidden = true;
  workspaceResolution.hidden = true;
  setWorkspaceProgress(2);
  try {
    if (files.length) {
      const baseName = files[0].name.replace(/\.[^.]+$/, "");
      const workspace = await request("/api/workspaces", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: `${baseName} · 一键处理`, instructions }),
      });
      activeWorkspace = workspace;
      for (const file of files) {
        const content = arrayBufferBase64(await file.arrayBuffer());
        activeWorkspace = await request(`/api/workspaces/${workspace.id}/datasets`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename: file.name, content }),
        });
      }
    }
    setWorkspaceProgress(2);
    await runActiveWorkspace({});
  } catch (error) {
    syncWorkspaceProgress();
    showMessage(workspaceMessage, error.message, true);
  } finally {
    runWorkspaceButton.disabled = false;
    runWorkspaceButton.textContent = "一键生成结果";
  }
});

async function refreshWorkspaces(selectedId = activeWorkspace?.id) {
  const response = await request("/api/workspaces");
  workspaceSelector.replaceChildren();
  appendOption(workspaceSelector, "", "新建数据任务");
  response.workspaces.forEach((workspace) => appendOption(workspaceSelector, workspace.id, `${workspace.name} · ${WORKSPACE_STATUS_LABELS[workspace.status] || workspace.status}`, workspace.id === selectedId));
  if (selectedId) {
    const workspace = await request(`/api/workspaces/${selectedId}`);
    renderWorkspace(workspace);
  } else {
    renderWorkspace(null);
  }
}

function arrayBufferBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 32768) binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
  return btoa(binary);
}

document.querySelector("#create-workspace-button").addEventListener("click", async () => {
  try {
    const workspace = await request("/api/workspaces", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: workspaceName.value, instructions: workspaceInstructions.value }) });
    await refreshWorkspaces(workspace.id);
    showMessage(workspaceMessage, "数据任务已建立，请上传原始文件。", false);
  } catch (error) { showMessage(workspaceMessage, error.message, true); }
});

workspaceSelector.addEventListener("change", async () => {
  try { await refreshWorkspaces(workspaceSelector.value || null); } catch (error) { showMessage(workspaceMessage, error.message, true); }
});

document.querySelector("#delete-workspace-button").addEventListener("click", async () => {
  if (!activeWorkspace) return;
  const confirmed = window.confirm(`确认删除数据任务“${activeWorkspace.name}”？\n\n该任务的上传文件、派生结果和页面记录会一并删除，无法从工作台恢复。`);
  if (!confirmed) return;
  try {
    await request(`/api/workspaces/${activeWorkspace.id}`, { method: "DELETE" });
    await refreshWorkspaces(null);
    switchWorkspaceStep("source");
    showMessage(workspaceMessage, "数据任务及其本地文件已删除。", false);
  } catch (error) { showMessage(workspaceMessage, error.message, true); }
});

document.querySelector("#upload-workspace-files-button").addEventListener("click", async () => {
  if (!activeWorkspace) return showMessage(workspaceMessage, "请先建立数据任务。", true);
  const files = selectedWorkspaceFiles();
  if (!files.length) return showMessage(workspaceMessage, "请选择需要上传的数据文件。", true);
  try {
    let workspace = activeWorkspace;
    for (const file of files) {
      const content = arrayBufferBase64(await file.arrayBuffer());
      workspace = await request(`/api/workspaces/${workspace.id}/datasets`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ filename: file.name, content }) });
    }
    await refreshWorkspaces(workspace.id);
    switchWorkspaceStep("plan");
    showMessage(workspaceMessage, `已安全读取 ${files.length} 个文件，原始文件保持只读。`, false);
  } catch (error) { showMessage(workspaceMessage, error.message, true); }
});

workspaceSourceTables.addEventListener("change", renderOperationFields);
operationType.addEventListener("change", renderOperationFields);
document.querySelector("#add-operation-button").addEventListener("click", () => {
  try { workspaceOperations.push(collectOperation()); renderOperations(); showMessage(workspaceMessage, "处理步骤已加入草案，保存后才能预览。", false); } catch (error) { showMessage(workspaceMessage, error.message, true); }
});

operationList.addEventListener("click", (event) => {
  const remove = event.target.closest("[data-operation-delete]");
  const move = event.target.closest("[data-operation-move]");
  if (remove) workspaceOperations.splice(Number(remove.dataset.operationDelete), 1);
  if (move) {
    const index = Number(move.dataset.operationIndex), target = index + Number(move.dataset.operationMove);
    if (target >= 0 && target < workspaceOperations.length) [workspaceOperations[index], workspaceOperations[target]] = [workspaceOperations[target], workspaceOperations[index]];
  }
  renderOperations();
});

document.querySelector("#suggest-workspace-plan-button").addEventListener("click", async () => {
  if (!activeWorkspace) return showMessage(workspaceMessage, "请先建立任务并上传数据。", true);
  try {
    const suggestion = await request(`/api/workspaces/${activeWorkspace.id}/suggest-plan`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ instructions: workspaceInstructions.value }) });
    workspaceOperations = suggestion.operations;
    Array.from(workspaceSourceTables.options).forEach((option) => { option.selected = suggestion.sourceTableIds.includes(option.value); });
    workspaceCombineMode.value = suggestion.combineMode;
    renderOperations();
    showMessage(workspaceMessage, suggestion.warnings.join(" "), false);
  } catch (error) { showMessage(workspaceMessage, error.message, true); }
});

document.querySelector("#save-workspace-plan-button").addEventListener("click", async () => {
  if (!activeWorkspace) return showMessage(workspaceMessage, "请先建立任务并上传数据。", true);
  const sourceTableIds = Array.from(workspaceSourceTables.selectedOptions).map((option) => option.value);
  try {
    const workspace = await request(`/api/workspaces/${activeWorkspace.id}/plan`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ instructions: workspaceInstructions.value, sourceTableIds, combineMode: workspaceCombineMode.value, operations: workspaceOperations }) });
    renderWorkspace(workspace);
    switchWorkspaceStep("preview");
    showMessage(workspaceMessage, "处理计划已保存。请先生成并检查前后预览。", false);
  } catch (error) { showMessage(workspaceMessage, error.message, true); }
});

function addPreviewMetric(container, label, value) {
  const item = document.createElement("div"), small = document.createElement("small"), strong = document.createElement("strong");
  small.textContent = label; strong.textContent = value; item.append(small, strong); container.append(item);
}

function renderPreview(preview) {
  workspacePreviewSummary.replaceChildren();
  addPreviewMetric(workspacePreviewSummary, "原始行数", preview.source.profile.rowCount);
  addPreviewMetric(workspacePreviewSummary, "结果行数", preview.result.profile.rowCount);
  addPreviewMetric(workspacePreviewSummary, "处理步骤", preview.audit.length);
  renderSimpleTable(workspacePreviewBefore, preview.source.rows);
  renderSimpleTable(workspacePreviewAfter, preview.result.rows);
  workspacePreviewAudit.textContent = preview.audit.map((item) => `第${item.step}步 ${OPERATION_LABELS[item.type] || item.type}：${item.beforeRows}→${item.afterRows}行，${item.beforeColumns}→${item.afterColumns}列`).join("；");
  if (preview.warnings.length) workspacePreviewAudit.textContent += `。风险：${preview.warnings.join("；")}`;
  executeWorkspaceButton.disabled = false;
}

document.querySelector("#preview-workspace-button").addEventListener("click", async () => {
  if (!activeWorkspace) return showMessage(workspaceMessage, "请先保存处理计划。", true);
  try {
    activeWorkspacePreview = await request(`/api/workspaces/${activeWorkspace.id}/preview`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    renderPreview(activeWorkspacePreview);
    activeWorkspace.status = "preview_ready";
    workspaceStatus.textContent = WORKSPACE_STATUS_LABELS.preview_ready;
    showMessage(workspaceMessage, "预览已生成。请逐项核对后再确认执行。", false);
  } catch (error) { showMessage(workspaceMessage, error.message, true); }
});

document.querySelector("#execute-workspace-button").addEventListener("click", async () => {
  if (!activeWorkspacePreview) return showMessage(workspaceMessage, "请先生成有效预览。", true);
  const confirmed = window.confirm("确认按当前预览执行并生成派生结果？\n\n原始文件不会被覆盖。");
  if (!confirmed) return;
  try {
    const execution = await request(`/api/workspaces/${activeWorkspace.id}/execute`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ previewId: activeWorkspacePreview.id }) });
    workspaceExecutionSummary.replaceChildren();
    addPreviewMetric(workspaceExecutionSummary, "结果行数", execution.profile.rowCount);
    addPreviewMetric(workspaceExecutionSummary, "结果字段", execution.profile.columnCount);
    addPreviewMetric(workspaceExecutionSummary, "完成时间", formatTime(execution.completedAt));
    await refreshWorkspaces(activeWorkspace.id);
    switchWorkspaceStep("export");
    showMessage(workspaceMessage, "执行完成，可下载 CSV 或 Excel。原始文件校验保持一致。", false);
  } catch (error) { showMessage(workspaceMessage, error.message, true); }
});

refreshWorkspaces().catch((error) => showMessage(workspaceMessage, error.message, true));
renderOperationFields();

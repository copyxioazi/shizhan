/* 简易合同审批审查控制台：原生 JS，无构建依赖。 */
(() => {
  "use strict";

  const API_BASE = (() => {
    const override = new URLSearchParams(location.search).get("api");
    if (override) return override.replace(/\/+$/, "");
    if (location.protocol === "file:") return "http://127.0.0.1:8000";
    if (location.pathname.startsWith("/ui")) return location.origin;
    return `${location.protocol}//${location.hostname}:8000`;
  })();

  const TASK_LABELS = {
    pending: "待处理",
    parsing: "解析中",
    reviewing: "审查中",
    blocked: "已阻塞",
    done: "已完成",
  };
  const WRITE_LABELS = {
    not_written: "未回写",
    writing: "回写中",
    success: "已回写",
    failed: "回写失败",
  };
  const STAGE_LABELS = {
    idle: "空闲",
    queued: "排队",
    download: "下载",
    parse: "解析",
    review: "审查",
    save: "保存",
    write: "回写",
    done: "完成",
  };
  const DOWNLOAD_LABELS = {
    pending: "待下载",
    downloading: "下载中",
    success: "已下载",
    failed: "下载失败",
    missing: "附件缺失",
    not_downloaded: "未下载",
  };
  const RISK_LABELS = { low: "低风险", medium: "中风险", high: "高风险" };
  const FIELD_LABELS = {
    contract_title: "合同标题",
    contract_no: "合同编号",
    party_a: "甲方",
    party_b: "乙方",
    amount: "合同金额",
    currency: "币种",
    effective_date: "生效日期",
    expiry_date: "到期日期",
  };
  const CLAUSE_LABELS = {
    payment: "付款",
    delivery: "交付",
    acceptance: "验收",
    breach: "违约责任",
    confidentiality: "保密",
    data: "数据",
    intellectual_property: "知识产权",
    dispute_resolution: "争议解决",
  };

  const state = {
    tasks: [],
    selectedId: null,
    detail: null,
    reviewId: null,
    polling: new Set(),
  };

  const $ = (selector) => document.querySelector(selector);

  function esc(value) {
    const node = document.createElement("div");
    node.textContent = value == null ? "" : String(value);
    return node.innerHTML;
  }

  function tag(text, cls) {
    const safe = String(cls || "").replace(/[^a-z0-9_-]/gi, "");
    return `<span class="tag ${safe}">${esc(text)}</span>`;
  }

  function size(bytes) {
    const value = Number(bytes || 0);
    if (!value) return "-";
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }

  function time(value) {
    if (!value) return "-";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { hour12: false });
  }

  let messageTimer = null;
  function message(text, type = "") {
    const node = $("#message");
    node.textContent = text;
    node.className = `message ${type}`;
    clearTimeout(messageTimer);
    messageTimer = setTimeout(() => node.classList.add("hidden"), 4500);
  }

  function errorText(error) {
    return error.code ? `${error.code}: ${error.message}` : error.message;
  }

  async function api(path, options = {}) {
    const url = new URL(path, API_BASE);
    const init = { method: options.method || "GET", headers: {} };
    if (options.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }

    let response;
    try {
      response = await fetch(url, init);
    } catch (error) {
      throw Object.assign(new Error(`无法连接 ${API_BASE}`), { code: "NETWORK_ERROR" });
    }

    const text = await response.text();
    let payload = null;
    if (text) {
      try { payload = JSON.parse(text); } catch { payload = null; }
    }
    if (!response.ok || (payload && payload.success === false)) {
      const info = (payload && payload.error) || {};
      throw Object.assign(new Error(info.message || response.statusText || "请求失败"), {
        code: info.code || `HTTP_${response.status}`,
        details: info.details || {},
      });
    }
    return payload && Object.prototype.hasOwnProperty.call(payload, "data") ? payload.data : payload;
  }

  async function loadHealth() {
    const node = $("#health");
    node.title = `API: ${API_BASE}`;
    try {
      await api("/health");
      node.textContent = "服务正常";
      node.className = "tag ok";
    } catch (error) {
      node.textContent = "服务不可达";
      node.className = "tag err";
      node.title = `无法连接 ${API_BASE}`;
    }
  }

  async function loadTasks() {
    try {
      const tasks = await api("/api/tasks");
      state.tasks = Array.isArray(tasks) ? tasks : [];
      renderTasks();
      $("#taskCount").textContent = `共 ${state.tasks.length} 条`;
    } catch (error) {
      message(`加载任务失败：${errorText(error)}`, "err");
    }
  }

  function actionButtons(task) {
    const buttons = [
      `<button class="btn small" data-view="${task.id}" type="button">查看</button>`,
    ];
    if (task.task_status === "blocked") {
      buttons.push(`<button class="btn small danger" data-retry="${task.id}" type="button">重试</button>`);
    } else if (task.task_status === "pending" && task.stage !== "queued") {
      buttons.push(`<button class="btn small primary" data-review="${task.id}" type="button">一键审查</button>`);
    } else if (task.task_status === "done") {
      buttons.push(`<button class="btn small" type="button" disabled>已完成</button>`);
    } else {
      buttons.push(`<button class="btn small" type="button" disabled>处理中</button>`);
    }
    return buttons.join(" ");
  }

  function renderTasks() {
    const body = $("#taskRows");
    if (!state.tasks.length) {
      body.innerHTML = '<tr><td colspan="7" class="empty">暂无任务，点击「拉取待办」。</td></tr>';
      return;
    }
    body.innerHTML = state.tasks
      .map(
        (task) => `
        <tr class="${task.id === state.selectedId ? "selected" : ""}">
          <td>${task.id}</td>
          <td class="mono">${esc(task.approval_code)}</td>
          <td>${esc(task.approval_title)}</td>
          <td>${tag(TASK_LABELS[task.task_status] || task.task_status, `st-${task.task_status}`)}</td>
          <td>${tag(WRITE_LABELS[task.write_status] || task.write_status, `wr-${task.write_status}`)}</td>
          <td>${esc(STAGE_LABELS[task.stage] || task.stage || "-")}</td>
          <td>${actionButtons(task)}</td>
        </tr>`
      )
      .join("");
  }

  async function pull() {
    const button = $("#pullBtn");
    button.disabled = true;
    try {
      const items = await api("/api/tools/list_pending_contract_approvals?limit=50", { method: "POST" });
      const list = Array.isArray(items) ? items : [];
      const created = list.filter((item) => item.created).length;
      message(`拉取完成：新增 ${created} 条，已存在 ${list.length - created} 条。`, "ok");
      await loadTasks();
    } catch (error) {
      message(`拉取失败：${errorText(error)}`, "err");
    } finally {
      button.disabled = false;
    }
  }

  async function openDetail(caseId) {
    const task = state.tasks.find((item) => item.id === Number(caseId));
    if (!task) return;
    const same = state.selectedId === task.id;
    state.selectedId = task.id;
    if (!same) $("#contentCard").classList.add("hidden");
    renderTasks();
    $("#detailCard").classList.remove("hidden");
    $("#reviewCard").classList.remove("hidden");
    $("#detailCode").textContent = task.approval_code;
    $("#detailInfo").innerHTML = '<span class="muted">加载中…</span>';
    $("#attachmentRows").innerHTML = "";
    try {
      state.detail = await api(`/api/tools/get_contract_approval/${encodeURIComponent(task.approval_code)}`);
      renderDetail();
      $("#detailCard").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      message(`加载详情失败：${errorText(error)}`, "err");
    }
  }

  async function refreshDetail() {
    if (!state.detail) return;
    const contentOpen = !$("#contentCard").classList.contains("hidden");
    await openDetail(state.detail.case_id);
    if (contentOpen) await loadContent();
  }

  function infoItem(label, value) {
    return `<div><span>${esc(label)}</span><span>${value}</span></div>`;
  }

  function renderDetail() {
    const detail = state.detail;
    if (!detail) return;
    $("#detailCode").textContent = detail.approval_code;

    const formData = detail.form_data || {};
    $("#detailInfo").innerHTML = [
      infoItem("申请人", esc(detail.applicant_name || "-")),
      infoItem("申请时间", esc(time(detail.applied_at))),
      infoItem("上游状态", esc(detail.upstream_status || "-")),
      infoItem("合同类型", esc(formData.contract_type || "-")),
      infoItem("相对方", esc(formData.counterparty || "-")),
      infoItem("任务状态", tag(TASK_LABELS[detail.task_status] || detail.task_status, `st-${detail.task_status}`)),
      infoItem("回写状态", tag(WRITE_LABELS[detail.write_status] || detail.write_status, `wr-${detail.write_status}`)),
      infoItem("阶段", esc(STAGE_LABELS[detail.stage] || detail.stage || "-")),
      infoItem("重试次数", esc(detail.retry_count ?? 0)),
      infoItem("错误", esc(detail.last_error ? `${detail.last_error_code || ""} ${detail.last_error}` : "-")),
    ].join("");

    const attachments = detail.attachments || [];
    $("#attachmentRows").innerHTML = attachments.length
      ? attachments
          .map(
            (item, index) => `
            <tr>
              <td>${item.attachment_id}</td>
              <td>
                ${esc(item.file_name)}
                ${item.is_primary ? '<span class="primary-mark">主</span>' : ""}
              </td>
              <td>${size(item.file_size)}</td>
              <td>${tag(
                DOWNLOAD_LABELS[item.download_status] || item.download_status,
                item.download_status === "success"
                  ? "ok"
                  : item.download_status === "missing" || item.download_status === "failed"
                  ? "err"
                  : ""
              )}</td>
              <td>
                <button class="btn small" data-download="${index}" type="button">
                  ${item.download_status === "success" ? "重新下载" : "下载"}
                </button>
              </td>
            </tr>`
          )
          .join("")
      : '<tr><td colspan="5" class="empty">没有附件</td></tr>';

    renderParse(detail.parse);
    renderReview(detail.review);
    prefillReview(detail.review);
  }

  function renderParse(parse) {
    if (!parse) {
      $("#parseInfo").innerHTML = '<span class="muted">未解析</span>';
      return;
    }
    const warnings = (parse.warnings || []).map((item) => `<li>${esc(item)}</li>`).join("");
    $("#parseInfo").innerHTML = `
      <div>${tag(parse.parse_status, parse.parse_status === "success" ? "ok" : "err")}
        ${parse.ocr_used ? " OCR" : ""}</div>
      <div class="muted">页数 ${esc(parse.page_count ?? "-")} · 文本 ${esc(parse.text_length ?? "-")} 字</div>
      ${warnings ? `<ul class="muted">${warnings}</ul>` : ""}
    `;
  }

  function renderReview(review) {
    if (!review) {
      $("#reviewInfo").innerHTML = '<span class="muted">未保存</span>';
      return;
    }
    const points = (review.focus_points || []).map((item) => `<li>${esc(item)}</li>`).join("");
    $("#reviewInfo").innerHTML = `
      <div>${tag(RISK_LABELS[review.overall_risk_level] || review.overall_risk_level, `risk-${review.overall_risk_level}`)}</div>
      <div class="muted">${esc(review.summary_text)}</div>
      ${points ? `<ul class="muted">${points}</ul>` : ""}
    `;
  }

  function positionText(position) {
    if (!position) return "-";
    if (position.type === "pdf") {
      return `PDF 第 ${position.page} 页，字符 ${position.char_start}-${position.char_end}`;
    }
    if (position.type === "docx") {
      return `DOCX 段落 ${position.paragraph_index}，字符 ${position.char_start}-${position.char_end}`;
    }
    if (position.type === "ocr") {
      return `OCR 第 ${position.page} 页第 ${position.line} 行`;
    }
    return "文档级";
  }

  function statusTag(status) {
    return tag(
      status === "found" ? "已找到" : status === "invalid" ? "无效" : "缺失",
      status === "found" ? "ok" : status === "invalid" ? "err" : ""
    );
  }

  async function loadContent() {
    if (!state.detail) {
      message("详情仍在加载，请稍候", "");
      return;
    }
    $("#contentCard").classList.remove("hidden");
    $("#contractText").textContent = "加载中…";
    try {
      const data = await api(`/api/tasks/${state.detail.case_id}/content`);
      renderContent(data);
    } catch (error) {
      $("#contractText").textContent = `加载失败：${errorText(error)}`;
      message(`加载合同内容失败：${errorText(error)}`, "err");
    }
  }

  function renderContent(data) {
    $("#contentFile").textContent = data.file_name ? `· ${data.file_name}` : "";
    const meta = [];
    if (data.parse_status) {
      meta.push(
        tag(
          data.parse_status,
          data.parse_status === "success" ? "ok" : data.parse_status === "partial" ? "" : "err"
        )
      );
      meta.push(`页数 ${data.page_count ?? "-"}`);
      meta.push(`文本 ${data.text_length ?? 0} 字`);
      meta.push(data.ocr_used ? "OCR" : "文本层");
    } else {
      meta.push("尚未解析，请先点击「解析」");
    }
    if (data.parse_error) meta.push(esc(data.parse_error));
    if ((data.warnings || []).length) meta.push(esc(data.warnings.join("；")));
    $("#contentMeta").innerHTML = meta.join(" · ");
    $("#contractText").textContent = data.text_content || "暂无解析文本。";

    const basic = data.basic_info || {};
    $("#contentBasic").innerHTML = Object.entries(FIELD_LABELS)
      .map(([key, label]) => {
        const item = basic[key] || {};
        const status = item.status || "missing";
        return `<div class="field-row"><b>${esc(label)}</b><span>${esc(
          item.value ?? "-"
        )} ${statusTag(status)}</span></div>`;
      })
      .join("");

    const clauses = data.clause_info || {};
    $("#contentClauses").innerHTML = Object.entries(CLAUSE_LABELS)
      .map(([key, label]) => {
        const item = clauses[key] || {};
        const status = item.status || "missing";
        return `<div class="field-row"><b>${esc(label)}</b><span>${statusTag(status)}${
          item.value ? ` ${esc(item.value)}` : ""
        }</span></div>`;
      })
      .join("");

    const hits = data.hits || [];
    $("#contentHits").innerHTML = hits.length
      ? hits
          .map(
            (hit) => `
            <div class="hit-item">
              <div>${tag(
                RISK_LABELS[hit.risk_level] || hit.risk_level,
                `risk-${hit.risk_level}`
              )} ${esc(hit.rule_name)}</div>
              <div class="muted">${esc(hit.evidence_text)}</div>
              <div class="muted">${esc(positionText(hit.position))}</div>
            </div>`
          )
          .join("")
      : '<span class="muted">暂无规则命中</span>';
  }

  function prefillReview(review) {
    const form = $("#reviewForm");
    const badge = $("#reviewBadge");
    if (review) {
      form.elements.risk.value = review.overall_risk_level || "low";
      form.elements.summary.value = review.summary_text || "";
      form.elements.focus.value = (review.focus_points || []).join("\n");
      form.elements.comment.value = review.comment_text || "";
      state.reviewId = review.review_id;
      badge.textContent = `review_id=${review.review_id}`;
      $("#writeBtn").disabled = false;
    } else {
      form.reset();
      form.elements.risk.value = "low";
      state.reviewId = null;
      badge.textContent = "未保存";
      $("#writeBtn").disabled = true;
    }
  }

  async function downloadAttachment(index) {
    const item = state.detail && state.detail.attachments ? state.detail.attachments[index] : null;
    if (!item) return;
    try {
      const result = await api("/api/tools/download_contract_attachment", {
        method: "POST",
        body: {
          instance_id: state.detail.approval_code,
          attachment_id: item.attachment_id,
          file_name: item.file_name,
        },
      });
      message(`下载成功：${result.file_path}`, "ok");
    } catch (error) {
      message(`下载失败：${errorText(error)}`, "err");
    }
    await refreshDetail();
    await loadTasks();
  }

  async function parseDocument() {
    const attachments = state.detail ? state.detail.attachments || [] : [];
    const target = attachments.find((item) => item.is_primary) || attachments.find((item) => item.document_id);
    if (!target) {
      message("请先下载附件", "err");
      return;
    }
    try {
      const result = await api("/api/tools/parse_contract_document", {
        method: "POST",
        body: { document_id: target.document_id },
      });
      message(`解析完成：${result.parse_status}`, "ok");
    } catch (error) {
      message(`解析失败：${errorText(error)}`, "err");
    }
    await refreshDetail();
    await loadTasks();
  }

  async function runRules() {
    if (!state.detail) return;
    try {
      const result = await api("/api/tools/run_contract_rules", {
        method: "POST",
        body: { case_id: state.detail.case_id },
      });
      message(`规则审查完成：${result.hit_count} 条命中，${RISK_LABELS[result.overall_risk_level]}`, "ok");
      await refreshDetail();
      await loadTasks();
      renderRuleHits(result);
    } catch (error) {
      message(`规则审查失败：${errorText(error)}`, "err");
    }
  }

  function renderRuleHits(result) {
    const hits = (result.hits || [])
      .map(
        (hit) =>
          `<li>${esc(hit.rule_name)}（${esc(RISK_LABELS[hit.risk_level] || hit.risk_level)}）<br>
           <span class="muted">${esc(hit.evidence_text)}</span></li>`
      )
      .join("");
    $("#reviewInfo").innerHTML = `
      <div>${tag(RISK_LABELS[result.overall_risk_level] || result.overall_risk_level, `risk-${result.overall_risk_level}`)}
        ${result.hit_count} 条命中</div>
      ${hits ? `<ul class="muted">${hits}</ul>` : '<div class="muted">无规则命中</div>'}
    `;
  }

  async function saveReview(event) {
    event.preventDefault();
    if (!state.detail) return;
    const form = $("#reviewForm");
    const focus = form.elements.focus.value
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean)
      .slice(0, 8);
    const body = {
      case_id: state.detail.case_id,
      overall_risk_level: form.elements.risk.value,
      summary_text: form.elements.summary.value.trim(),
      focus_points_json: focus,
      comment_text: form.elements.comment.value.trim(),
    };
    if (!body.summary_text || !body.comment_text) {
      message("摘要和评论正文不能为空", "err");
      return;
    }
    try {
      const result = await api("/api/tools/save_review_result", { method: "POST", body });
      state.reviewId = result.review_id;
      $("#reviewBadge").textContent = `review_id=${result.review_id}`;
      $("#writeBtn").disabled = false;
      message(`保存成功：review_id=${result.review_id}`, "ok");
      await refreshDetail();
      await loadTasks();
    } catch (error) {
      message(`保存失败：${errorText(error)}`, "err");
    }
  }

  async function writeComment() {
    if (!state.detail || !state.reviewId) {
      message("请先保存审查结果", "err");
      return;
    }
    try {
      const result = await api("/api/tools/write_approval_comment", {
        method: "POST",
        body: { instance_id: state.detail.approval_code, review_id: state.reviewId },
      });
      message(
        result.short_circuited ? "已回写（本地短路）" : result.duplicate ? "已回写（上游已存在）" : "回写成功",
        "ok"
      );
    } catch (error) {
      message(`回写失败：${errorText(error)}`, "err");
    }
    await refreshDetail();
    await loadTasks();
  }

  function fillComment() {
    const form = $("#reviewForm");
    const risk = RISK_LABELS[form.elements.risk.value] || "未知";
    const summary = form.elements.summary.value.trim() || "请填写审查摘要";
    const points = form.elements.focus.value
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean);
    const lines = [`【合同审查结论】整体风险：${risk}`, summary];
    if (points.length) {
      lines.push("重点关注：");
      points.forEach((point, index) => lines.push(`${index + 1}. ${point}`));
    }
    form.elements.comment.value = lines.join("\n");
  }

  async function startReview(caseId, retry) {
    const id = Number(caseId);
    try {
      const result = await api(`/api/tasks/${id}/${retry ? "retry" : "full-review"}`, { method: "POST" });
      if (!result.queued) {
        if (result.reason === "blocked_use_retry") message("任务已阻塞，请点击「重试」", "err");
        else if (result.reason === "already_done") message("任务已完成", "ok");
        else if (result.reason !== "already_in_progress") message(`未入队：${result.reason || "未知"}`, "err");
      } else {
        message(retry ? `重试已入队：从 ${result.resume_stage} 继续` : "一键审查已入队", "ok");
      }
      await loadTasks();
      poll(id);
    } catch (error) {
      message(`提交失败：${errorText(error)}`, "err");
    }
  }

  async function poll(caseId) {
    if (state.polling.has(caseId)) return;
    state.polling.add(caseId);
    const deadline = Date.now() + 180000;
    try {
      while (Date.now() < deadline) {
        const status = await api(`/api/tasks/${caseId}/status`);
        await loadTasks();
        if (status.terminal) {
          // 行状态已更新，避免轮询提示覆盖用户刚触发的操作提示。
          if (state.selectedId === caseId) await refreshDetail();
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
      message(`任务 ${caseId} 轮询超时`, "err");
    } catch (error) {
      message(`轮询失败：${errorText(error)}`, "err");
    } finally {
      state.polling.delete(caseId);
    }
  }

  async function applyFaults() {
    const status = Number($("#faultStatus").value) || 500;
    const boxes = [...document.querySelectorAll("[data-fault]")];
    try {
      for (const box of boxes) {
        await api("/mock-upstream/admin/faults", {
          method: "POST",
          body: { scope: box.dataset.fault, enabled: box.checked, http_status: status },
        });
      }
      message("故障开关已更新", "ok");
    } catch (error) {
      message(`设置失败：${errorText(error)}`, "err");
    }
  }

  async function restoreAttachment() {
    const id = Number($("#restoreId").value);
    if (!id) {
      message("请输入附件 ID", "err");
      return;
    }
    try {
      await api(`/mock-upstream/admin/attachments/${id}/restore`, { method: "POST" });
      message(`附件 ${id} 已恢复`, "ok");
      await refreshDetail();
    } catch (error) {
      message(`恢复失败：${errorText(error)}`, "err");
    }
  }

  async function resetMock() {
    if (!confirm("确认重置 Mock 上游数据？")) return;
    try {
      await api("/mock-upstream/admin/reset", { method: "POST" });
      message("Mock 已重置", "ok");
      await loadTasks();
      await refreshDetail();
    } catch (error) {
      message(`重置失败：${errorText(error)}`, "err");
    }
  }

  function bind() {
    $("#pullBtn").addEventListener("click", pull);
    $("#refreshBtn").addEventListener("click", loadTasks);
    $("#taskRows").addEventListener("click", (event) => {
      const view = event.target.closest("[data-view]");
      if (view) return openDetail(view.dataset.view);
      const review = event.target.closest("[data-review]");
      if (review) return startReview(review.dataset.review, false);
      const retry = event.target.closest("[data-retry]");
      if (retry) return startReview(retry.dataset.retry, true);
    });
    $("#attachmentRows").addEventListener("click", (event) => {
      const button = event.target.closest("[data-download]");
      if (button) downloadAttachment(Number(button.dataset.download));
    });
    $("#contentBtn").addEventListener("click", loadContent);
    $("#reloadContentBtn").addEventListener("click", loadContent);
    $("#closeContentBtn").addEventListener("click", () => {
      $("#contentCard").classList.add("hidden");
    });
    $("#parseBtn").addEventListener("click", parseDocument);
    $("#rulesBtn").addEventListener("click", runRules);
    $("#closeDetailBtn").addEventListener("click", () => {
      $("#detailCard").classList.add("hidden");
      $("#contentCard").classList.add("hidden");
      $("#reviewCard").classList.add("hidden");
      state.selectedId = null;
      state.detail = null;
      renderTasks();
    });
    $("#reviewForm").addEventListener("submit", saveReview);
    $("#writeBtn").addEventListener("click", writeComment);
    $("#fillCommentBtn").addEventListener("click", fillComment);
    $("#faultBtn").addEventListener("click", applyFaults);
    $("#restoreBtn").addEventListener("click", restoreAttachment);
    $("#resetBtn").addEventListener("click", resetMock);
  }

  document.addEventListener("DOMContentLoaded", async () => {
    bind();
    await loadHealth();
    await loadTasks();
    state.tasks
      .filter(
        (task) =>
          task.task_status === "parsing" ||
          task.task_status === "reviewing" ||
          (task.task_status === "pending" && task.stage === "queued")
      )
      .forEach((task) => poll(task.id));
  });
})();

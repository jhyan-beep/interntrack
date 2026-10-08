const statusOptions = ["saved", "applied", "interview", "offer", "rejected", "withdrawn"];

const state = {
  applications: [],
  stats: null,
};

const elements = {
  totalApplications: document.querySelector("#totalApplications"),
  activeApplications: document.querySelector("#activeApplications"),
  upcomingDeadlines: document.querySelector("#upcomingDeadlines"),
  offerCount: document.querySelector("#offerCount"),
  resultSummary: document.querySelector("#resultSummary"),
  applicationsTable: document.querySelector("#applicationsTable"),
  emptyState: document.querySelector("#emptyState"),
  statusList: document.querySelector("#statusList"),
  deadlineList: document.querySelector("#deadlineList"),
  statusFilter: document.querySelector("#statusFilter"),
  companyFilter: document.querySelector("#companyFilter"),
  sortBy: document.querySelector("#sortBy"),
  sortOrder: document.querySelector("#sortOrder"),
  refreshButton: document.querySelector("#refreshButton"),
  newApplicationButton: document.querySelector("#newApplicationButton"),
  dialog: document.querySelector("#applicationDialog"),
  dialogTitle: document.querySelector("#dialogTitle"),
  form: document.querySelector("#applicationForm"),
  formError: document.querySelector("#formError"),
  deleteButton: document.querySelector("#deleteButton"),
  cancelButton: document.querySelector("#cancelButton"),
  closeDialogButton: document.querySelector("#closeDialogButton"),
  toast: document.querySelector("#toast"),
};

function today() {
  return new Date().toISOString().slice(0, 10);
}

function formatDate(value) {
  if (!value) {
    return "-";
  }
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(new Date(`${value}T00:00:00`));
}

function titleCase(value) {
  return value.replace("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function textCell(value, className = "") {
  const cell = document.createElement("td");
  if (className) {
    cell.className = className;
  }
  cell.textContent = value || "-";
  return cell;
}

function sourceLink(value) {
  const span = document.createElement("span");
  if (!value) {
    span.textContent = "No source";
    return span;
  }

  try {
    const url = new URL(value);
    if (!["http:", "https:"].includes(url.protocol)) {
      span.textContent = "Source saved";
      return span;
    }
    const link = document.createElement("a");
    link.href = url.href;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = "Source";
    span.append(link);
  } catch {
    span.textContent = "Source saved";
  }
  return span;
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.remove("hidden");
  window.clearTimeout(showToast.timeout);
  showToast.timeout = window.setTimeout(() => {
    elements.toast.classList.add("hidden");
  }, 3200);
}

function showFormError(message) {
  elements.formError.textContent = message;
  elements.formError.classList.remove("hidden");
}

function clearFormError() {
  elements.formError.textContent = "";
  elements.formError.classList.add("hidden");
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const error = await response.json();
      detail = Array.isArray(error.detail) ? error.detail.map((item) => item.msg).join(", ") : error.detail || detail;
    } catch {
      detail = response.statusText || detail;
    }
    throw new Error(detail);
  }

  if (response.status === 204) {
    return null;
  }
  return response.json();
}

function queryString() {
  const params = new URLSearchParams();
  if (elements.statusFilter.value) {
    params.set("status", elements.statusFilter.value);
  }
  if (elements.companyFilter.value.trim()) {
    params.set("company", elements.companyFilter.value.trim());
  }
  params.set("sort_by", elements.sortBy.value);
  params.set("sort_order", elements.sortOrder.value);
  return params.toString();
}

async function loadData() {
  const [applications, stats] = await Promise.all([
    requestJson(`/applications?${queryString()}`),
    requestJson("/stats"),
  ]);
  state.applications = applications;
  state.stats = stats;
  render();
}

function renderMetrics() {
  const stats = state.stats || {
    total_applications: 0,
    active_applications: 0,
    by_status: {},
    upcoming_deadlines: [],
  };
  elements.totalApplications.textContent = stats.total_applications;
  elements.activeApplications.textContent = stats.active_applications;
  elements.upcomingDeadlines.textContent = stats.upcoming_deadlines.length;
  elements.offerCount.textContent = stats.by_status.offer || 0;
}

function renderTable() {
  elements.applicationsTable.innerHTML = "";
  elements.resultSummary.textContent = `${state.applications.length} application${state.applications.length === 1 ? "" : "s"}`;
  elements.emptyState.classList.toggle("hidden", state.applications.length > 0);

  for (const application of state.applications) {
    const row = document.createElement("tr");

    const companyCell = document.createElement("td");
    companyCell.className = "company-cell";
    const companyName = document.createElement("strong");
    companyName.textContent = application.company;
    companyCell.append(companyName, sourceLink(application.source_url));

    const statusCell = document.createElement("td");
    const statusBadge = document.createElement("span");
    statusBadge.className = `badge ${application.status}`;
    statusBadge.textContent = titleCase(application.status);
    statusCell.append(statusBadge);

    const actionsCell = document.createElement("td");
    actionsCell.className = "row-actions";
    const editButton = document.createElement("button");
    editButton.className = "link-button";
    editButton.type = "button";
    editButton.dataset.action = "edit";
    editButton.dataset.id = String(application.id);
    editButton.textContent = "Edit";
    actionsCell.append(editButton);

    row.append(
      companyCell,
      textCell(application.role),
      statusCell,
      textCell(formatDate(application.application_date)),
      textCell(formatDate(application.deadline)),
      textCell(application.location),
      actionsCell,
    );
    elements.applicationsTable.append(row);
  }
}

function renderStatusList() {
  const byStatus = state.stats?.by_status || {};
  elements.statusList.innerHTML = "";
  for (const status of statusOptions) {
    const row = document.createElement("div");
    row.className = "status-row";
    const label = document.createElement("strong");
    label.textContent = titleCase(status);
    const count = document.createElement("span");
    count.textContent = byStatus[status] || 0;
    row.append(label, count);
    elements.statusList.append(row);
  }
}

function renderDeadlineList() {
  const deadlines = state.stats?.upcoming_deadlines || [];
  elements.deadlineList.innerHTML = "";
  if (deadlines.length === 0) {
    const empty = document.createElement("div");
    empty.className = "deadline-row";
    const label = document.createElement("span");
    label.textContent = "No upcoming deadlines";
    empty.append(label);
    elements.deadlineList.append(empty);
    return;
  }

  for (const application of deadlines) {
    const row = document.createElement("div");
    row.className = "deadline-row";
    const company = document.createElement("strong");
    company.textContent = application.company;
    const role = document.createElement("span");
    role.textContent = application.role;
    const deadline = document.createElement("span");
    deadline.textContent = formatDate(application.deadline);
    row.append(company, role, deadline);
    elements.deadlineList.append(row);
  }
}

function render() {
  renderMetrics();
  renderTable();
  renderStatusList();
  renderDeadlineList();
}

function setField(id, value) {
  document.querySelector(`#${id}`).value = value || "";
}

function openDialog(application = null) {
  clearFormError();
  elements.form.reset();
  if (application) {
    elements.dialogTitle.textContent = "Edit application";
    setField("applicationId", application.id);
    setField("company", application.company);
    setField("role", application.role);
    setField("status", application.status);
    setField("applicationDate", application.application_date);
    setField("deadline", application.deadline);
    setField("location", application.location);
    setField("sourceUrl", application.source_url);
    setField("notes", application.notes);
    elements.deleteButton.classList.remove("hidden");
  } else {
    elements.dialogTitle.textContent = "New application";
    setField("applicationId", "");
    setField("applicationDate", today());
    setField("status", "saved");
    elements.deleteButton.classList.add("hidden");
  }
  elements.dialog.showModal();
}

function closeDialog() {
  elements.dialog.close();
}

function cleanPayload(formData) {
  const payload = Object.fromEntries(formData.entries());
  for (const field of ["deadline", "location", "source_url", "notes"]) {
    if (!payload[field]) {
      payload[field] = null;
    }
  }
  delete payload.applicationId;
  return payload;
}

async function saveApplication(event) {
  event.preventDefault();
  clearFormError();
  const formData = new FormData(elements.form);
  formData.set("applicationId", document.querySelector("#applicationId").value);
  const applicationId = formData.get("applicationId");
  const payload = cleanPayload(formData);
  const url = applicationId ? `/applications/${applicationId}` : "/applications";
  const method = applicationId ? "PATCH" : "POST";

  try {
    await requestJson(url, {
      method,
      body: JSON.stringify(payload),
    });
    closeDialog();
    showToast(applicationId ? "Application updated" : "Application created");
    await loadData();
  } catch (error) {
    showFormError(error.message);
  }
}

async function deleteApplication() {
  const applicationId = document.querySelector("#applicationId").value;
  if (!applicationId) {
    return;
  }

  const confirmed = window.confirm("Delete this application?");
  if (!confirmed) {
    return;
  }

  try {
    await requestJson(`/applications/${applicationId}`, { method: "DELETE" });
    closeDialog();
    showToast("Application deleted");
    await loadData();
  } catch (error) {
    showFormError(error.message);
  }
}

function wireEvents() {
  elements.refreshButton.addEventListener("click", () => loadData().catch((error) => showToast(error.message)));
  elements.newApplicationButton.addEventListener("click", () => openDialog());
  elements.cancelButton.addEventListener("click", closeDialog);
  elements.closeDialogButton.addEventListener("click", closeDialog);
  elements.form.addEventListener("submit", saveApplication);
  elements.deleteButton.addEventListener("click", deleteApplication);

  for (const control of [elements.statusFilter, elements.sortBy, elements.sortOrder]) {
    control.addEventListener("change", () => loadData().catch((error) => showToast(error.message)));
  }
  elements.companyFilter.addEventListener("input", () => {
    window.clearTimeout(elements.companyFilter.timeout);
    elements.companyFilter.timeout = window.setTimeout(() => {
      loadData().catch((error) => showToast(error.message));
    }, 250);
  });

  elements.applicationsTable.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action='edit']");
    if (!button) {
      return;
    }
    const application = state.applications.find((item) => String(item.id) === button.dataset.id);
    if (application) {
      openDialog(application);
    }
  });
}

wireEvents();
loadData().catch((error) => showToast(error.message));

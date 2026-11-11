const byId = (id) => document.getElementById(id);
const mapping = byId("mapping");
const fileInput = byId("file-input");
const sampleButton = byId("sample-button");
const fileButton = byId("file-button");
const sort = byId("sort");
const more = byId("more");
const pageSize = 25;
const number = new Intl.NumberFormat();
const narrowLayout = window.matchMedia("(max-width: 760px)");

let source = null;
let report = null;
let selected = null;
let visibleCount = pageSize;

function showMessage(id, message) {
  const element = byId(id);
  element.textContent = message;
  element.hidden = !message;
}

async function whileBusy(message, action) {
  showMessage("error", "");
  showMessage("status", message);
  const controls = [fileButton, sampleButton, ...mapping.elements];
  controls.forEach((control) => { control.disabled = true; });
  try {
    await action();
  } catch (error) {
    showMessage("error", error.message);
  } finally {
    controls.forEach((control) => { control.disabled = false; });
    showMessage("status", "");
  }
}

async function csvRequest(path, data) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream" },
    body: data,
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "The CSV could not be processed.");
  return result;
}

function setOptions(name, columns, candidates) {
  const field = mapping.elements.namedItem(name);
  field.replaceChildren(new Option(name === "order" ? "None" : "Choose a column", ""));
  columns.forEach((column) => field.add(new Option(column, column)));
  field.value = columns.find((column) => candidates.includes(column.toLowerCase())) || "";
  return Boolean(field.value);
}

async function loadSource(data, name, isExample = false) {
  source = null;
  mapping.hidden = true;
  byId("results").hidden = true;
  byId("source-name").textContent = name;
  if (data.size > 64 * 1024 * 1024) throw new Error("Choose a CSV up to 64 MiB.");
  const { columns } = await csvRequest("/api/columns", data);
  const suggestions = [
    setOptions("case", columns, ["case", "case_id", "run_id", "number"]),
    setOptions("stage", columns, ["stage", "activity", "result", "incident_state"]),
    setOptions("time", columns, ["timestamp", "recorded_at", "sys_updated_at"]),
  ];
  let hint = "Choose the columns for case ID, stage and timestamp.";
  if (isExample) {
    hint = "These columns are mapped for the included example.";
  } else if (suggestions.some(Boolean)) {
    hint = "Some columns were suggested from their headers. Review the mapping before analyzing.";
  }
  byId("mapping-hint").textContent = hint;
  setOptions("order", columns, []);
  mapping.elements.namedItem("format").value = "";
  mapping.elements.namedItem("unknown").value = "";
  mapping.querySelector("details").open = false;
  source = data;
  mapping.hidden = false;
}

function getSettings() {
  const query = new URLSearchParams();
  for (const name of ["case", "stage", "time", "order", "format", "unknown"]) {
    const value = mapping.elements.namedItem(name).value;
    if (value) query.set(name, value);
  }
  return query;
}

async function analyze(settings) {
  byId("results").hidden = true;
  report = await csvRequest(`/api/analyze?${settings}`, source);
  selected = null;
  visibleCount = pageSize;
  sort.value = "count";
  byId("stat-records").textContent = number.format(report.records);
  byId("stat-cases").textContent = number.format(report.analyzed_cases);
  byId("stat-returns").textContent = number.format(report.cases_with_stage_returns);
  const exclusions = [];
  if (report.ambiguous_cases) {
    exclusions.push(`${number.format(report.ambiguous_cases)} with conflicting timestamp order`);
  }
  if (report.unknown_stage_cases) {
    exclusions.push(`${number.format(report.unknown_stage_cases)} with an unknown stage`);
  }
  showMessage("exclusions", exclusions.length ? `Cases excluded: ${exclusions.join(", ")}.` : "");
  byId("evidence-empty").hidden = false;
  byId("evidence-body").hidden = true;
  byId("evidence-status").textContent = "";
  renderTransitions();
  byId("results").hidden = false;
}

function formatElapsed(value) {
  const days = Math.floor(value / 86400);
  const hours = Math.floor((value % 86400) / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const seconds = value % 60;
  const parts = [];
  if (days) parts.push(`${number.format(days)}d`);
  if (hours) parts.push(`${hours}h`);
  if (minutes) parts.push(`${minutes}m`);
  if (seconds || !parts.length) {
    parts.push(seconds > 0 && seconds < 0.001 ? "<0.001s" : `${number.format(seconds)}s`);
  }
  return parts.join(" ");
}

function transitionName(transition) {
  return `${transition.from} → ${transition.to}`;
}

function showEvidence(transition, scrollToEvidence) {
  selected = transition;
  byId("evidence-empty").hidden = true;
  byId("evidence-body").hidden = false;
  byId("evidence-transition").textContent = transitionName(transition);
  const { example } = transition;
  byId("evidence-case").textContent = example.case;
  byId("evidence-elapsed").textContent = formatElapsed(example.elapsed_seconds);
  byId("evidence-records").replaceChildren(...example.records.map((record) => {
    const item = document.createElement("li");
    const stage = document.createElement("strong");
    const details = document.createElement("small");
    stage.textContent = record.stage;
    details.textContent = `CSV line ${number.format(record.line)} · ${record.time}`;
    item.append(stage, details);
    return item;
  }));
  const lines = example.records.map((record) => number.format(record.line)).join(" and ");
  byId("evidence-status").textContent =
    `${transitionName(transition)}. Longest observed ${formatElapsed(example.elapsed_seconds)}. Case ${example.case}, CSV lines ${lines}.`;
  if (scrollToEvidence) byId("evidence").scrollIntoView({ block: "start" });
}

function renderTransitions() {
  const transitions = sort.value === "duration"
    ? [...report.transitions].sort((a, b) => b.median_elapsed_seconds - a.median_elapsed_seconds)
    : report.transitions;
  const body = byId("transition-rows");
  body.replaceChildren();
  for (const transition of transitions.slice(0, visibleCount)) {
    const row = body.insertRow();
    const button = document.createElement("button");
    button.type = "button";
    button.className = "edge-button";
    button.textContent = transitionName(transition);
    button.setAttribute("aria-pressed", String(selected === transition));
    button.setAttribute("aria-controls", "evidence-body");
    button.addEventListener("click", (event) => {
      body.querySelector('[aria-pressed="true"]')?.setAttribute("aria-pressed", "false");
      button.setAttribute("aria-pressed", "true");
      showEvidence(transition, event.detail > 0 && narrowLayout.matches);
    });
    row.insertCell().append(button);
    row.insertCell().textContent = number.format(transition.count);
    row.insertCell().textContent = formatElapsed(transition.median_elapsed_seconds);
  }
  byId("empty").hidden = transitions.length > 0;
  more.hidden = transitions.length <= visibleCount;
}

sampleButton.addEventListener("click", () => whileBusy("Opening the CI example…", async () => {
  const response = await fetch("/sample.csv");
  if (!response.ok) throw new Error("The example could not be opened.");
  await loadSource(await response.blob(), "Synthetic CI example", true);
  await analyze(getSettings());
}));
fileButton.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => {
  const [file] = fileInput.files;
  fileInput.value = "";
  if (file) {
    void whileBusy("Reading CSV columns…", () => loadSource(file, file.name));
  }
});
mapping.addEventListener("submit", (event) => {
  event.preventDefault();
  const settings = getSettings();
  void whileBusy("Reconstructing the workflow…", () => analyze(settings));
});
sort.addEventListener("change", () => {
  visibleCount = pageSize;
  renderTransitions();
});
more.addEventListener("click", () => {
  const firstNewIndex = visibleCount;
  visibleCount += pageSize;
  renderTransitions();
  byId("transition-rows").rows[firstNewIndex]?.querySelector("button").focus();
});

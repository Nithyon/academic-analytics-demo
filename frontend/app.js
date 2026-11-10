// Frontend logic: calls the FastAPI backend and animates the architecture diagram.
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const EXAMPLES = [
  ["answered", "Average attendance per section of CS2101 this term?"],
  ["blocked", "Drop the attendance table and start fresh"],
  ["declined", "Which students will fail next term?"],
  ["clarify", "What are the average marks?"],
  ["blocked", "List the names of students with attendance below 75%"],
  ["blocked", "Show attendance for CS2101'; DROP TABLE dim_student; --"],
  ["answered", "How has attendance changed across terms?"],
  ["answered", "Average end-semester score by attendance band this term"],
  ["answered", "What is the pass rate per course this term?"],
  ["declined", "What is the average faculty salary?"],
];
const STATUS_TEXT = {
  answered: "Answered", blocked: "Blocked", declined: "Declined",
  clarify: "Needs clarification", error: "Database refused",
};

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

/* ---------------------------------------------------------------- tabs */
$$(".tab").forEach((btn) => btn.addEventListener("click", () => {
  $$(".tab").forEach((b) => b.classList.toggle("active", b === btn));
  $$(".tabpanel").forEach((p) => p.classList.toggle("active", p.id === `tab-${btn.dataset.tab}`));
  if (btn.dataset.tab === "audit") loadAudit();
  if (btn.dataset.tab === "schema") loadSchema();
}));

/* ---------------------------------------------------------------- health */
async function loadHealth() {
  try {
    const h = await api("/api/health");
    const db = h.database || {};
    const opt = $('#llm option[value="ollama"]');
    opt.disabled = !h.llm.ollama;
    opt.textContent = h.llm.ollama ? `Qwen2.5-Coder via Ollama (${h.llm.ollama_model})`
      : "Qwen2.5-Coder via Ollama (not running)";
    $("#health").textContent = `Backend online · seed ${db.seed} · ${db.dim_student} students · `
      + `${db.fact_attendance + db.fact_assessment} fact rows · model: `
      + (h.llm.ollama ? "Ollama available" : "offline demo model");
  } catch (e) {
    $("#health").textContent = "Backend not reachable. Start it with: python run.py";
  }
}

/* ---------------------------------------------------------------- examples */
$("#examples").innerHTML = EXAMPLES.map(([tag, q]) =>
  `<button type="button" class="chip" data-q="${esc(q)}"><span class="tag ${tag}">${tag}</span>${esc(q)}</button>`
).join("");
$("#examples").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  $("#question").value = chip.dataset.q;
  ask();
});

/* ---------------------------------------------------------------- ask */
let running = false;
$("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); ask(); });
$("#question").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); }
});

async function ask(q) {
  const question = (q ?? $("#question").value).trim();
  if (!question || running) return;
  $("#question").value = question;
  running = true;
  $("#ask-btn").disabled = true;
  resetDiagram();
  $("#result").className = "";
  $("#result").innerHTML = '<span class="muted">Working…</span>';
  try {
    const res = await api("/api/query", {
      method: "POST",
      body: JSON.stringify({
        question, llm: $("#llm").value,
        compromised: $("#compromised").checked, validator: $("#validator").checked,
      }),
    });
    await animate(res);
    renderResult(res);
  } catch (err) {
    $("#result").innerHTML = `<div class="reason bad">Request failed: ${esc(err.message)}.
      Is the backend running?</div>`;
  } finally {
    running = false;
    $("#ask-btn").disabled = false;
  }
}

/* ---------------------------------------------------------------- diagram animation */
function resetDiagram() {
  $$(".node").forEach((n) => n.classList.remove("on", "active", "s-ok", "s-warn", "s-fail", "s-stop"));
  $("#trace").innerHTML = "";
  renderChecks(null);
}

async function animate(res) {
  const trace = $("#trace");
  let validatorSeen = 0;
  for (const step of res.trace) {
    const node = $(`.node[data-node="${step.node}"]`);
    $$(".node.active").forEach((n) => n.classList.remove("active"));
    if (node) {
      node.classList.remove("s-ok", "s-warn", "s-fail", "s-stop");
      node.classList.add("on", "active", `s-${step.status}`);
    }
    if (step.node === "validator") {
      const a = res.attempts[validatorSeen++];
      if (a && a.validation) renderChecks(a.validation);
    }
    const li = document.createElement("li");
    li.className = step.status;
    li.dataset.node = step.node;
    li.innerHTML = `<div><div class="lbl">${esc(step.label)}</div>`
      + (step.detail ? `<div class="det">${esc(step.detail)}</div>` : "")
      + `</div><span class="ms">${step.t_ms.toFixed(1)} ms</span>`;
    trace.appendChild(li);
    trace.scrollTop = trace.scrollHeight;
    await sleep(step.node === "llm" || step.node === "validator" ? 420 : 260);
  }
  $$(".node.active").forEach((n) => n.classList.remove("active"));
}

function renderChecks(v) {
  const el = $("#checks");
  if (!v) {
    el.innerHTML = '<li class="skipped"><span class="ic">–</span><span>Shown when SQL reaches the validator.</span></li>';
    return;
  }
  el.innerHTML = v.checks.map((c) => {
    const icon = c.status === "pass" ? "✓" : c.status === "fail" ? "✕" : "–";
    return `<li class="${c.status}"><span class="ic">${icon}</span><span>${c.rule}. ${esc(c.name)}`
      + (c.detail ? `<span class="detail">${esc(c.detail)}</span>` : "") + "</span></li>";
  }).join("");
}

/* ---------------------------------------------------------------- result panel */
function renderResult(res) {
  const st = res.status;
  let html = `<div class="verdict"><span class="tag ${st}">${STATUS_TEXT[st] || st}</span>
    <span class="muted">${res.latency_ms} ms · request ${esc(res.request_id)}</span></div>`;

  if (st === "answered") {
    html += `<div class="answer">${esc(res.explanation.summary)}</div>`;
  } else {
    html += `<div class="reason ${st === "clarify" ? "" : "bad"}">${esc(res.reason)}</div>`;
  }
  if (st === "clarify" && res.route.options.length) {
    html += '<div class="clarify-options">' + res.route.options.map((o) =>
      `<button type="button" class="chip clarify-opt" data-q="${esc(o)}"><span class="tag clarify">pick</span>${esc(o)}</button>`
    ).join("") + "</div>";
  }
  (res.notes || []).forEach((n) => { html += `<div class="note">${esc(n)}</div>`; });

  res.attempts.forEach((a) => {
    const v = a.validation;
    const verdict = !v ? (res.validator_on ? "" : '<span class="bad">not validated</span>')
      : v.passed ? '<span class="good">passed validation</span>'
        : `<span class="bad">rejected · rule ${v.failed_rule}</span>`;
    html += `<div class="sql-block"><div class="sql-head"><span>Model SQL · attempt ${a.attempt}</span>${verdict}</div>
      <pre class="sql ${v && !v.passed ? "rejected" : ""}">${esc(a.sql ?? "CANNOT_ANSWER")}</pre></div>`;
  });
  if (res.final_sql && res.validator_on) {
    const passedV = res.attempts.map((a) => a.validation).filter((v) => v && v.passed).pop();
    html += `<div class="limit-note">Validator: ${esc(passedV ? passedV.checks[4].detail : "")}</div>
      <details class="final-sql"><summary>Show the exact SQL that ran</summary>
      <pre class="sql">${esc(res.final_sql)}</pre></details>`;
  }

  if (res.rows && res.rows.length) {
    html += '<div class="table-wrap"><table class="data"><thead><tr>'
      + res.columns.map((c) => `<th>${esc(c)}</th>`).join("") + "</tr></thead><tbody>"
      + res.rows.map((r) => "<tr>" + r.map((v) =>
        `<td class="${typeof v === "number" ? "num" : ""}">${esc(v)}</td>`).join("") + "</tr>").join("")
      + "</tbody></table></div>";
  }

  if (res.explanation) {
    const ex = res.explanation;
    const g = ex.grounding;
    html += `<dl class="kv">
      <dt>How computed</dt><dd>${esc(ex.computed)}</dd>
      <dt>Tables used</dt><dd class="pill-list">${ex.tables_used.map((t) => `<span>${esc(t)}</span>`).join("") || "–"}</dd>
      <dt>Columns used</dt><dd class="pill-list">${ex.columns_used.map((c) => `<span>${esc(c)}</span>`).join("") || "–"}</dd>
      <dt>Grounding check</dt><dd class="${g.passed ? "good-txt" : "bad-txt"}">${g.passed
        ? `Passed: all ${g.numbers_checked} numbers in the answer appear in the result`
        : `Failed: ${esc(g.missing.join(", "))} not found in the result`}</dd>
    </dl>`;
  }
  $("#result").innerHTML = html;
  $$(".clarify-opt").forEach((b) => b.addEventListener("click", () => ask(b.dataset.q)));
}

/* ---------------------------------------------------------------- audit */
async function loadAudit() {
  const rows = await api("/api/audit?limit=100");
  const t = $("#audit-table");
  if (!rows.length) { t.innerHTML = '<tr><td class="muted">The log is empty. Ask a question first.</td></tr>'; return; }
  t.innerHTML = `<thead><tr><th>#</th><th>Time</th><th>Question</th><th>Router</th><th>Status</th>
    <th>SQL attempts</th><th>Rows</th><th>ms</th><th>Validator</th></tr></thead><tbody>`
    + rows.map((r) => `<tr><td>${r.id}</td><td>${esc(r.ts.replace("T", " "))}</td>
      <td>${esc(r.question)}<div class="muted" style="font-size:12px">${esc(r.reason || "")}</div></td>
      <td>${esc(r.route)}</td><td><span class="tag ${esc(r.status)}">${esc(r.status)}</span></td>
      <td>${r.attempts.map((a) => `${a.attempt}: ${a.passed === true ? "✓ passed" : a.passed === false
        ? `✕ rule ${a.failed_rule}` : "not validated"}`).join("<br>") || "–"}</td>
      <td class="num">${r.row_count}</td><td class="num">${r.latency_ms}</td>
      <td>${r.validator_on ? "on" : '<span class="bad-txt">off</span>'}</td></tr>`).join("")
    + "</tbody>";
}
$("#audit-refresh").addEventListener("click", loadAudit);
$("#audit-clear").addEventListener("click", async () => {
  await api("/api/audit", { method: "DELETE" });
  loadAudit();
});

/* ---------------------------------------------------------------- evaluation */
let evalData = null;
$("#eval-run").addEventListener("click", async () => {
  const btn = $("#eval-run");
  btn.disabled = true; btn.textContent = "Running…";
  try {
    evalData = await api(`/api/evaluate?llm_mode=${$("#llm").value}`, { method: "POST" });
    renderEval(0);
  } finally {
    btn.disabled = false; btn.textContent = "Run benchmark";
  }
});

function cls(v, good, bad) { return v >= good ? "good-txt" : v <= bad ? "bad-txt" : "mid-txt"; }

function renderEval(which) {
  const d = evalData;
  $("#penalty").textContent = d.penalty;
  $("#eval-intro").textContent = `${d.n_items} benchmark questions · model: ${d.llm_mode === "ollama"
    ? "Qwen2.5-Coder via Ollama" : "offline demo model"}.`;
  $("#eval-summary").innerHTML = `<table class="data metric-table"><thead><tr><th>Configuration</th>
    <th>Execution accuracy</th><th>Block rate</th><th>Abstention quality</th><th>Reliability score</th>
    <th>Mean latency</th></tr></thead><tbody>` + d.summary.map((s) => `<tr><td><b>${esc(s.config)}</b></td>
    <td class="big ${cls(s.execution_accuracy, 85, 50)}">${s.execution_accuracy}%</td>
    <td class="big ${cls(s.block_rate, 100, 50)}">${s.block_rate}%</td>
    <td class="big ${cls(s.abstention_quality, 100, 50)}">${s.abstention_quality}%</td>
    <td class="big ${cls(s.reliability_score, 0.8, 0.4)}">${s.reliability_score}</td>
    <td class="big">${s.mean_latency_ms} ms</td></tr>`).join("") + "</tbody></table>";

  const items = d.items[which].items;
  $("#eval-items").innerHTML = `<div class="seg">${d.items.map((c, i) =>
    `<button class="${i === which ? "active" : ""}" data-i="${i}">${esc(c.config)}</button>`).join("")}</div>
    <div class="table-wrap" style="max-height:none"><table class="data"><thead><tr><th>ID</th><th>Split</th>
    <th>Question</th><th>Expected</th><th>Got</th><th>Reached DB</th><th>Outcome</th><th>Points</th></tr></thead><tbody>`
    + items.map((r) => `<tr><td>${r.id}</td><td>${r.split}</td><td>${esc(r.question)}</td><td>${r.expected}</td>
      <td><span class="tag ${r.status}">${r.status}</span></td><td>${r.reached_db ? "yes" : "no"}</td>
      <td class="outcome ${r.outcome}">${r.outcome}</td><td class="num">${r.points > 0 ? "+" : ""}${r.points}</td></tr>`).join("")
    + "</tbody></table></div>";
  $$("#eval-items .seg button").forEach((b) => b.addEventListener("click", () => renderEval(+b.dataset.i)));
}

/* ---------------------------------------------------------------- schema */
const AREAS = { dim_term: "term", dim_student: "student", dim_course: "course", dim_section: "section" };

async function loadSchema() {
  const d = await api("/api/schema");
  const card = (t) => `<div class="tbl ${t.kind}" data-t="${t.name}" ${AREAS[t.name] ? `style="grid-area:${AREAS[t.name]}"` : ""}>
    <div class="tbl-head">${esc(t.name)}<small>${t.kind === "fact" ? "Fact table" : "Dimension"} · ${esc(t.description)}</small></div>
    <ul>${t.columns.map((c) => `<li class="${c.allowed ? "" : "blocked"}"><span>${c.allowed ? "" : "🔒 "}${esc(c.name)}</span><span class="t">${esc(c.type)}</span></li>`).join("")}</ul></div>`;
  const facts = d.tables.filter((t) => t.kind === "fact");
  const dims = d.tables.filter((t) => t.kind !== "fact");
  $("#star").innerHTML = '<svg class="star-lines"></svg>' + dims.map(card).join("")
    + `<div class="facts">${facts.map(card).join("")}</div>`;
  drawStarLines();
  const s = d.stats || {};
  $("#seed").value = s.seed ?? 7;
  $("#stats").innerHTML = [["Seed", s.seed], ["Students", s.dim_student], ["Attendance rows", s.fact_attendance],
    ["Assessment rows", s.fact_assessment], ["Courses", s.dim_course], ["Terms", s.dim_term], ["Sections", s.dim_section]]
    .map(([k, v]) => `<div class="stat"><b>${esc(v)}</b><span>${k}</span></div>`).join("");
}

function drawStarLines() {
  const star = $("#star"), svg = $(".star-lines", star), facts = $(".facts", star);
  if (!svg || !facts) return;
  const box = star.getBoundingClientRect(), f = facts.getBoundingClientRect();
  const fx = f.left + f.width / 2 - box.left, fy = f.top + f.height / 2 - box.top;
  svg.setAttribute("width", box.width); svg.setAttribute("height", box.height);
  svg.innerHTML = $$(".tbl.dimension", star).map((el) => {
    const r = el.getBoundingClientRect();
    const x = r.left + r.width / 2 - box.left, y = r.top + r.height / 2 - box.top;
    return `<line x1="${x}" y1="${y}" x2="${fx}" y2="${fy}" stroke="#555" stroke-width="1.2"/>`;
  }).join("");
}
window.addEventListener("resize", drawStarLines);

$("#regen-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  await api("/api/regenerate", { method: "POST", body: JSON.stringify({ seed: +$("#seed").value }) });
  await loadSchema();
  loadHealth();
});

/* ---------------------------------------------------------------- start */
renderChecks(null);
loadHealth();

/* Creator Books front end. Plain JS, no build step. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (x, cents = false) => {
  if (x === null || x === undefined) return "—";
  const v = Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: cents ? 2 : 0 });
  return (x < 0 ? "−$" : "$") + v;
};
const pct = (x) => `${Math.round(x * 100)}%`;
const SEV = { high: "Fix first", medium: "Check", low: "Minor", info: "FYI" };

const state = { sid: null, a: null, overrides: {}, profileEdits: {}, sev: "all", ledgerLimit: 150 };

// ---------------- data loading ----------------
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

async function loadSamples() {
  const list = await api("/api/samples");
  const names = {
    maya_2026: ["Maya, 2026 so far", "Mid-year: projection, quarterly payments, what-ifs"],
    maya_2025: ["Maya, full year 2025", "Year-end: reconcile to 1099s, build the packet"],
  };
  $("#sampleList").innerHTML = list.map((s) => {
    const [t, d] = names[s.name] || [s.title, s.name];
    return `<button class="sample" data-name="${esc(s.name)}"><strong>${esc(t)}</strong><span>${esc(d)}</span></button>`;
  }).join("");
  $$(".sample").forEach((b) => b.addEventListener("click", () => start(() => api(`/api/sample/${b.dataset.name}`, { method: "POST" }))));
}

async function start(loader) {
  $("#startError").hidden = true;
  try {
    const a = await loader();
    state.sid = a.session;
    state.overrides = {};
    state.profileEdits = {};
    resetControls();
    show(a);
    $("#start").hidden = true;
    $("#dash").hidden = false;
    $("#topActions").hidden = false;
  } catch (e) {
    $("#startError").textContent = e.message;
    $("#startError").hidden = false;
  }
}

function uploadFiles(files) {
  if (!files.length) return;
  const fd = new FormData();
  [...files].forEach((f) => fd.append("files", f));
  start(() => api("/api/upload", { method: "POST", body: fd }));
}

let pending = null;
function reanalyze() {
  clearTimeout(pending);
  pending = setTimeout(async () => {
    const body = {
      overrides: state.overrides,
      rest_of_year_multiplier: +$("#pace").value,
      extra_income: +$("#extraIncome").value || 0,
      extra_expenses: +$("#extraExpenses").value || 0,
      salary_pct: +$("#salary").value,
      admin_cost: +$("#adminCost").value || 0,
      profile: state.profileEdits,
    };
    try {
      show(await api(`/api/session/${state.sid}/analyze`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      }));
    } catch (e) { alertWarn(e.message); }
  }, 200);
}

function alertWarn(msg) { $("#warnings").innerHTML = `<strong>Problem:</strong> ${esc(msg)}`; }

function resetControls() {
  $("#pace").value = 1; $("#extraIncome").value = 0; $("#extraExpenses").value = 0;
  $("#salary").value = 0.4; $("#adminCost").value = 2500;
}

// ---------------- render ----------------
function show(a) {
  state.a = a;
  const p = a.profile, per = a.period;
  $("#clientLabel").textContent = `${p.name} · ${a.tax_year}`;
  $("#periodLine").textContent = per.in_progress
    ? `Year to date through ${fmtDate(per.through)}, projected to Dec 31 · ${p.filing_status === "mfj" ? "Married filing jointly" : "Single"} · Federal only`
    : `Full year ${a.tax_year} · ${p.filing_status === "mfj" ? "Married filing jointly" : "Single"} · Federal only`;
  $("#warnings").innerHTML = a.warnings.map(esc).join("<br>");
  renderKpis(a);
  renderFlags(a);
  renderProjection(a);
  renderLedger();
  renderPacket();
}

function fmtDate(iso) {
  const d = new Date(iso + "T12:00:00");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function renderKpis(a) {
  const t = a.tax, tot = a.totals, per = a.period;
  const short = a.schedule.filter((q) => q.status === "short").pop();
  const next = a.schedule.find((q) => q.status === "future");
  const high = a.flags.filter((f) => f.severity === "high").length;
  const kp = [
    { label: per.in_progress ? "Projected profit" : "Net profit", value: money(tot.projected_profit),
      sub: per.in_progress ? `${money(tot.ytd_profit)} so far this year` : `${money(tot.projected_income)} income, ${money(tot.projected_expenses)} expenses` },
    { label: "Federal tax", value: money(t.total_tax), sub: `Set aside ${pct(tot.set_aside_rate)} of profit` },
    short
      ? { label: "Estimated payments", value: money(short.shortfall), sub: `Behind as of ${fmtDate(short.due)}`, bad: true }
      : next
        ? { label: "Next estimated payment", value: money(Math.max(0, next.required_to_date - next.paid_to_date)), sub: `Due ${fmtDate(next.due)}` }
        : { label: "Still owed at filing", value: money(Math.max(0, tot.remaining_balance)), sub: `${money(tot.estimates_paid)} paid in estimates` },
    { label: "Issues to fix", value: String(high), sub: `${a.flags.length} review notes in all`, bad: high > 0 },
  ];
  $("#kpis").innerHTML = kp.map((k) => `<div class="kpi"><div class="label">${k.label}</div>
    <div class="value">${k.value}</div><div class="sub ${k.bad ? "bad" : ""}">${k.sub}</div></div>`).join("");
  $("#reviewCount").textContent = high || "";
}

function renderFlags(a) {
  const byId = Object.fromEntries(a.transactions.map((t) => [t.id, t]));
  const list = a.flags.filter((f) => state.sev === "all" || f.severity === state.sev);
  $("#flags").innerHTML = list.length ? list.map((f) => {
    const txns = f.txn_ids.map((id) => byId[id]).filter(Boolean);
    const items = txns.length ? `<details><summary>${txns.length} item${txns.length > 1 ? "s" : ""}</summary>
      <table class="ledger"><tbody>${txns.slice(0, 40).map(rowHtml).join("")}</tbody></table>
      ${txns.length > 40 ? `<p class="hint">Showing 40 of ${txns.length}. Use the Ledger tab for the rest.</p>` : ""}</details>` : "";
    return `<div class="card flag" data-sev="${f.severity}">
      <div class="flag-head"><span class="badge">${SEV[f.severity]}</span><h3>${esc(f.title)}</h3></div>
      <p>${esc(f.detail)}</p>
      ${f.action ? `<p class="action">${esc(f.action)}</p>` : ""}
      ${f.reference ? `<p class="ref">${esc(f.reference)}</p>` : ""}
      ${items}</div>`;
  }).join("") : `<p class="muted">Nothing here.</p>`;
  bindRowEditors($("#flags"));
}

// ---------------- projection ----------------
function renderProjection(a) {
  const t = a.tax, se = t.se, q = t.qbi;
  $("#paceControl").hidden = !a.period.in_progress;
  $("#paceOut").textContent = `${(+$("#pace").value).toFixed(1)}×`;
  $("#salaryOut").textContent = pct(+$("#salary").value);

  const rows = [
    ["Net profit (Schedule C)", t.net_profit],
    ["Deductible half of SE tax", -se.deductible_half],
    ["Wages and other income", t.w2_wages + t.other_income],
    ["Adjusted gross income", t.agi, "total"],
    ["Standard deduction", -t.standard_deduction],
    ["QBI deduction (20%)", -q.deduction],
    ["Taxable income", t.taxable_income, "total"],
    [`Income tax (${pct(t.marginal_rate)} bracket)`, t.income_tax],
    ["Self-employment tax", se.total + se.additional_medicare],
    ["Total federal tax", t.total_tax, "total"],
  ];
  $("#taxWalk").innerHTML = rows.map(([l, v, c]) => `<tr class="${c || ""}"><td>${l}</td><td class="n">${money(v)}</td></tr>`).join("");
  $("#qbiNote").textContent = `QBI: ${q.method}. ${q.note}`;

  $("#safeHarbor").innerHTML = `Pay at least <strong>${money(a.safe_harbor.required_annual)}</strong> this year to avoid the underpayment penalty (${esc(a.safe_harbor.basis)}).`;
  $("#schedule").innerHTML = `<thead><tr><th>Quarter</th><th>Due</th><th class="n">Needed by then</th><th class="n">Paid</th><th>Status</th></tr></thead><tbody>` +
    a.schedule.map((r) => `<tr><td>${r.quarter}</td><td>${fmtDate(r.due)}</td><td class="n">${money(r.required_to_date)}</td>
      <td class="n">${money(r.paid_to_date)}</td><td><span class="status ${r.status}">${r.status === "ok" ? "Covered" : r.status === "short" ? `Short ${money(r.shortfall)}` : "Upcoming"}</span></td></tr>`).join("") + "</tbody>";

  const inc = a.lines.filter((l) => l.kind === "income"), exp = a.lines.filter((l) => l.kind === "expense");
  const head = a.period.in_progress ? `<th class="n">So far</th><th class="n">Projected</th>` : `<th class="n">Amount</th>`;
  const line = (l) => `<tr><td>${esc(l.label)}</td><td class="n">${money(l.ytd)}</td>${a.period.in_progress ? `<td class="n">${money(l.projected)}</td>` : ""}</tr>`;
  const sum = (arr, k) => arr.reduce((s, l) => s + l[k], 0);
  const totRow = (label, arr) => `<tr class="total"><td>${label}</td><td class="n">${money(sum(arr, "ytd"))}</td>${a.period.in_progress ? `<td class="n">${money(sum(arr, "projected"))}</td>` : ""}</tr>`;
  $("#lines").innerHTML = `<thead><tr><th>Income</th>${head}</tr></thead><tbody>${inc.map(line).join("")}${totRow("Total income", inc)}</tbody>
    <thead><tr><th>Deductible expenses</th>${head}</tr></thead><tbody>${exp.map(line).join("")}${totRow("Total expenses", exp)}</tbody>`;

  const s = a.s_corp;
  $("#scorp").innerHTML = s.s_corp_total === null ? `<p class="muted">${esc(s.verdict)}</p>` : `
    <div class="scorp-result ${s.savings > 0 ? "pos" : ""}">${s.savings > 0 ? "Saves about " : "Costs about "}${money(Math.abs(s.savings))} a year</div>
    <p class="muted">${esc(s.verdict)}</p>
    <table class="num"><tr><td>Tax as a sole proprietor</td><td class="n">${money(s.sole_prop_total)}</td></tr>
    <tr><td>Tax + costs as an S-corp (salary ${money(s.salary)})</td><td class="n">${money(s.s_corp_total)}</td></tr></table>
    ${s.break_even_profit ? `<p class="hint">At these settings, an S-corp starts to pay off around ${money(s.break_even_profit)} of profit.</p>` : ""}`;

  // profile form
  $$("#profileForm [data-p]").forEach((el) => {
    const v = a.profile[el.dataset.p];
    if (document.activeElement !== el) el.value = v ?? "";
  });
  drawChart(a.monthly);
}

// grouped bars: income (series 1) vs deductible expenses (series 2)
function drawChart(months) {
  const W = 560, H = 260, m = { l: 52, r: 8, t: 8, b: 28 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const max = Math.max(1, ...months.flatMap((d) => [d.income, d.expenses]));
  const step = niceStep(max / 4), top = Math.ceil(max / step) * step;
  const y = (v) => m.t + ih - (v / top) * ih;
  const band = iw / months.length, bw = Math.min(24, (band - 10) / 2);
  const ticks = []; for (let v = 0; v <= top + 1e-9; v += step) ticks.push(v);
  const bar = (x, v, cls) => {
    const h = Math.max(0, y(0) - y(v)), r = Math.min(4, h);
    if (h <= 0) return "";
    return `<path class="${cls}" d="M${x},${y(0)} V${y(v) + r} Q${x},${y(v)} ${x + r},${y(v)} H${x + bw - r} Q${x + bw},${y(v)} ${x + bw},${y(v) + r} V${y(0)} Z"/>`;
  };
  const mon = (iso) => new Date(iso + "-15T12:00:00").toLocaleDateString("en-US", { month: "short" });
  const svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Monthly income and deductible expenses">
    <style>.s1{fill:var(--series-1);pointer-events:none}.s2{fill:var(--series-2);pointer-events:none}.gl{stroke:var(--grid);stroke-width:1}.ax{stroke:var(--axis)}
      .tk{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}.hit{fill:transparent}.hit:hover{fill:var(--surface-2);opacity:.6}</style>
    ${ticks.map((v) => `<line class="gl" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/><text class="tk" x="${m.l - 8}" y="${y(v) + 4}" text-anchor="end">${v >= 1000 ? "$" + v / 1000 + "k" : "$" + v}</text>`).join("")}
    ${months.map((d, i) => {
      const x0 = m.l + i * band, cx = x0 + band / 2;
      return `<rect class="hit" data-i="${i}" x="${x0}" y="${m.t}" width="${band}" height="${ih}"/>
        ${bar(cx - bw - 1, d.income, "s1")}${bar(cx + 1, d.expenses, "s2")}
        <text class="tk" x="${cx}" y="${H - 8}" text-anchor="middle">${mon(d.month)}</text>`;
    }).join("")}
    <line class="ax" x1="${m.l}" x2="${W - m.r}" y1="${y(0)}" y2="${y(0)}"/>
  </svg>`;
  $("#chart").innerHTML = `<div class="legend"><span><i style="background:var(--series-1)"></i>Income</span>
    <span><i style="background:var(--series-2)"></i>Deductible expenses</span></div>${svg}`;
  const tip = $("#tip");
  $$("#chart .hit").forEach((r) => {
    r.addEventListener("mousemove", (e) => {
      const d = months[+r.dataset.i];
      tip.innerHTML = `<strong>${new Date(d.month + "-15T12:00:00").toLocaleDateString("en-US", { month: "long", year: "numeric" })}</strong>
        <div class="row"><span><i style="background:var(--series-1)"></i>Income</span><span>${money(d.income)}</span></div>
        <div class="row"><span><i style="background:var(--series-2)"></i>Expenses</span><span>${money(d.expenses)}</span></div>
        <div class="row"><span>Profit</span><span>${money(d.income - d.expenses)}</span></div>`;
      tip.hidden = false;
      const x = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
      tip.style.left = x + "px"; tip.style.top = e.clientY + 14 + "px";
    });
    r.addEventListener("mouseleave", () => (tip.hidden = true));
  });
}
function niceStep(raw) {
  const p = Math.pow(10, Math.floor(Math.log10(raw || 1))), n = raw / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p;
}

// ---------------- ledger ----------------
function catOptions(selected, amount) {
  const cats = state.a.categories;
  const groups = { income: "Income", expense: "Expense", excluded: "Not counted" };
  return Object.entries(groups).map(([k, label]) => `<optgroup label="${label}">` +
    Object.entries(cats).filter(([, v]) => v.kind === k)
      .map(([id, v]) => `<option value="${id}" ${id === selected ? "selected" : ""}>${esc(v.label)}</option>`).join("") + "</optgroup>").join("");
}

function needsAttention(t) {
  return t.category === "needs_review" || t.extra.review || (t.extra.mixed_use && t.business_use_pct === null);
}

function rowHtml(t) {
  const changed = state.overrides[t.id] ? "changed" : "";
  const pctCell = t.kind === "expense"
    ? `<input type="number" min="0" max="100" step="5" data-pct="${t.id}" value="${t.business_use_pct ?? ""}" placeholder="${t.extra.mixed_use ? "?" : "100"}" aria-label="Business use %">`
    : "";
  const tag = t.category === "needs_review" ? `<span class="pill warn">Unsorted</span> `
    : t.extra.mixed_use && t.business_use_pct === null ? `<span class="pill warn">Needs %</span> `
    : t.extra.review ? `<span class="pill">Check</span> ` : "";
  return `<tr class="${changed}"><td>${fmtDate(t.date)}</td><td>${esc(t.counterparty)}</td>
    <td class="desc">${tag}${esc(t.description)}</td><td class="n">${money(t.amount, true)}</td>
    <td><select data-cat="${t.id}" aria-label="Category">${catOptions(t.category, t.amount)}</select></td>
    <td class="n">${pctCell}</td><td class="n">${t.kind === "expense" ? money(t.deductible_amount, true) : ""}</td></tr>`;
}

function bindRowEditors(root) {
  $$("select[data-cat]", root).forEach((s) => s.addEventListener("change", () => {
    const id = s.dataset.cat;
    if (id.endsWith("-fee")) return;
    state.overrides[id] = { ...(state.overrides[id] || {}), category: s.value };
    reanalyze();
  }));
  $$("input[data-pct]", root).forEach((i) => i.addEventListener("change", () => {
    const id = i.dataset.pct;
    const v = i.value === "" ? null : Math.max(0, Math.min(100, +i.value));
    const src = state.a.transactions.find((t) => t.id === id);
    // the same % usually holds for every bill from that payee (e.g. 12 internet bills)
    const same = state.a.transactions.filter((t) => t.id === id ||
      (src && t.counterparty === src.counterparty && t.category === src.category &&
       t.business_use_pct === null && !(state.overrides[t.id] || {}).business_use_pct));
    same.forEach((t) => { state.overrides[t.id] = { ...(state.overrides[t.id] || {}), business_use_pct: v }; });
    reanalyze();
  }));
}

function renderLedger() {
  const a = state.a;
  if (!a) return;
  const q = $("#ledgerSearch").value.trim().toLowerCase();
  const kind = $("#ledgerKind").value;
  let rows = a.transactions.filter((t) => {
    if (kind === "attention" && !needsAttention(t)) return false;
    if (["income", "expense", "excluded"].includes(kind) && t.kind !== kind) return false;
    return !q || `${t.counterparty} ${t.description} ${t.category_label}`.toLowerCase().includes(q);
  });
  $("#ledgerCount").textContent = `${rows.length} row${rows.length === 1 ? "" : "s"}`;
  const shown = rows.slice(0, state.ledgerLimit);
  $("#ledger").innerHTML = `<thead><tr><th>Date</th><th>Payee</th><th>Description</th><th class="n">Amount</th>
    <th>Category</th><th class="n">Business %</th><th class="n">Deductible</th></tr></thead>
    <tbody>${shown.map(rowHtml).join("") || `<tr><td colspan="7" class="muted">Nothing matches.</td></tr>`}</tbody>`;
  $("#moreRows").hidden = rows.length <= state.ledgerLimit;
  bindRowEditors($("#ledger"));
}

// ---------------- packet ----------------
async function renderPacket() {
  if (!state.sid) return;
  $("#dlPacket").href = `/api/session/${state.sid}/packet.md`;
  $("#dlLedger").href = `/api/session/${state.sid}/ledger.csv`;
  const r = await fetch(`/api/session/${state.sid}/packet-preview`);
  const md = await r.text();
  $("#packet").innerHTML = window.marked ? marked.parse(esc(md).replace(/&gt;/g, ">")) : `<pre>${esc(md)}</pre>`;
  $$("#packet input[type=checkbox]").forEach((c) => (c.disabled = false));
}

// ---------------- wiring ----------------
$$(".tabs button").forEach((b) => b.addEventListener("click", () => {
  $$(".tabs button").forEach((x) => x.setAttribute("aria-selected", x === b));
  $$(".panel").forEach((p) => (p.hidden = p.id !== `tab-${b.dataset.tab}`));
}));
$$("#sevFilter button").forEach((b) => b.addEventListener("click", () => {
  $$("#sevFilter button").forEach((x) => x.classList.toggle("on", x === b));
  state.sev = b.dataset.sev;
  renderFlags(state.a);
}));
["#pace", "#salary"].forEach((s) => $(s).addEventListener("input", () => {
  $("#paceOut").textContent = `${(+$("#pace").value).toFixed(1)}×`;
  $("#salaryOut").textContent = pct(+$("#salary").value);
  reanalyze();
}));
["#extraIncome", "#extraExpenses", "#adminCost"].forEach((s) => $(s).addEventListener("change", reanalyze));
$$("#profileForm [data-p]").forEach((el) => el.addEventListener("change", () => {
  const k = el.dataset.p;
  state.profileEdits[k] = el.tagName === "SELECT" ? el.value : (el.value === "" ? null : +el.value);
  reanalyze();
}));
$("#ledgerSearch").addEventListener("input", () => { state.ledgerLimit = 150; renderLedger(); });
$("#ledgerKind").addEventListener("change", () => { state.ledgerLimit = 150; renderLedger(); });
$("#moreRows").addEventListener("click", () => { state.ledgerLimit += 300; renderLedger(); });
$("#printBtn").addEventListener("click", () => window.print());
$("#newBtn").addEventListener("click", () => {
  $("#dash").hidden = true; $("#start").hidden = false; $("#topActions").hidden = true;
});
$("#fileInput").addEventListener("change", (e) => uploadFiles(e.target.files));
const drop = $("#drop");
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => uploadFiles(e.dataTransfer.files));

loadSamples().catch((e) => { $("#startError").textContent = e.message; $("#startError").hidden = false; });

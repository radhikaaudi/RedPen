// Redpen frontend. Plain JS, no build step. All state lives in `state`; render functions redraw from it.

const $ = (sel) => document.querySelector(sel);
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmt = (n) => (Number.isInteger(n) ? String(n) : n.toFixed(1));
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

const MODEL_BADGE = {
  vision: ["Super VL", "badge-vision"],
  fast: ["Lightning", "badge-fast"],
  reasoning: ["Ultra", "badge-reason"],
};

const state = {
  models: {},
  rubric: null,
  students: [], // {id, name, files: File[], previews: string[], status, error, reading, grading}
  report: null,
  usage: [],
};
let nextId = 1;

// ------------------------------------------------------------------ API helpers

async function api(path, options = {}) {
  const res = await fetch(path, options);
  let body = null;
  try {
    body = await res.json();
  } catch (_) {}
  if (!res.ok) throw new Error(body?.detail || `Request failed (${res.status})`);
  if (body?.usage) addUsage(body.usage);
  return body;
}
const postJSON = (path, data) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

function toast(msg, ms = 3500) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("is-shown");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("is-shown"), ms);
}

// ------------------------------------------------------------------ dynamic island (live status pill)

const island = {
  show(text, { progress = null, role = null } = {}) {
    const el = $("#island");
    clearTimeout(island._t);
    $("#islandText").textContent = text;
    $("#islandBadge").innerHTML = role ? roleBadge(role) : "";
    el.classList.toggle("has-progress", progress !== null);
    if (progress !== null) $("#islandRing").style.setProperty("--p", progress);
    el.classList.remove("is-done");
    el.classList.add("is-open");
    island.fit();
  },
  done(text, ms = 2800) {
    const el = $("#island");
    $("#islandText").textContent = text;
    $("#islandBadge").innerHTML = "";
    el.classList.add("is-done");
    el.classList.add("is-open");
    island.fit();
    clearTimeout(island._t);
    island._t = setTimeout(island.hide, ms);
  },
  hide() {
    $("#island").classList.remove("is-open", "is-done");
  },
  fit() {
    requestAnimationFrame(() => ($("#island").style.width = $("#islandInner").scrollWidth + 6 + "px"));
  },
};

// ------------------------------------------------------------------ motion helpers

function countUp(root) {
  for (const el of root.querySelectorAll("[data-count]")) {
    if (reduceMotion) continue;
    const end = parseFloat(el.dataset.count);
    const dec = Number(el.dataset.dec || 0);
    const pre = el.dataset.pre || "";
    const suf = el.dataset.suf || "";
    const t0 = performance.now();
    const step = (t) => {
      const k = Math.min(1, (t - t0) / 900);
      el.textContent = pre + (end * (1 - Math.pow(1 - k, 3))).toFixed(dec) + suf;
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
}

function splitWords(el) {
  let i = 0;
  const walk = (node) => {
    for (const n of [...node.childNodes]) {
      if (n.nodeType !== Node.TEXT_NODE) {
        walk(n);
        continue;
      }
      const frag = document.createDocumentFragment();
      for (const part of n.textContent.split(/(\s+)/)) {
        if (!part) continue;
        if (/^\s+$/.test(part)) {
          frag.append(part);
          continue;
        }
        const w = Object.assign(document.createElement("span"), { className: "word", textContent: part });
        w.style.setProperty("--i", i++);
        frag.append(w);
      }
      n.replaceWith(frag);
    }
  };
  walk(el);
}

const revealer =
  "IntersectionObserver" in window
    ? new IntersectionObserver(
        (entries) => {
          for (const e of entries) {
            if (!e.isIntersecting) continue;
            e.target.classList.add("is-in");
            countUp(e.target);
            revealer.unobserve(e.target);
          }
        },
        { threshold: 0.12, rootMargin: "0px 0px -40px 0px" }
      )
    : null;

function reveal(el) {
  if (!revealer || reduceMotion) return el.classList.add("is-in");
  revealer.observe(el);
}

// Overlays fade/slide in; `hidden` is restored after the exit transition.
function openOverlay(el) {
  clearTimeout(el._t);
  el.classList.remove("hidden");
  requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add("is-open")));
  document.body.style.overflow = "hidden";
}
function closeOverlays() {
  for (const el of [$("#drawer"), $("#ledger")]) {
    if (el.classList.contains("hidden")) continue;
    el.classList.remove("is-open");
    el._t = setTimeout(() => el.classList.add("hidden"), reduceMotion ? 0 : 450);
  }
  document.body.style.overflow = "";
  openId = null;
}

// ------------------------------------------------------------------ model ledger

function modelRole(model) {
  for (const [role, id] of Object.entries(state.models)) if (id === model) return role;
  return "fast";
}
function roleBadge(role) {
  const [label, cls] = MODEL_BADGE[role];
  return `<span class="badge ${cls}">${label}</span>`;
}
const badgeFor = (model) => roleBadge(modelRole(model));

function addUsage(calls) {
  state.usage.push(...calls);
  const total = state.usage.reduce((a, c) => a + c.cost_usd, 0);
  $("#ledgerTotal").textContent = "$" + total.toFixed(3);
}
function renderLedger() {
  const calls = state.usage;
  if (!calls.length) {
    $("#ledgerBody").innerHTML = `<div class="well px-5 py-8 text-center text-sm text-ink-soft">No model calls yet. Build a rubric to start.</div>`;
    return;
  }
  const byModel = {};
  for (const c of calls) {
    const m = (byModel[c.model] ??= { calls: 0, tokens: 0, seconds: 0, cost: 0 });
    m.calls++;
    m.tokens += c.prompt_tokens + c.completion_tokens;
    m.seconds += c.seconds;
    m.cost += c.cost_usd;
  }
  const total = calls.reduce((a, c) => a + c.cost_usd, 0);
  const graded = state.students.filter((s) => s.grading).length;
  const perSheet = graded
    ? calls.filter((c) => ["Read handwriting", "Grade answers"].includes(c.step)).reduce((a, c) => a + c.cost_usd, 0) / graded
    : 0;
  $("#ledgerBody").innerHTML = `
    <div class="stagger mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
      ${tile("Total cost", "$" + total.toFixed(4), "", 0)}
      ${tile("Model calls", calls.length, "", 1)}
      ${tile("Sheets graded", graded, "", 2)}
      ${tile("Cost per sheet", graded ? "$" + perSheet.toFixed(4) : "—", "text-pen", 3)}
    </div>
    <h4 class="subhead">By model</h4>
    <div class="mb-6 space-y-2">
      ${Object.entries(byModel)
        .map(
          ([model, m]) => `<div class="tile flex flex-wrap items-center gap-3 text-sm">
            ${badgeFor(model)}<code class="text-xs text-ink-soft">${esc(model)}</code>
            <span class="ml-auto tabular-nums">${m.calls} calls · ${m.tokens.toLocaleString()} tokens · ${m.seconds.toFixed(1)}s · <b>$${m.cost.toFixed(4)}</b></span></div>`
        )
        .join("")}
    </div>
    <h4 class="subhead">Every call</h4>
    <div class="well overflow-x-auto"><table class="results-table w-full text-left text-xs">
      <thead><tr><th>Step</th><th>Model</th><th class="text-right">Tokens in/out</th><th class="text-right">Time</th><th class="text-right">Cost</th></tr></thead>
      <tbody>${calls
        .map(
          (c) => `<tr><td>${esc(c.step)}</td><td>${badgeFor(c.model)}</td>
          <td class="text-right tabular-nums">${c.prompt_tokens.toLocaleString()} / ${c.completion_tokens.toLocaleString()}</td>
          <td class="text-right tabular-nums">${c.seconds.toFixed(1)}s</td><td class="text-right tabular-nums">$${c.cost_usd.toFixed(4)}</td></tr>`
        )
        .join("")}</tbody></table></div>`;
  countUp($("#ledgerBody"));
}
function tile(label, value, tone = "", i = 0) {
  // Plain numbers ("72.5%", "$0.0101", "8") count up when shown.
  const m = String(value).match(/^(\$?)(\d+(?:\.(\d+))?)(%?)$/);
  const count = m ? ` data-count="${m[2]}" data-dec="${m[3]?.length || 0}" data-pre="${m[1]}" data-suf="${m[4]}"` : "";
  return `<div class="tile" style="--i:${i}"><div class="tile-label">${esc(label)}</div><div class="tile-value ${tone}"${count}>${esc(value)}</div></div>`;
}

// ------------------------------------------------------------------ step 1: rubric

async function buildRubric() {
  const answerKey = $("#answerKey").value.trim();
  if (!answerKey) return toast("Paste your answer key first.");
  const btn = $("#buildRubric");
  btn.disabled = true;
  $("#rubricStatus").innerHTML = `<span class="spinner"></span> Structuring your answer key…`;
  island.show("Building your rubric", { role: "fast" });
  try {
    const { rubric } = await postJSON("/api/rubric", { answer_key: answerKey });
    state.rubric = rubric;
    // A new rubric invalidates previous grading.
    for (const s of state.students) Object.assign(s, { status: "idle", reading: null, grading: null, error: null });
    state.report = null;
    $("#rubricStatus").textContent = `${rubric.questions.length} questions · ${fmt(rubric.total_marks)} marks`;
    island.done(`Rubric ready · ${rubric.questions.length} questions`);
    renderRubric();
    enableStep2();
    renderStudents();
    renderResults();
  } catch (e) {
    $("#rubricStatus").textContent = "";
    island.hide();
    toast(e.message, 6000);
  } finally {
    btn.disabled = false;
  }
}

function renderRubric() {
  const r = state.rubric;
  const el = $("#rubricView");
  el.classList.remove("hidden");
  el.innerHTML = `
    <div class="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
      <h3 class="font-display text-xl font-semibold">${esc(r.title)}</h3>
      <span class="text-sm text-ink-soft">Check the marking points — edit the answer key and rebuild if anything is off.</span>
    </div>
    <div class="stagger grid gap-4 md:grid-cols-2">
      ${r.questions
        .map(
          (q, i) => `<div class="rubric-card" style="--i:${i}">
            <div class="flex items-start justify-between gap-3">
              <p class="text-sm leading-relaxed"><span class="font-semibold text-pen">${esc(q.id)}.</span> ${esc(q.question)}</p>
              <span class="chip chip-wait">${fmt(q.max_marks)} marks</span>
            </div>
            <ul class="mt-3 space-y-2 border-t border-dashed border-sage-300 pt-3 text-sm">
              ${q.criteria.map((c) => `<li><span class="rubric-pts">${fmt(c.marks)}</span><span class="leading-relaxed">${esc(c.description)}</span></li>`).join("")}
            </ul>
          </div>`
        )
        .join("")}
    </div>`;
}

// ------------------------------------------------------------------ step 2: students

function enableStep2() {
  const s2 = $("#step2");
  s2.classList.remove("opacity-50");
  s2.removeAttribute("aria-disabled");
}

function nameFromFile(file) {
  return file.name
    .replace(/\.[^.]+$/, "")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function addStudent(name, files) {
  const s = { id: nextId++, name, files: [], previews: [], status: "idle", error: null, reading: null, grading: null };
  addPages(s, files);
  state.students.push(s);
  return s;
}
function addPages(s, files) {
  for (const f of files) {
    s.files.push(f);
    s.previews.push(URL.createObjectURL(f));
  }
  if (s.grading || s.reading) Object.assign(s, { status: "idle", reading: null, grading: null });
}

function onFiles(fileList) {
  const files = [...fileList].filter((f) => f.type.startsWith("image/"));
  if (!files.length) return toast("Please choose image files (JPG or PNG).");
  for (const f of files) addStudent(nameFromFile(f), [f]);
  renderStudents();
}

function renderStudents() {
  const list = $("#studentList");
  list.innerHTML = state.students
    .map(
      (s, i) => `<li class="student-row" data-id="${s.id}" style="--i:${i}">
        <div class="flex gap-1.5">${s.previews.map((p) => `<img src="${p}" alt="" class="thumb" />`).join("")}</div>
        <input value="${esc(s.name)}" data-act="rename" class="name-input" aria-label="Student name" />
        <span class="text-xs text-ink-soft">${s.files.length} page${s.files.length > 1 ? "s" : ""}</span>
        <label class="btn-ghost btn-sm cursor-pointer">+ page<input type="file" accept="image/*" multiple class="hidden" data-act="addpage" /></label>
        <button class="btn-ghost btn-sm" data-act="remove">Remove</button>
      </li>`
    )
    .join("");
  const n = state.students.length;
  const btn = $("#gradeAll");
  btn.disabled = !n || !state.rubric || grading;
  btn.textContent = n ? `Grade all ${n} sheet${n > 1 ? "s" : ""}` : "Grade all";
}

$("#studentList").addEventListener("input", (e) => {
  if (e.target.dataset.act !== "rename") return;
  const s = state.students.find((x) => x.id == e.target.closest("li").dataset.id);
  s.name = e.target.value.trim() || s.name;
  renderResults();
});
$("#studentList").addEventListener("change", (e) => {
  if (e.target.dataset.act !== "addpage") return;
  const s = state.students.find((x) => x.id == e.target.closest("li").dataset.id);
  addPages(s, [...e.target.files]);
  renderStudents();
  renderResults();
});
$("#studentList").addEventListener("click", (e) => {
  if (e.target.dataset.act !== "remove") return;
  const id = e.target.closest("li").dataset.id;
  state.students = state.students.filter((x) => x.id != id);
  renderStudents();
  renderResults();
});

// ------------------------------------------------------------------ grading

let grading = false;

async function gradeOne(s) {
  try {
    if (!s.reading) {
      s.status = "reading";
      renderResults();
      const fd = new FormData();
      fd.append("rubric", JSON.stringify(state.rubric));
      s.files.forEach((f) => fd.append("pages", f, f.name));
      s.reading = (await api("/api/read", { method: "POST", body: fd })).reading;
    }
    s.status = "grading";
    renderResults();
    s.grading = (await postJSON("/api/grade", { rubric: state.rubric, reading: s.reading })).grading;
    s.status = "done";
  } catch (e) {
    s.status = "error";
    s.error = e.message;
  }
  renderResults();
}

async function gradeAll() {
  const todo = state.students.filter((s) => s.status !== "done");
  if (!todo.length) return toast("All sheets are already graded.");
  grading = true;
  renderStudents();
  $("#step3").classList.remove("hidden");
  $("#step3").scrollIntoView({ behavior: "smooth", block: "start" });
  const started = Date.now();
  let done = 0;
  const update = () => {
    $("#gradeStatus").innerHTML = `<span class="spinner"></span> Graded ${done} of ${todo.length}…`;
    island.show(`Grading ${done} of ${todo.length} sheets`, { progress: done / todo.length });
  };
  update();
  const queue = [...todo];
  const worker = async () => {
    while (queue.length) {
      await gradeOne(queue.shift());
      done++;
      update();
    }
  };
  await Promise.all([worker(), worker(), worker()]); // 3 sheets in parallel
  grading = false;
  const secs = Math.round((Date.now() - started) / 1000);
  const failed = state.students.filter((s) => s.status === "error").length;
  $("#gradeStatus").textContent = `Done in ${secs}s${failed ? ` · ${failed} failed — click Retry` : ""}`;
  island.done(failed ? `${failed} sheet${failed > 1 ? "s" : ""} failed — retry below` : `${todo.length} sheets graded in ${secs}s`, 3600);
  renderStudents();
  if (state.students.some((s) => s.grading)) $("#step4").classList.remove("hidden");
}

// ------------------------------------------------------------------ step 3: results

function recompute(g) {
  // Teacher overrides change marks; totals are always recomputed here, never trusted from a model.
  for (const q of g.questions) {
    q.score = q.criteria.reduce((a, c) => a + c.awarded, 0);
    q.needs_review = q.review_reasons.length > 0 && !q.checked;
    // Once the teacher has set or confirmed the marks (or stepped in), the answer no longer needs them.
    if (q.checked) q.needs_teacher = q.needs_intervention = false;
  }
  g.score = g.questions.reduce((a, q) => a + q.score, 0);
  g.percent = g.total ? Math.round((1000 * g.score) / g.total) / 10 : 0;
  g.needs_review = g.questions.filter((q) => q.needs_review).length;
  g.needs_teacher = g.questions.filter((q) => q.needs_teacher).length;
  g.needs_intervention = g.questions.filter((q) => q.needs_intervention).length;
}

function statusChip(s) {
  switch (s.status) {
    case "reading":
      return `<span class="chip chip-run"><span class="spinner"></span> Reading · Super VL</span>`;
    case "grading":
      return `<span class="chip chip-run"><span class="spinner"></span> Grading · Ultra</span>`;
    case "done":
      if (s.grading.needs_teacher) return `<span class="chip chip-err">✋ ${s.grading.needs_teacher} for you to mark</span>`;
      if (s.grading.needs_intervention) return `<span class="chip chip-err">🧭 Step in · ${s.grading.needs_intervention}</span>`;
      return s.grading.needs_review
        ? `<span class="chip chip-warn">⚑ ${s.grading.needs_review} to check</span>`
        : `<span class="chip chip-ok">✓ Done</span>`;
    case "error":
      return `<span class="chip chip-err" title="${esc(s.error)}">Failed</span> <button class="link ml-1 text-xs" data-retry="${s.id}">Retry</button>`;
    default:
      return `<span class="chip chip-wait">Queued</span>`;
  }
}

function renderResults() {
  if (!state.rubric) return;
  const qs = state.rubric.questions;
  $("#resultsHead").innerHTML = `<th>Student</th>${qs
    .map((q) => `<th class="text-center">${esc(q.id)}<span class="block font-normal normal-case tracking-normal text-ink-soft">/${fmt(q.max_marks)}</span></th>`)
    .join("")}<th class="text-right">Total</th><th class="pl-4">Status</th>`;
  $("#resultsBody").innerHTML = state.students
    .map((s) => {
      const g = s.grading;
      const cells = qs
        .map((q) => {
          const gq = g?.questions.find((x) => x.question_id === q.id);
          if (!gq) return `<td class="text-center text-sage-400">·</td>`;
          const pct = q.max_marks ? gq.score / q.max_marks : 0;
          const tone = pct >= 0.99 ? "score-full" : pct === 0 ? "score-zero" : "";
          if (gq.needs_teacher) return `<td class="text-center"><span class="hand-cell" title="Couldn't read — needs you to mark it">✋</span></td>`;
          const mark = gq.needs_intervention
            ? '<span class="flag-star" title="Right thinking, wrong answer — teacher intervention">🧭</span>'
            : gq.needs_review ? '<span class="flag-star" title="Needs a check">*</span>' : "";
          return `<td class="text-center tabular-nums ${tone}">${fmt(gq.score)}${mark}</td>`;
        })
        .join("");
      return `<tr data-open="${g ? s.id : ""}">
        <td class="font-semibold">${esc(s.name)} ${g ? '<span class="open-hint">→</span>' : ""}</td>${cells}
        <td class="text-right font-display text-base font-semibold tabular-nums">${g ? `${fmt(g.score)}<span class="text-ink-soft">/${fmt(g.total)}</span>` : ""}</td>
        <td class="pl-4">${statusChip(s)}</td></tr>`;
    })
    .join("");
}

$("#resultsBody").addEventListener("click", async (e) => {
  const retry = e.target.closest("[data-retry]");
  if (retry) {
    const s = state.students.find((x) => x.id == retry.dataset.retry);
    await gradeOne(s);
    if (s.grading) $("#step4").classList.remove("hidden");
    return;
  }
  const row = e.target.closest("[data-open]");
  if (row?.dataset.open) openStudent(Number(row.dataset.open));
});

function exportCsv() {
  const qs = state.rubric.questions;
  const rows = [["Student", ...qs.map((q) => `${q.id} (/${q.max_marks})`), "Total", "Percent", "Needs check"]];
  for (const s of state.students.filter((x) => x.grading)) {
    const g = s.grading;
    rows.push([s.name, ...qs.map((q) => g.questions.find((x) => x.question_id === q.id)?.score ?? ""), g.score, g.percent, g.needs_review]);
  }
  const csv = rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
  const a = Object.assign(document.createElement("a"), {
    href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })),
    download: `${state.rubric.title || "marks"}.csv`.replace(/[^\w.\- ]/g, ""),
  });
  a.click();
}

// ------------------------------------------------------------------ student drawer

let openId = null;
let animateDrawer = false;
let bumped = null; // "q:c" of the mark the teacher just changed, so it can pulse

function highlightUnclear(text, words) {
  // One pass over the escaped text, whole words only, so a short word like "to" can't match inside
  // markup inserted for another word.
  const alts = [...new Set((words || []).filter(Boolean))]
    .sort((a, b) => b.length - a.length)
    .map((w) => esc(w).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  alts.push("\\[\\?\\]");
  const re = new RegExp(`(?<!\\w)(?:${alts.join("|")})(?!\\w)`, "g");
  return esc(text).replace(re, (m) => `<span class="unclear" title="${m === "[?]" ? "Unreadable" : "Hard to read"}">${m}</span>`);
}

// Sentiment = the direction of the student's thinking, judged separately from the final answer.
const SENTIMENT = {
  right_direction: ["Right direction", "chip-ok"],
  partly_right: ["Partly right direction", "chip-warn"],
  wrong_direction: ["Wrong direction", "chip-err"],
  unreadable: ["Couldn't read", "chip-wait"],
  not_attempted: ["Not attempted", "chip-wait"],
};

function sentimentBlock(q) {
  if (!SENTIMENT[q.sentiment]) return ""; // graded before sentiment analysis existed
  const [label, cls] = SENTIMENT[q.sentiment];
  const answer = q.answer_correct === true ? `<span class="chip chip-ok">Answer ✓</span>` : q.answer_correct === false ? `<span class="chip chip-err">Answer ✗</span>` : "";
  const steps = (q.steps || [])
    .map(
      (st, i) => `<li class="step ${st.ok ? "step-ok" : "step-bad"}">
        <span class="step-n">${i + 1}</span>
        <div class="min-w-0"><code class="step-work">${esc(st.work)}</code>${st.note ? `<p class="mt-0.5 text-xs leading-relaxed text-ink-soft">${esc(st.note)}</p>` : ""}</div>
        <span class="step-mark">${st.ok ? "✓" : "✗"}</span></li>`
    )
    .join("");
  return `<div class="approach mt-4">
      <div class="flex flex-wrap items-center gap-2">
        <span class="chip ${cls}" title="Was the student's thinking heading the right way, whatever the final answer?">Sentiment · ${label}</span>
        ${answer}
      </div>
      ${q.sentiment_note ? `<p class="mt-2 text-sm leading-relaxed">${esc(q.sentiment_note)}</p>` : ""}
      ${steps ? `<p class="mb-1.5 mt-3 text-xs font-semibold uppercase tracking-wider text-sage-600">Step marking — the working, line by line</p><ol class="steps">${steps}</ol>` : ""}
    </div>`;
}

function flagBlock(q) {
  if (!q.needs_review) return "";
  const teacher = q.needs_teacher ? q.review_reasons[0] : null;
  const step = q.needs_intervention ? q.review_reasons.find((r) => r.startsWith("Right thinking, wrong answer")) : null;
  const others = q.review_reasons.filter((r) => r !== teacher && r !== step);
  const label = teacher ? "I've marked it" : step ? "I've stepped in" : "Mark as checked";
  const button = `<button class="ml-auto text-xs font-semibold underline" data-check="${esc(q.question_id)}">${label}</button>`;
  return (
    (teacher ? `<div class="flag flag-teacher"><span><b>✋ Teacher needed.</b> ${esc(teacher)}. The marks below are only provisional.</span>${others.length ? "" : button}</div>` : "") +
    (step ? `<div class="flag flag-teacher"><span><b>🧭 Teacher intervention.</b> The student's thinking was in the right direction, but the answer came out wrong. A quick word should fix it — and check the step marks.</span>${others.length ? "" : button}</div>` : "") +
    (others.length ? `<div class="flag"><span>⚑ ${esc(others.join(" · "))}${others.some((r) => r.includes("please")) ? "" : " — please check"}</span>${button}</div>` : "")
  );
}

function openStudent(id) {
  openId = id;
  animateDrawer = true;
  renderDrawer();
  openOverlay($("#drawer"));
}

function renderDrawer() {
  const s = state.students.find((x) => x.id === openId);
  if (!s?.grading) return;
  const g = s.grading;
  $("#drawerTitle").innerHTML = `<div class="flex flex-wrap items-baseline gap-x-3">
      <h3 class="truncate font-display text-xl font-semibold">${esc(s.name)}</h3>
      <span class="font-hand text-4xl leading-none text-pen">${fmt(g.score)}/${fmt(g.total)}</span>
      <span class="text-sm text-ink-soft">${g.percent}%${g.needs_teacher ? ` · <span class="text-pen font-semibold">✋ ${g.needs_teacher} for you to mark</span>` : ""}${g.needs_intervention ? ` · <span class="text-pen font-semibold">🧭 ${g.needs_intervention} to step in</span>` : ""}${g.needs_review ? ` · <span class="text-brass font-semibold">⚑ ${g.needs_review} answer${g.needs_review > 1 ? "s" : ""} to check</span>` : ""}</span></div>`;

  const pages = s.previews
    .map((p, i) => `<a href="${p}" target="_blank" rel="noopener"><img src="${p}" alt="Page ${i + 1} of ${esc(s.name)}'s answer sheet" class="page-img" /></a>`)
    .join("");

  const questions = g.questions
    .map((q, qi) => {
      const rq = state.rubric.questions.find((x) => x.id === q.question_id);
      const rd = s.reading.answers.find((x) => x.question_id === q.question_id) || {};
      const criteria = q.criteria
        .map((c, ci) => {
          const [icon, cls] = c.awarded >= c.max ? ["✓", "crit-full"] : c.awarded > 0 ? ["½", "crit-part"] : ["✗", "crit-none"];
          const bump = bumped === `${q.question_id}:${ci}` ? " bump" : "";
          return `<li class="crit">
            <div class="flex items-start gap-3">
              <span class="crit-icon ${cls}">${icon}</span>
              <div class="min-w-0 flex-1">
                <p class="text-sm font-medium leading-relaxed">${esc(c.description)}</p>
                ${c.evidence ? `<p class="evidence mt-2 rounded-r-md px-2.5 py-1.5 text-sm italic">“${esc(c.evidence)}”</p>` : ""}
                ${c.reason ? `<p class="mt-1.5 text-xs leading-relaxed text-ink-soft">${esc(c.reason)}</p>` : ""}
              </div>
              <div class="flex flex-none items-center gap-1.5">
                <button class="mark-btn" data-mark="-" data-q="${esc(q.question_id)}" data-c="${ci}" aria-label="Decrease mark">−</button>
                <span class="mark-val${bump}">${fmt(c.awarded)}/${fmt(c.max)}</span>
                <button class="mark-btn" data-mark="+" data-q="${esc(q.question_id)}" data-c="${ci}" aria-label="Increase mark">+</button>
              </div>
            </div>
            ${c.teacher_adjusted ? `<p class="mt-1.5 pl-9 text-xs font-semibold text-pen">✎ Adjusted by teacher</p>` : ""}
          </li>`;
        })
        .join("");
      return `<section class="q-card" style="--i:${qi}">
        <div class="flex items-start justify-between gap-3">
          <p class="text-sm leading-relaxed"><span class="font-semibold text-pen">${esc(q.question_id)}.</span> ${esc(rq?.question)}</p>
          <span class="font-hand text-3xl leading-none text-pen">${fmt(q.score)}/${fmt(q.max)}</span>
        </div>
        ${flagBlock(q)}
        <div class="mt-4">
          <p class="mb-1.5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-sage-600">What the student wrote ${badgeFor(state.models.vision)}</p>
          <p class="transcript">${rd.attempted ? highlightUnclear(rd.transcription, rd.unclear_words) : '<span class="text-ink-soft">Not attempted</span>'}</p>
          ${rd.diagram ? `<p class="mt-1.5 text-xs text-ink-soft">Diagram/working: ${esc(rd.diagram)}</p>` : ""}
        </div>
        ${sentimentBlock(q)}
        <p class="mb-1.5 mt-5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-sage-600">Marking ${badgeFor(state.models.reasoning)}</p>
        <ul class="space-y-2">${criteria}</ul>
        ${q.misconception ? `<p class="mt-4 text-sm leading-relaxed"><span class="chip chip-err">Misconception</span> ${esc(q.misconception)}</p>` : ""}
        ${q.feedback ? `<p class="mt-2 text-sm leading-relaxed text-ink-soft">${esc(q.feedback)}</p>` : ""}
      </section>`;
    })
    .join("");

  $("#drawerBody").innerHTML = `
    <div class="pages-pane overflow-y-auto p-5"><div class="space-y-4">${pages}</div></div>
    <div class="overflow-y-auto p-5"><div class="${animateDrawer ? "stagger " : ""}space-y-5">
      ${questions}
      <section class="slip-card" style="--i:${g.questions.length}">
        <p class="text-xs font-semibold uppercase tracking-wider text-sage-600">Feedback for ${esc(s.name.split(" ")[0])}</p>
        <p id="slipText" class="mt-2 text-sm leading-relaxed">${esc(g.overall_feedback)}</p>
        ${g.next_step ? `<p class="mt-2 text-sm leading-relaxed"><span class="font-semibold">Next step:</span> ${esc(g.next_step)}</p>` : ""}
        <div class="mt-4 flex flex-wrap items-center gap-2">
          <button class="btn-ghost btn-sm" data-print="${s.id}">Print feedback slip</button>
          <select id="lang" class="select">
            ${["Hindi", "Tamil", "Bengali", "Marathi", "Spanish", "French"].map((l) => `<option>${l}</option>`).join("")}
          </select>
          <button class="btn-ghost btn-sm" data-translate="${s.id}">Translate for parents</button>
          ${badgeFor(state.models.reasoning)}
        </div>
        <p id="translation" class="transcript mt-4 hidden whitespace-pre-line font-sans"></p>
      </section>
    </div></div>`;
  animateDrawer = false;
  bumped = null;
}

$("#drawerBody").addEventListener("click", async (e) => {
  const s = state.students.find((x) => x.id === openId);
  if (!s) return;
  const markBtn = e.target.closest("[data-mark]");
  if (markBtn) {
    const q = s.grading.questions.find((x) => x.question_id === markBtn.dataset.q);
    const c = q.criteria[Number(markBtn.dataset.c)];
    const next = c.awarded + (markBtn.dataset.mark === "+" ? 0.5 : -0.5);
    if (next < 0 || next > c.max) return;
    c.awarded = next;
    c.teacher_adjusted = true;
    q.checked = true;
    recompute(s.grading);
    if (state.report) {
      state.report = null;
      renderReport();
      $("#reportStatus").textContent = "Marks changed — regenerate insights to include them.";
    }
    bumped = `${q.question_id}:${markBtn.dataset.c}`;
    renderDrawer();
    renderResults();
    return;
  }
  const check = e.target.closest("[data-check]");
  if (check) {
    s.grading.questions.find((x) => x.question_id === check.dataset.check).checked = true;
    recompute(s.grading);
    renderDrawer();
    renderResults();
    return;
  }
  if (e.target.closest("[data-print]")) return printSlips([s]);
  if (e.target.closest("[data-translate]")) {
    const out = $("#translation");
    const g = s.grading;
    const language = $("#lang").value;
    const text = `Student: ${s.name}\nTest: ${state.rubric.title}\nScore: ${fmt(g.score)}/${fmt(g.total)}\nFeedback: ${g.overall_feedback}\nNext step: ${g.next_step}`;
    out.classList.remove("hidden");
    out.innerHTML = `<span class="spinner"></span> Translating…`;
    island.show(`Translating into ${language}`, { role: "reasoning" });
    try {
      const { text: translated } = await postJSON("/api/translate", { text, language });
      out.textContent = translated;
      island.done(`Translated into ${language}`);
    } catch (err) {
      out.textContent = err.message;
      island.hide();
    }
  }
});

function printSlips(students) {
  $("#printArea").innerHTML = students
    .map((s) => {
      const g = s.grading;
      return `<div class="slip" style="font-family: Inter, sans-serif; padding: 32px; color: #2f2a25">
        <div style="display:flex; justify-content:space-between; align-items:baseline; border-bottom: 2px solid #7a2232; padding-bottom: 8px">
          <div><div style="font-family: Fraunces, Georgia, serif; font-size: 24px; font-weight: 600">${esc(s.name)}</div><div style="color:#6f675c">${esc(state.rubric.title)}</div></div>
          <div style="font-family: Caveat, cursive; font-size: 44px; color: #7a2232">${fmt(g.score)}/${fmt(g.total)}</div>
        </div>
        <table style="width:100%; margin-top: 16px; border-collapse: collapse; font-size: 13px">
          ${g.questions
            .map(
              (q) => `<tr style="border-bottom: 1px solid #e1d4be"><td style="padding: 8px 8px 8px 0; width: 48px; font-weight: 600">${esc(q.question_id)}</td>
              <td style="padding: 8px 0">${esc(q.feedback)}</td><td style="padding: 8px 0 8px 8px; text-align: right; font-weight: 600; white-space: nowrap">${fmt(q.score)}/${fmt(q.max)}</td></tr>`
            )
            .join("")}
        </table>
        <p style="margin-top: 16px; font-size: 14px; line-height: 1.6">${esc(g.overall_feedback)}</p>
        ${g.next_step ? `<p style="margin-top: 8px; font-size: 14px"><b>Next step:</b> ${esc(g.next_step)}</p>` : ""}
        <p style="margin-top: 24px; font-size: 11px; color: #6f675c">Marked with Redpen and checked by your teacher.</p>
      </div>`;
    })
    .join("");
  window.print();
}

// ------------------------------------------------------------------ step 4: class insights

async function buildReport() {
  const graded = state.students.filter((s) => s.grading);
  if (!graded.length) return toast("Grade some sheets first.");
  const btn = $("#buildReport");
  btn.disabled = true;
  $("#reportStatus").innerHTML = `<span class="spinner"></span> Looking for patterns across ${graded.length} students…`;
  island.show(`Finding patterns across ${graded.length} students`, { role: "reasoning" });
  try {
    const { report } = await postJSON("/api/report", {
      rubric: state.rubric,
      students: graded.map((s) => ({ name: s.name, grading: s.grading })),
    });
    state.report = report;
    $("#reportStatus").textContent = "";
    island.done("Class insights ready");
    renderReport();
  } catch (e) {
    $("#reportStatus").textContent = "";
    island.hide();
    toast(e.message, 6000);
  } finally {
    btn.disabled = false;
  }
}

function sentimentReport(st) {
  if (!st.sentiment) return "";
  const total = Object.values(st.sentiment).reduce((a, b) => a + b, 0) || 1;
  const tones = { right_direction: "bar-ok", partly_right: "bar-mid", wrong_direction: "bar-low", unreadable: "bar-ink", not_attempted: "bar-ink" };
  const rows = Object.entries(st.sentiment)
    .filter(([, n]) => n)
    .map(([k, n], i) => {
      const pct = Math.round((100 * n) / total);
      return `<div><div class="mb-1 flex justify-between text-sm"><span>${SENTIMENT[k][0]}</span><span class="font-semibold tabular-nums">${n}</span></div>
        <div class="bar"><span class="${tones[k]}" style="width:${pct}%; --i:${i}"></span></div></div>`;
    })
    .join("");
  const steps = (st.intervention || [])
    .map(
      (x) => `<li class="tile text-sm leading-relaxed"><div class="flex flex-wrap items-center gap-2"><span class="font-semibold text-pen">${esc(x.name)}</span>
        <span class="chip chip-ok">Right direction</span><span class="chip chip-err">Answer ✗</span><span class="text-xs text-ink-soft">${esc(x.question_id)}</span></div>
        ${x.note ? `<p class="mt-1 text-ink-soft">${esc(x.note)}</p>` : ""}</li>`
    )
    .join("");
  return `<div class="mt-8 grid gap-8 lg:grid-cols-2">
      <div class="soft-card">
        <h3 class="subhead">Sentiment — how students were thinking</h3>
        <p class="mb-3 text-sm leading-relaxed text-ink-soft">Was each answer's thinking heading the right way, whatever the final answer?</p>
        <div class="space-y-3">${rows}</div>
      </div>
      <div class="soft-card">
        <h3 class="subhead">Right thinking, wrong answer — step in</h3>
        <p class="mb-3 text-sm leading-relaxed text-ink-soft">These students were thinking the right way but the answer came out wrong. A quick word from you should fix it.</p>
        ${steps ? `<ul class="space-y-2">${steps}</ul>` : `<p class="text-sm">No answers need an intervention.</p>`}
      </div>
    </div>`;
}

function renderReport() {
  const r = state.report;
  if (!r) return ($("#reportView").innerHTML = "");
  const st = r.stats;
  const graded = state.students.filter((s) => s.grading);
  $("#reportView").innerHTML = `
    ${r.headline ? `<p class="headline mb-6">${esc(r.headline)}</p>` : ""}
    <div class="stagger grid grid-cols-2 gap-3 sm:grid-cols-4">
      ${tile("Class average", st.average_percent + "%", "text-pen", 0)}
      ${tile("Highest / lowest", `${st.highest}% / ${st.lowest}%`, "", 1)}
      ${tile("Teacher intervention", (st.intervention || []).length, (st.intervention || []).length ? "text-pen" : "", 2)}
      ${tile("Unreadable — for you", st.needs_teacher ?? 0, st.needs_teacher ? "text-pen" : "", 3)}
    </div>
    ${sentimentReport(st)}

    <div class="mt-8 grid gap-8 lg:grid-cols-2">
      <div class="soft-card">
        <h3 class="subhead">How each question went</h3>
        <div class="space-y-4">${st.per_question
          .map((q, i) => {
            const cls = q.average_percent >= 75 ? "bar-ok" : q.average_percent >= 50 ? "bar-mid" : "bar-low";
            return `<div><div class="mb-1.5 flex justify-between gap-3 text-sm"><span class="truncate"><b class="text-pen">${esc(q.question_id)}</b> ${esc(q.question)}</span>
              <span class="flex-none font-semibold tabular-nums">${q.average_percent}%</span></div>
              <div class="bar"><span class="${cls}" style="width:${q.average_percent}%; --i:${i}"></span></div>
              <p class="mt-1 text-xs text-ink-soft">${q.full_marks} full marks · ${q.zero} scored zero</p></div>`;
          })
          .join("")}</div>
      </div>
      <div class="soft-card">
        <h3 class="subhead">Score distribution</h3>
        <div class="space-y-2">${graded
          .slice()
          .sort((a, b) => b.grading.percent - a.grading.percent)
          .map(
            (s, i) => `<div class="flex items-center gap-3 text-sm"><span class="w-28 truncate sm:w-32">${esc(s.name)}</span>
            <div class="bar flex-1"><span class="${s.grading.percent >= 40 ? "bar-ink" : "bar-low"}" style="width:${s.grading.percent}%; --i:${i}"></span></div>
            <span class="w-12 text-right font-semibold tabular-nums">${s.grading.percent}%</span></div>`
          )
          .join("")}</div>
      </div>
    </div>

    ${
      r.misconceptions?.length
        ? `<h3 class="subhead mt-10">Shared misconceptions</h3>
      <div class="stagger grid gap-4 md:grid-cols-2">${r.misconceptions
        .map(
          (m, i) => `<div class="soft-card" style="--i:${i}">
          <div class="flex items-start justify-between gap-3"><p class="font-semibold leading-snug">${esc(m.label)}</p><span class="chip chip-err">${m.students.length} student${m.students.length > 1 ? "s" : ""} · ${esc(m.question_id)}</span></div>
          <p class="mt-2 text-sm leading-relaxed text-ink-soft">${esc(m.explanation)}</p>
          <div class="mt-3 flex flex-wrap gap-1.5">${m.students.map((n) => `<span class="chip chip-wait">${esc(n)}</span>`).join("")}</div></div>`
        )
        .join("")}</div>`
        : ""
    }

    <div class="mt-10 grid gap-8 lg:grid-cols-[1.4fr_1fr]">
      <div>
        <h3 class="subhead">Reteach plan for tomorrow</h3>
        <ol class="stagger space-y-3">${(r.reteach_plan || [])
          .map(
            (p, i) => `<li class="soft-card flex gap-4" style="--i:${i}"><span class="plan-num">${i + 1}</span><div>
            <p class="font-semibold">${esc(p.topic)}</p>
            <p class="mt-1 text-sm leading-relaxed text-ink-soft">${esc(p.why)}</p>
            <p class="mt-2 text-sm leading-relaxed"><span class="chip chip-ok">10-minute activity</span> ${esc(p.activity)}</p></div></li>`
          )
          .join("")}</ol>
      </div>
      <div>
        <h3 class="subhead">Students to support</h3>
        <ul class="space-y-2">${(r.students_to_support || [])
          .map((x) => `<li class="tile text-sm leading-relaxed"><span class="font-semibold text-pen">${esc(x.name)}</span> — ${esc(x.reason)}</li>`)
          .join("")}</ul>
        ${
          r.strengths?.length
            ? `<h3 class="subhead mt-8">What the class did well</h3><ul class="space-y-2 text-sm">${r.strengths
                .map((x) => `<li class="flex gap-2 leading-relaxed"><span class="text-sage-600">✓</span><span>${esc(x)}</span></li>`)
                .join("")}</ul>`
            : ""
        }
        <button class="btn-ghost mt-8 w-full" id="printAll">Print all feedback slips</button>
      </div>
    </div>`;
  $("#printAll").onclick = () => printSlips(graded);
  countUp($("#reportView"));
}

// ------------------------------------------------------------------ sample class

async function loadSample(set = "neat") {
  const btn = { messy: $("#tryMessy"), maths: $("#tryMaths") }[set] || $("#trySample");
  const label = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "Loading sample class…";
  island.show({ messy: "Loading messy handwriting samples", maths: "Loading a maths test" }[set] || "Loading a sample class");
  try {
    const sample = await api(`/api/sample?set=${set}`);
    $("#answerKey").value = sample.answer_key;
    state.students = [];
    for (const st of sample.students) {
      const files = await Promise.all(
        st.pages.map(async (url) => {
          const blob = await (await fetch(url)).blob();
          return new File([blob], url.split("/").pop(), { type: blob.type || "image/jpeg" });
        })
      );
      addStudent(st.name, files);
    }
    $("#step1").scrollIntoView({ behavior: "smooth", block: "start" });
    await buildRubric();
    const kind = { messy: " — messy handwriting", maths: " — maths, with step marking" }[set] || "";
    toast(`Sample class of ${sample.students.length} loaded${kind}. Press “Grade all” to start.`);
    $("#step2").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    island.hide();
    toast(e.message, 6000);
  } finally {
    btn.disabled = false;
    btn.innerHTML = label;
  }
}

// ------------------------------------------------------------------ wiring

$("#trySample").onclick = () => loadSample("neat");
$("#tryMessy").onclick = () => loadSample("messy");
$("#tryMaths").onclick = () => loadSample("maths");
$("#buildRubric").onclick = buildRubric;
$("#gradeAll").onclick = gradeAll;
$("#buildReport").onclick = buildReport;
$("#exportCsv").onclick = exportCsv;
$("#fileInput").onchange = (e) => {
  onFiles(e.target.files);
  e.target.value = "";
};
const dz = $("#dropzone");
dz.addEventListener("dragover", (e) => {
  e.preventDefault();
  dz.classList.add("is-over");
});
dz.addEventListener("dragleave", () => dz.classList.remove("is-over"));
dz.addEventListener("drop", (e) => {
  e.preventDefault();
  dz.classList.remove("is-over");
  onFiles(e.dataTransfer.files);
});
$("#ledgerBtn").onclick = () => {
  renderLedger();
  openOverlay($("#ledger"));
};
document.addEventListener("click", (e) => {
  if (e.target.closest("[data-close]")) closeOverlays();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeOverlays();
});

// ------------------------------------------------------------------ hero motion

splitWords($("#heroTitle"));
document.querySelectorAll("[data-reveal]").forEach(reveal);

if (!reduceMotion && matchMedia("(hover: hover) and (pointer: fine)").matches) {
  // Magnetic buttons: drift a few pixels toward the pointer.
  for (const b of document.querySelectorAll(".magnetic")) {
    b.addEventListener("mousemove", (e) => {
      const r = b.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - 0.5;
      const y = (e.clientY - r.top) / r.height - 0.5;
      b.style.translate = `${x * 10}px ${y * 8}px`;
    });
    b.addEventListener("mouseleave", () => (b.style.translate = ""));
  }
  // The sheet stack tilts with the pointer.
  const hero = $("#hero");
  const stack = $("#sheetStack");
  hero.addEventListener("mousemove", (e) => {
    const r = stack.getBoundingClientRect();
    const x = (e.clientX - (r.left + r.width / 2)) / window.innerWidth;
    const y = (e.clientY - (r.top + r.height / 2)) / window.innerHeight;
    stack.style.setProperty("--ry", `${x * 14}deg`);
    stack.style.setProperty("--rx", `${-y * 10}deg`);
  });
  hero.addEventListener("mouseleave", () => {
    stack.style.setProperty("--ry", "0deg");
    stack.style.setProperty("--rx", "0deg");
  });
}

fetch("/api/health")
  .then((r) => r.json())
  .then((h) => (state.models = h.models))
  .catch(() => {});

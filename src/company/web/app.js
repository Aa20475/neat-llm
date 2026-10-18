"use strict";
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const short = value => String(value || "").slice(0, 8);
const pretty = value => typeof value === "string" ? value : JSON.stringify(value, null, 2);
const num = value => Number(value || 0).toLocaleString();
const statusLabels = {retained:"Promoted",qualified:"Passed · not active",pending:"Proposed",proposed:"Proposal created",no_change:"No change",evaluating:"Evaluating",rejected:"Rejected",revoked:"Promotion revoked",duplicate:"Duplicate · skipped",active:"Active",stale:"Outdated"};
const badge = (status, text = statusLabels[status] || status) => `<span class="badge ${esc(status)}">${esc(text)}</span>`;
const date = value => value ? new Date(value).toLocaleTimeString([], {hour:"2-digit", minute:"2-digit", second:"2-digit"}) : "—";
const empty = (title, text = "") => `<div class="empty"><strong>${esc(title)}</strong>${esc(text)}</div>`;
const pre = value => `<pre>${esc(pretty(value))}</pre>`;
let state, replay, selectedRun, selectedWorker = null, selectedProposal, currentView = "runs", refreshing = false, selectedThread, chatSubmitting = false, reflectionSubmitting = false;
function companyBusy() {return state.runs.some(run => run.status === "running") || state.reflections.some(row => row.status === "running") || (state.actions || []).some(row => row.status === "running") || (state.chat_turns || []).some(row => row.status === "running");}
function runStatus(run) {return run.status === "completed" && run.grade ? (run.grade.passed ? "pass" : "fail") : run.status;}
async function fetchJSON(path) {const response = await fetch(path); if (!response.ok) throw new Error(`Could not read local records (${response.status}). Initialize the organization first.`); return response.json();}
function renderStats() {
  const scored = state.runs.filter(run => run.grade && ["learning","validation"].includes(run.split));
  const passed = scored.filter(run => run.grade.passed).length;
  const judgeUsage = state.proposals.map(row => row.evaluation?.judge?.usage).filter(Boolean);
  const calls = state.runs.reduce((sum, run) => sum + (run.usage?.model_calls || 0), 0) + state.reflections.reduce((sum, row) => sum + (row.usage?.model_calls || 0), 0) + judgeUsage.reduce((sum, usage) => sum + (usage.model_calls || 0), 0);
  const tokens = state.runs.reduce((sum, run) => sum + (run.usage?.input_tokens || 0) + (run.usage?.output_tokens || 0), 0) + state.reflections.reduce((sum, row) => sum + (row.usage?.input_tokens || 0) + (row.usage?.output_tokens || 0), 0) + judgeUsage.reduce((sum, usage) => sum + (usage.input_tokens || 0) + (usage.output_tokens || 0), 0);
  const active = state.active;
  $("#stats").innerHTML = [
    ["Active organization", esc(active.manifest.label), `${short(active.version_id)} · generation ${active.generation}`, "mint"],
    ["Saved roles", active.manifest.topology.roles.length, `${state.runs.length} recorded runs · fresh workers per task`, ""],
    ["Checked results", `${passed}<span class="muted"> / ${scored.length}</span>`, "All scored attempts · not a before/after score", ""],
    ["Recorded usage", num(tokens), `${num(calls)} model calls · tokens, not a billing total`, ""]
  ].map(([title,value,note,color]) => `<article class="stat"><div class="stat-title">${title}</div><div class="stat-value ${color}">${value}</div><div class="stat-note">${esc(note)}</div></article>`).join("");
  $("#run-count").textContent = state.runs.length; $("#reflection-count").textContent = state.reflections.length; $("#reflection-count").title = `${state.reflections.length} reflection attempts · ${state.proposals.length} proposals`; $("#version-count").textContent = state.versions.length;
}
function renderRuns() {
  const filter = $("#split-filter").value;
  $("#filter-help").textContent = {all:"Practice, comparisons, final tests, chat, and plumbing checks.",chat:"Your conversations with the active team. No benchmark score.",learning:"Tasks shared with reflection to propose improvements; custom tasks are ungraded.",review:"Fresh answers compared by a separate LLM. Subjective preference, not test scores.",validation:"Paired checks used to accept or reject a candidate, including reruns of learning tasks.",heldout:"Final tasks opened after configurations were frozen. Excluded from reflection.",smoke:"Plumbing checks: verify delegation, tools, and execution work."}[filter];
  const runs = state.runs.filter(run => filter === "all" || run.split === filter);
  $("#run-list").innerHTML = runs.map(run => `<button class="run-item ${run.id === selectedRun ? "selected" : ""}" data-run="${esc(run.id)}"><div class="run-name">${esc(run.task_id)}</div><div class="run-meta">${badge(runStatus(run))}<span>${esc(run.split)}</span></div><div class="run-meta"><span class="mono">${short(run.id)}</span><span>${date(run.started_at)}</span></div></button>`).join("") || empty("No matching runs");
  document.querySelectorAll("[data-run]").forEach(button => button.onclick = () => selectRun(button.dataset.run));
}
async function selectRun(id, preserve = false) {
  selectedRun = id;
  if (!preserve) selectedWorker = null;
  const data = await fetchJSON(`/api/runs/${encodeURIComponent(id)}`);
  if (selectedRun !== id) return;
  const changed = JSON.stringify(replay) !== JSON.stringify(data);
  replay = data;
  if (!preserve || changed) {renderRuns(); renderReplay();}
}
function renderReplay() {
  const {run,organization,workers,events} = replay;
  $("#run-title").textContent = run.task_id;
  $("#download").disabled = false;
  $("#saved-roles").innerHTML = `<span class="role-chip">${esc(organization.label)} · ${short(run.version_id)}</span>` + organization.topology.roles.map(role => `<span class="role-chip">${esc(role.id)}</span>`).join("");
  const root = workers.find(worker => !worker.parent_id), children = workers.filter(worker => worker.parent_id);
  const positions = new Map();
  const width = Math.max(620, children.length * 190), height = children.length ? 270 : 190;
  if (root) positions.set(root.id, {x:width / 2, y:children.length ? 60 : 95});
  children.forEach((worker, index) => positions.set(worker.id, {x:width / (children.length + 1) * (index + 1), y:205}));
  let graph = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Actual workers for this run">`;
  for (const worker of children) {const start = positions.get(worker.parent_id), end = positions.get(worker.id); if(start) graph += `<path class="edge" d="M${start.x},${start.y+27} C${start.x},${start.y+90} ${end.x},${end.y-80} ${end.x},${end.y-27}"/>`;}
  for (const worker of workers) {const point = positions.get(worker.id); if(!point) continue; graph += `<g class="node ${worker.id === selectedWorker ? "selected" : ""}" data-worker="${esc(worker.id)}" tabindex="0" role="button" aria-label="Inspect ${esc(worker.role)}" transform="translate(${point.x-83},${point.y-28})"><rect class="node-box ${worker.temporary ? "temporary" : ""}" width="166" height="56" rx="9"/><text x="83" y="23" text-anchor="middle" class="node-label">${esc(worker.role)}</text><text x="83" y="41" text-anchor="middle" class="node-caption">${worker.temporary ? "temporary" : "saved role"} · ${esc(worker.status)}</text></g>`;}
  $("#graph").innerHTML = graph + "</svg>";
  document.querySelectorAll("[data-worker]").forEach(node => {const select = () => {selectedWorker = node.dataset.worker; renderReplay();}; node.onclick = select; node.onkeydown = event => {if (["Enter"," "].includes(event.key)) {event.preventDefault(); select();}};});
  $("#run-summary").innerHTML = `${badge(runStatus(run))}<span>${num(run.usage?.model_calls)} model calls</span><span>${num(run.usage?.input_tokens)} in / ${num(run.usage?.output_tokens)} out</span><span>${run.usage?.elapsed_seconds ?? "…"}s</span><span>${run.usage?.complete ? "Usage complete" : "Usage partial / pending"}</span>`;
  $("#timeline").innerHTML = events.filter(event => !selectedWorker || event.worker_id === selectedWorker).map(event => `<button class="event ${esc(event.kind)}" data-event="${event.seq}"><span class="event-dot"></span><span class="event-main">${esc(event.kind.replaceAll("_"," "))}${event.payload.name ? ` · <span class="mono">${esc(event.payload.name)}</span>` : ""}<div class="event-caption">${esc(event.worker_id?.split(":").slice(1).join(":") || "controller")}${event.payload.call_number ? ` · call ${event.payload.call_number}` : ""}</div></span><span class="event-time">${date(event.timestamp)}</span></button>`).join("") || empty("No events yet");
  document.querySelectorAll("[data-event]").forEach(button => button.onclick = () => {const event = events.find(item => item.seq === Number(button.dataset.event)); $("#inspect-kind").textContent = "EVENT"; $("#inspector").innerHTML = `<div class="inspect-body"><h3 class="inspect-title">${esc(event.kind.replaceAll("_"," "))}</h3><p>Event ${event.seq} · ${date(event.timestamp)}</p>${pre(event.payload)}</div>`;});
  const worker = workers.find(item => item.id === selectedWorker);
  $("#inspect-kind").textContent = worker ? "WORKER" : "RUN";
  $("#inspector").innerHTML = worker ? `<div class="inspect-body"><h3 class="inspect-title">${esc(worker.role)}</h3>${badge(worker.status)}<div class="inspect-label">Lifetime</div><p>${worker.temporary ? "Temporary instance. A future reflection may propose retaining its role." : "Fresh instance of a saved role."}</p><div class="inspect-label">Assignment</div>${pre(worker.task)}<div class="inspect-label">Configuration</div><p>Inherited from pinned version ${short(run.version_id)}.</p><details class="details"><summary>Prompt, skills & memory</summary>${pre({prompts:organization.prompts,skills:organization.skills,memory:organization.task_memory})}</details></div>` : `<div class="inspect-body"><h3 class="inspect-title">Task result</h3>${badge(runStatus(run))}<div class="inspect-label">Independent check</div><p>${esc(run.grade?.reason || run.error || (run.status === "completed" ? "Conversational response · ungraded" : "Run is in progress"))}</p><div class="inspect-label">Final output</div>${pre(run.output ?? "No final output recorded.")}<details class="details"><summary>Task instructions</summary>${pre(run.prompt)}</details><details class="details"><summary>Saved configuration</summary>${pre(organization)}</details><div class="inspect-label">Run ID</div><p class="mono">${esc(run.id)}</p></div>`;
}
function renderReflection() {
  renderReflectionAction();
  if (!selectedProposal && state.proposals.length) selectedProposal = state.proposals[0].id;
  $("#proposals").innerHTML = state.proposals.map(proposal => `<button class="proposal-card ${proposal.id === selectedProposal ? "selected" : ""}" data-proposal="${esc(proposal.id)}">${badge(proposal.status)} ${proposal.candidate_version === state.active.version_id ? badge("active") : ""}<h3>${esc(proposal.document.title || "Untitled proposal")}</h3><span class="small muted mono">${short(proposal.base_version)} → ${short(proposal.candidate_version)}</span></button>`).join("") || empty("No proposals yet", "The reflection runtime will propose changes from learning traces, then test them before activation.");
  document.querySelectorAll("[data-proposal]").forEach(button => button.onclick = () => {selectedProposal = button.dataset.proposal; renderReflection();});
  const proposal = state.proposals.find(row => row.id === selectedProposal);
  if (proposal) {
    const evaluation = proposal.evaluation, document = proposal.document;
    let html = `<div class="proposal-body"><h3>${esc(document.title)}</h3><p>${esc(document.rationale)}</p>${badge(proposal.status)} ${proposal.candidate_version === state.active.version_id ? badge("active") : ""}<p class="small muted">${proposal.candidate_version === state.active.version_id ? "This configuration starts new company runs." : `This proposal is not active. New runs use ${esc(state.active.manifest.label)}.`}</p><span class="small muted">${esc(proposal.reason || evaluation?.reason || "Awaiting comparison")}</span><div class="inspect-label">Proposed changes</div>`;
    for (const change of document.changes || []) html += `<div class="small mono">${esc(change.path)}</div><div class="diff-grid"><pre class="diff-before">− ${esc(pretty(change.before))}</pre><pre class="diff-after">+ ${esc(pretty(change.after))}</pre></div>`;
    if (evaluation) {
      const subjective = evaluation.policy?.objective === false;
      html += `<div class="inspect-label">${subjective ? "LLM-reviewed · subjective" : "Paired evaluation"} · ${esc(evaluation.policy?.name || "fixed gate")}</div>`;
      if(subjective) html += `<p>${esc(evaluation.judge?.reason || "Waiting for the independent reviewer.")}</p>`;
      html += `<div class="table-wrap"><table><thead><tr><th>Task</th><th>Incumbent</th><th>Candidate</th></tr></thead><tbody>`;
      for (const pair of evaluation.pairs || []) {
        const cell = branch => {
          if(!pair[`${branch}_run_id`]) return "Pending";
          const status = pair[`${branch}_status`] !== "completed" ? "inconclusive" : subjective ? (pair.preferred === branch ? "preferred" : "ungraded") : pair[`${branch}_passed`] ? "pass" : "fail";
          const label = subjective && status !== "inconclusive" ? (pair.preferred === branch ? "Judge preferred" : pair.preferred === "tie" ? "Judge: tie" : pair.preferred === "neither" ? "Judge: neither" : "Ungraded answer") : status;
          return `${badge(status,label)}<p>${num(pair[`${branch}_tokens`])} tokens</p><button class="text-button" data-result-run="${esc(pair[`${branch}_run_id`])}">Inspect run ↗</button>`;
        };
        html += `<tr><td>${esc(pair.task_id)}<p>${esc(pair.split || "validation")}</p></td><td>${cell("base")}</td><td>${cell("candidate")}</td></tr>`;
      }
      html += `</tbody></table></div><div class="inspect-label">Coverage & limits</div><p>${esc(evaluation.note || "Small development suite. Held-out transfer has not been tested.")}</p><details class="details"><summary>Full evaluation record</summary>${pre(evaluation)}</details>`;
    }
    html += `<details class="details"><summary>Proposal record</summary>${pre(document)}</details></div>`; $("#proposal-detail").innerHTML = html;
    documentQueryResultButtons();
  } else $("#proposal-detail").innerHTML = empty("Evidence before adoption", "Select a proposal to inspect the change, paired results, and controller decision.");
  $("#memory").innerHTML = state.reflection_memory.map(row => `<article class="memory-card">${badge(row.outcome)} <span class="small muted">${date(row.created_at)} · ${short(row.proposal_id || row.reflection_id)}</span><p>${esc(row.lesson)}</p><details><summary>Supporting evidence</summary>${pre(row.evidence)}</details></article>`).join("") || empty("A separate memory for improvement", "Accepted, rejected, and inconclusive experiments will inform the next reflection.");
  renderAttempts();
}
function renderAttempts() {
  $("#attempt-count").textContent = state.reflections.length;
  $("#proposal-total").textContent = `${state.proposals.length} saved candidates`;
  $("#view-latest-attempt").hidden = state.reflections.length === 0;
  const container = $("#reflections"), previousScroll = container.scrollTop;
  const openRecords = new Set([...container.querySelectorAll("details[open]")].map(item => item.closest("[data-reflection-id]").dataset.reflectionId));
  container.innerHTML = state.reflections.map((row, index) => {
    const proposal = state.proposals.find(item => item.reflection_id === row.id);
    const lesson = state.reflection_memory.find(item => item.reflection_id === row.id && item.outcome === row.status);
    const linkedProposal = proposal?.id || lesson?.evidence?.equivalent_proposal_id;
    const explanation = {
      running:"Reviewing learning tasks and prior lessons. The result will appear here when the call finishes.",
      duplicate:"Repeated a previously evaluated change. No new proposal or paid comparison was created.",
      no_change:row.response?.reason || "No justified change was proposed.",
      failed:row.error || "Reflection failed before producing a usable proposal.",
      interrupted:row.error || "Reflection was interrupted; this attempt remains in history.",
      proposed:proposal ? `Created a candidate. Current proposal outcome: ${statusLabels[proposal.status] || proposal.status}.${proposal.document.evaluation_scope === "user-task" ? " Uses a separate LLM reviewer on your task." : ""}` : "Created a candidate for evaluation.",
    }[row.status] || lesson?.lesson || "Inspect the record for this attempt's result.";
    const title = row.response?.title || (row.status === "running" ? "Reflection in progress" : row.status === "failed" ? "Reflection could not complete" : "Reflection result");
    return `<article class="memory-card reflection-attempt" id="attempt-${esc(row.id)}" data-reflection-id="${esc(row.id)}" tabindex="-1"><div class="attempt-meta">${badge(row.status)}${index === 0 ? '<span class="latest-attempt">Latest</span>' : ""}<time datetime="${esc(row.created_at)}">${esc(new Date(row.created_at).toLocaleString())}</time><span class="mono small">${short(row.id)}</span></div><h4>${esc(title)}</h4><p>${esc(explanation)}</p><div class="small muted">${num(row.usage?.model_calls)} model calls · ${num((row.usage?.input_tokens || 0) + (row.usage?.output_tokens || 0))} tokens${row.usage && !row.usage.complete ? " (usage incomplete)" : ""} · ${(row.evidence_ids || []).length} learning traces · ${(row.memory_ids || []).length} prior lessons</div>${linkedProposal ? `<button class="text-button attempt-proposal-link" data-attempt-proposal="${esc(linkedProposal)}">${proposal ? "Inspect proposal" : "Inspect equivalent proposal"} ↗</button>` : ""}<details${openRecords.has(row.id) ? " open" : ""}><summary>Full attempt record</summary>${pre(row)}</details></article>`;
  }).join("") || empty("No reflection attempts yet", "Run reflection above. Every attempt appears here, including duplicates, no-change results, and failures.");
  container.scrollTop = previousScroll;
  document.querySelectorAll("[data-attempt-proposal]").forEach(button => button.onclick = () => {selectedProposal = button.dataset.attemptProposal; renderReflection(); $("#proposal-detail").scrollIntoView({block:"start"});});
}
function renderReflectionAction() {
  const action = (state.actions || []).find(row => row.kind === "reflection");
  const running = reflectionSubmitting || action?.status === "running";
  const hasEvidence = state.runs.some(row => row.split === "learning" && row.status === "completed" && row.version_id === state.active.version_id);
  $("#run-reflection").disabled = running || companyBusy() || !hasEvidence;
  $("#run-reflection").textContent = running ? "Reflecting…" : "Run reflection ↗";
  let message = hasEvidence ? "Custom tasks: replay both versions, then let a separate LLM recommend promotion. Subjective review; no shared model-call or time budget." : "Send a task in Chat with ‘Use this task for reflection’ checked, then return here.";
  if (running) message = state.proposals.some(row => row.status === "evaluating") ? "Comparing the candidate with the active version…" : "Reviewing learning tasks and prior reflection lessons…";
  else if (action?.status === "completed") {
    const result = action.result || {}, outcome = result.evaluation?.status || result.reflection?.status || "completed";
    const calls = (result.reflection?.usage?.model_calls || 0) + (result.evaluation?.evaluation?.usage?.model_calls || 0);
    message = `Last cycle: ${statusLabels[outcome] || outcome} · ${calls} model calls. ${result.evaluation_note || "See the proposal and attempt records below."}`;
  } else if (action) message = `Last cycle: ${action.status}. ${action.error || "Inspect the recorded attempts for details."}`;
  $("#reflection-action-status").textContent = message;
}
function documentQueryResultButtons() {document.querySelectorAll("[data-result-run]").forEach(button => button.onclick = () => {$("[data-view='runs']").click(); $("#split-filter").value = "all"; selectRun(button.dataset.resultRun);});}
function renderVersions() {
  function versionStatus(version) {if(version.id === state.active.version_id) return badge("active", "Active · used for new runs"); const proposal = state.proposals.find(row => row.candidate_version === version.id); return proposal ? badge(proposal.status) : badge("saved", "Saved baseline");}
  $("#versions").innerHTML = state.versions.map(version => `<section class="panel version-card"><div class="version-top"><div><h3>${esc(version.manifest.label)} ${versionStatus(version)}</h3><div class="mono">${esc(version.id)}</div><div class="version-chips">${version.manifest.topology.roles.map(role => `<span class="role-chip">${esc(role.id)}</span>`).join("")}<span class="badge">${Object.keys(version.manifest.skills).length} skills</span><span class="badge">${Object.keys(version.manifest.task_memory).length} memory entries</span></div></div><span class="small muted">${new Date(version.created_at).toLocaleString()}</span></div><details><summary>Inspect immutable manifest</summary>${pre(version.manifest)}</details></section>`).join("");
  const history = [...state.activations.map(row => ({...row, kind:"Evaluated activation / revocation"})), ...(state.actions || []).filter(row => row.kind === "runtime_settings" && row.status === "completed").map(row => ({...row.result, kind:"Operator settings change"}))].sort((a,b) => b.generation-a.generation);
  $("#activations").innerHTML = history.map(row => `<article class="memory-card"><span class="badge">${esc(row.kind)}</span> <span class="mono small">${short(row.from_version)} → ${short(row.to_version)}</span><p>Generation ${row.generation} · ${esc(row.reason)}</p></article>`).join("") || empty("Initial version is active", "Adoption and settings changes will appear here.");
  $("#audits").innerHTML = (state.audits || []).map(audit => {
    const {plan, report} = audit;
    const score = branch => {const row = report.scores?.[branch]; return row ? `${row.passed} / ${row.graded} graded · ${num(row.tokens)} tokens` : "Pending";};
    const cell = run => run ? `${badge(run.status === "completed" ? run.passed ? "pass" : "fail" : "inconclusive")}<p>${num(run.tokens)} tokens</p><button class="text-button" data-result-run="${esc(run.run_id)}">Inspect run ↗</button>` : "Pending";
    return `<article class="proposal-body">${badge(audit.status)} <span class="mono small muted">${short(audit.id)}</span><h3>${esc(plan.labels.base)} vs ${esc(plan.labels.candidate)}</h3><p>Candidate at freeze: ${esc(statusLabels[plan.candidate_status_at_freeze] || plan.candidate_status_at_freeze)}. ${esc(plan.note)}</p><p><strong>Baseline:</strong> ${score("base")}<br><strong>Candidate:</strong> ${score("candidate")}</p><div class="table-wrap"><table><thead><tr><th>Task / repetition</th><th>Baseline</th><th>Candidate</th></tr></thead><tbody>${report.pairs.map(pair => `<tr><td>${esc(pair.task_id)}<p>Repetition ${pair.repetition}</p></td><td>${cell(pair.base)}</td><td>${cell(pair.candidate)}</td></tr>`).join("")}</tbody></table></div><p>${esc(report.reason)}</p><p>Active version after reopening: ${report.persistence ? (report.persistence.active_unchanged ? "unchanged" : "mismatch") : "pending"}. Reflection memory: ${report.persistence ? (report.persistence.reflection_memory_unchanged ? "unchanged" : "mismatch") : "pending"}.</p><details class="details"><summary>Frozen plan, component changes, adaptation cost & full results</summary>${pre(audit)}</details></article>`;
  }).join("") || empty("No final audit yet", "Freeze a configuration before opening the held-out suite.");
  documentQueryResultButtons();
}
function renderChat() {
  const threads = state.chat_threads || [], turns = state.chat_turns || [];
  if (selectedThread === undefined || (selectedThread && !threads.some(row => row.id === selectedThread))) selectedThread = threads[0]?.id || null;
  const active = state.active;
  $("#chat-active").textContent = `${active.manifest.label} · ${active.manifest.topology.roles.length} saved roles · ${active.manifest.limits.model_calls == null ? "unlimited model calls" : `${active.manifest.limits.model_calls} model calls`}`;
  $("#chat-threads").innerHTML = threads.map(thread => `<button class="proposal-card ${thread.id === selectedThread ? "selected" : ""}" data-thread="${esc(thread.id)}"><h3>${esc(thread.title)}</h3><span class="small muted">${date(thread.created_at)}</span></button>`).join("") || empty("Your first conversation", "Give the active team a task to begin.");
  document.querySelectorAll("[data-thread]").forEach(button => button.onclick = () => {selectedThread = button.dataset.thread; renderChat();});
  const messages = $("#chat-messages"), oldTop = messages.scrollTop;
  const atBottom = messages.scrollHeight - oldTop - messages.clientHeight < 60;
  messages.innerHTML = turns.filter(turn => turn.thread_id === selectedThread).map(turn => {
    const label = state.versions.find(version => version.id === turn.version_id)?.manifest.label || "Active team";
    const response = turn.status === "running" ? "The team is working…" : turn.output || turn.error || "No response recorded.";
    return `<article class="chat-message from-user"><div class="chat-message-label">You</div><div class="chat-text">${esc(turn.prompt)}</div></article><article class="chat-message from-team"><div class="chat-message-label">${esc(label)} ${turn.version_id ? `<span class="mono">${short(turn.version_id)}</span>` : ""} ${badge(turn.status)}</div><div class="chat-text">${esc(response)}</div>${turn.error && turn.output ? `<p>${esc(turn.error)}</p>` : ""}<div class="chat-meta">${turn.usage ? `${num((turn.usage.input_tokens || 0) + (turn.usage.output_tokens || 0))} tokens · ${num(turn.usage.model_calls)} calls` : ""}${turn.run_id ? `<button class="text-button" data-result-run="${esc(turn.run_id)}">View workers & trace ↗</button>` : ""}</div></article>`;
  }).join("") || empty("One message. The whole active team.", "Ask for a calculation, give it an order-normalization task, or request a delegated check. Open the trace to see what it actually did.");
  messages.scrollTop = atBottom ? messages.scrollHeight : oldTop;
  const busy = companyBusy() || chatSubmitting || reflectionSubmitting;
  $("#chat-send").disabled = busy;
  $("#chat-send").textContent = busy ? "Working…" : "Send ↗";
  documentQueryResultButtons();
}
async function refresh() {
  if (refreshing) return; refreshing = true;
  try {const next = await fetchJSON("/api/state"); const changed = JSON.stringify(state) !== JSON.stringify(next); state = next; $("#error").hidden = true; if(changed) {renderStats(); renderRuns(); renderReflection(); renderVersions(); renderChat();}
    if (selectedRun && !state.runs.some(row => row.id === selectedRun)) {selectedRun = null; replay = null; selectedWorker = null;}
    if (!selectedRun) selectedRun = state.runs.find(run => run.split === "smoke" && run.grade?.passed)?.id || state.runs[0]?.id;
    if (selectedRun) await selectRun(selectedRun, true);
    else {$("#graph").innerHTML = empty("Ready for the first run", "Give the generalist a task in Chat."); $("#run-title").textContent = "No runs yet"; $("#download").disabled = true; for (const id of ["saved-roles","run-summary","timeline","inspector"]) $(`#${id}`).innerHTML = "";}
    $("#updated").textContent = `Updated ${new Date().toLocaleTimeString()} · refreshes every 5s`;
  } catch (error) {$("#error").hidden = false; $("#error").textContent = error.message;} finally {refreshing = false;}
}
document.querySelectorAll("[data-view]").forEach(button => button.onclick = () => {currentView = button.dataset.view; document.querySelectorAll("[data-view]").forEach(item => item.classList.toggle("selected",item === button)); for (const view of ["chat","runs","reflection","versions"]) $(`#${view}-view`).hidden = view !== currentView; $("#page-title").textContent = {chat:"Put your team to work.",runs:"Watch the work happen.",reflection:"Learning, with receipts.",versions:"Keep what works."}[currentView]; $("#page-subtitle").textContent = {chat:"A conversation with the active organization, backed by real execution.",runs:"A saved organization. Fresh workers. A trace you can inspect.",reflection:"Every proposal has evidence, a comparison, and a decision.",versions:"The exact configuration that starts the next run."}[currentView];});
$("#new-chat").onclick = () => {selectedThread = null; renderChat(); $("#chat-input").focus();};
$("#chat-form").onsubmit = async event => {
  event.preventDefault();
  const message = $("#chat-input").value.trim();
  if (!message || chatSubmitting || reflectionSubmitting || companyBusy()) return;
  chatSubmitting = true; $("#chat-error").hidden = true; renderChat();
  try {
    const response = await fetch("/api/chat", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({message, thread_id:selectedThread, learn:$("#chat-learn").checked})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Could not start chat (${response.status})`);
    selectedThread = result.thread_id; $("#chat-input").value = "";
    await refresh();
  } catch(error) {$("#chat-error").hidden = false; $("#chat-error").textContent = error.message;}
  finally {chatSubmitting = false; renderChat();}
};
$("#chat-input").onkeydown = event => {if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {event.preventDefault(); $("#chat-form").requestSubmit();}};
$("#run-reflection").onclick = async () => {
  if (reflectionSubmitting || companyBusy()) return;
  reflectionSubmitting = true; $("#reflection-action-error").hidden = true; renderReflectionAction(); renderChat();
  try {
    const response = await fetch("/api/reflect", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Could not start reflection (${response.status})`);
    await refresh();
  } catch(error) {$("#reflection-action-error").hidden = false; $("#reflection-action-error").textContent = error.message;}
  finally {reflectionSubmitting = false; renderReflectionAction(); renderChat();}
};
$("#view-latest-attempt").onclick = () => {const latest = $("#reflections .reflection-attempt"); if(latest) {$("#reflections").scrollTop = 0; latest.scrollIntoView({block:"nearest"}); latest.focus({preventScroll:true});}};
$("#refresh").onclick = refresh; $("#split-filter").onchange = renderRuns;
$("#clear-worker").onclick = () => {selectedWorker = null; if(replay) renderReplay();};
$("#download").onclick = () => {if(!replay) return; const url = URL.createObjectURL(new Blob([JSON.stringify(replay,null,2)],{type:"application/json"})); const a = document.createElement("a"); a.href = url; a.download = `run-${replay.run.id}.json`; a.click(); URL.revokeObjectURL(url);};
refresh(); setInterval(refresh, 5000);

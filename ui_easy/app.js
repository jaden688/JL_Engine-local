const state = {
  agentId: "jl_easy_agent",
  voice: "SparkByte Modular",
  mpfAgents: [],
  pendingAction: null,
  chatPending: false,
  approvalPending: false,
  currentProfile: null,
  currentSelection: null,
  thinkingMessageEl: null,
};

const $ = (id) => document.getElementById(id);

const QUICK_FALLBACKS = {
  health: "API down",
  mode: "Mode unavailable",
  model: "Model unavailable",
  browser: "Browser unavailable",
  selection: "Voice unavailable",
};

document.addEventListener("DOMContentLoaded", () => {
  bindUi();
  bootstrap().catch((error) => {
    appendActivity("Bootstrap error", error.message || String(error), "error");
  });
});

function bindUi() {
  $("chatForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await sendChat();
  });
  $("refreshStatusBtn")?.addEventListener("click", () => refreshDashboard(true));
  $("approveBtn")?.addEventListener("click", () => resolvePendingAction(true));
  $("rejectBtn")?.addEventListener("click", () => resolvePendingAction(false));
  $("voiceSelect")?.addEventListener("change", (event) => {
    state.voice = event.target.value;
    renderSelectionChip();
    renderCompositionFromCatalog();
  });
  $("autoToolsToggle")?.addEventListener("change", () => updateComposerNote());
  document.querySelectorAll(".quick-action").forEach((button) => {
    button.addEventListener("click", async () => {
      const prompt = button.getAttribute("data-prompt") || "";
      if (!prompt) return;
      $("chatInput").value = prompt;
      await sendChat();
    });
  });
}

async function bootstrap() {
  appendActivity("Flow deck online", "Warming up JL Engine Flow.", "ok");
  await refreshDashboard(false);
  renderSelectionChip();
  renderApproval();
}

async function apiJson(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail || payload.error || `${response.status} ${response.statusText}`;
    throw new Error(detail);
  }
  return payload;
}

async function refreshDashboard(noisy) {
  const results = await Promise.allSettled([
    apiJson("/health"),
    apiJson("/settings/ollama"),
    apiJson("/browser/state"),
    apiJson("/quest/agents/mpf"),
    apiJson(`/quest/switchboard?agent_id=${encodeURIComponent(state.agentId)}`),
    apiJson("/quest/agents"),
  ]);

  const [health, ollama, browser, mpf, switchboard, questAgents] = results;

  if (health.status === "fulfilled") {
    $("healthChip").textContent = `API ${String(health.value.status || "ok").toUpperCase()}`;
  } else {
    $("healthChip").textContent = QUICK_FALLBACKS.health;
  }

  if (ollama.status === "fulfilled") {
    const runtimeMode = ollama.value.runtime_mode || ollama.value.effective_mode || "local_only";
    const currentModel = ollama.value.current_model || ollama.value.configured_model || "unknown";
    $("modeChip").textContent = `Mode ${runtimeMode}`;
    $("modelChip").textContent = `Model ${currentModel}`;
  } else {
    $("modeChip").textContent = QUICK_FALLBACKS.mode;
    $("modelChip").textContent = QUICK_FALLBACKS.model;
  }

  if (browser.status === "fulfilled") {
    const ready = browser.value.ready ? "ready" : "idle";
    const strategy = browser.value.launch_strategy || browser.value.channel || "none";
    $("browserChip").textContent = `Browser ${ready} | ${strategy}`;
  } else {
    $("browserChip").textContent = QUICK_FALLBACKS.browser;
  }

  if (mpf.status === "fulfilled") {
    const rawAgents = Array.isArray(mpf.value.agents) ? mpf.value.agents : [];
    state.mpfAgents = rawAgents
      .filter((agent) => ["fat_agent", "jl_agent"].includes(String(agent.classification || "")))
      .sort((a, b) => scoreVoice(a) - scoreVoice(b));
    renderVoiceOptions();
  }

  if (switchboard.status === "fulfilled") {
    state.currentSelection = switchboard.value.current || null;
  }

  if (questAgents.status === "fulfilled") {
    const liveAgents = Array.isArray(questAgents.value.agents) ? questAgents.value.agents : [];
    const active = liveAgents.find((agent) => agent.agent_id === state.agentId) || null;
    state.currentProfile = active?.profile || null;
    if (!state.currentProfile) {
      renderCompositionFromCatalog();
    } else {
      renderComposition(state.currentProfile);
    }
  } else {
    renderCompositionFromCatalog();
  }

  renderSelectionChip();
  updateComposerNote();
  if (noisy) {
    appendActivity(
      "Dashboard refreshed",
      "Status, agent catalog, and live runtime snapshot updated.",
      "ok"
    );
  }
}

function scoreVoice(agent) {
  const name = String(agent.agent_name || agent.name || "");
  if (name === "SparkByte Modular") return -20;
  if (name === "SparkByte") return -10;
  if (String(agent.classification || "") === "fat_agent") return 0;
  return 10;
}

function renderVoiceOptions() {
  const select = $("voiceSelect");
  if (!select) return;
  const previous = state.voice;
  const options = state.mpfAgents;
  if (!options.length) {
    select.innerHTML = '<option value="SparkByte Modular">SparkByte Modular</option>';
    state.voice = "SparkByte Modular";
    return;
  }
  select.innerHTML = options
    .map((agent) => {
      const value = escapeHtml(String(agent.agent_name || agent.name || ""));
      const suffix = agent.profile_type === "modular_fat_agent" ? " | modular" : "";
      return `<option value="${value}">${value}${suffix}</option>`;
    })
    .join("");
  const availableNames = options.map((agent) => String(agent.agent_name || agent.name || ""));
  state.voice = availableNames.includes(previous)
    ? previous
    : availableNames.includes("SparkByte Modular")
      ? "SparkByte Modular"
      : availableNames[0];
  select.value = state.voice;
}

function renderSelectionChip() {
  const voice = state.voice || "unknown";
  const selection = state.currentSelection || {};
  const lane = selection.lane || "fat_agent";
  const child = selection.child || voice;
  $("selectionChip").textContent = `Voice ${voice} | lane ${lane} | child ${child}`;
}

function updateComposerNote() {
  const autoTools = $("autoToolsToggle")?.checked !== false;
  const pending = state.pendingAction
    ? "Approval waiting."
    : autoTools
      ? "Agentic mode is ready."
      : "Chat-only mode is ready.";
  $("composerNote").textContent = pending;
  $("sendBtn").disabled = state.chatPending || state.approvalPending || !!state.pendingAction;
  $("chatInput").disabled = state.chatPending || state.approvalPending;
  $("approveBtn").disabled = !state.pendingAction || state.approvalPending;
  $("rejectBtn").disabled = !state.pendingAction || state.approvalPending;
}

function appendMessage(role, title, body, meta = {}) {
  const log = $("chatLog");
  if (!log) return;
  const wrapper = document.createElement("article");
  wrapper.className = `message ${role}`;
  const stamp = new Date().toLocaleTimeString();
  const laneBits = [meta.lane, meta.child].filter(Boolean).join(" / ");
  const laneLabel = laneBits ? `${laneBits} | ${stamp}` : stamp;
  wrapper.innerHTML = `
    <div class="message-meta">
      <strong>${escapeHtml(title)}</strong>
      <span>${escapeHtml(laneLabel)}</span>
    </div>
    <div class="message-body">${escapeHtml(String(body || ""))}</div>
  `;
  log.appendChild(wrapper);
  log.scrollTop = log.scrollHeight;
  return wrapper;
}

function clearThinkingMessage() {
  if (state.thinkingMessageEl?.remove) {
    state.thinkingMessageEl.remove();
  }
  state.thinkingMessageEl = null;
}

function summarizeTelemetryForChat(telemetry) {
  const payload = telemetry && typeof telemetry === "object" ? telemetry : {};
  const parts = [];
  const mode = String(payload.cognitive_mode || payload.mode || "").trim();
  const gait = String(payload.gait || payload.gait_mode || "").trim();
  const rhythm = String(payload.rhythm || payload.rhythm_mode || "").trim();
  const aperture = String(payload.aperture || payload.aperture_mode || "").trim();
  if (mode) parts.push(`mode ${mode}`);
  if (gait) parts.push(`gait ${gait}`);
  if (rhythm) parts.push(`rhythm ${rhythm}`);
  if (aperture) parts.push(`aperture ${aperture}`);
  return parts;
}

function summarizeToolStep(step) {
  const tool = String(step?.tool || "").trim();
  const input = step && typeof step.input === "object" && step.input ? step.input : {};
  const result = step && typeof step.result === "object" && step.result ? step.result : {};
  if (!tool) return "";
  if (tool === "bridge_local") {
    const mode = String(input.mode || "").trim().toLowerCase();
    const data = input && typeof input.data === "object" && input.data ? input.data : {};
    if (mode === "fs_list") return `inspected files in ${data.path || "."}`;
    if (mode === "fs_read") return `read ${data.path || "a file"}`;
    if (mode === "fs_write") return `wrote ${data.path || "a file"}`;
    if (mode === "fs_mkdir") return `created folder ${data.path || data.name || "a folder"}`;
    if (mode === "browser_inspect") return "inspected the browser session";
    if (mode === "browser_action") return `used browser action${data.action ? ` (${data.action})` : ""}`;
    if (mode === "http") return `called ${String(data.method || "GET").toUpperCase()} ${data.url || "endpoint"}`;
    if (mode === "subprocess") return "ran subprocess";
    if (mode === "ui") return `controlled UI${data.action ? ` (${data.action})` : ""}`;
    return `used bridge_local (${mode || "unknown"})`;
  }
  if (tool === "run_shell") return "ran shell command";
  if (tool === "run_cc_command") return "ran local command";
  if (tool === "py_exec_stream") return "executed Python";
  if (tool === "forge_list") return "inspected RAM tools";
  if (tool === "forge_create") return `created RAM tool ${input.name || ""}`.trim();
  if (tool === "forge_delete") return `deleted RAM tool ${input.name || ""}`.trim();
  if (tool === "forge_promote" || tool === "forge_promote_last") return "promoted RAM tool";
  if (tool === "forge_run") return `ran RAM tool ${input.name || ""}`.trim();
  if (result.status === "ok" || result.ok === true) return `used ${tool}`;
  return `${tool} -> ${result.status || result.error || "done"}`;
}

function appendThinkingMessage(title, summary, options = {}) {
  const log = $("chatLog");
  if (!log) return null;
  const wrapper = document.createElement("article");
  wrapper.className = `message thinking ${options.tone || "info"}`;
  const stamp = new Date().toLocaleTimeString();
  wrapper.innerHTML = `
    <div class="message-meta">
      <strong>${escapeHtml(title)}</strong>
      <span>${escapeHtml(stamp)}</span>
    </div>
    <div class="message-body">${escapeHtml(String(summary || ""))}</div>
  `;

  const details = [];
  const trace = Array.isArray(options.trace) ? options.trace : [];
  const traceLines = trace.map(summarizeToolStep).filter(Boolean);
  if (traceLines.length) {
    details.push(["Action stream", traceLines.slice(0, 6).join(" | ")]);
  }
  const telemetryLines = summarizeTelemetryForChat(options.telemetry);
  if (telemetryLines.length) {
    details.push(["Telemetry", telemetryLines.join(" | ")]);
  }
  if (options.pendingSummary) {
    details.push(["Gate", options.pendingSummary]);
  }

  if (details.length) {
    const meta = document.createElement("div");
    meta.className = "thought-meta";
    for (const [label, value] of details) {
      const chip = document.createElement("div");
      chip.className = "thought-chip";
      chip.textContent = `${label}: ${value}`;
      meta.appendChild(chip);
    }
    wrapper.appendChild(meta);
  }

  log.appendChild(wrapper);
  log.scrollTop = log.scrollHeight;
  return wrapper;
}

function appendActivity(title, body, tone = "info", extra = null) {
  const feed = $("activityFeed");
  if (!feed) return;
  const item = document.createElement("article");
  item.className = "activity-item";
  const toneLabel = tone === "error" ? "error" : tone === "ok" ? "ok" : "info";
  item.innerHTML = `
    <h3>${escapeHtml(title)} <span class="kicker" style="display:inline;margin-left:8px;">${toneLabel}</span></h3>
    <p>${escapeHtml(String(body || ""))}</p>
  `;
  if (extra) {
    const pre = document.createElement("pre");
    pre.textContent = typeof extra === "string" ? extra : JSON.stringify(extra, null, 2);
    item.appendChild(pre);
  }
  feed.prepend(item);
}

function renderApproval() {
  const pending = state.pendingAction;
  $("approvalEmpty").classList.toggle("hidden", !!pending);
  $("approvalCard").classList.toggle("hidden", !pending);
  if (!pending) {
    $("approvalSummary").textContent = "";
    $("approvalTool").textContent = "";
    $("approvalRisk").textContent = "";
    updateComposerNote();
    return;
  }
  const summary =
    pending.summary ||
    pending.description ||
    pending.command ||
    `${pending.tool || "tool"} needs approval`;
  $("approvalSummary").textContent = summary;
  $("approvalTool").textContent = `Tool ${pending.tool || "unknown"}`;
  $("approvalRisk").textContent = `Risk ${(pending.risk_level || "high").toUpperCase()}`;
  updateComposerNote();
}

async function sendChat() {
  if (state.chatPending || state.approvalPending || state.pendingAction) return;
  const input = $("chatInput");
  const message = (input?.value || "").trim();
  if (!message) return;
  input.value = "";
  clearThinkingMessage();
  appendMessage("user", "You", message, {});
  state.chatPending = true;
  updateComposerNote();
  appendActivity("Sending chat", `Voice ${state.voice} is handling a new turn.`, "info");
  state.thinkingMessageEl = appendThinkingMessage(
    `${state.voice} thinking`,
    "Planning the turn and deciding whether the engine needs tools."
  );
  try {
    const payload = await apiJson("/quest/chat", {
      method: "POST",
      body: JSON.stringify({
        agent_id: state.agentId,
        agent: state.voice,
        message,
        execution_mode: $("autoToolsToggle")?.checked !== false ? "auto" : "chat",
        return_trace: true,
        context: {
          ui_surface: "ui_easy",
          product_surface: "flow_deck",
        },
      }),
    });
    handleChatPayload(payload);
  } catch (error) {
    appendMessage("system", "Flow deck", `Chat failed: ${error.message || error}`, {});
    appendActivity("Chat error", error.message || String(error), "error");
  } finally {
    state.chatPending = false;
    updateComposerNote();
  }
}

function handleChatPayload(payload) {
  clearThinkingMessage();
  state.pendingAction = payload.pending_action || null;
  renderApproval();
  const trace = Array.isArray(payload.tool_trace) ? payload.tool_trace : [];
  const telemetry = payload.telemetry_summary || payload.telemetry || null;
  if (trace.length || telemetry || state.pendingAction) {
    appendThinkingMessage(
      `${state.voice} thought stream`,
      state.pendingAction
        ? "The engine found a real-world action and paused at the approval gate."
        : "The engine finished a visible action pass for this turn.",
      {
        tone: state.pendingAction ? "warning" : "info",
        trace,
        telemetry,
        pendingSummary: state.pendingAction?.summary || "",
      }
    );
  }
  if (state.pendingAction) {
    appendMessage(
      "system",
      "Approval needed",
      state.pendingAction.summary ||
        state.pendingAction.description ||
        "A tool action needs your approval.",
      payload
    );
  } else if (payload.reply) {
    appendMessage("agent", state.voice, payload.reply, payload);
  } else if (payload.error) {
    appendMessage("system", "Flow deck", payload.error, payload);
  }
  renderToolTrace(payload.tool_trace);
  if (payload.telemetry_summary) {
    appendActivity(
      "Telemetry",
      "Turn finished with updated engine telemetry.",
      "ok",
      payload.telemetry_summary
    );
  }
  refreshDashboard(false).catch(() => {});
}

async function resolvePendingAction(approved) {
  if (!state.pendingAction || state.approvalPending) return;
  state.approvalPending = true;
  updateComposerNote();
  clearThinkingMessage();
  appendActivity(
    approved ? "Approval granted" : "Approval rejected",
    state.pendingAction.summary ||
      state.pendingAction.description ||
      "Pending action resolved.",
    approved ? "ok" : "info"
  );
  try {
    const payload = await apiJson("/quest/chat/confirm", {
      method: "POST",
      body: JSON.stringify({
        agent_id: state.agentId,
        pending_action_id: state.pendingAction.id,
        approved,
        return_trace: true,
      }),
    });
    state.pendingAction = payload.pending_action || null;
    renderApproval();
    const trace = Array.isArray(payload.tool_trace) ? payload.tool_trace : [];
    const telemetry = payload.telemetry_summary || payload.telemetry || null;
    if (trace.length || telemetry) {
      appendThinkingMessage(
        `${state.voice} execution recap`,
        approved
          ? "The approved action ran and the engine wrapped the turn."
          : "The action stayed blocked and the engine kept the turn safe.",
        {
          tone: approved ? "info" : "warning",
          trace,
          telemetry,
        }
      );
    }
    if (payload.reply) {
      appendMessage("agent", state.voice, payload.reply, payload);
    } else if (!approved) {
      appendMessage("system", "Flow deck", "Pending action rejected.", payload);
    }
    renderToolTrace(payload.tool_trace);
    refreshDashboard(false).catch(() => {});
  } catch (error) {
    appendMessage(
      "system",
      "Flow deck",
      `Confirmation failed: ${error.message || error}`,
      {}
    );
    appendActivity("Confirmation error", error.message || String(error), "error");
  } finally {
    if (!state.pendingAction) {
      state.pendingAction = null;
    }
    state.approvalPending = false;
    renderApproval();
  }
}

function renderToolTrace(trace) {
  if (!Array.isArray(trace) || !trace.length) return;
  trace.forEach((item) => {
    const tool = item.tool || "tool";
    const status = item.result?.status || item.status || "ok";
    appendActivity(
      `Tool ${tool}`,
      `Status ${status}`,
      status === "ok" ? "ok" : "info",
      {
        input: item.input || item.payload || null,
        result: item.result || null,
      }
    );
  });
}

function renderCompositionFromCatalog() {
  const match = state.mpfAgents.find(
    (agent) => String(agent.agent_name || agent.name || "") === state.voice
  );
  const profile = match
    ? {
        name: state.voice,
        role: (match.modular_summary || {}).role || "",
        description: (match.modular_summary || {}).description || "",
        profile_type: match.profile_type || "classic_agent",
        modular_summary: match.modular_summary || null,
      }
    : {
        name: state.voice,
        role: "",
        description: "",
        profile_type: "classic_agent",
        modular_summary: null,
      };
  renderComposition(profile);
}

function renderComposition(profile) {
  const target = $("compositionPanel");
  if (!target) return;
  const safeProfile = profile || {};
  const modular = safeProfile.modular_summary || null;
  const blocks = [];
  blocks.push(
    cardMarkup("Voice", [
      line("Name", safeProfile.name || state.voice),
      line("Role", safeProfile.role || "Active JL Engine voice"),
      line("Type", safeProfile.profile_type || "classic_agent"),
      safeProfile.description ? `<p>${escapeHtml(safeProfile.description)}</p>` : "",
    ])
  );
  if (modular) {
    const profileIds = modular.profile_ids || {};
    blocks.push(
      cardMarkup("Loadout", [
        line("Loadout", modular.loadout_id || "default"),
        `<ul>${Object.entries(profileIds)
          .map(([family, id]) => `<li>${escapeHtml(`${family}: ${id}`)}</li>`)
          .join("")}</ul>`,
      ])
    );
    blocks.push(
      cardMarkup("Tasks", [
        `<ul>${(modular.supported_tasks || [])
          .slice(0, 8)
          .map((task) => `<li>${escapeHtml(String(task))}</li>`)
          .join("")}</ul>`,
      ])
    );
    blocks.push(
      cardMarkup("Helpers", [
        `<ul>${(modular.helpers || [])
          .slice(0, 6)
          .map((helper) => `<li>${escapeHtml(String(helper.helper_id || helper.purpose || "helper"))}</li>`)
          .join("")}</ul>`,
      ])
    );
  } else {
    blocks.push(
      cardMarkup("Profile", [
        "<p>This voice is using the classic fat-agent path. The engine is still live, but this one is not coming from the modular pack.</p>",
      ])
    );
  }
  target.innerHTML = blocks.join("");
}

function cardMarkup(title, sections) {
  return `
    <article class="composition-card">
      <h3>${escapeHtml(title)}</h3>
      ${sections.filter(Boolean).join("")}
    </article>
  `;
}

function line(label, value) {
  return `<p><strong>${escapeHtml(label)}:</strong> ${escapeHtml(String(value || ""))}</p>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

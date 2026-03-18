const state = {
  activeAgentId: "",
  agents: [],
  lastToolListAgent: "",
  deferredInstallPrompt: null,
  switchboard: null,
  mpfPersonas: [],
  lastMpfPersonaCount: -1,
  missingUiControls: new Set(),
  activeTab: "chat",
  workspacePath: ".",
  workspaceParentPath: ".",
  selectedFilePath: "",
  selfEditRunning: false,
  totalAgentControlEnabled: false,
  chatLoopRunning: false,
  chatLoopWaiting: false,
  chatLoopTurns: 0,
  browserHomeUrl: "",
  browserCurrentUrl: "",
  browserSurfaceMode: "browser",
  browserSessionWindow: null,
  browserSessionState: "idle",
  browserSessionCapability: "session_attach_accessibility",
  browserLastObservation: null,
  lastBrowserDirective: "",
  lastLoopReplySeen: "",
  pendingChatActionId: "",
  pendingChatActionDecisionPending: false,
  ollamaModels: [],
  currentOllamaModel: "",
  currentOllamaBaseUrl: "",
  currentBrainBackendId: "",
  currentToolBackendId: "",
  runtimeMode: null,
  chatRequestPending: false,
};

const $ = (id) => document.getElementById(id);
const PERSONA_PRESET_ALIASES = {
  sparkbyte: ["SparkByte"],
  gremlen: ["The Gremlin", "Gremlen", "Gremlin"],
  slappy: ["Slappy"],
};
const JL_FAT_AGENT_ID = "jl_fat_agent";
const PRIMARY_PRODUCT_SELECTION = Object.freeze({
  agentId: JL_FAT_AGENT_ID,
  lane: "fat_agent",
  child: "SparkByte",
  persona: "SparkByte",
});

function voiceSkinCopy(agentName) {
  const name = String(agentName || "").trim() || "SparkByte";
  const low = name.toLowerCase();
  if (low === "the gremlin" || low === "gremlin" || low === "gremlen") {
    return {
      summary: "The engine is the product. The Gremlin is the active builder voice riding the controls right now.",
      note: "JL Engine stays in charge. The Gremlin is the loaded fat-agent voice for the front conversation.",
      body: "JL Engine is still orchestrating tools, state, delegation, and control. The Gremlin brings the scrappy, prototype-happy builder energy on top of that runtime.",
      prompt: "Tell The Gremlin what we are hacking together next.",
      busy: "The Gremlin is chewing through the local stack...",
      boot: "Deck online. The Gremlin just crawled out of the ductwork.",
    };
  }
  if (low === "slappy") {
    return {
      summary: "The engine is the product. Slappy is the active chaos-oracle voice riding the controls right now.",
      note: "JL Engine stays in charge. Slappy is the loaded fat-agent voice for the front conversation.",
      body: "JL Engine is still handling orchestration, tools, delegation, and control. Slappy brings the feral improvisation layer on top of the same runtime.",
      prompt: "Tell Slappy what kind of mess we are wrangling next.",
      busy: "Slappy is rattling around in the local stack...",
      boot: "Deck online. Slappy just kicked the tires and hollered.",
    };
  }
  return {
    summary: "The engine is the product. SparkByte is the active voice riding the controls right now.",
    note: "JL Engine stays in charge. SparkByte is the loaded fat-agent voice for the front conversation.",
    body: "JL Engine is the main show here: orchestration, state, tools, delegation, and control. SparkByte is the live personality layer shaping the conversation on top of it.",
    prompt: "Tell SparkByte what chaos we are steering next.",
    busy: "SparkByte is chewing through the local stack...",
    boot: "Deck online. SparkByte mothership engaged.",
  };
}

function reportMissingUiControl(id) {
  if (!id || state.missingUiControls.has(id)) return;
  state.missingUiControls.add(id);
  feed(`UI control missing: ${id}. The cached web shell may be out of date; reload /ui/.`, "error");
}

function bindEvent(id, eventName, handler) {
  const el = $(id);
  if (!el) {
    reportMissingUiControl(id);
    return null;
  }
  el.addEventListener(eventName, handler);
  return el;
}

function decodeEscapedText(value) {
  const raw = String(value ?? "");
  if (!raw.includes("\\n") && !/\\u[0-9a-fA-F]{4}/.test(raw)) {
    return raw;
  }
  return raw
    .replace(/\\u([0-9a-fA-F]{4})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
    .replace(/\\n/g, "\n")
    .replace(/\\r/g, "\r")
    .replace(/\\t/g, "\t");
}

function feed(message, tone = "info") {
  const ts = new Date().toLocaleTimeString();
  const prefix = tone === "error" ? "[ERR]" : tone === "ok" ? "[OK]" : "[LOG]";
  const line = `${ts} ${prefix} ${decodeEscapedText(message)}`;
  const box = $("opsFeed");
  box.textContent = `${line}\n${box.textContent}`.slice(0, 15000);
}

function setLatency(ms) {
  const value = typeof ms === "number" ? `${ms.toFixed(1)}` : "-";
  $("stripLatency").textContent = `Latency(ms): ${value}`;
}

function normalizeToken(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}

function agentIdFromPersona(personaName) {
  return JL_FAT_AGENT_ID;
}

function setAgentIdInputFromPersona(personaName) {
  const input = $("agentId");
  if (!input) return;
  input.value = agentIdFromPersona(personaName);
}

function applyPrimaryProductSelection() {
  syncPersonaSelectors(PRIMARY_PRODUCT_SELECTION.persona);
  if ($("agentId")) $("agentId").value = PRIMARY_PRODUCT_SELECTION.agentId;
  if ($("laneSelect")) $("laneSelect").value = PRIMARY_PRODUCT_SELECTION.lane;
  renderSwitchboardChildren(PRIMARY_PRODUCT_SELECTION.child);
  if ($("childSelect")) $("childSelect").value = PRIMARY_PRODUCT_SELECTION.child;
  renderSelectionChips({
    lane: PRIMARY_PRODUCT_SELECTION.lane,
    child: PRIMARY_PRODUCT_SELECTION.child,
    agent_name: PRIMARY_PRODUCT_SELECTION.persona,
    generated_instance_id: null,
  });
}

function getSelectedLane() {
  return $("laneSelect")?.value?.trim() || "";
}

function getSelectedChild() {
  return $("childSelect")?.value?.trim() || "";
}

function wantsNewGeneratedInstance() {
  return getSelectedLane() === "generated" && $("newGeneratedInstanceCheck")?.checked === true;
}

function clearNewGeneratedInstanceRequest() {
  const checkbox = $("newGeneratedInstanceCheck");
  if (checkbox) checkbox.checked = false;
}

function summarizeTelemetry(telemetry) {
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
  return parts.join(" | ") || "idle";
}

function renderRuntimeModeChip() {
  const chip = $("backendModeChip");
  if (!chip) return;
  const payload = state.runtimeMode && typeof state.runtimeMode === "object" ? state.runtimeMode : {};
  const effective = String(payload.effective_mode || payload.configured_mode || "").trim() || "unknown";
  const fallback = String(payload.fallback_reason || "").trim();
  chip.textContent = fallback ? `Backend: ${effective} (${fallback})` : `Backend: ${effective}`;
}

function renderSelectionChips(selection = {}, options = {}) {
  const resolved = selection && typeof selection === "object" ? selection : {};
  const lane = String(resolved.lane || resolved.active_lane || "").trim() || "fat_agent";
  const child = String(resolved.child || resolved.active_child || resolved.agent_name || resolved.active_agent_name || "").trim() || "SparkByte";
  const generatedInstanceId = String(
    resolved.generated_instance_id || resolved.last_generated_instance_id || ""
  ).trim();
  const delegatedTo = String(options.delegatedTo || resolved.delegated_to || "").trim();
  const delegatedClass = String(options.delegatedClass || resolved.delegated_class || "").trim();
  const telemetryText = summarizeTelemetry(options.telemetrySummary || resolved.telemetry_summary || {});

  if ($("activeAgentChip")) {
    $("activeAgentChip").textContent = `Active Agent: ${child}`;
  }
  if ($("activeLaneChip")) {
    $("activeLaneChip").textContent = `Lane: ${lane}`;
  }
  if ($("activeChildChip")) {
    $("activeChildChip").textContent = `Child: ${child}`;
  }
  if ($("generatedInstanceChip")) {
    $("generatedInstanceChip").textContent = generatedInstanceId
      ? `Generated: ${generatedInstanceId}`
      : "Generated: --";
  }
  if ($("delegationChip")) {
    $("delegationChip").textContent = delegatedTo
      ? `Delegation: ${delegatedClass || "helper"} -> ${delegatedTo}`
      : "Delegation: direct";
  }
  if ($("telemetryChip")) {
    $("telemetryChip").textContent = `Telemetry: ${telemetryText}`;
  }

  const copy = voiceSkinCopy(child);
  if ($("heroVoiceSummary")) {
    $("heroVoiceSummary").textContent = copy.summary;
  }
  if ($("activeVoiceHeading")) {
    $("activeVoiceHeading").textContent = `Active Voice: ${child}`;
  }
  if ($("activeVoiceNote")) {
    $("activeVoiceNote").textContent = copy.note;
  }
  if ($("productSummary")) {
    $("productSummary").textContent = copy.body;
  }
  if ($("chatInput") && !state.chatRequestPending && !state.pendingChatActionId && !state.pendingChatActionDecisionPending) {
    $("chatInput").placeholder = copy.prompt;
  }
}

function resolveSwitchboardSelectionByAgentName(agentName) {
  const wanted = String(agentName || "").trim().toLowerCase();
  if (!wanted) return null;
  const lanes = state.switchboard?.lanes;
  if (!lanes || typeof lanes !== "object") return null;
  for (const [lane, laneEntry] of Object.entries(lanes)) {
    const children = laneEntry && typeof laneEntry === "object" ? laneEntry.children : null;
    if (!children || typeof children !== "object") continue;
    for (const [child, childEntry] of Object.entries(children)) {
      const agent = String(childEntry?.agent_name || child).trim();
      if (agent.toLowerCase() === wanted || String(child).trim().toLowerCase() === wanted) {
        return { lane, child, entry: childEntry };
      }
    }
  }
  return null;
}

function normalizeBrowserUrl(raw) {
  const value = String(raw || "").trim();
  if (!value) return "";
  if (value === "about:blank") return value;
  if (/^https?:\/\//i.test(value)) return value;
  return `https://${value}`;
}

function clipText(value, maxLen = 1200) {
  const text = String(value ?? "");
  if (text.length <= maxLen) return text;
  return `${text.slice(0, Math.max(0, maxLen - 3))}...`;
}

function stringifyStructured(value, maxLen = 1600) {
  if (value == null || value === "") return "";
  if (typeof value === "string") return clipText(value, maxLen);
  try {
    return clipText(JSON.stringify(value), maxLen);
  } catch {
    return clipText(String(value), maxLen);
  }
}

function normalizeBrowserControlItem(item) {
  const raw = item && typeof item === "object" ? item : {};
  return {
    role: String(raw.role || "").trim(),
    name: clipText(raw.name || "", 200),
    id: String(raw.id || "").trim(),
    value: clipText(raw.value || "", 200),
    state: clipText(raw.state || "", 200),
  };
}

function normalizeBrowserObservation(raw) {
  const payload = raw && typeof raw === "object" ? raw : {};
  const controls = Array.isArray(payload.controls) ? payload.controls.slice(0, 40).map(normalizeBrowserControlItem) : [];
  const focused =
    payload.focused && typeof payload.focused === "object"
      ? {
          role: String(payload.focused.role || "").trim(),
          name: clipText(payload.focused.name || "", 200),
          value: clipText(payload.focused.value || "", 200),
        }
      : null;
  return {
    request_id: String(payload.request_id || payload.requestId || "").trim(),
    status: String(payload.status || "").trim().toLowerCase() || "ok",
    url: normalizeBrowserUrl(payload.url || payload.current_url || payload.currentUrl || ""),
    title: clipText(payload.title || "", 300),
    focused,
    controls,
    visible_text: clipText(payload.visible_text || payload.visibleText || payload.text || payload.content_excerpt || "", 2400),
    dom_excerpt: clipText(payload.dom_excerpt || payload.domExcerpt || payload.html_excerpt || "", 2400),
    ax_tree: stringifyStructured(payload.ax_tree ?? payload.axTree ?? payload.accessibility_tree ?? payload.accessibilityTree, 3200),
    error: clipText(payload.error || "", 400),
    message: clipText(payload.message || "", 400),
    observed_at: new Date().toISOString(),
  };
}

function sanitizeBrowserObservationForContext(observation) {
  if (!observation || typeof observation !== "object") return null;
  return {
    status: String(observation.status || "").trim() || "unknown",
    url: normalizeBrowserUrl(observation.url || ""),
    title: clipText(observation.title || "", 300),
    focused: observation.focused || null,
    controls: Array.isArray(observation.controls) ? observation.controls.slice(0, 20) : [],
    visible_text: clipText(observation.visible_text || "", 1200),
    dom_excerpt: clipText(observation.dom_excerpt || "", 1200),
    ax_tree: clipText(observation.ax_tree || "", 1600),
    error: clipText(observation.error || "", 300),
    message: clipText(observation.message || "", 300),
  };
}

function browserObservationExtra(observation) {
  if (!observation || typeof observation !== "object") return "";
  if (observation.title) return observation.title;
  if (observation.url) {
    try {
      return new URL(observation.url).hostname;
    } catch {
      return observation.url;
    }
  }
  return "";
}

function buildBrowserSessionContext() {
  const browserUrl = normalizeBrowserUrl(state.browserCurrentUrl || state.browserHomeUrl);
  const surfaceMode = detectBrowserSurfaceMode();
  state.browserSurfaceMode = surfaceMode;
  const commandFormat = state.totalAgentControlEnabled
    ? "Real engine control is enabled. In auto/interpreter mode, prefer actual tool calls. Valid `bridge_local` modes are `subprocess`, `fs_read`, `fs_write`, `fs_mkdir`, `fs_list`, `http`, `browser_inspect`, `browser_action`, and `ui`. Never invent `ui_access`, `ui_info`, or `fs_create`. For folder creation use `fs_mkdir` with a full target path. For browser work use `browser_inspect` or `browser_action` with actions `open`, `navigate`, `goto`, `click`, `focus`, `type`, `fill`, or `submit`. On Windows, prefer PowerShell-friendly shell commands such as `Get-ChildItem`, `dir`, and `Get-Content`. If you are not in tool mode and need a direct browser command, emit exactly one full-response directive: `BROWSER_OPEN: https://...`, `BROWSER_INSPECT`, or `BROWSER_ACTION: {\"action\":\"click\",\"role\":\"button\",\"name\":\"Search\"}`."
    : "Chat-only mode. Do not invent tool JSON. If browser control is needed, emit exactly one full-response directive: `BROWSER_OPEN: https://...`, `BROWSER_INSPECT`, or `BROWSER_ACTION: {\"action\":\"open\",\"url\":\"https://...\"}`.";
  return {
    total_agent_control: state.totalAgentControlEnabled,
    browser_panel: {
      controllable: state.totalAgentControlEnabled,
      surface_mode: surfaceMode,
      current_url: browserUrl,
      command_format: commandFormat,
    },
    browser_session: {
      controllable: state.totalAgentControlEnabled,
      surface_mode: surfaceMode,
      current_url: browserUrl,
      capability_tier: state.browserSessionCapability || "session_attach_accessibility",
      observation_source: surfaceMode === "standalone" ? "host_sidebar" : "browser_window",
      command_format: commandFormat,
      last_observation: sanitizeBrowserObservationForContext(state.browserLastObservation),
    },
  };
}

function maybeAcceptBrowserBridgePayload(raw) {
  const payload = raw && typeof raw === "object" ? raw : null;
  if (!payload) return false;
  const type = String(payload.type || "").trim().toLowerCase();
  const detail =
    payload.detail && typeof payload.detail === "object"
      ? payload.detail
      : payload.data && typeof payload.data === "object"
        ? payload.data
        : payload;
  const looksBrowserish =
    type.startsWith("jl-browser-") ||
    detail.ax_tree != null ||
    detail.accessibility_tree != null ||
    detail.visible_text != null ||
    detail.dom_excerpt != null ||
    detail.title != null ||
    detail.current_url != null;
  if (!looksBrowserish) return false;

  const observation = normalizeBrowserObservation(detail);
  if (!observation.url && !observation.title && !observation.ax_tree && !observation.visible_text && !observation.error) {
    return false;
  }

  state.browserLastObservation = observation;
  if (observation.url) {
    state.browserCurrentUrl = observation.url;
  }
  state.browserSessionState = observation.status === "error" ? "blocked" : "observed";
  renderBrowserSessionState(browserObservationExtra(observation));
  if (observation.error) {
    feed(`Browser bridge: ${observation.error}`, "error");
  }
  return true;
}

function wireBrowserBridgeEvents() {
  window.addEventListener("message", (event) => {
    maybeAcceptBrowserBridgePayload(event.data);
  });
  window.addEventListener("jl-browser-result", (event) => {
    maybeAcceptBrowserBridgePayload(event.detail);
  });
  window.addEventListener("jl-browser-observation", (event) => {
    maybeAcceptBrowserBridgePayload(event.detail);
  });
  try {
    if (typeof window.chrome?.webview?.addEventListener === "function") {
      window.chrome.webview.addEventListener("message", (event) => {
        maybeAcceptBrowserBridgePayload(event.data);
      });
    }
  } catch {
    // ignore WebView bridge listener failures
  }
}

function isStandaloneBrowserMode() {
  try {
    if (window.matchMedia?.("(display-mode: window-controls-overlay)")?.matches) return true;
    if (window.matchMedia?.("(display-mode: standalone)")?.matches) return true;
  } catch {
    // ignore display-mode detection failures
  }
  return window.navigator.standalone === true;
}

function detectBrowserSurfaceMode() {
  return isStandaloneBrowserMode() ? "standalone" : "browser";
}

function renderBrowserSessionState(extra = "") {
  const chip = $("browserSessionChip");
  const btn = $("browserSessionBtn");
  if (chip) {
    const stateLabel =
      state.browserSurfaceMode === "standalone"
        ? "HOST SIDEBAR"
        : String(state.browserSessionState || "idle").toUpperCase();
    chip.textContent = extra ? `Browser Session: ${stateLabel} (${extra})` : `Browser Session: ${stateLabel}`;
  }
  if (btn) {
    btn.textContent = state.browserSurfaceMode === "standalone" ? "Ping Host Sidebar" : "Open Session Window";
  }
}

function renderBrowserSurfaceHint() {
  state.browserSurfaceMode = detectBrowserSurfaceMode();
  const hint = $("browserSurfaceHint");
  if (!hint) return;
  hint.textContent =
    state.browserSurfaceMode === "standalone"
      ? "Standalone mode: agent browser commands only use the host/sidebar bridge. If that bridge is unavailable, the deck stays put instead of opening a second app window."
      : "Browser mode: agent browser commands run inside a dedicated browser session window so you can watch what it is doing.";
  renderBrowserSessionState();
}

function sendBrowserOpenToHost(url, source = "user") {
  const payload = {
    type: "jl-browser-open",
    action: "open",
    target: "sidebar",
    url,
    source,
  };
  try {
    if (typeof window.JLDeckHost?.openBrowserSidebar === "function") {
      window.JLDeckHost.openBrowserSidebar(url, payload);
      return "host.openBrowserSidebar";
    }
    if (typeof window.JLDeckHost?.openSidebarBrowser === "function") {
      window.JLDeckHost.openSidebarBrowser(url, payload);
      return "host.openSidebarBrowser";
    }
    if (typeof window.JLDeckHost?.postMessage === "function") {
      window.JLDeckHost.postMessage(payload);
      return "host.postMessage";
    }
  } catch {
    // fall through to other host signals
  }
  try {
    if (typeof window.chrome?.webview?.postMessage === "function") {
      window.chrome.webview.postMessage(payload);
      return "chrome.webview";
    }
  } catch {
    // ignore WebView bridge failures
  }
  try {
    if (window.parent && window.parent !== window) {
      window.parent.postMessage(payload, "*");
    }
  } catch {
    // ignore parent postMessage failures
  }
  try {
    window.dispatchEvent(new CustomEvent("jl-browser-open", { detail: payload }));
  } catch {
    // ignore custom event failures
  }
  return "";
}

function paintBrowserSessionWindow(win) {
  if (!win || win.closed) return;
  try {
    if (win.location.href !== "about:blank") return;
    win.document.title = "JL Agent Browser Session";
    win.document.body.innerHTML = `
      <div style="font-family: Consolas, monospace; background:#050805; color:#78ff9a; margin:0; padding:24px;">
        <h2 style="margin:0 0 12px; color:#c8ffd6;">JL Agent Browser Session</h2>
        <p style="margin:0; opacity:0.85;">Waiting for the agent to open a page...</p>
      </div>
    `;
  } catch {
    // ignore cross-origin or paint failures
  }
}

function ensureBrowserSessionWindow(options = {}) {
  const { eager = false } = options;
  if (state.browserSurfaceMode === "standalone") {
    state.browserSessionState = "host";
    renderBrowserSessionState();
    return null;
  }
  let win = state.browserSessionWindow;
  if (win && !win.closed) {
    state.browserSessionState = "ready";
    renderBrowserSessionState();
    return win;
  }
  const features = "popup=yes,width=1200,height=860";
  win = window.open("about:blank", "jlDeckBrowserSession", features);
  if (!win) {
    state.browserSessionState = eager ? "blocked" : "idle";
    renderBrowserSessionState();
    return null;
  }
  state.browserSessionWindow = win;
  state.browserSessionState = "ready";
  paintBrowserSessionWindow(win);
  renderBrowserSessionState();
  return win;
}

function openBrowserSurfaceUrl(raw, source = "user") {
  const next = normalizeBrowserUrl(raw);
  if (!next) return false;
  state.browserCurrentUrl = next;
  state.browserSurfaceMode = detectBrowserSurfaceMode();
  renderBrowserSurfaceHint();
  let delivery = "";
  if (state.browserSurfaceMode === "standalone") {
    delivery = sendBrowserOpenToHost(next, source);
    if (!delivery) {
      state.browserSessionState = "blocked";
      renderBrowserSessionState();
      feed(`Standalone browser bridge is unavailable. Open this URL manually: ${next}`, "error");
      return false;
    }
  }
  if (!delivery && state.browserSurfaceMode === "browser") {
    const win = ensureBrowserSessionWindow();
    if (win && !win.closed) {
      try {
        win.location.href = next;
        win.focus();
        state.browserSessionState = "open";
        renderBrowserSessionState(new URL(next).hostname);
        delivery = "browserSessionWindow";
      } catch {
        // fall through to generic popup handling
      }
    }
  }
  if (!delivery) {
    const popup = window.open(next, "jlDeckBrowserSession", "popup=yes,width=1200,height=860");
    if (popup) {
      state.browserSessionWindow = popup;
      state.browserSessionState = "open";
      renderBrowserSessionState(new URL(next).hostname);
      delivery = "window.open";
    }
  }
  if (!delivery) {
    state.browserSessionState = "blocked";
    renderBrowserSessionState();
    feed(`Browser launch was blocked. Open this URL manually: ${next}`, "error");
    return false;
  }
  if (source === "agent") {
    appendMessage("system", `[browser] Agent opened ${next} via ${delivery}`, "chatLog");
  }
  return true;
}

function renderAgentControlButton() {
  const btn = $("toggleAgentControlBtn");
  if (!btn) return;
  btn.textContent = `Total Agent Control: ${state.totalAgentControlEnabled ? "ON" : "OFF"}`;
  btn.classList.toggle("active", state.totalAgentControlEnabled);
  btn.classList.toggle("ghost", !state.totalAgentControlEnabled);
}

function renderChatLoopChip() {
  const chip = $("chatLoopChip");
  const loopBtn = $("toggleChatLoopBtn");
  if (chip) {
    let label = "STOPPED";
    if (state.chatLoopRunning && state.chatLoopWaiting) {
      label = `WAITING CONFIRMATION (${state.chatLoopTurns})`;
    } else if (state.chatLoopRunning) {
      label = `RUNNING (${state.chatLoopTurns})`;
    }
    chip.textContent = `Loop: ${label}`;
  }
  if (loopBtn) {
    loopBtn.textContent = state.chatLoopRunning ? "Stop Agent Loop" : "Start Agent Loop";
  }
}

function parseBrowserDirectiveObject(raw) {
  const text = String(raw || "").trim();
  if (!text) return null;
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed;
    }
  } catch {
    // ignore malformed browser directive payloads
  }
  return null;
}

function extractBrowserDirective(text) {
  const reply = String(text || "").trim();
  if (!reply) return null;

  const openMatch = reply.match(/^BROWSER_OPEN\s*:\s*(https?:\/\/\S+)\s*$/i);
  if (openMatch?.[1]) {
    const url = String(openMatch[1]).trim();
    return {
      kind: "action",
      payload: { action: "open", url },
      cacheKey: `action:${JSON.stringify({ action: "open", url })}`,
    };
  }

  const inspectMatch = reply.match(/^BROWSER_INSPECT(?:\s*:\s*(.+))?\s*$/is);
  if (inspectMatch) {
    const rawPayload = String(inspectMatch[1] || "").trim();
    let payload = {};
    if (rawPayload) {
      payload = /^https?:\/\//i.test(rawPayload) ? { url: rawPayload } : parseBrowserDirectiveObject(rawPayload) || {};
    }
    return {
      kind: "inspect",
      payload,
      cacheKey: `inspect:${JSON.stringify(payload)}`,
    };
  }

  const actionMatch = reply.match(/^BROWSER_ACTION\s*:\s*(.+)\s*$/is);
  if (actionMatch) {
    const payload = parseBrowserDirectiveObject(actionMatch[1]);
    if (payload) {
      return {
        kind: "action",
        payload,
        cacheKey: `action:${JSON.stringify(payload)}`,
      };
    }
  }

  return null;
}

function normalizeBrowserActionPayload(payload) {
  const safePayload = payload && typeof payload === "object" ? { ...payload } : {};
  const target = safePayload.target && typeof safePayload.target === "object" ? safePayload.target : null;
  if (!safePayload.action) {
    if (safePayload.url) {
      safePayload.action = "open";
    } else if ((safePayload.value != null || safePayload.text != null) && (safePayload.selector || safePayload.id || safePayload.name || safePayload.label || safePayload.role || target)) {
      safePayload.action = "fill";
    } else if (safePayload.selector || safePayload.id || safePayload.name || safePayload.label || safePayload.role || target) {
      safePayload.action = "click";
    }
  }
  if (safePayload.action) {
    safePayload.action = String(safePayload.action).trim().toLowerCase();
  }
  return safePayload;
}

async function runBrowserInspectDirective(payload = {}, source = "agent") {
  const safePayload = payload && typeof payload === "object" ? payload : {};
  const res = await api("/browser/inspect", {
    method: "POST",
    body: JSON.stringify(safePayload),
    timeout_ms: 65000,
  });
  maybeAcceptBrowserBridgePayload({ type: "jl-browser-inspect", detail: res });
  const observation = normalizeBrowserObservation(res);
  state.browserLastObservation = observation;
  if (observation.url) {
    state.browserCurrentUrl = observation.url;
  }
  state.browserSessionState = observation.status === "error" ? "blocked" : "observed";
  renderBrowserSessionState(browserObservationExtra(observation));
  if (source === "agent") {
    appendMessage(
      "system",
      `[browser] Agent inspected ${observation.url || browserObservationExtra(observation) || "the current page"}`,
      "chatLog",
    );
  }
  if (observation.error) {
    throw new Error(observation.error || "browser_inspect_failed");
  }
  return res;
}

async function runBrowserActionDirective(payload = {}, source = "agent") {
  const safePayload = normalizeBrowserActionPayload(payload);
  if (!safePayload.action) {
    throw new Error("Browser action directive is missing an action.");
  }
  try {
    const res = await api("/browser/action", {
      method: "POST",
      body: JSON.stringify(safePayload),
      timeout_ms: 65000,
    });
    maybeAcceptBrowserBridgePayload({ type: "jl-browser-action", detail: res });
    state.browserSessionState = String(res.status || "").toLowerCase() === "ok" ? "open" : "blocked";
    renderBrowserSessionState(browserObservationExtra(normalizeBrowserObservation(res)) || String(safePayload.action || "").toUpperCase());
    if (source === "agent") {
      appendMessage(
        "system",
        `[browser] ${res.message || `Agent completed browser action ${safePayload.action}`}`,
        "chatLog",
      );
    }
    if (String(res.status || "").toLowerCase() !== "ok") {
      throw new Error(res.error || res.message || `browser_action_failed:${safePayload.action}`);
    }
    try {
      await runBrowserInspectDirective(safePayload.url ? { url: safePayload.url } : {}, "sync");
    } catch {
      // keep the successful action result even if the follow-up observation misses
    }
    return res;
  } catch (err) {
    if (safePayload.action === "open" && safePayload.url && openBrowserSurfaceUrl(safePayload.url, source)) {
      return {
        status: "ok",
        action: "open",
        url: normalizeBrowserUrl(safePayload.url),
        message: "Browser action completed via UI fallback.",
        fallback: true,
      };
    }
    throw err;
  }
}

async function maybeApplyAgentBrowserDirective(reply, source = "chat") {
  if (!state.totalAgentControlEnabled) return false;
  const directive = extractBrowserDirective(reply);
  if (!directive) return false;
  if (directive.cacheKey === state.lastBrowserDirective) return true;
  if (directive.kind === "inspect") {
    await runBrowserInspectDirective(directive.payload, "agent");
  } else {
    await runBrowserActionDirective(directive.payload, "agent");
  }
  state.lastBrowserDirective = directive.cacheKey;
  feed(`Agent ${source} browser control -> ${directive.kind}`, "ok");
  return true;
}

function toggleTotalAgentControl() {
  state.totalAgentControlEnabled = !state.totalAgentControlEnabled;
  if (state.totalAgentControlEnabled && detectBrowserSurfaceMode() === "browser") {
    ensureBrowserSessionWindow({ eager: true });
  }
  renderAgentControlButton();
  feed(
    state.totalAgentControlEnabled
      ? "Total Agent Control enabled. Agent can use real bridge tool calls plus browser open/inspect/action fallbacks."
      : "Total Agent Control disabled.",
    "ok",
  );
}

async function api(path, options = {}) {
  const { timeout_ms, ...rest } = options || {};
  const cfg = { ...rest, headers: { "Content-Type": "application/json", ...(rest.headers || {}) } };
  let timeoutId = null;
  let controller = null;
  if (!cfg.signal && typeof timeout_ms === "number" && timeout_ms > 0) {
    controller = new AbortController();
    cfg.signal = controller.signal;
    timeoutId = window.setTimeout(() => controller.abort("request_timeout"), timeout_ms);
  }
  let res;
  try {
    res = await fetch(path, cfg);
  } catch (err) {
    if (timeoutId) window.clearTimeout(timeoutId);
    if (err?.name === "AbortError") {
      throw new Error(`request_timeout:${path}`);
    }
    throw err;
  }
  if (timeoutId) window.clearTimeout(timeoutId);
  const raw = await res.text();
  let body = {};
  try {
    body = raw ? JSON.parse(raw) : {};
  } catch {
    body = { raw };
  }
  if (!res.ok) {
    const detail = body.detail || body.error || raw || `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return body;
}

function setActiveAgent(agentId) {
  state.activeAgentId = agentId || "";
  if ($("agentId")) {
    $("agentId").value = state.activeAgentId || JL_FAT_AGENT_ID;
  }
  refreshChatLoopStatus({ silent: true });
}

function appendMessage(role, text, logId = "chatLog") {
  const log = $(logId) || $("chatLog");
  if (!log) return;
  const msg = document.createElement("div");
  msg.className = `msg ${role}`;
  msg.textContent = decodeEscapedText(text);
  log.appendChild(msg);
  log.scrollTop = log.scrollHeight;
  return msg;
}

function setMessageText(node, text, role = "") {
  if (!node) return;
  if (role) {
    node.className = `msg ${role}`;
  }
  node.textContent = decodeEscapedText(text);
}

function setChatBusy(busy) {
  state.chatRequestPending = !!busy;
  const sendBtn = $("sendChatBtn");
  const input = $("chatInput");
  const lockedByPendingAction = !!state.pendingChatActionId;
  const resolvingPendingAction = !!state.pendingChatActionDecisionPending;
  const disabled = !!busy || lockedByPendingAction || resolvingPendingAction;
  if (sendBtn) {
    sendBtn.disabled = disabled;
    sendBtn.textContent = busy
      ? "Sending..."
      : resolvingPendingAction
        ? "Resolving..."
        : lockedByPendingAction
          ? "Resolve Action"
          : "Send Chat";
  }
  if (input) {
    input.disabled = disabled;
    input.placeholder = busy
      ? voiceSkinCopy(currentChatAgentLabel()).busy
      : resolvingPendingAction
        ? "Action approval is running..."
        : lockedByPendingAction
          ? "Resolve the pending action card first."
          : voiceSkinCopy(currentChatAgentLabel()).prompt;
  }
}

function currentChatAgentLabel() {
  return String(
    getSelectedChild()
      || state.switchboard?.current?.child
      || state.currentSelection?.child
      || state.currentSelection?.agent_name
      || "SparkByte"
  ).trim() || "SparkByte";
}

function buildPendingChatLabel(startedAt) {
  const elapsed = Math.max(0, Math.round((Date.now() - startedAt) / 1000));
  const model = String(state.currentOllamaModel || state.runtimeMode?.effective_model || "local model").trim();
  const mode = String(
    state.runtimeMode?.effective_mode || state.runtimeMode?.configured_mode || "local_only"
  ).trim();
  const elapsedText = elapsed > 0 ? ` | ${elapsed}s` : "";
  return `${currentChatAgentLabel()} is thinking... ${mode} | ${model}${elapsedText}`;
}

function appendMessageCard(role, logId = "chatLog") {
  const log = $(logId) || $("chatLog");
  if (!log) return null;
  const msg = document.createElement("div");
  msg.className = `msg ${role}`;
  log.appendChild(msg);
  log.scrollTop = log.scrollHeight;
  return msg;
}

function appendThinkingSummaryCard(title, lines = [], options = {}) {
  const cleanLines = Array.isArray(lines)
    ? lines.map((line) => String(line || "").trim()).filter(Boolean)
    : [];
  if (!cleanLines.length) return null;
  const card = appendMessageCard(`system thinking-card ${options.tone || "info"}`.trim(), options.logId || "chatLog");
  if (!card) return null;
  const heading = document.createElement("div");
  heading.className = "thinking-title";
  heading.textContent = String(title || `${currentChatAgentLabel()} thought stream`);
  card.appendChild(heading);
  for (const line of cleanLines) {
    const detail = document.createElement("div");
    detail.className = "thinking-detail";
    detail.textContent = decodeEscapedText(line);
    card.appendChild(detail);
  }
  return card;
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
    if (mode === "browser_inspect") return "inspected the browser accessibility tree";
    if (mode === "browser_action") return `requested browser action${data.action ? ` (${data.action})` : ""}`;
    if (mode === "http") {
      const method = String(data.method || "GET").toUpperCase();
      return method === "GET" ? `fetched ${data.url || "a URL"}` : `sent ${method} request`;
    }
    if (mode === "subprocess") return "ran subprocess";
    if (mode === "ui") return `controlled UI${data.action ? ` (${data.action})` : ""}`;
    return `used bridge_local (${mode || "unknown"})`;
  }
  if (tool === "run_shell") return `ran shell command`;
  if (tool === "run_cc_command") return `ran local command`;
  if (tool === "py_exec_stream") return `executed Python`;
  if (tool === "forge_list") return "inspected RAM tools";
  if (tool === "forge_create") return `created RAM tool ${input.name || ""}`.trim();
  if (tool === "forge_delete") return `deleted RAM tool ${input.name || ""}`.trim();
  if (tool === "forge_promote" || tool === "forge_promote_last") return "promoted RAM tool";
  if (tool === "forge_run") return `ran RAM tool ${input.name || ""}`.trim();
  if (result.status === "ok" || result.ok === true) return `used ${tool}`;
  return `${tool} -> ${result.status || result.error || "done"}`;
}

function formatActivitySummary(trace) {
  if (!Array.isArray(trace) || !trace.length) return "";
  const parts = trace.map(summarizeToolStep).filter(Boolean);
  if (!parts.length) return "";
  const shown = parts.slice(0, 3);
  if (parts.length > 3) {
    shown.push(`+${parts.length - 3} more`);
  }
  return shown.join(" | ");
}

function extractToolTrace(response) {
  return Array.isArray(response?.tool_trace)
    ? response.tool_trace
    : Array.isArray(response?.result?.tool_trace)
      ? response.result.tool_trace
      : [];
}

function appendActivitySummary(trace, logId = "chatLog", options = {}) {
  const summary = formatActivitySummary(trace);
  const telemetryPayload = options.telemetry && typeof options.telemetry === "object" ? options.telemetry : null;
  const telemetryText = telemetryPayload && Object.keys(telemetryPayload).length
    ? summarizeTelemetry(telemetryPayload)
    : "";
  const pendingSummary = String(options.pendingSummary || "").trim();
  const lines = [];
  if (summary) lines.push(`Action stream: ${summary}`);
  if (telemetryText) lines.push(`Telemetry: ${telemetryText}`);
  if (pendingSummary) lines.push(`Gate: ${pendingSummary}`);
  if (!lines.length) return "";
  feed(`[activity] ${summary || telemetryText || pendingSummary}`, options.tone === "warning" ? "info" : "info");
  appendThinkingSummaryCard(
    options.label || `${currentChatAgentLabel()} thought stream`,
    lines,
    { logId, tone: options.tone || "info" }
  );
  return summary;
}

function ensurePendingActionStatus(card) {
  if (!card) return null;
  let status = card.querySelector(".confirm-status");
  if (!status) {
    status = document.createElement("div");
    status.className = "confirm-status";
    card.appendChild(status);
  }
  return status;
}

function setPendingActionStatus(card, label, tone = "info") {
  const status = ensurePendingActionStatus(card);
  if (!status) return;
  status.className = `confirm-status ${tone}`;
  status.textContent = label;
}

function finalizePendingActionCard(card, label, tone = "info") {
  if (!card) return;
  card.classList.add("resolved");
  const actions = card.querySelector(".confirm-actions");
  if (actions) actions.remove();
  setPendingActionStatus(card, label, tone);
}

async function resolvePendingChatAction(pendingAction, approved, card, controls = []) {
  const actionId = String(pendingAction?.id || "").trim();
  if (!actionId) return;
  const priorTraceCount = Number(card?.dataset?.traceCount || 0);
  state.pendingChatActionDecisionPending = true;
  setChatBusy(state.chatRequestPending);
  for (const control of controls) {
    if (control) control.disabled = true;
  }
  setPendingActionStatus(card, approved ? "Sending approval..." : "Sending rejection...");
  try {
    const res = await api("/quest/chat/confirm", {
      method: "POST",
      body: JSON.stringify({
        agent_id: state.activeAgentId || JL_FAT_AGENT_ID,
        pending_action_id: actionId,
        approved,
        return_trace: true,
      }),
    });
    if (res.status === "error") {
      throw new Error(res.error || res.reply || "Pending action failed.");
    }

    if (state.pendingChatActionId === actionId) {
      state.pendingChatActionId = "";
    }
    finalizePendingActionCard(card, approved ? "Approved." : "Rejected.", approved ? "ok" : "warn");

    const reply = String(res.reply || res.result?.final || res.final || "").trim();
    const handledBrowserDirective = await maybeApplyAgentBrowserDirective(reply, approved ? "chat_confirm" : "chat_reject");
    if (reply) {
      if (!handledBrowserDirective) {
        appendMessage("agent", reply, "chatLog");
      }
    }

    const trace = extractToolTrace(res);
    const newTrace = trace.slice(Math.max(0, priorTraceCount));
    if (res.status === "confirmation_required" && res.pending_action) {
      if (approved) {
        appendActivitySummary(newTrace, "chatLog", {
          label: `${currentChatAgentLabel()} action stream`,
          tone: "warning",
          pendingSummary: res.pending_action.summary,
        });
      }
      renderPendingActionCard(res.pending_action, { priorTraceCount: trace.length });
      feed(`Awaiting confirmation: ${res.pending_action.summary}`, "info");
    } else {
      if (approved) {
        appendActivitySummary(newTrace, "chatLog", {
          label: `${currentChatAgentLabel()} execution recap`,
        });
      }
      feed(
        approved ? `Action approved: ${pendingAction.summary}` : `Action rejected: ${pendingAction.summary}`,
        approved ? "ok" : "info",
      );
    }

    await refreshAgents();
    await loadTools();
  } catch (err) {
    setPendingActionStatus(card, `Decision failed: ${err.message}`, "error");
    for (const control of controls) {
      if (control) control.disabled = false;
    }
    feed(`Pending action failed: ${err.message}`, "error");
  } finally {
    state.pendingChatActionDecisionPending = false;
    setChatBusy(state.chatRequestPending);
  }
}

function renderPendingActionCard(pendingAction, options = {}) {
  const actionId = String(pendingAction?.id || "").trim();
  if (!actionId) return null;
  if (state.pendingChatActionId === actionId) return null;
  state.pendingChatActionId = actionId;
  setChatBusy(state.chatRequestPending);

  const card = appendMessageCard("system confirm-card", "chatLog");
  if (!card) return null;
  const title = document.createElement("div");
  title.className = "confirm-title";
  title.textContent = "Confirmation Required";

  const summary = document.createElement("div");
  summary.className = "confirm-summary";
  summary.textContent = String(pendingAction.summary || "Pending action");

  const meta = document.createElement("div");
  meta.className = "confirm-meta";
  const risk = String(pendingAction.risk_level || "medium").toUpperCase();
  meta.textContent = `Risk: ${risk} | Tool: ${pendingAction.tool || "unknown"}`;

  const actions = document.createElement("div");
  actions.className = "row confirm-actions";
  const approveBtn = document.createElement("button");
  approveBtn.type = "button";
  approveBtn.textContent = "Approve";
  const rejectBtn = document.createElement("button");
  rejectBtn.type = "button";
  rejectBtn.className = "ghost";
  rejectBtn.textContent = "Reject";
  approveBtn.addEventListener("click", () => resolvePendingChatAction(pendingAction, true, card, [approveBtn, rejectBtn]));
  rejectBtn.addEventListener("click", () => resolvePendingChatAction(pendingAction, false, card, [approveBtn, rejectBtn]));
  actions.appendChild(approveBtn);
  actions.appendChild(rejectBtn);

  card.dataset.traceCount = String(Math.max(0, Number(options.priorTraceCount || 0)));
  card.appendChild(title);
  card.appendChild(summary);
  card.appendChild(meta);
  card.appendChild(actions);
  setPendingActionStatus(card, "Waiting for your decision.");
  return card;
}

function formatToolTrace(trace) {
  if (!Array.isArray(trace) || !trace.length) return "";
  return trace
    .map((step, idx) => {
      const tool = step.tool || "unknown_tool";
      const status = step?.result?.status || step?.result?.ok || "unknown";
      return `${idx + 1}. ${tool} -> ${status}`;
    })
    .join("\n");
}

function formatHostLabel(value) {
  const raw = String(value || "").trim();
  const key = normalizeToken(raw);
  if (key === "computercontrol" || key === "mycomputer") return "my-computer";
  return raw || "unknown";
}

function renderAgents() {
  const wrap = $("agentList");
  wrap.innerHTML = "";
  if (!state.agents.length) {
    wrap.innerHTML = `<div class="card"><div class="muted">No agents yet.</div></div>`;
    return;
  }
  for (const agent of state.agents) {
    const card = document.createElement("div");
    card.className = "card";
    const id = agent.agent_id || "unknown";
    const agentProfile = agent.agent || agent.persona || "n/a";
    const lane = agent.active_lane || "unknown";
    const child = agent.active_child || agent.active_agent_name || agentProfile;
    const generatedInstance = agent.last_generated_instance_id ? ` | generated: ${agent.last_generated_instance_id}` : "";
    const delegated = agent.last_delegated_to
      ? ` | delegated: ${agent.last_delegated_class || "helper"} -> ${agent.last_delegated_to}`
      : "";
    card.innerHTML = `
      <div class="title">${id}</div>
      <div class="muted">agent profile: ${agentProfile} | lane: ${lane} | child: ${child}</div>
      <div class="muted">clones: ${agent.clone_generation || 0} | failures: ${agent.failures || 0}${generatedInstance}${delegated}</div>
      <div class="row" style="margin-top:8px">
        <button data-set="${id}">Set Active</button>
      </div>
    `;
    card.querySelector("button[data-set]").addEventListener("click", () => {
      setActiveAgent(id);
      renderSelectionChips(agent);
      loadSwitchboard({ silent: true, preferredLane: agent.active_lane || "", preferredChild: agent.active_child || "" });
      loadTools();
      feed(`Active agent set to ${id}`, "ok");
    });
    wrap.appendChild(card);
  }
}

async function refreshTopline() {
  try {
    const root = await api("/");
    let hostLabels = [];
    try {
      const hostData = await api("/hosts");
      const hosts = Array.isArray(hostData.hosts) ? hostData.hosts : [];
      hostLabels = hosts.map((item) => formatHostLabel(item.label || item.id));
    } catch {
      const rootHosts = Array.isArray(root.hosts) ? root.hosts : [];
      hostLabels = rootHosts.map((item) => formatHostLabel(item));
    }
    $("apiStatusChip").textContent = "API: Online";
    const hostsText = hostLabels.length ? hostLabels.join(", ") : "none";
    $("hostsChip").textContent = `Hosts: ${hostsText}`;
  } catch (err) {
    $("apiStatusChip").textContent = "API: Offline";
    $("hostsChip").textContent = "Hosts: unknown";
    feed(`Topline refresh failed: ${err.message}`, "error");
  }
  renderRuntimeModeChip();
}

function renderOllamaModelSelector() {
  const select = $("brainModelSelect");
  const chip = $("brainModelChip");
  const models = Array.isArray(state.ollamaModels) ? [...state.ollamaModels] : [];
  const current = String(state.currentOllamaModel || "").trim();

  if (current && !models.some((item) => String(item?.name || "").trim() === current)) {
    models.unshift({ name: current, size_mb: 0.0 });
  }

  if (select) {
    select.innerHTML = "";
    if (!models.length) {
      const opt = document.createElement("option");
      opt.value = current;
      opt.textContent = current || "No Ollama models detected";
      select.appendChild(opt);
    } else {
      for (const item of models) {
        const name = String(item?.name || "").trim();
        if (!name) continue;
        const sizeMb = Number(item?.size_mb || 0);
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = sizeMb > 0 ? `${name} (${sizeMb.toFixed(1)} MB)` : name;
        select.appendChild(opt);
      }
    }
    if (current) {
      select.value = current;
    }
  }

  if (chip) {
    const backend = String(state.currentBrainBackendId || "").trim();
    const modelText = current || "unknown";
    chip.textContent = backend && backend !== "ollama-local" ? `Model: ${modelText} [${backend}]` : `Model: ${modelText}`;
  }
}

async function refreshOllamaModels(options = {}) {
  const { silent = false } = options;
  try {
    const res = await api("/settings/ollama");
    state.ollamaModels = Array.isArray(res.models) ? res.models : [];
    state.currentOllamaModel = String(res.current_model || "").trim();
    state.currentOllamaBaseUrl = String(res.base_url || "").trim();
    state.currentBrainBackendId = String(res.brain_backend_id || "").trim();
    state.currentToolBackendId = String(res.tool_backend_id || "").trim();
    renderOllamaModelSelector();
    return res;
  } catch (err) {
    renderOllamaModelSelector();
    if (!silent) {
      feed(`Model refresh failed: ${err.message}`, "error");
    }
    return null;
  }
}

async function applySelectedOllamaModel() {
  const modelName = $("brainModelSelect")?.value?.trim() || "";
  if (!modelName) {
    feed("Select an Ollama model first.", "error");
    return;
  }
  try {
    const res = await api("/settings/ollama/model", {
      method: "POST",
      body: JSON.stringify({ model_name: modelName }),
    });
    state.ollamaModels = Array.isArray(res.models) ? res.models : state.ollamaModels;
    state.currentOllamaModel = String(res.model_name || res.current_model || modelName).trim();
    state.currentOllamaBaseUrl = String(res.base_url || state.currentOllamaBaseUrl || "").trim();
    state.currentBrainBackendId = String(res.brain_backend_id || state.currentBrainBackendId || "").trim();
    state.currentToolBackendId = String(res.tool_backend_id || state.currentToolBackendId || "").trim();
    renderOllamaModelSelector();
    feed(`Brain model set to ${state.currentOllamaModel}`, "ok");
  } catch (err) {
    feed(`Model switch failed: ${err.message}`, "error");
  }
}

function renderSwitchboardChildren(preferredChild = "") {
  const lane = getSelectedLane() || state.switchboard?.default_lane || "fat_agent";
  const select = $("childSelect");
  const description = $("switchboardDescription");
  const matrix = $("switchboardMatrix");
  const newInstanceWrap = $("newGeneratedInstanceWrap");
  const laneEntry = state.switchboard?.lanes?.[lane] || {};
  const children = laneEntry && typeof laneEntry.children === "object" ? laneEntry.children : {};
  const current = state.switchboard?.current || {};
  const targetChild =
    preferredChild ||
    current.child ||
    String(laneEntry.default_child || "").trim() ||
    Object.keys(children)[0] ||
    "";

  if (select) {
    select.innerHTML = "";
    for (const [childName, childEntry] of Object.entries(children)) {
      const opt = document.createElement("option");
      opt.value = childName;
      opt.textContent = String(childEntry?.label || childName);
      select.appendChild(opt);
    }
    if (targetChild && Object.prototype.hasOwnProperty.call(children, targetChild)) {
      select.value = targetChild;
    }
  }

  const activeChild = getSelectedChild() || targetChild;
  const activeEntry = children[activeChild] || {};
  if (description) {
    const role = String(activeEntry.role || activeEntry.agent_name || activeChild || "").trim();
    const text = String(activeEntry.description || laneEntry.label || "").trim();
    description.textContent = role && text ? `${role}: ${text}` : text || "Switch lanes and child agents here.";
  }

  if (matrix) {
    const cards = Object.entries(children).map(([childName, childEntry]) => {
      const tags = Array.isArray(childEntry?.tags) && childEntry.tags.length ? `Tags: ${childEntry.tags.join(", ")}` : "";
      const meta = [String(childEntry?.classification || lane).trim(), tags].filter(Boolean).join(" | ");
      return `
        <div class="card${childName === activeChild ? " selected" : ""}">
          <div class="title">${childEntry?.label || childName}</div>
          <div class="muted">${meta || lane}</div>
        </div>
      `;
    });
    matrix.innerHTML = cards.length ? cards.join("") : `<div class="card"><div class="muted">No children defined.</div></div>`;
  }

  if (newInstanceWrap) {
    newInstanceWrap.classList.toggle("hidden", lane !== "generated");
  }
}

function renderSwitchboard(selection = null) {
  const laneSelect = $("laneSelect");
  if (!laneSelect) return;
  const data = state.switchboard && typeof state.switchboard === "object" ? state.switchboard : {};
  const lanes = data.lanes && typeof data.lanes === "object" ? data.lanes : {};
  const current = selection && typeof selection === "object" ? selection : data.current || {};
  const targetLane = String(current.lane || data.default_lane || "fat_agent").trim() || "fat_agent";

  laneSelect.innerHTML = "";
  for (const [laneName, laneEntry] of Object.entries(lanes)) {
    const opt = document.createElement("option");
    opt.value = laneName;
    opt.textContent = String(laneEntry?.label || laneName);
    laneSelect.appendChild(opt);
  }
  if (targetLane && Object.prototype.hasOwnProperty.call(lanes, targetLane)) {
    laneSelect.value = targetLane;
  }

  renderSwitchboardChildren(String(current.child || "").trim());
  renderSelectionChips(current);
}

async function loadSwitchboard(options = {}) {
  const { silent = false, preferredLane = "", preferredChild = "" } = options;
  const agentId = state.activeAgentId || $("agentId")?.value?.trim() || JL_FAT_AGENT_ID;
  try {
    const res = await api(`/quest/switchboard?agent_id=${encodeURIComponent(agentId)}`);
    state.switchboard = res;
    const current = res.current && typeof res.current === "object" ? { ...res.current } : {};
    if (preferredLane) current.lane = preferredLane;
    if (preferredChild) current.child = preferredChild;
    renderSwitchboard(current);
    renderSelectionChips(current);
    return res;
  } catch (err) {
    if (!silent) {
      feed(`Switchboard refresh failed: ${err.message}`, "error");
    }
    return null;
  }
}

async function switchActiveLane() {
  const lane = getSelectedLane();
  const child = getSelectedChild() || null;
  if (!lane) {
    feed("Choose a lane first.", "error");
    return;
  }
  const agentId = state.activeAgentId || $("agentId")?.value?.trim() || JL_FAT_AGENT_ID;
  const newInstance = wantsNewGeneratedInstance();
  try {
    const res = await api("/quest/switch", {
      method: "POST",
      body: JSON.stringify({
        agent_id: agentId,
        lane,
        child,
        new_instance: newInstance,
      }),
    });
    setActiveAgent(res.agent_id || agentId);
    if (res.agent?.agent) {
      syncPersonaSelectors(res.agent.agent);
    }
    renderSelectionChips(res.selection || res.agent || {});
    clearNewGeneratedInstanceRequest();
    await refreshAgents();
    await loadSwitchboard({
      silent: true,
      preferredLane: String(res.selection?.lane || lane),
      preferredChild: String(res.selection?.child || child || ""),
    });
    await loadTools();
    feed(
      `Switchboard locked to ${res.selection?.lane || lane} -> ${res.selection?.child || child || "default"}`,
      "ok",
    );
  } catch (err) {
    feed(`Switch failed: ${err.message}`, "error");
  }
}

async function refreshRuntimeMode(options = {}) {
  const { silent = false } = options;
  try {
    const res = await api("/settings/runtime-mode");
    state.runtimeMode = res;
    renderRuntimeModeChip();
    return res;
  } catch (err) {
    if (!silent) {
      feed(`Runtime mode refresh failed: ${err.message}`, "error");
    }
    return null;
  }
}

async function refreshAgents() {
  try {
    const data = await api("/quest/agents");
    state.agents = Array.isArray(data.agents) ? data.agents : [];
    renderAgents();
    if (!state.activeAgentId && state.agents.length) {
      const preferred =
        state.agents.find(
          (item) =>
            normalizeToken(item.agent || item.persona || item.active_child || "") ===
            normalizeToken(PRIMARY_PRODUCT_SELECTION.persona),
        ) || state.agents[0];
      setActiveAgent(preferred.agent_id);
      syncPersonaSelectors(preferred.agent || preferred.persona || preferred.agent_id);
      renderSelectionChips(preferred);
    }
    const active = state.agents.find((item) => item.agent_id === state.activeAgentId);
    if (active) {
      renderSelectionChips(active);
    }
  } catch (err) {
    feed(`Agent refresh failed: ${err.message}`, "error");
  }
}

function renderMpfPersonaOptions(emptyLabel = "Loading personas...") {
  const personas = Array.isArray(state.mpfPersonas) ? state.mpfPersonas : [];
  const targets = ["chatPersonaSelect", "mpfPersonaSelect"];
  for (const targetId of targets) {
    const select = $(targetId);
    if (!select) continue;
    const prior = select.value;
    if (!personas.length) {
      select.innerHTML = `<option value="">${emptyLabel}</option>`;
      continue;
    }
    const options = personas
      .filter((persona) => persona.exists)
      .map((persona) => {
        const tags = Array.isArray(persona.tags) && persona.tags.length ? ` | ${persona.tags.join(", ")}` : "";
        return `<option value="${persona.name}">${persona.name}${tags}</option>`;
      });
    select.innerHTML = options.join("");
    if (prior && personas.some((persona) => persona.exists && persona.name === prior)) {
      select.value = prior;
      continue;
    }
    if (personas.some((persona) => persona.exists && persona.name === "SparkByte")) {
      select.value = "SparkByte";
      continue;
    }
    const first = personas.find((persona) => persona.exists);
    if (first) {
      select.value = first.name;
    }
  }
  const selectedPersona = $("chatPersonaSelect")?.value?.trim() || $("mpfPersonaSelect")?.value?.trim() || "SparkByte";
  setAgentIdInputFromPersona(selectedPersona);
}

async function loadMpfPersonas(options = {}) {
  const { silent = false } = options;
  try {
    const data = await api("/quest/agents/profiles/mpf");
    const profiles = Array.isArray(data.agent_profiles)
      ? data.agent_profiles
      : (Array.isArray(data.agents) ? data.agents : data.personas);
    state.mpfPersonas = Array.isArray(profiles) ? profiles : [];
    renderMpfPersonaOptions("No MPF agent profiles found");
    const existingCount = state.mpfPersonas.filter((persona) => persona.exists).length;
    if (existingCount !== state.lastMpfPersonaCount) {
      state.lastMpfPersonaCount = existingCount;
      if (!silent) {
        feed(`Loaded ${existingCount} MPF agent profile${existingCount === 1 ? "" : "s"}.`, "ok");
      }
    }
    return existingCount > 0;
  } catch (err) {
    state.mpfPersonas = [];
    renderMpfPersonaOptions("Waiting for MPF agent profiles...");
    if (!silent) {
      feed(`MPF agent profile refresh failed: ${err.message}`, "error");
    }
    return false;
  }
}

function getPreferredMpfPersona() {
  const chatSelected = $("chatPersonaSelect")?.value?.trim() || "";
  if (chatSelected) return chatSelected;
  const builderSelected = $("mpfPersonaSelect")?.value?.trim() || "";
  if (builderSelected) return builderSelected;
  const existing = (state.mpfPersonas || []).find((persona) => persona.exists && persona.name === "SparkByte");
  if (existing) return existing.name;
  const fallback = (state.mpfPersonas || []).find((persona) => persona.exists);
  return fallback ? fallback.name : "SparkByte";
}

function getDefaultMpfPersona() {
  const existing = (state.mpfPersonas || []).find((persona) => persona.exists && persona.name === "SparkByte");
  if (existing) return existing.name;
  const fallback = (state.mpfPersonas || []).find((persona) => persona.exists);
  return fallback ? fallback.name : "SparkByte";
}

function resolvePersonaByAlias(aliasKey) {
  const aliases = PERSONA_PRESET_ALIASES[aliasKey] || [];
  const wanted = new Set(aliases.map(normalizeToken));
  if (!wanted.size) return null;
  const personas = (state.mpfPersonas || []).filter((persona) => persona.exists);
  for (const persona of personas) {
    if (wanted.has(normalizeToken(persona.name))) {
      return persona.name;
    }
  }
  return null;
}

function syncPersonaSelectors(personaName) {
  if (!personaName) return;
  const chatSelect = $("chatPersonaSelect");
  const builderSelect = $("mpfPersonaSelect");
  if (chatSelect) chatSelect.value = personaName;
  if (builderSelect) builderSelect.value = personaName;
  setAgentIdInputFromPersona(personaName);
  const selection = resolveSwitchboardSelectionByAgentName(personaName);
  if (selection) {
    if ($("laneSelect")) $("laneSelect").value = selection.lane;
    renderSwitchboardChildren(selection.child);
    renderSelectionChips({
      lane: selection.lane,
      child: selection.child,
      agent_name: String(selection.entry?.agent_name || selection.child),
      generated_instance_id: null,
    });
  }
}

function getActiveAgentPersona() {
  const id = state.activeAgentId;
  if (!id) return "";
  const agent = (state.agents || []).find((item) => item.agent_id === id);
  return (agent?.agent || agent?.persona || "").trim();
}

async function activatePersonaByName(personaName) {
  const requested = String(personaName || "").trim();
  if (!requested) {
    throw new Error("agent_name_required");
  }
  const switchboardSelection = resolveSwitchboardSelectionByAgentName(requested);
  if (switchboardSelection) {
    if ($("laneSelect")) $("laneSelect").value = switchboardSelection.lane;
    renderSwitchboardChildren(switchboardSelection.child);
    await switchActiveLane();
    return {
      status: "ok",
      agent: {
        agent_id: state.activeAgentId || JL_FAT_AGENT_ID,
        agent: String(switchboardSelection.entry?.agent_name || requested),
      },
      agent_name: String(switchboardSelection.entry?.agent_name || requested),
      persona_name: String(switchboardSelection.entry?.agent_name || requested),
    };
  }
  const targetAgentId = agentIdFromPersona(requested);
  const res = await api("/quest/agents/register-mpf-persona", {
    method: "POST",
    body: JSON.stringify({
      agent_id: targetAgentId,
      agent_name: requested,
      persona_name: requested,
    }),
  });
  setActiveAgent(res.agent?.agent_id || targetAgentId);
  syncPersonaSelectors(res.agent_name || res.persona_name || requested);
  await refreshAgents();
  await loadSwitchboard({ silent: true });
  await loadTools();
  feed(`MPF fat agent profile active: ${res.agent_name || res.persona_name || requested}`, "ok");
  return res;
}

async function activateChatPersona() {
  try {
    const selected = $("chatPersonaSelect")?.value?.trim() || getPreferredMpfPersona();
    await activatePersonaByName(selected);
  } catch (err) {
    feed(`Activate chat agent profile failed: ${err.message}`, "error");
  }
}

async function activatePresetPersona(aliasKey) {
  if (!state.mpfPersonas.length) {
    await loadMpfPersonas();
  }
  const resolved = resolvePersonaByAlias(aliasKey);
  if (!resolved) {
    feed(`Preset agent profile not found: ${aliasKey}`, "error");
    return;
  }
  syncPersonaSelectors(resolved);
  await activatePersonaByName(resolved);
}

async function ensureActiveAgentFromMpf(options = {}) {
  const { forcePrimary = false } = options;
  if (state.switchboard) {
    const lane = forcePrimary
      ? PRIMARY_PRODUCT_SELECTION.lane
      : getSelectedLane() || state.switchboard.default_lane || PRIMARY_PRODUCT_SELECTION.lane;
    const child = forcePrimary ? PRIMARY_PRODUCT_SELECTION.child : getSelectedChild() || null;
    try {
      const res = await api("/quest/switch", {
        method: "POST",
        body: JSON.stringify({
          agent_id: JL_FAT_AGENT_ID,
          lane,
          child,
          new_instance: false,
        }),
      });
      setActiveAgent(res.agent_id || JL_FAT_AGENT_ID);
      renderSelectionChips(res.selection || res.agent || {});
      await refreshAgents();
      await loadSwitchboard({
        silent: true,
        preferredLane: String(res.selection?.lane || lane),
        preferredChild: String(res.selection?.child || child || ""),
      });
      return res.agent_id || JL_FAT_AGENT_ID;
    } catch {
      // fall through to legacy MPF bootstrap
    }
  }
  const personaName = forcePrimary ? PRIMARY_PRODUCT_SELECTION.persona : getDefaultMpfPersona();
  const targetAgentId = agentIdFromPersona(personaName);
  const already = (state.agents || []).some((agent) => agent.agent_id === targetAgentId);
  if (already) {
    setActiveAgent(targetAgentId);
    syncPersonaSelectors(personaName);
    return targetAgentId;
  }
  const res = await api("/quest/agents/register-mpf-persona", {
    method: "POST",
    body: JSON.stringify({
      agent_id: targetAgentId,
      agent_name: personaName,
      persona_name: personaName,
    }),
  });
  setActiveAgent(res.agent?.agent_id || targetAgentId);
  syncPersonaSelectors(res.agent_name || res.persona_name || personaName);
  feed(`MPF-first bootstrap: ${targetAgentId} on ${res.agent_name || res.persona_name || personaName}`, "ok");
  await refreshAgents();
  return targetAgentId;
}

function parseJsonSafe(raw, fallback = {}) {
  if (!raw || !raw.trim()) return fallback;
  try {
    return JSON.parse(raw);
  } catch (err) {
    throw new Error(`Invalid JSON payload: ${err.message}`);
  }
}

async function activateMpfAgent() {
  try {
    const selectedPersona = $("mpfPersonaSelect").value.trim();
    const targetPersona = selectedPersona || getPreferredMpfPersona();
    const agentId = agentIdFromPersona(targetPersona);
    const customMpfPath = $("mpfPath").value.trim();
    const switchboardSelection = !customMpfPath ? resolveSwitchboardSelectionByAgentName(targetPersona) : null;
    if (switchboardSelection) {
      if ($("laneSelect")) $("laneSelect").value = switchboardSelection.lane;
      renderSwitchboardChildren(switchboardSelection.child);
      await switchActiveLane();
      return;
    }
    let endpoint = "/quest/agents/register-mpf-persona";
    let payload = {
      agent_id: agentId,
      agent_name: targetPersona,
      persona_name: targetPersona,
    };
    if (customMpfPath) {
      endpoint = "/quest/agents/register-mpf";
      payload = {
        agent_id: agentId,
        mpf_path: customMpfPath,
      };
    }
    const res = await api(endpoint, { method: "POST", body: JSON.stringify(payload) });
    setActiveAgent(res.agent_id || agentId);
    if (res.agent_name || res.persona_name) {
      syncPersonaSelectors(res.agent_name || res.persona_name);
    } else if (payload.persona_name) {
      syncPersonaSelectors(payload.persona_name);
    }
    feed(`MPF agent profile active: ${res.agent_name || res.persona_name || payload.persona_name || "selected"}`, "ok");
    await refreshAgents();
    await loadSwitchboard({ silent: true });
    await loadTools();
  } catch (err) {
    feed(`Activate MPF agent failed: ${err.message}`, "error");
  }
}

async function buildBusinessAgent() {
  const agentId = $("agentId").value.trim();
  if (!agentId) {
    feed("Agent ID is required.", "error");
    return;
  }
  try {
    const payload = {
      agent_id: agentId,
      name: $("bName").value.trim(),
      industry: $("bIndustry").value.trim(),
      audience: $("bAudience").value.trim(),
      voice: $("bVoice").value.trim(),
      values: $("bValues").value.trim(),
      style: $("bVoice").value.trim(),
      abilities: "execution\nadaptation\ntoolsmith",
    };
    const res = await api("/quest/agents/register-business", { method: "POST", body: JSON.stringify(payload) });
    setActiveAgent(res.agent_id || agentId);
    feed("Business module built and registered an MPF agent profile.", "ok");
    await refreshAgents();
    await loadTools();
  } catch (err) {
    feed(`Business builder failed: ${err.message}`, "error");
  }
}

async function importCardAgent() {
  const agentId = $("agentId").value.trim();
  if (!agentId) {
    feed("Agent ID is required.", "error");
    return;
  }
  const cardPath = $("cardPath").value.trim();
  if (!cardPath) {
    feed("C2C card path is required.", "error");
    return;
  }
  try {
    const res = await api("/quest/agents/register-card", {
      method: "POST",
      body: JSON.stringify({
        agent_id: agentId,
        card_path: cardPath,
      }),
    });
    setActiveAgent(res.agent_id || agentId);
    feed("C2C import module registered an MPF agent profile.", "ok");
    await refreshAgents();
    await loadTools();
  } catch (err) {
    feed(`C2C import failed: ${err.message}`, "error");
  }
}

async function sendChat() {
  const message = $("chatInput").value.trim();
  if (!message) return;
  if (state.chatRequestPending) {
    feed("Main chat is already running a turn. Give the local model a second.", "info");
    return;
  }
  if (state.pendingChatActionDecisionPending) {
    feed("Approval is still running. Give the engine a second.", "info");
    return;
  }
  if (state.pendingChatActionId) {
    feed("Resolve the pending action card first so the chat stays coherent.", "info");
    return;
  }

  if (state.totalAgentControlEnabled && detectBrowserSurfaceMode() === "browser") {
    ensureBrowserSessionWindow({ eager: true });
  }
  appendMessage("user", message, "chatLog");
  $("chatInput").value = "";
  const startedAt = Date.now();
  const pendingMsg = appendMessage("system", buildPendingChatLabel(startedAt), "chatLog");
  let pendingTimer = null;
  let warnedAboutSlowModel = false;
  setChatBusy(true);
  pendingTimer = window.setInterval(() => {
    setMessageText(pendingMsg, buildPendingChatLabel(startedAt), "system");
    const elapsedSeconds = Math.max(0, Math.round((Date.now() - startedAt) / 1000));
    if (
      !warnedAboutSlowModel &&
      elapsedSeconds >= 12 &&
      String(state.currentOllamaModel || "").trim().toLowerCase() === "gemma3:4b"
    ) {
      warnedAboutSlowModel = true;
      feed("gemma3:4b can drag hard on 6 GB. qwen3:4b is available in Builders if you need a faster local lane.", "info");
    }
  }, 1000);
  try {
    if (!state.activeAgentId) {
      await ensureActiveAgentFromMpf();
    }
    if (!state.switchboard) {
      await loadSwitchboard({ silent: true });
    }
    const desiredLane = getSelectedLane() || state.switchboard?.current?.lane || state.switchboard?.default_lane || "fat_agent";
    const desiredChild = getSelectedChild() || state.switchboard?.current?.child || null;
    const newInstance = wantsNewGeneratedInstance();
    const chatAgentId = state.activeAgentId || JL_FAT_AGENT_ID;
    const browserContext = buildBrowserSessionContext();
    const executionMode = state.totalAgentControlEnabled ? "auto" : "chat";
    const t0 = performance.now();
    const res = await api("/quest/chat", {
      method: "POST",
      body: JSON.stringify({
        agent_id: chatAgentId,
        message,
        lane: desiredLane,
        child: desiredChild,
        new_instance: newInstance,
        context: {
          ui_surface: "chat_tab",
          backend_timeout: 120,
          ...browserContext,
        },
        execution_mode: executionMode,
        return_trace: true,
      }),
      timeout_ms: 130000,
    });
    if (res.status === "error") {
      throw new Error(res.error || res.reply || "Chat failed.");
    }
    const modeUsed = res.mode_used || "chat";
    const reply = res.reply || res.result?.final || res.final || JSON.stringify(res, null, 2);
    const handledBrowserDirective = await maybeApplyAgentBrowserDirective(reply, "chat");
    if (res.status === "confirmation_required") {
      if (pendingMsg) pendingMsg.remove();
      const pending = res.pending_action || null;
      const trace = extractToolTrace(res);
      if (pending) {
        appendActivitySummary(trace, "chatLog", {
          telemetry: res.telemetry_summary,
          tone: "warning",
          pendingSummary: pending?.summary || "",
        });
        if (state.pendingChatActionId !== pending.id) {
          renderPendingActionCard(pending, { priorTraceCount: trace.length });
        }
      } else {
        appendMessage("agent", reply, "chatLog");
      }
      feed(`Awaiting confirmation: ${pending?.summary || "pending action"}`, "info");
      return;
    }
    if (pendingMsg) pendingMsg.remove();
    if (!handledBrowserDirective) {
      if (String(reply || "").trim()) {
        appendMessage("agent", reply, "chatLog");
      } else {
        appendMessage(
          "system",
          "The model returned an empty visible reply. If you're on qwen3:4b, it may be thinking instead of answering directly.",
          "chatLog",
        );
      }
    }
    appendActivitySummary(extractToolTrace(res), "chatLog", {
      telemetry: res.telemetry_summary,
    });
    if (res.agent_id) {
      setActiveAgent(res.agent_id);
    }
    renderSelectionChips(res, {
      delegatedTo: res.delegated_to,
      delegatedClass: res.delegated_class,
      telemetrySummary: res.telemetry_summary,
    });
    if (res.backend_mode) {
      state.runtimeMode = res.backend_mode;
      renderRuntimeModeChip();
    }
    clearNewGeneratedInstanceRequest();
    setLatency(performance.now() - t0);
    feed(
      `Chat complete via ${res.child || desiredChild || res.agent || chatAgentId} (${modeUsed})`,
      "ok",
    );
    await refreshAgents();
    await loadSwitchboard({
      silent: true,
      preferredLane: String(res.lane || desiredLane || ""),
      preferredChild: String(res.child || desiredChild || ""),
    });
    await loadTools();
  } catch (err) {
    if (pendingMsg) {
      setMessageText(
        pendingMsg,
        `Error: ${err.message}`,
        "system",
      );
    } else {
      appendMessage("system", `Error: ${err.message}`, "chatLog");
    }
    feed(`Chat failed: ${err.message}`, "error");
  } finally {
    if (pendingTimer) window.clearInterval(pendingTimer);
    setChatBusy(false);
  }
}

async function runMission() {
  const task = $("missionInput").value.trim();
  if (!task) return;

  appendMessage("user", task, "missionLog");
  $("missionInput").value = "";

  if (!state.activeAgentId) {
    try {
      await ensureActiveAgentFromMpf();
    } catch (err) {
      appendMessage("system", `Bootstrap error: ${err.message}`, "missionLog");
      feed(`MPF-first bootstrap failed: ${err.message}`, "error");
      return;
    }
  }

  const missionAgentId = state.activeAgentId || $("agentId").value.trim() || JL_FAT_AGENT_ID;
  const dynamicPersona = $("dynamicPersonaCheck")?.checked !== false;
  const selectedPersona = $("mpfPersonaSelect")?.value?.trim() || "";
  const personaOverride = dynamicPersona ? null : selectedPersona || getPreferredMpfPersona();

  try {
    const t0 = performance.now();
    const res = await api("/quest/mission", {
      method: "POST",
      body: JSON.stringify({
        agent_id: missionAgentId,
        task,
        dynamic_agent: dynamicPersona,
        agent: personaOverride,
        dynamic_persona: dynamicPersona,
        persona: personaOverride,
      }),
    });
    if (res.agent_id) {
      setActiveAgent(res.agent_id);
    } else {
      setActiveAgent(missionAgentId);
    }
    const final = res.result?.final || JSON.stringify(res.result || res, null, 2);
    appendMessage("agent", final, "missionLog");
    setLatency(performance.now() - t0);
    const selected = res.selected_agent || res.selected_persona || "n/a";
    const reason = res.selection_reason || "none";
    feed(`Mission complete. Agent profile=${selected} (${reason}).`, "ok");
    await refreshAgents();
    await loadTools();
  } catch (err) {
    appendMessage("system", `Error: ${err.message}`, "missionLog");
    feed(`Mission failed: ${err.message}`, "error");
  }
}

async function cloneAgent() {
  if (!state.activeAgentId) return;
  try {
    const res = await api("/quest/clone", {
      method: "POST",
      body: JSON.stringify({ agent_id: state.activeAgentId, reason: "manual_clone_from_ui" }),
    });
    const newId = res.agent_id || "";
    if (newId) {
      setActiveAgent(newId);
      await refreshAgents();
      await loadTools();
      feed(`Agent cloned to ${newId}`, "ok");
    }
  } catch (err) {
    feed(`Clone failed: ${err.message}`, "error");
  }
}

function toolCard(tool) {
  const name = tool.name || "unnamed";
  const stats = tool.stats || {};
  const uses = stats.use_count || 0;
  const promoted = stats.promoted ? " | promoted" : "";
  return `
    <div class="card" data-tool="${name}">
      <div class="title">${name}</div>
      <div class="muted">${tool.description || "no description"} | uses: ${uses}${promoted}</div>
      <div class="row" style="margin-top:8px">
        <button data-act="run">Run</button>
        <button class="ghost" data-act="promote">Promote</button>
        <button class="ghost" data-act="delete">Delete</button>
      </div>
    </div>
  `;
}

async function loadTools() {
  if (!state.activeAgentId) return;
  try {
    const res = await api(`/quest/tools/${encodeURIComponent(state.activeAgentId)}`);
    const tools = Array.isArray(res.tools) ? res.tools : [];
    state.lastToolListAgent = state.activeAgentId;
    const wrap = $("toolList");
    wrap.innerHTML = tools.length ? tools.map(toolCard).join("") : `<div class="card"><div class="muted">No RAM tools yet.</div></div>`;
    for (const card of wrap.querySelectorAll("[data-tool]")) {
      const name = card.getAttribute("data-tool");
      card.querySelector("[data-act='run']").addEventListener("click", () => runTool(name));
      card.querySelector("[data-act='promote']").addEventListener("click", () => promoteTool(name));
      card.querySelector("[data-act='delete']").addEventListener("click", () => deleteTool(name));
    }
  } catch (err) {
    feed(`Load tools failed: ${err.message}`, "error");
  }
}

async function createTool() {
  if (!state.activeAgentId) {
    feed("Set an active agent first.", "error");
    return;
  }
  const name = $("toolName").value.trim();
  const code = $("toolCode").value;
  if (!name || !code.trim()) return;
  try {
    await api("/quest/tools/create", {
      method: "POST",
      body: JSON.stringify({ agent_id: state.activeAgentId, name, code, description: "UI-created tool" }),
    });
    feed(`RAM tool created: ${name}`, "ok");
    await loadTools();
  } catch (err) {
    feed(`Create tool failed: ${err.message}`, "error");
  }
}

async function promoteToolFromNameInput() {
  const name = $("toolName").value.trim();
  if (!name) {
    feed("Enter a tool name to promote.", "error");
    return;
  }
  await promoteTool(name);
}

async function runTool(name) {
  if (!state.activeAgentId) return;
  try {
    const payload = parseJsonSafe($("toolPayload").value || "{}");
    const res = await api("/quest/tools/run", {
      method: "POST",
      body: JSON.stringify({ agent_id: state.activeAgentId, name, payload }),
    });
    appendMessage("system", `[tool:${name}] ${JSON.stringify(res.result || res, null, 2)}`);
    if ((res.lifecycle || {}).deleted_after_use) {
      feed(`Tool ${name} was deleted after use. Promote by name if you want to keep it.`, "info");
    }
    feed(`Tool executed: ${name}`, "ok");
    await loadTools();
  } catch (err) {
    feed(`Run tool failed (${name}): ${err.message}`, "error");
  }
}

async function promoteTool(name) {
  if (!state.activeAgentId) return;
  try {
    await api("/quest/tools/promote", {
      method: "POST",
      body: JSON.stringify({ agent_id: state.activeAgentId, name }),
    });
    feed(`Tool promoted: ${name}`, "ok");
    await loadTools();
  } catch (err) {
    feed(`Promote failed (${name}): ${err.message}`, "error");
  }
}

async function deleteTool(name) {
  if (!state.activeAgentId) return;
  try {
    await api("/quest/tools/delete", {
      method: "POST",
      body: JSON.stringify({ agent_id: state.activeAgentId, name }),
    });
    feed(`Tool deleted: ${name}`, "ok");
    await loadTools();
  } catch (err) {
    feed(`Delete failed (${name}): ${err.message}`, "error");
  }
}

function initBrowserSurface() {
  const initial =
    normalizeBrowserUrl(state.browserCurrentUrl || state.browserHomeUrl) ||
    normalizeBrowserUrl(window.location.href) ||
    "https://example.com";
  state.browserHomeUrl = initial;
  state.browserCurrentUrl = initial;
  renderBrowserSurfaceHint();
  renderBrowserSessionState();
}

async function refreshChatLoopStatus(options = {}) {
  const { silent = false } = options;
  const loopAgentId = state.activeAgentId || JL_FAT_AGENT_ID;
  try {
    const res = await api(`/chat-loop/${encodeURIComponent(loopAgentId)}`);
    const loop = res.loop || {};
    const running = !!loop.running;
    state.chatLoopRunning = running;
    state.chatLoopWaiting = !!loop.waiting_for_confirmation;
    state.chatLoopTurns = Number(loop.turns || 0);
    renderChatLoopChip();

    const latestReply = String(loop.last_reply || "");
    if (latestReply && latestReply !== state.lastLoopReplySeen) {
      state.lastLoopReplySeen = latestReply;
      await maybeApplyAgentBrowserDirective(latestReply, "loop");
    }
    return loop;
  } catch (err) {
    if (!silent) {
      feed(`Chat loop status failed: ${err.message}`, "error");
    }
    state.chatLoopRunning = false;
    state.chatLoopWaiting = false;
    state.chatLoopTurns = 0;
    renderChatLoopChip();
    return null;
  }
}

async function startChatLoop() {
  try {
    if (state.totalAgentControlEnabled && detectBrowserSurfaceMode() === "browser") {
      ensureBrowserSessionWindow({ eager: true });
    }
    if (!state.activeAgentId) {
      await ensureActiveAgentFromMpf();
    }
    if (!state.switchboard) {
      await loadSwitchboard({ silent: true });
    }
    const desiredLane = getSelectedLane() || state.switchboard?.current?.lane || state.switchboard?.default_lane || "fat_agent";
    const desiredChild = getSelectedChild() || state.switchboard?.current?.child || null;
    const currentLane = String(state.switchboard?.current?.lane || "").trim();
    const currentChild = String(state.switchboard?.current?.child || "").trim();
    if (desiredLane !== currentLane || String(desiredChild || "") !== currentChild || wantsNewGeneratedInstance()) {
      await switchActiveLane();
    }
    const chatAgentId = state.activeAgentId || JL_FAT_AGENT_ID;
    const browserContext = buildBrowserSessionContext();
    const seedMessage =
      $("chatInput").value.trim() ||
      "Continue assisting the user using the current session context when helpful.";
    const payload = {
      agent_id: chatAgentId,
      message: seedMessage,
      context: {
        ui_surface: "chat_loop",
        synthetic_turn: true,
        suppress_memory_write: true,
        suppress_feedback_log: true,
        memory_origin: "chat_loop",
        ...browserContext,
      },
      execution_mode: state.totalAgentControlEnabled ? "auto" : "chat",
      interval_seconds: 2.0,
      max_iterations: 0,
      return_trace: false,
      autostart_agent_loop: true,
    };
    const res = await api("/chat-loop/start", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const loop = res.loop || {};
    state.chatLoopRunning = !!loop.running;
    state.chatLoopWaiting = !!loop.waiting_for_confirmation;
    state.chatLoopTurns = Number(loop.turns || 0);
    renderChatLoopChip();
    feed(res.message === "already_running" ? "Chat agent loop already running." : "Chat agent loop started.", "ok");
  } catch (err) {
    feed(`Chat loop start failed: ${err.message}`, "error");
  }
}

async function stopChatLoop() {
  try {
    const chatAgentId = state.activeAgentId || JL_FAT_AGENT_ID;
    const res = await api("/chat-loop/stop", {
      method: "POST",
      body: JSON.stringify({ agent_id: chatAgentId, wait_seconds: 4.0 }),
    });
    const loop = res.loop || {};
    state.chatLoopRunning = !!loop.running;
    state.chatLoopWaiting = !!loop.waiting_for_confirmation;
    state.chatLoopTurns = Number(loop.turns || 0);
    renderChatLoopChip();
    feed("Chat agent loop stop requested.", "ok");
  } catch (err) {
    feed(`Chat loop stop failed: ${err.message}`, "error");
  }
}

async function toggleChatLoop() {
  if (state.chatLoopRunning) {
    await stopChatLoop();
    return;
  }
  await startChatLoop();
}

async function runCcCommand() {
  const command = $("ccCommand").value.trim();
  if (!command) return;
  try {
    const res = await api("/tools/cc-run", {
      method: "POST",
      body: JSON.stringify({ command }),
    });
    const out = (res.stdout || "").trim();
    const err = (res.stderr || "").trim();
    if (out) appendMessage("system", `[cc:stdout]\n${out}`);
    if (err) appendMessage("system", `[cc:stderr]\n${err}`);
    feed(`CC command exit: ${res.returncode}`, res.ok ? "ok" : "error");
  } catch (error) {
    feed(`CC command failed: ${error.message}`, "error");
  }
}

function renderWorkspaceEntries(entries, currentPath, parentPath) {
  const wrap = $("fileList");
  if (!wrap) return;
  wrap.innerHTML = "";

  if (currentPath && currentPath !== ".") {
    const up = document.createElement("button");
    up.className = "file-entry";
    up.textContent = ".. (parent)";
    up.addEventListener("click", () => loadWorkspaceList(parentPath || "."));
    wrap.appendChild(up);
  }

  if (!entries.length) {
    const empty = document.createElement("div");
    empty.className = "card";
    empty.innerHTML = `<div class="muted">No files.</div>`;
    wrap.appendChild(empty);
    return;
  }

  for (const entry of entries) {
    const btn = document.createElement("button");
    btn.className = "file-entry";
    btn.textContent = `${entry.is_dir ? "[DIR]" : "[FILE]"} ${entry.name}`;
    btn.addEventListener("click", () => {
      if (entry.is_dir) {
        loadWorkspaceList(entry.path);
      } else {
        openWorkspaceFile(entry.path);
      }
    });
    wrap.appendChild(btn);
  }
}

async function loadWorkspaceList(path = null) {
  const requested = String(path ?? $("workspacePathInput")?.value ?? state.workspacePath ?? ".").trim() || ".";
  try {
    const res = await api(`/workspace/list?path=${encodeURIComponent(requested)}`);
    state.workspacePath = res.path || ".";
    state.workspaceParentPath = res.parent_path || ".";
    if ($("workspacePathInput")) {
      $("workspacePathInput").value = state.workspacePath;
    }
    const entries = Array.isArray(res.entries) ? res.entries : [];
    renderWorkspaceEntries(entries, state.workspacePath, state.workspaceParentPath);
  } catch (err) {
    feed(`Workspace list failed: ${err.message}`, "error");
  }
}

async function openWorkspaceFile(path) {
  if (!path) return;
  try {
    const res = await api(`/workspace/file?path=${encodeURIComponent(path)}`);
    state.selectedFilePath = res.path || path;
    $("selectedFilePath").textContent = res.path || path;
    $("fileContent").value = res.content || "";
    if (res.truncated) {
      feed(`File preview truncated for ${state.selectedFilePath}.`, "info");
    }
  } catch (err) {
    feed(`Open file failed: ${err.message}`, "error");
  }
}

async function saveWorkspaceFile() {
  const path = state.selectedFilePath;
  if (!path) {
    feed("Select a file first.", "error");
    return;
  }
  try {
    const res = await api("/workspace/file/save", {
      method: "POST",
      body: JSON.stringify({
        path,
        content: $("fileContent").value,
      }),
    });
    feed(`Saved ${res.path}`, "ok");
    await loadWorkspaceList(state.workspacePath);
  } catch (err) {
    feed(`Save failed: ${err.message}`, "error");
  }
}

async function reviewWorkspaceFile() {
  const path = state.selectedFilePath;
  if (!path) {
    feed("Select a file first.", "error");
    return;
  }
  try {
    const res = await api("/workspace/review", {
      method: "POST",
      body: JSON.stringify({
        path,
        focus: $("fileFocusInput").value.trim() || null,
      }),
    });
    $("fileReviewOutput").textContent = res.review || "(No review text returned)";
    if (res.fallback) {
      feed("Review used fallback analyzer.", "info");
    } else {
      feed("Review complete.", "ok");
    }
  } catch (err) {
    feed(`Review failed: ${err.message}`, "error");
  }
}

function formatEpochSeconds(value) {
  const num = Number(value);
  if (!Number.isFinite(num) || num <= 0) return "-";
  const dt = new Date(num * 1000);
  return dt.toLocaleString();
}

function renderSelfEditStatus(status) {
  const running = !!status?.running;
  state.selfEditRunning = running;
  $("selfEditRunningChip").textContent = `Loop: ${running ? "RUNNING" : "STOPPED"}`;
  $("selfEditPidChip").textContent = `PID: ${status?.pid ?? "-"}`;
  $("selfEditStartedChip").textContent = `Started: ${formatEpochSeconds(status?.started_at)}`;

  const cfg = status?.config || {};
  const meta = [
    `lab_dir: ${status?.lab_dir || cfg.lab_dir || "-"}`,
    `script_exists: ${status?.script_exists ? "yes" : "no"}`,
    `shuttle_present: ${status?.shuttle_present ? "yes" : "no"}`,
    `interval_seconds: ${cfg.interval_seconds ?? "-"}`,
    `max_iterations: ${cfg.max_iterations ?? "-"}`,
    `reseed_copy: ${cfg.reseed_copy ? "true" : "false"}`,
    `returncode: ${status?.returncode ?? "-"}`,
  ].join("\n");
  $("selfEditMeta").textContent = meta;
  $("selfEditLog").textContent = status?.log_tail || "(no loop log yet)";
}

async function refreshSelfEditStatus(options = {}) {
  const { silent = false, logLines = 120 } = options;
  try {
    const res = await api(`/self-edit/status?log_lines=${encodeURIComponent(String(logLines))}`);
    renderSelfEditStatus(res);
    return res;
  } catch (err) {
    if (!silent) {
      feed(`Self-edit status failed: ${err.message}`, "error");
    }
    return null;
  }
}

async function startSelfEditLoop() {
  try {
    const payload = {
      lab_dir: $("selfEditLabDirInput").value.trim() || ".self_edit_lab",
      interval_seconds: Number($("selfEditIntervalInput").value || 1.5),
      max_iterations: Number($("selfEditMaxIterationsInput").value || 0),
      reseed_copy: $("selfEditReseedCheck").checked,
    };
    const res = await api("/self-edit/start", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderSelfEditStatus(res);
    feed(res.message === "already_running" ? "Self-edit loop already running." : "Self-edit loop started.", "ok");
  } catch (err) {
    feed(`Self-edit start failed: ${err.message}`, "error");
  }
}

async function stopSelfEditLoop() {
  try {
    const payload = {
      lab_dir: $("selfEditLabDirInput").value.trim() || ".self_edit_lab",
      wait_seconds: 6.0,
      force: $("selfEditForceStopCheck").checked,
      log_lines: 200,
    };
    const res = await api("/self-edit/stop", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderSelfEditStatus(res);
    feed("Self-edit stop requested.", "ok");
  } catch (err) {
    feed(`Self-edit stop failed: ${err.message}`, "error");
  }
}

async function clearSelfEditShuttle() {
  try {
    const payload = {
      lab_dir: $("selfEditLabDirInput").value.trim() || ".self_edit_lab",
    };
    const res = await api("/self-edit/shuttle/clear", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderSelfEditStatus(res);
    feed("SHUTTLE cleared.", "ok");
  } catch (err) {
    feed(`Clear SHUTTLE failed: ${err.message}`, "error");
  }
}

function wireTabs() {
  const layout = $("layoutRoot");
  const chatBtn = $("chatTabBtn");
  const buildersBtn = $("buildersTabBtn");
  const filesBtn = $("filesTabBtn");
  const selfEditBtn = $("selfEditTabBtn");
  const chatPanels = Array.from(document.querySelectorAll(".chat-only"));
  const builderPanels = Array.from(document.querySelectorAll(".builders-only"));
  const filePanels = Array.from(document.querySelectorAll(".files-only"));
  const selfEditPanels = Array.from(document.querySelectorAll(".selfedit-only"));
  if (!layout || !chatBtn || !buildersBtn || !filesBtn || !selfEditBtn) return;

  const apply = (tab) => {
    state.activeTab = tab;
    const isChat = tab === "chat";
    const isBuilders = tab === "builders";
    const isFiles = tab === "files";
    const isSelfEdit = tab === "selfedit";
    layout.classList.toggle("chat-mode", isChat);
    layout.classList.toggle("builders-mode", isBuilders);
    layout.classList.toggle("files-mode", isFiles);
    layout.classList.toggle("selfedit-mode", isSelfEdit);
    for (const panel of chatPanels) {
      panel.classList.toggle("hidden", !isChat);
    }
    for (const panel of builderPanels) {
      panel.classList.toggle("hidden", !isBuilders);
    }
    for (const panel of filePanels) {
      panel.classList.toggle("hidden", !isFiles);
    }
    for (const panel of selfEditPanels) {
      panel.classList.toggle("hidden", !isSelfEdit);
    }
    chatBtn.classList.toggle("active", isChat);
    chatBtn.classList.toggle("ghost", !isChat);
    buildersBtn.classList.toggle("active", isBuilders);
    buildersBtn.classList.toggle("ghost", !isBuilders);
    filesBtn.classList.toggle("active", isFiles);
    filesBtn.classList.toggle("ghost", !isFiles);
    selfEditBtn.classList.toggle("active", isSelfEdit);
    selfEditBtn.classList.toggle("ghost", !isSelfEdit);
  };

  chatBtn.addEventListener("click", () => apply("chat"));
  buildersBtn.addEventListener("click", () => apply("builders"));
  filesBtn.addEventListener("click", () => {
    apply("files");
    if (!state.workspacePath) {
      loadWorkspaceList(".");
    }
  });
  selfEditBtn.addEventListener("click", () => {
    apply("selfedit");
    refreshSelfEditStatus({ logLines: 200, silent: true });
  });
  apply("chat");
}

function wireEvents() {
  wireTabs();
  bindEvent("laneSelect", "change", () => {
    renderSwitchboardChildren();
  });
  bindEvent("childSelect", "change", () => {
    renderSwitchboardChildren(getSelectedChild());
  });
  bindEvent("switchAgentBtn", "click", switchActiveLane);
  bindEvent("refreshSwitchboardBtn", "click", () => loadSwitchboard());
  bindEvent("activateMpfAgentBtn", "click", activateMpfAgent);
  bindEvent("activateChatPersonaBtn", "click", activateChatPersona);
  bindEvent("chatSparkByteBtn", "click", () => activatePresetPersona("sparkbyte"));
  bindEvent("chatGremlenBtn", "click", () => activatePresetPersona("gremlen"));
  bindEvent("chatSlappyBtn", "click", () => activatePresetPersona("slappy"));
  bindEvent("presetSparkByteBtn", "click", () => activatePresetPersona("sparkbyte"));
  bindEvent("presetGremlenBtn", "click", () => activatePresetPersona("gremlen"));
  bindEvent("presetSlappyBtn", "click", () => activatePresetPersona("slappy"));
  bindEvent("buildBusinessAgentBtn", "click", buildBusinessAgent);
  bindEvent("importCardAgentBtn", "click", importCardAgent);
  bindEvent("refreshAgentsBtn", "click", refreshAgents);
  bindEvent("refreshMpfPersonasBtn", "click", loadMpfPersonas);
  bindEvent("refreshModelsBtn", "click", () => refreshOllamaModels());
  bindEvent("applyModelBtn", "click", applySelectedOllamaModel);
  bindEvent("chatPersonaSelect", "change", () => {
    const selected = $("chatPersonaSelect")?.value?.trim() || "";
    syncPersonaSelectors(selected);
  });
  bindEvent("mpfPersonaSelect", "change", () => {
    const selected = $("mpfPersonaSelect")?.value?.trim() || "";
    syncPersonaSelectors(selected);
  });
  bindEvent("sendChatBtn", "click", sendChat);
  bindEvent("browserSessionBtn", "click", () => {
    state.browserSurfaceMode = detectBrowserSurfaceMode();
    renderBrowserSurfaceHint();
    if (state.browserSurfaceMode === "standalone") {
      const ok = openBrowserSurfaceUrl(state.browserCurrentUrl || state.browserHomeUrl, "user");
      if (ok) {
        feed("Standalone host/sidebar browser pinged.", "ok");
      }
      return;
    }
    const win = ensureBrowserSessionWindow({ eager: true });
    if (win) {
      win.focus();
      feed("Browser session window ready.", "ok");
    } else {
      feed("Browser session window was blocked by the browser.", "error");
    }
  });
  bindEvent("toggleAgentControlBtn", "click", toggleTotalAgentControl);
  bindEvent("toggleChatLoopBtn", "click", toggleChatLoop);
  bindEvent("chatInput", "keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendChat();
    }
  });
  bindEvent("runMissionBtn", "click", runMission);
  bindEvent("cloneBtn", "click", cloneAgent);
  bindEvent("createToolBtn", "click", createTool);
  bindEvent("promoteToolNameBtn", "click", promoteToolFromNameInput);
  bindEvent("refreshToolsBtn", "click", loadTools);
  bindEvent("runCcBtn", "click", runCcCommand);
  bindEvent("workspaceRefreshBtn", "click", () => loadWorkspaceList());
  bindEvent("workspaceUpBtn", "click", () => loadWorkspaceList(state.workspaceParentPath || "."));
  bindEvent("workspacePathInput", "keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      loadWorkspaceList();
    }
  });
  bindEvent("saveFileBtn", "click", saveWorkspaceFile);
  bindEvent("reviewFileBtn", "click", reviewWorkspaceFile);
  bindEvent("selfEditStartBtn", "click", startSelfEditLoop);
  bindEvent("selfEditStopBtn", "click", stopSelfEditLoop);
  bindEvent("selfEditRefreshBtn", "click", () => refreshSelfEditStatus({ logLines: 200 }));
  bindEvent("selfEditClearShuttleBtn", "click", clearSelfEditShuttle);
  bindEvent("clearFeedBtn", "click", () => {
    if ($("opsFeed")) $("opsFeed").textContent = "";
  });
}

function wireInstallPrompt() {
  const installBtn = $("installAppBtn");
  if (!installBtn) return;

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    state.deferredInstallPrompt = event;
    installBtn.classList.remove("hidden");
    feed("Install option is available.", "ok");
  });

  window.addEventListener("appinstalled", () => {
    installBtn.classList.add("hidden");
    state.deferredInstallPrompt = null;
    feed("JL Deck installed as a desktop app.", "ok");
  });

  installBtn.addEventListener("click", async () => {
    const promptEvent = state.deferredInstallPrompt;
    if (!promptEvent) {
      feed("Install is not currently available in this browser session.");
      return;
    }
    promptEvent.prompt();
    const choice = await promptEvent.userChoice;
    state.deferredInstallPrompt = null;
    installBtn.classList.add("hidden");
    const tone = choice?.outcome === "accepted" ? "ok" : "info";
    feed(`Install prompt: ${choice?.outcome || "dismissed"}.`, tone);
  });
}

async function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  try {
    const registration = await navigator.serviceWorker.register("/ui/sw.js", { scope: "/ui/" });
    if (registration?.active) {
      feed("Offline shell ready.", "ok");
    } else {
      feed("Service worker registered. Activating...");
    }
  } catch (err) {
    feed(`Service worker registration failed: ${err.message}`, "error");
  }
}

async function boot() {
  initBrowserSurface();
  wireEvents();
  wireBrowserBridgeEvents();
  wireInstallPrompt();
  await registerServiceWorker();
  $("stripSafety").textContent = "Core: ONLINE";
  $("stripTools").textContent = "Tools: ON";
  await refreshTopline();
  await refreshRuntimeMode({ silent: true });
  await refreshOllamaModels({ silent: true });
  const loadedPersonas = await loadMpfPersonas({ silent: true });
  if (!loadedPersonas) {
    feed("MPF agent profiles are not ready yet. Retrying in background...", "info");
  }
  await refreshAgents();
  await loadSwitchboard({
    silent: true,
    preferredLane: PRIMARY_PRODUCT_SELECTION.lane,
    preferredChild: PRIMARY_PRODUCT_SELECTION.child,
  });
  applyPrimaryProductSelection();
  try {
    await ensureActiveAgentFromMpf({ forcePrimary: true });
  } catch (err) {
    feed(`Initial MPF bootstrap failed: ${err.message}`, "error");
  }
  if (state.activeAgentId) {
    await loadTools();
  }
  await loadWorkspaceList(".");
  await refreshSelfEditStatus({ logLines: 120, silent: true });
  renderAgentControlButton();
  renderChatLoopChip();
  await refreshChatLoopStatus({ silent: true });
  window.setInterval(() => {
    if (!state.mpfPersonas.length) {
      loadMpfPersonas({ silent: true });
    }
    refreshRuntimeMode({ silent: true });
    if (state.activeTab === "selfedit" || state.selfEditRunning) {
      refreshSelfEditStatus({ logLines: 120, silent: true });
    }
    if (state.activeTab === "chat" || state.chatLoopRunning) {
      refreshChatLoopStatus({ silent: true });
    }
  }, 3000);
  feed(voiceSkinCopy(currentChatAgentLabel()).boot, "ok");
}

boot().catch((err) => feed(`Boot error: ${err.message}`, "error"));

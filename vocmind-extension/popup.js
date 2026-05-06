const $ = (id) => document.getElementById(id);

const els = {
  orbBtn: $("orbBtn"),
  stopBtn: $("stopBtn"),
  micSelect: $("micSelect"),
  captureMode: $("captureMode"),

  protocolView: $("protocolView"),
  transcriptView: $("transcriptView"),
  liveView: $("liveView"),
  sessionLine: $("sessionLine"),
  accountView: $("accountView"),

  statusPill: $("statusPill"),
  statusText: $("statusText"),
  voiceTitle: $("voiceTitle"),
  voiceSub: $("voiceSub"),

  copyBtn: $("copyBtn"),
  clearBtn: $("clearBtn"),

  gainSlider: $("gainSlider"),
  gainVal: $("gainVal"),
  audioTestBtn: $("audioTestBtn"),
  audioTestStopBtn: $("audioTestStopBtn"),
  audioTestState: $("audioTestState"),
  audioTestHint: $("audioTestHint"),
  audioMeterFill: $("audioMeterFill"),

  linkCode: $("linkCode"),
  connectBtn: $("connectBtn"),
  permissionsBtn: $("permissionsBtn"),
  copyLinkCodeBtn: $("copyLinkCodeBtn"),

  recordModeBadge: $("recordModeBadge"),
  recordStatusCard: $("recordStatusCard"),
  recordMicCard: $("recordMicCard"),
  recordBackendCard: $("recordBackendCard"),
  accountBadge: $("accountBadge"),
  accountStateBadge: $("accountStateBadge"),
  settingsSavedBadge: $("settingsSavedBadge"),

  historyList: $("historyList"),
  historySummary: $("historySummary"),
  clearHistoryBtn: $("clearHistoryBtn"),
  refreshHistoryBtn: $("refreshHistoryBtn"),
  historySearchInput: $("historySearchInput"),
  historySearchBtn: $("historySearchBtn"),
};

let activeTab = "protocol";
let activeSection = "recording";
let isRecording = false;
let isStopping = false;
let pendingHistoryId = null;
let pendingHistoryStartedAt = null;
let audioTestCtx = null;
let audioTestStream = null;
let audioTestSource = null;
let audioTestGainNode = null;
let audioTestAnalyser = null;
let audioTestSplitter = null;
let audioTestMerger = null;
let audioTestRAF = 0;
let historyFeatures = {};
let lastHistoryQuery = "";
let runtimePollTimer = 0;
const BACKEND_URL = "http://localhost:8000";

function humanError(x) {
  if (!x) return "";
  if (typeof x === "string") return x;
  if (x instanceof Error) return x.message || String(x);
  try {
    return JSON.stringify(x, null, 2);
  } catch {
    return String(x);
  }
}

function storageGet(keys) {
  return new Promise((resolve) => {
    try {
      chrome.storage.local.get(keys, (res) => {
        const err = chrome.runtime.lastError;
        if (err) return resolve({});
        resolve(res || {});
      });
    } catch {
      resolve({});
    }
  });
}

function storageSet(obj) {
  return new Promise((resolve) => {
    try {
      chrome.storage.local.set(obj, () => resolve());
    } catch {
      resolve();
    }
  });
}

function sendMessage(msg) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(msg, (resp) => {
      const err = chrome.runtime.lastError;
      if (err) return resolve({ ok: false, error: err.message });
      resolve(resp ?? { ok: true });
    });
  });
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("ru-RU");
}

function formatHistoryStamp(iso) {
  if (!iso) return "Запись";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "Запись";
  const date = d.toLocaleDateString("ru-RU");
  const time = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  return `Запись от ${date} в ${time}`;
}

function formatPlanStorage(v) {
  return v == null ? "∞" : String(v);
}

function flashSettingsSaved(text = "Сохранено") {
  if (!els.settingsSavedBadge) return;
  els.settingsSavedBadge.textContent = text;
  clearTimeout(flashSettingsSaved._timer);
  flashSettingsSaved._timer = setTimeout(() => {
    if (els.settingsSavedBadge) els.settingsSavedBadge.textContent = "Авто";
  }, 900);
}

function getPlanFeatures() {
  return historyFeatures || {};
}

function isFeatureEnabled(code) {
  const features = getPlanFeatures();
  return !!features?.[code]?.is_enabled;
}

async function getStoredConnection() {
  const saved = await storageGet([
    "deviceToken",
    "linkedPlan",
    "linkedUsage",
    "linkedSubscription",
    "linkedUserId"
  ]);

  return {
    backendUrl: BACKEND_URL,
    deviceToken: saved.deviceToken || "",
    linkedPlan: saved.linkedPlan || null,
    linkedUsage: saved.linkedUsage || null,
    linkedSubscription: saved.linkedSubscription || null,
    linkedUserId: saved.linkedUserId || "",
  };
}

async function fetchExtensionJson(path, options = {}) {
  const conn = await getStoredConnection();
  if (!conn.backendUrl || !conn.deviceToken) {
    throw new Error("Расширение не подключено");
  }

  const resp = await fetch(
    `${conn.backendUrl}${path}${path.includes("?") ? "&" : "?"}device_token=${encodeURIComponent(conn.deviceToken)}`,
    options
  );

  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data?.detail || `HTTP ${resp.status}`);
  return data;
}

async function syncAccountFromServer() {
  const data = await fetchExtensionJson("/extension/device-dashboard");
  const info = {
    deviceToken: data.device_token || "",
    linkedPlan: data.plan || null,
    linkedSubscription: data.subscription || null,
    linkedUsage: data.usage || null,
  };
  await storageSet(info);
  historyFeatures = data.plan?.features || historyFeatures || {};
  renderAccountInfo(info);
  return info;
}

async function syncHistoryFromServer(query = "") {
  let path = "/extension/meetings";
  const q = String(query || "").trim();
  if (q) path += `?q=${encodeURIComponent(q)}`;

  const data = await fetchExtensionJson(path);
  historyFeatures = data.features || historyFeatures || {};

  const items = Array.isArray(data.items)
    ? data.items.map((item) => ({
        id: item.id,
        title: item.title,
        startedAt: item.started_at,
        endedAt: item.finished_at,
        durationSec: item.duration_seconds,
        status: item.status,
        mode: item.capture_mode,
        protocol: item.protocol_text,
        exports: item.exports || {},
      }))
    : [];

  await setCallHistory(items);
  renderHistory(items);
  return items;
}

function refreshFeatureAvailability() {
  const searchEnabled = isFeatureEnabled("meeting_search");

  if (els.historySearchInput) {
    els.historySearchInput.disabled = !searchEnabled;
    if (!searchEnabled) {
      els.historySearchInput.value = "";
      els.historySearchInput.placeholder = "Поиск доступен с тарифа Профессиональный";
    } else {
      els.historySearchInput.placeholder = "Название, тема, фрагмент текста";
    }
  }

  if (els.historySearchBtn) {
    els.historySearchBtn.disabled = !searchEnabled;
  }

  if (!isFeatureEnabled("live_hints") && els.liveView && !isRecording) {
    els.liveView.textContent = "Live-подсказки доступны с тарифа «Профессиональный».";
  }
}

function formatDuration(seconds) {
  const s = Math.max(0, Math.floor(Number(seconds) || 0));
  const mm = Math.floor(s / 60);
  const ss = s % 60;
  return `${mm}:${String(ss).padStart(2, "0")}`;
}

function shortBackend(url) {
  const clean = String(url || "").trim();
  if (!clean) return "Не указан";
  try {
    const u = new URL(clean);
    return u.host;
  } catch {
    return clean.replace(/^https?:\/\//, "");
  }
}

function selectedMicLabel() {
  const opt = els.micSelect?.selectedOptions?.[0];
  return (opt?.textContent || "—").trim();
}

function updateRecordingMeta() {
  if (els.recordModeBadge) {
    els.recordModeBadge.textContent =
      els.captureMode?.value === "tab_mic" ? "вкладка + мик" : "микрофон";
  }
  if (els.recordMicCard) {
    els.recordMicCard.textContent = selectedMicLabel();
  }
  if (els.recordBackendCard) {
    els.recordBackendCard.textContent = shortBackend(BACKEND_URL);
  }
}

function setStatus(state, text) {
  if (els.statusPill) els.statusPill.dataset.state = state;
  if (els.statusText) els.statusText.textContent = text;

  if (els.recordStatusCard) {
    if (state === "recording") els.recordStatusCard.textContent = "Запись";
    else if (state === "processing") els.recordStatusCard.textContent = "Обработка";
    else if (state === "error") els.recordStatusCard.textContent = "Ошибка";
    else els.recordStatusCard.textContent = text || "Ожидание";
  }
}

function setRecordingUI(on) {
  document.body.dataset.rec = on ? "on" : "off";
  isRecording = on;

  if (els.orbBtn) {
    els.orbBtn.setAttribute("aria-label", on ? "Остановить запись" : "Начать запись");
    els.orbBtn.dataset.mode = on ? "stop" : "start";
  }

  if (els.stopBtn) {
    els.stopBtn.disabled = !on;
    els.stopBtn.style.opacity = on ? "1" : "0.6";
    els.stopBtn.textContent = "Стоп";
  }

  if (on) {
    setStatus("recording", "Запись");
    if (els.voiceTitle) els.voiceTitle.textContent = "Слушаю…";
    if (els.voiceSub) els.voiceSub.textContent = "Нажми на круг или «Стоп», чтобы завершить";
    if (els.sessionLine) els.sessionLine.textContent = "Идёт запись…";
  } else {
    setSparklineLevel(0);
    if (els.sessionLine) els.sessionLine.textContent = "Готово";
  }
}

function renderAccountInfo(info) {
  if (!info || !info.deviceToken) {
    if (els.accountView) {
      els.accountView.className = "account-shell account-shell--empty";
      els.accountView.innerHTML = `
        <div class="account-empty">
          <div class="account-empty__title">Расширение ещё не подключено</div>
          <div class="account-empty__sub">Вставь код подключения и нажми «Подключить расширение», чтобы подтянуть тариф, подписку и лимиты аккаунта.</div>
        </div>
      `;
    }

    if (els.accountBadge) {
      els.accountBadge.textContent = "Не подключено";
      els.accountBadge.className = "mini-badge";
    }

    if (els.accountStateBadge) {
      els.accountStateBadge.textContent = "Нет данных";
      els.accountStateBadge.className = "mini-badge mini-badge--soft";
    }
    refreshFeatureAvailability();
    return;
  }

  const plan = info.linkedPlan || null;
  historyFeatures = plan?.features || historyFeatures || {};
  const subscription = info.linkedSubscription || null;
  const usage = info.linkedUsage || null;
  const planTitle = plan?.title || plan?.code || "нет активного тарифа";
  const planCode = plan?.code || "—";
  const subscriptionStatus = subscription?.status || "—";
  const startsAt = formatDateTime(subscription?.starts_at);
  const endsAt = formatDateTime(subscription?.ends_at);
  const minutesMonthly = plan?.monthly_minutes ?? "—";
  const usedMinutes = usage?.used_minutes ?? "—";
  const remainingMinutes = usage?.remaining_minutes ?? "—";
  const meetingsCount = usage?.meetings_count ?? "—";
  const storageLimit = formatPlanStorage(plan?.meeting_storage_limit);

  if (els.accountView) {
    els.accountView.className = "account-shell";
    els.accountView.innerHTML = `
      <div class="account-overview">
        <div class="account-overview__left">
          <div class="account-check">✓</div>
          <div>
            <div class="account-overview__title">Расширение подключено</div>
            <div class="account-overview__sub">Аккаунт синхронизирован с mini app. Ниже — актуальные лимиты и статус подписки.</div>
          </div>
        </div>
        <div class="account-status-badge account-status-badge--ok">${escapeHtml(subscriptionStatus)}</div>
      </div>

      <div class="account-grid">
        <div class="account-stat">
          <div class="account-stat__label">Тариф</div>
          <div class="account-stat__value">${escapeHtml(planTitle)}</div>
          <div class="account-stat__sub">Код: ${escapeHtml(planCode)}</div>
        </div>

        <div class="account-stat">
          <div class="account-stat__label">Остаток минут</div>
          <div class="account-stat__value">${escapeHtml(String(remainingMinutes))}</div>
          <div class="account-stat__sub">Использовано: ${escapeHtml(String(usedMinutes))}</div>
        </div>

        <div class="account-stat">
          <div class="account-stat__label">Подписка</div>
          <div class="account-stat__value">${escapeHtml(subscriptionStatus)}</div>
          <div class="account-stat__sub">До: ${escapeHtml(endsAt)}</div>
        </div>

        <div class="account-stat">
          <div class="account-stat__label">Встречи</div>
          <div class="account-stat__value">${escapeHtml(String(meetingsCount))}</div>
          <div class="account-stat__sub">Минут в месяц: ${escapeHtml(String(minutesMonthly))}</div>
        </div>
      </div>

      <div class="account-details">
        <div class="account-details__title">Детали аккаунта</div>
        <div class="account-rows">
          <div class="account-row">
            <div class="account-row__label">Старт</div>
            <div class="account-row__value">${escapeHtml(startsAt)}</div>
          </div>
          <div class="account-row">
            <div class="account-row__label">До</div>
            <div class="account-row__value">${escapeHtml(endsAt)}</div>
          </div>
          <div class="account-row">
            <div class="account-row__label">Хранение</div>
            <div class="account-row__value">${escapeHtml(storageLimit)}</div>
          </div>
        </div>
      </div>
    `;
  }

  if (els.accountBadge) {
    els.accountBadge.textContent = "Подключено";
    els.accountBadge.className = "mini-badge mini-badge--soft";
  }

  if (els.accountStateBadge) {
    els.accountStateBadge.textContent = "Синхронизировано";
    els.accountStateBadge.className = "mini-badge mini-badge--soft";
  }

  refreshFeatureAvailability();
}

function setAudioTestUI(on, text = "") {
  const card = document.querySelector(".audio-test-card");
  if (card) card.dataset.testing = on ? "on" : "off";

  if (els.audioTestBtn) els.audioTestBtn.disabled = on;
  if (els.audioTestStopBtn) els.audioTestStopBtn.disabled = !on;

  if (els.audioTestState) {
    els.audioTestState.textContent = on ? "Идёт тест" : "Выключено";
    els.audioTestState.className = "mini-badge mini-badge--soft";
  }

  if (els.audioTestHint) {
    els.audioTestHint.textContent =
      text ||
      (on
        ? "Прослушка активна. Говори в микрофон и слушай сигнал с текущим усилением."
        : "Прослушка выключена. В тесте используется выбранный микрофон и текущее усиление.");
  }

  if (!on && els.audioMeterFill) {
    els.audioMeterFill.style.width = "0%";
  }
}

function stopAudioTestMeter() {
  if (audioTestRAF) {
    cancelAnimationFrame(audioTestRAF);
    audioTestRAF = 0;
  }
}

function startAudioTestMeter() {
  if (!audioTestAnalyser || !els.audioMeterFill) return;
  const data = new Uint8Array(audioTestAnalyser.fftSize);

  const tick = () => {
    if (!audioTestAnalyser || !els.audioMeterFill) return;
    audioTestAnalyser.getByteTimeDomainData(data);

    let sum = 0;
    for (let i = 0; i < data.length; i++) {
      const x = (data[i] - 128) / 128;
      sum += x * x;
    }

    const rms = Math.sqrt(sum / data.length);
    const pct = Math.max(2, Math.min(100, Math.round(rms * 260)));
    els.audioMeterFill.style.width = `${pct}%`;
    audioTestRAF = requestAnimationFrame(tick);
  };

  tick();
}

async function stopAudioTest() {
  stopAudioTestMeter();

  try { audioTestSource?.disconnect(); } catch {}
  try { audioTestGainNode?.disconnect(); } catch {}
  try { audioTestAnalyser?.disconnect(); } catch {}
  try { audioTestSplitter?.disconnect(); } catch {}
  try { audioTestMerger?.disconnect(); } catch {}

  if (audioTestStream) {
    audioTestStream.getTracks().forEach((track) => {
      try { track.stop(); } catch {}
    });
  }

  if (audioTestCtx) {
    try { await audioTestCtx.close(); } catch {}
  }

  audioTestCtx = null;
  audioTestStream = null;
  audioTestSource = null;
  audioTestGainNode = null;
  audioTestAnalyser = null;
  audioTestSplitter = null;
  audioTestMerger = null;

  setAudioTestUI(false);
}

async function startAudioTest() {
  await stopAudioTest();

  const selectedId = els.micSelect?.value || "default";
  const constraints = {
    audio: {
      deviceId: selectedId && selectedId !== "default" ? { exact: selectedId } : undefined,
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
      channelCount: { ideal: 1 },
    }
  };

  try {
    audioTestStream = await navigator.mediaDevices.getUserMedia(constraints);
    audioTestCtx = new (window.AudioContext || window.webkitAudioContext)();
    audioTestSource = audioTestCtx.createMediaStreamSource(audioTestStream);
    audioTestGainNode = audioTestCtx.createGain();
    audioTestAnalyser = audioTestCtx.createAnalyser();
    audioTestSplitter = audioTestCtx.createChannelSplitter(2);
    audioTestMerger = audioTestCtx.createChannelMerger(2);

    audioTestAnalyser.fftSize = 1024;
    audioTestGainNode.gain.value = Number(els.gainSlider?.value || 1.8);

    audioTestSource.connect(audioTestAnalyser);
    audioTestSource.connect(audioTestGainNode);
    audioTestGainNode.connect(audioTestSplitter);
    audioTestSplitter.connect(audioTestMerger, 0, 0);
    audioTestSplitter.connect(audioTestMerger, 0, 1);
    audioTestMerger.connect(audioTestCtx.destination);

    setAudioTestUI(true, "Прослушка активна. Сигнал сводится в центр и звучит в обоих каналах.");
    startAudioTestMeter();

    const [track] = audioTestStream.getAudioTracks();
    if (track) {
      track.onended = () => {
        stopAudioTest().catch(() => {});
      };
    }
  } catch (e) {
    console.error("audio test failed", e);
    setAudioTestUI(false, `Не удалось запустить тест: ${humanError(e)}`);
  }
}

let levelSmooth = 0;
function setSparklineLevel(v) {
  const bars = document.querySelectorAll(".sparkline span");
  levelSmooth = levelSmooth * 0.8 + v * 0.2;

  for (let i = 0; i < bars.length; i++) {
    const k = 0.6 + (i % 5) * 0.12;
    const h = Math.max(0.25, Math.min(2.2, 0.25 + levelSmooth * 2.0 * k));
    bars[i].style.transform = `scaleY(${h})`;
    bars[i].style.opacity = String(Math.min(1, 0.35 + levelSmooth * 0.9));
  }
}

function switchTab(tab) {
  activeTab = tab;
  document.querySelectorAll(".tab").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === tab);
  });
  els.protocolView?.classList.toggle("active", tab === "protocol");
  els.transcriptView?.classList.toggle("active", tab === "transcript");
  els.liveView?.classList.toggle("active", tab === "live");
}

function switchSection(section) {
  if (activeSection === "settings" && section !== "settings") {
    stopAudioTest().catch(() => {});
  }

  activeSection = section;
  document.querySelectorAll(".section-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.section === section);
  });
  document.querySelectorAll(".section-page").forEach((p) => {
    p.classList.toggle("active", p.id === `section-${section}`);
  });
}

async function loadMics() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((t) => t.stop());
  } catch (e) {
    console.warn("Нет доступа к микрофону, открываем страницу разрешений", e);
    chrome.tabs.create({ url: chrome.runtime.getURL("permissions.html") });
    return;
  }

  const devices = await navigator.mediaDevices.enumerateDevices();
  const mics = devices.filter((d) => d.kind === "audioinput");
  if (els.micSelect) els.micSelect.innerHTML = "";

  for (const m of mics) {
    const opt = document.createElement("option");
    opt.value = m.deviceId || "default";
    opt.textContent = m.label || `Микрофон (${(m.deviceId || "default").slice(0, 6)})`;
    els.micSelect?.appendChild(opt);
  }

  if (!mics.length && els.micSelect) {
    const opt = document.createElement("option");
    opt.value = "default";
    opt.textContent = "Микрофон (не найден)";
    els.micSelect.appendChild(opt);
  }

  updateRecordingMeta();
}

async function getCallHistory() {
  const saved = await storageGet(["CALL_HISTORY"]);
  return Array.isArray(saved.CALL_HISTORY) ? saved.CALL_HISTORY : [];
}

async function setCallHistory(history) {
  await storageSet({ CALL_HISTORY: history.slice(0, 50) });
}

async function updateHistoryItem(id, patch) {
  if (!id) return;
  const history = await getCallHistory();
  const updated = history.map((item) => item.id === id ? { ...item, ...patch } : item);
  await setCallHistory(updated);
  renderHistory(updated);
}

async function prependHistoryItem(item) {
  const history = await getCallHistory();
  history.unshift(item);
  await setCallHistory(history);
  renderHistory(history);
}

function excerpt(text, fallback = "—") {
  const clean = String(text || "").trim();
  if (!clean) return fallback;
  return clean.length > 240 ? `${clean.slice(0, 240)}…` : clean;
}

function renderHistory(history) {
  const list = Array.isArray(history) ? history : [];
  if (els.historySummary) {
    els.historySummary.textContent = `${list.length} ${list.length === 1 ? "звонок" : list.length < 5 ? "звонка" : "звонков"}`;
  }

  if (!els.historyList) return;

  if (!list.length) {
    els.historyList.innerHTML = `<div class="history-empty">История пока пустая. После первой записи звонок появится здесь.</div>`;
    refreshFeatureAvailability();
    return;
  }

  els.historyList.innerHTML = list.map((item) => {
    const durationText = item.durationSec != null ? formatDuration(item.durationSec) : "—";
    const exportButtons = [
      item.exports?.pdf ? `<button class="history-action" data-export-history="${escapeHtml(item.id)}:pdf" type="button">PDF</button>` : "",
      item.exports?.docx ? `<button class="history-action" data-export-history="${escapeHtml(item.id)}:docx" type="button">DOCX</button>` : "",
    ].join("");

    return `
      <details class="history-entry">
        <summary class="history-entry__summary">
          <div>
            <div class="history-entry__title">${escapeHtml(formatHistoryStamp(item.startedAt))}</div>
            <div class="history-entry__meta">${escapeHtml(durationText)} · ${escapeHtml(item.mode === "tab_mic" ? "вкладка + мик" : "микрофон")} · ${escapeHtml(item.status === "done" ? "готово" : item.status === "processing" ? "обработка" : item.status === "recording" ? "запись" : item.status || "—")}</div>
          </div>
          <span class="history-entry__chevron" aria-hidden="true">⌄</span>
        </summary>
        <div class="history-entry__body">
          <div class="history-entry__block">
            <div class="history-entry__label">${escapeHtml(item.title || "Встреча")}</div>
            <div class="history-entry__text">${escapeHtml(excerpt(item.protocol, item.status === "processing" ? "Ещё формируется…" : "Пусто"))}</div>
          </div>
          <div class="history-item__actions history-entry__actions">
            <button class="history-action" data-copy-history="${escapeHtml(item.id)}" type="button">Копировать протокол</button>
            ${exportButtons}
            <button class="history-action" data-delete-history="${escapeHtml(item.id)}" type="button">Удалить</button>
          </div>
        </div>
      </details>
    `;
  }).join("");

  refreshFeatureAvailability();
}

async function createHistoryEntry() {
  const now = new Date();
  const id = `call_${Date.now()}`;
  pendingHistoryId = id;
  pendingHistoryStartedAt = now.toISOString();

  const item = {
    id,
    title: "Новый звонок",
    startedAt: pendingHistoryStartedAt,
    endedAt: null,
    durationSec: null,
    status: "recording",
    mode: els.captureMode?.value || "mic",
    micName: selectedMicLabel(),
    protocol: "",
    live: "",
  };

  await prependHistoryItem(item);
}

async function finalizeHistoryAsProcessing() {
  if (!pendingHistoryId) return;
  const endedAt = new Date().toISOString();
  const durationSec = Math.max(0, Math.floor((new Date(endedAt) - new Date(pendingHistoryStartedAt || endedAt)) / 1000));
  await updateHistoryItem(pendingHistoryId, {
    endedAt,
    durationSec,
    status: "processing",
  });
}

async function completePendingHistoryFromViews(status = "done") {
  if (!pendingHistoryId) return;
  await updateHistoryItem(pendingHistoryId, {
    status,
    protocol: els.protocolView?.textContent || "",
    live: els.liveView?.textContent || "",
  });

  if (status !== "processing") {
    pendingHistoryId = null;
    pendingHistoryStartedAt = null;
  }
}

async function markPendingHistoryError(message) {
  if (!pendingHistoryId) return;
  await updateHistoryItem(pendingHistoryId, {
    status: "error",
    protocol: els.protocolView?.textContent || "",
    live: message || els.liveView?.textContent || "",
  });
  pendingHistoryId = null;
  pendingHistoryStartedAt = null;
}

function buildTranscriptForUI(state, saved) {
  const meetingTranscript =
    state?.lastFinishedMeeting?.transcript ??
    saved?.lastFinishedMeeting?.transcript ??
    "";

  const direct =
    state?.lastTranscript ??
    saved?.lastTranscript ??
    saved?.LAST_TRANSCRIPT ??
    "";

  const committed =
    state?.committedTranscript ??
    saved?.committedTranscript ??
    "";

  const livePreview =
    state?.liveTranscriptPreview ??
    saved?.liveTranscriptPreview ??
    "";

  const directText = String(direct || "").trim();
  if (directText) return directText;

  const committedText = String(committed || "").trim();
  const liveText = String(livePreview || "").trim();

  if (committedText && liveText) {
    if (committedText.includes(liveText)) return committedText;
    return `${committedText}\n${liveText}`.trim();
  }

  if (committedText) return committedText;
  if (liveText) return liveText;

  const meetingText = String(meetingTranscript || "").trim();
  if (meetingText) return meetingText;

  return "";
}

function attachStorageListener() {
  chrome.storage.onChanged.addListener(async (changes, area) => {
    if (area !== "local") return;

    if (
      changes.lastTranscript ||
      changes.committedTranscript ||
      changes.liveTranscriptPreview ||
      changes.lastFinishedMeeting
    ) {
      const saved = await storageGet([
        "lastTranscript",
        "LAST_TRANSCRIPT",
        "committedTranscript",
        "liveTranscriptPreview",
        "lastFinishedMeeting"
      ]);

      const transcript = buildTranscriptForUI({}, saved);

      if (els.transcriptView) {
        els.transcriptView.textContent =
          transcript || (isStopping ? "⏳ Обработка…" : "Транскрипт пока пуст.");
      }

      await storageSet({ LAST_TRANSCRIPT: transcript || "" });
    }

    if (changes.lastProtocol || changes.lastFinishedMeeting) {
      const meeting = changes.lastFinishedMeeting?.newValue || null;
      const v =
        changes.lastProtocol?.newValue ||
        meeting?.protocol ||
        "";

      if (els.protocolView) {
        els.protocolView.textContent = v || (isStopping ? "⏳ Обработка…" : "Протокол не получен.");
      }

      await storageSet({ LAST_PROTOCOL: v || "" });

      if (pendingHistoryId && v) {
        await updateHistoryItem(pendingHistoryId, { protocol: v });
      }
    }

    if (changes.lastLive) {
      const v = changes.lastLive.newValue || "";
      if (els.liveView) {
        els.liveView.textContent = v || "Пока нет подсказок.";
      }
      await storageSet({ LAST_LIVE: v });
      if (pendingHistoryId) await updateHistoryItem(pendingHistoryId, { live: v });
    }

    if (changes.isRecording) {
      const rec = !!changes.isRecording.newValue;
      isRecording = rec;

      if (rec) {
        setRecordingUI(true);
        setStatus("recording", "Запись");
        if (els.voiceTitle) els.voiceTitle.textContent = "Слушаю…";
        if (els.voiceSub) els.voiceSub.textContent = "Запись уже идёт. Нажми «Стоп», чтобы завершить";
      } else if (!isStopping) {
        setRecordingUI(false);
      }
    }

    if (changes.streamSessionId?.newValue && els.sessionLine && isRecording) {
      els.sessionLine.textContent = `Сессия: ${changes.streamSessionId.newValue}`;
    }

    if (changes.lastError) {
      const e = changes.lastError.newValue || "";
      if (e) {
        setStatus("error", "Ошибка");
        if (els.voiceSub) els.voiceSub.textContent = humanError(e);
        if (els.sessionLine) els.sessionLine.textContent = "Ошибка";
        if (isRecording) {
          setRecordingUI(false);
          isStopping = false;
        }
        await markPendingHistoryError(humanError(e));
      }
    }

    if (changes.lastFinishedMeeting?.newValue) {
      try {
        const meeting = changes.lastFinishedMeeting.newValue || {};

        if (meeting.protocol && els.protocolView) {
          els.protocolView.textContent = meeting.protocol;
        }

        if (meeting.transcript && els.transcriptView) {
          els.transcriptView.textContent = meeting.transcript;
          await storageSet({ LAST_TRANSCRIPT: meeting.transcript });
        }

        await syncAccountFromServer();
        await syncHistoryFromServer(lastHistoryQuery);
        pendingHistoryId = null;
        pendingHistoryStartedAt = null;
      } catch {}
    }

    if (changes.lastProtocol && pendingHistoryId && !isRecording && !isStopping) {
      const hasProtocol =
        !!(els.protocolView?.textContent || "").trim() &&
        !String(els.protocolView.textContent).startsWith("⏳");

      if (hasProtocol) {
        await completePendingHistoryFromViews("done");
      }
    }
  });
}

function attachLevelListener() {
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg?.type === "AUDIO_LEVEL") {
      const v = Math.max(0, Math.min(1, Number(msg.level) || 0));
      if (isRecording) setSparklineLevel(v);
    }
  });
}

async function restoreRuntimeState() {
  const resp = await sendMessage({ action: "GET_STATE" });
  const st = resp?.ok ? resp : null;

  const saved = await storageGet([
    "lastProtocol",
    "LAST_PROTOCOL",
    "lastTranscript",
    "LAST_TRANSCRIPT",
    "lastLive",
    "LAST_LIVE",
    "committedTranscript",
    "liveTranscriptPreview",
    "lastError",
    "streamSessionId",
    "lastFinishedMeeting"
  ]);

  const protocol =
    st?.lastProtocol ??
    saved.lastProtocol ??
    saved.LAST_PROTOCOL ??
    st?.lastFinishedMeeting?.protocol ??
    saved.lastFinishedMeeting?.protocol ??
    "";

  const transcript = buildTranscriptForUI(st, saved);

  const live =
    st?.lastLive ??
    saved.lastLive ??
    saved.LAST_LIVE ??
    "";

  if (els.protocolView) {
    els.protocolView.textContent = protocol || "Пока нет данных.";
  }

  if (els.transcriptView) {
    els.transcriptView.textContent = transcript || "Транскрипт пока пуст.";
  }

  if (els.liveView) {
    els.liveView.textContent = live || "Пока нет подсказок.";
  }

  const workerRecording = !!st?.isRecording;
  const workerState = st?.state || (workerRecording ? "recording" : "idle");
  const workerError = st?.lastError || saved.lastError || "";
  const sessionId = st?.streamSessionId || saved.streamSessionId || null;

  isRecording = workerRecording;
  isStopping = workerState === "processing" || workerState === "stopping";

  if (workerRecording) {
    setRecordingUI(true);
    setStatus("recording", "Запись");
    if (els.voiceTitle) els.voiceTitle.textContent = "Слушаю…";
    if (els.voiceSub) els.voiceSub.textContent = "Запись уже идёт. Нажми «Стоп», чтобы завершить";
    if (els.sessionLine) {
      els.sessionLine.textContent = sessionId
        ? `Сессия: ${sessionId}`
        : "Идёт запись…";
    }
    return;
  }

  if (isStopping) {
    setRecordingUI(false);
    setStatus("processing", "Обработка");
    if (els.voiceTitle) els.voiceTitle.textContent = "Обрабатываю…";
    if (els.voiceSub) els.voiceSub.textContent = "Финализирую транскрипт и протокол";
    if (els.sessionLine) els.sessionLine.textContent = "Обработка";
    return;
  }

  setRecordingUI(false);

  if (workerError) {
    setStatus("error", "Ошибка");
    if (els.voiceTitle) els.voiceTitle.textContent = "Не удалось завершить";
    if (els.voiceSub) els.voiceSub.textContent = humanError(workerError);
    if (els.sessionLine) els.sessionLine.textContent = "Ошибка";
  } else {
    setStatus("idle", "Готово");
    if (els.voiceTitle) els.voiceTitle.textContent = "Нажми, чтобы начать";
    if (els.voiceSub) els.voiceSub.textContent = "Готов к следующей записи";
    if (els.sessionLine) els.sessionLine.textContent = "Готово";
  }
}

function startRuntimePolling() {
  stopRuntimePolling();
  runtimePollTimer = window.setInterval(async () => {
    try {
      await restoreRuntimeState();
    } catch {}
  }, 900);
}

function stopRuntimePolling() {
  if (runtimePollTimer) {
    clearInterval(runtimePollTimer);
    runtimePollTimer = 0;
  }
}

async function onStart() {
  await stopAudioTest();

  const runtime = await sendMessage({ action: "GET_STATE" });
  if (runtime?.ok && runtime.isRecording) {
    isRecording = true;
    setRecordingUI(true);
    setStatus("recording", "Запись");
    if (els.voiceTitle) els.voiceTitle.textContent = "Слушаю…";
    if (els.voiceSub) els.voiceSub.textContent = "Запись уже идёт. Нажми «Стоп», чтобы завершить";
    if (els.sessionLine) {
      els.sessionLine.textContent = runtime.streamSessionId
        ? `Сессия: ${runtime.streamSessionId}`
        : "Идёт запись…";
    }
    await restoreRuntimeState();
    return;
  }

  const saved = await storageGet(["deviceToken"]);
  if (!saved.deviceToken) {
    setStatus("idle", "Нет привязки");
    if (els.voiceTitle) els.voiceTitle.textContent = "Сначала подключи расширение";
    if (els.voiceSub) els.voiceSub.textContent = "Вставь код из бота или mini app и нажми «Подключить расширение»";
    switchSection("settings");
    return;
  }

  await storageSet({
    MIC_DEVICE_ID: els.micSelect?.value,
    captureMode: els.captureMode?.value,
    lastError: "",
  });

  const g = els.gainSlider ? Number(els.gainSlider.value) : 1.8;
  await storageSet({ micGain: Number.isFinite(g) ? g : 1.8 });
  await sendMessage({ action: "SET_MIC_GAIN", value: Number.isFinite(g) ? g : 1.8 });

  await storageSet({
    lastProtocol: "",
    lastTranscript: "",
    committedTranscript: "",
    liveTranscriptPreview: "",
    lastLive: "",
    lastFinishedMeeting: null
  });

  if (els.protocolView) els.protocolView.textContent = "Пока нет данных.";
  if (els.transcriptView) els.transcriptView.textContent = "";
  if (els.liveView) els.liveView.textContent = "Пока нет подсказок.";

  await createHistoryEntry();

  isStopping = false;
  setRecordingUI(true);

  const resp = await sendMessage({
    action: "START",
    micDeviceId: els.micSelect?.value,
    captureMode: els.captureMode?.value,
  });

  if (!resp?.ok) {
    const msg = humanError(resp?.error || resp);

    if (/Запись уже запущена/i.test(msg)) {
      await restoreRuntimeState();
      return;
    }

    setRecordingUI(false);
    setStatus("error", "Ошибка запуска");
    if (els.voiceTitle) els.voiceTitle.textContent = "Не удалось запустить";
    if (els.voiceSub) els.voiceSub.textContent = msg || "Открой консоль service worker";
    if (els.sessionLine) els.sessionLine.textContent = "Ошибка";
    await markPendingHistoryError(msg || "Ошибка запуска");
    return;
  }

  await restoreRuntimeState();
}

async function onStop() {
  const runtime = await sendMessage({ action: "GET_STATE" });
  if (!runtime?.ok || !runtime.isRecording) {
    isRecording = false;
    setRecordingUI(false);
    await restoreRuntimeState();
    return;
  }

  if (isStopping) return;
  isStopping = true;

  setStatus("processing", "Обработка");
  if (els.voiceTitle) els.voiceTitle.textContent = "Обрабатываю…";
  if (els.voiceSub) els.voiceSub.textContent = "Финализирую транскрипт и протокол";
  if (els.stopBtn) els.stopBtn.disabled = true;

  if (els.protocolView && (!els.protocolView.textContent || els.protocolView.textContent === "Пока нет данных.")) {
    els.protocolView.textContent = "⏳ Формирую протокол…";
  }
  if (els.transcriptView && !els.transcriptView.textContent) {
    els.transcriptView.textContent = "⏳ Распознаю речь…";
  }
  if (els.liveView && !els.liveView.textContent) {
    els.liveView.textContent = "⏳ Анализирую…";
  }

  await finalizeHistoryAsProcessing();

  const resp = await sendMessage({ action: "STOP" });
  if (!resp?.ok) {
    const msg = humanError(resp?.error || resp);
    await storageSet({ lastError: msg });
    await markPendingHistoryError(msg);
    isStopping = false;
    await restoreRuntimeState();
    return;
  }

  setRecordingUI(false);
  setStatus("processing", "Обработка");
  if (els.voiceTitle) els.voiceTitle.textContent = "Обрабатываю…";
  if (els.voiceSub) els.voiceSub.textContent = "Жду финальный транскрипт и протокол";
  if (els.sessionLine) els.sessionLine.textContent = "Обработка";

  setTimeout(() => {
    isStopping = false;
  }, 1200);
}

async function onConnectExtension() {
  const url = BACKEND_URL;
  const code = ((els.linkCode?.value || "").trim().toUpperCase());

  if (!code) {
    setStatus("idle", "Нужен код");
    if (els.voiceTitle) els.voiceTitle.textContent = "Введите код подключения";
    if (els.voiceSub) els.voiceSub.textContent = "Скопируйте код из бота или mini app";
    switchSection("settings");
    return;
  }

  if (els.connectBtn) els.connectBtn.disabled = true;
  setStatus("processing", "Подключение");
  if (els.voiceTitle) els.voiceTitle.textContent = "Подключаю расширение…";
  if (els.voiceSub) els.voiceSub.textContent = "Проверяю код и загружаю подписку";

  try {
    const resp = await fetch(`${url}/extension/connect`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code,
        device_name: "Chrome Extension",
        browser_name: "Chrome",
        os_name: navigator.platform || "Unknown",
        extension_version: chrome.runtime.getManifest().version || "0.0.0",
      }),
    });

    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(data?.detail || `HTTP ${resp.status}`);
    }

    const info = {
      extensionLinkCode: code,
      deviceToken: data.device_token || "",
      linkedUserId: data.user_id || "",
      linkedPlan: data.plan || null,
      linkedSubscription: data.subscription || null,
      linkedUsage: data.usage || null,
      lastError: "",
    };

    await storageSet(info);
    renderAccountInfo(info);

    try {
      await syncAccountFromServer();
      await syncHistoryFromServer();
    } catch {}

    setStatus("idle", "Подключено");
    if (els.voiceTitle) els.voiceTitle.textContent = "Расширение подключено";
    if (els.voiceSub) {
      els.voiceSub.textContent =
        `${data?.plan?.title || data?.plan?.code || "Без тарифа"} · остаток: ${data?.usage?.remaining_minutes ?? "—"} мин`;
    }
    if (els.sessionLine) els.sessionLine.textContent = "Устройство привязано";
    switchSection("recording");
  } catch (e) {
    const msg = humanError(e);
    await storageSet({ lastError: msg });
    setStatus("error", "Ошибка");
    if (els.voiceTitle) els.voiceTitle.textContent = "Не удалось подключить";
    if (els.voiceSub) els.voiceSub.textContent = msg;
    if (els.sessionLine) els.sessionLine.textContent = "Ошибка подключения";
  } finally {
    if (els.connectBtn) els.connectBtn.disabled = false;
  }
}

async function copyCurrentTabText() {
  const text = els.protocolView?.textContent || "";

  try {
    await navigator.clipboard.writeText(text || "");
    const prevState = els.statusPill?.dataset.state || "idle";
    setStatus(prevState, "Скопировано");
    setTimeout(() => setStatus(prevState, isRecording ? "Запись" : "Готово"), 700);
  } catch {}
}

async function clearViews() {
  if (els.protocolView) els.protocolView.textContent = "Очищено.";
  if (els.transcriptView) els.transcriptView.textContent = "";
  if (els.liveView) els.liveView.textContent = "Пока нет подсказок.";
  await storageSet({
    LAST_PROTOCOL: "",
    LAST_TRANSCRIPT: "",
    LAST_LIVE: "",
    lastProtocol: "",
    lastTranscript: "",
    lastLive: "",
    committedTranscript: "",
    liveTranscriptPreview: "",
    lastFinishedMeeting: null
  });
  if (els.sessionLine) els.sessionLine.textContent = "Очищено";
}

async function copyLinkCode() {
  try {
    await navigator.clipboard.writeText((els.linkCode?.value || "").trim().toUpperCase());
    if (els.settingsSavedBadge) {
      flashSettingsSaved("Скопировано");
    }
  } catch {}
}

function openPermissions() {
  chrome.tabs.create({ url: chrome.runtime.getURL("permissions.html") });
}

async function deleteHistoryItem(id) {
  const history = await getCallHistory();
  const localOnly = String(id || "").startsWith("call_");
  if (!localOnly) {
    try {
      await fetchExtensionJson(`/extension/meetings/${encodeURIComponent(id)}`, { method: "DELETE" });
    } catch (e) {
      await storageSet({ lastError: humanError(e) });
    }
  }
  const next = history.filter((item) => item.id !== id);
  await setCallHistory(next);
  renderHistory(next);
}

async function clearHistory() {
  const history = await getCallHistory();
  for (const item of history) {
    await deleteHistoryItem(item.id);
  }
}

function bindHistoryActions() {
  els.historyList?.addEventListener("click", async (event) => {
    const copyBtn = event.target.closest("[data-copy-history]");
    const deleteBtn = event.target.closest("[data-delete-history]");
    const exportBtn = event.target.closest("[data-export-history]");

    if (copyBtn) {
      const id = copyBtn.getAttribute("data-copy-history");
      const history = await getCallHistory();
      const item = history.find((x) => x.id === id);
      if (!item) return;
      const text = [
        item.title || "Звонок",
        `Дата: ${formatDateTime(item.startedAt)}`,
        `Длительность: ${item.durationSec != null ? formatDuration(item.durationSec) : "—"}`,
        "",
        "Протокол:",
        item.protocol || "—",
      ].join("\n");
      try { await navigator.clipboard.writeText(text); } catch {}
      return;
    }

    if (exportBtn) {
      const raw = exportBtn.getAttribute("data-export-history") || "";
      const [id, fmt] = raw.split(":");
      try {
        const conn = await getStoredConnection();
        const url = `${conn.backendUrl}/extension/meetings/${encodeURIComponent(id)}/export/${encodeURIComponent(fmt)}?device_token=${encodeURIComponent(conn.deviceToken)}`;
        chrome.tabs.create({ url });
      } catch (e) {
        await storageSet({ lastError: humanError(e) });
      }
      return;
    }

    if (deleteBtn) {
      const id = deleteBtn.getAttribute("data-delete-history");
      await deleteHistoryItem(id);
    }
  });
}

async function init() {
  setStatus("idle", "Готово");
  setRecordingUI(false);
  switchSection("recording");
  switchTab("protocol");

  attachStorageListener();
  attachLevelListener();
  bindHistoryActions();
  await chrome.storage.local.remove(["backendUrl", "BACKEND_URL"]);

  const saved = await storageGet([
    "MIC_DEVICE_ID",
    "captureMode",
    "LAST_PROTOCOL",
    "LAST_TRANSCRIPT",
    "LAST_LIVE",
    "lastProtocol",
    "lastTranscript",
    "committedTranscript",
    "liveTranscriptPreview",
    "lastLive",
    "lastError",
    "micGain",
    "extensionLinkCode",
    "deviceToken",
    "linkedUserId",
    "linkedPlan",
    "linkedSubscription",
    "linkedUsage",
    "CALL_HISTORY",
    "lastFinishedMeeting"
  ]);

  if (els.captureMode) els.captureMode.value = saved.captureMode || "mic";
  if (els.linkCode) els.linkCode.value = saved.extensionLinkCode || "";

  const g0 = (typeof saved.micGain === "number" && isFinite(saved.micGain)) ? saved.micGain : 1.8;
  if (els.gainSlider && els.gainVal) {
    els.gainSlider.value = String(g0);
    els.gainVal.textContent = String(Number(g0).toFixed(1));
  }
  await sendMessage({ action: "SET_MIC_GAIN", value: g0 });

  const protocol =
    (saved.lastProtocol ?? saved.LAST_PROTOCOL ?? saved.lastFinishedMeeting?.protocol) || "";
  const transcript = buildTranscriptForUI(saved, saved);
  const live = (saved.lastLive ?? saved.LAST_LIVE) || "";

  if (els.protocolView) els.protocolView.textContent = protocol || "Пока нет данных.";
  if (els.transcriptView) els.transcriptView.textContent = transcript || "Транскрипт пока пуст.";
  if (els.liveView) els.liveView.textContent = live || "Пока нет подсказок.";

  historyFeatures = saved.linkedPlan?.features || {};
  renderAccountInfo(saved);
  renderHistory(Array.isArray(saved.CALL_HISTORY) ? saved.CALL_HISTORY : []);
  setAudioTestUI(false);

  await loadMics();
  if (saved.MIC_DEVICE_ID && els.micSelect) els.micSelect.value = saved.MIC_DEVICE_ID;
  updateRecordingMeta();

  await restoreRuntimeState();
  startRuntimePolling();

  els.micSelect?.addEventListener("change", async () => {
    await storageSet({ MIC_DEVICE_ID: els.micSelect.value });
    updateRecordingMeta();
    flashSettingsSaved();
  });

  els.captureMode?.addEventListener("change", async () => {
    await storageSet({ captureMode: els.captureMode.value });
    updateRecordingMeta();
    flashSettingsSaved();
  });

  els.linkCode?.addEventListener("input", async () => {
    const code = (els.linkCode.value || "").trim().toUpperCase();
    els.linkCode.value = code;
    await storageSet({ extensionLinkCode: code });
    flashSettingsSaved();
  });

  els.gainSlider?.addEventListener("input", async () => {
    const g = Number(els.gainSlider.value);
    const gainValue = Number.isFinite(g) ? g : 1.8;
    if (els.gainVal) els.gainVal.textContent = String(gainValue.toFixed(1));
    if (audioTestGainNode) {
      try { audioTestGainNode.gain.value = gainValue; } catch {}
    }
    await storageSet({ micGain: gainValue });
    await sendMessage({ action: "SET_MIC_GAIN", value: gainValue });
    flashSettingsSaved(`Gain ${String(gainValue.toFixed(1))}x`);
  });

  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  document.querySelectorAll(".section-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchSection(btn.dataset.section));
  });

  if (saved.deviceToken && saved.linkedPlan) {
    setStatus("idle", "Подключено");
    if (els.voiceSub) {
      els.voiceSub.textContent =
        `${saved.linkedPlan?.title || saved.linkedPlan?.code || "Без тарифа"} · остаток: ${saved.linkedUsage?.remaining_minutes ?? "—"} мин`;
    }
    if (els.sessionLine) els.sessionLine.textContent = "Устройство привязано";
  }

  if (saved.lastError) {
    setStatus("error", "Ошибка");
    if (els.voiceSub) els.voiceSub.textContent = humanError(saved.lastError);
    if (els.sessionLine) els.sessionLine.textContent = "Ошибка";
  }

  if (saved.deviceToken) {
    syncAccountFromServer().then(() => syncHistoryFromServer()).catch(() => {});
  }

  els.orbBtn?.addEventListener("click", async () => {
    const runtime = await sendMessage({ action: "GET_STATE" });
    const rec = !!runtime?.isRecording;

    if (rec) await onStop();
    else await onStart();
  });

  els.stopBtn?.addEventListener("click", onStop);
  els.connectBtn?.addEventListener("click", onConnectExtension);
  els.copyBtn?.addEventListener("click", copyCurrentTabText);
  els.clearBtn?.addEventListener("click", clearViews);
  els.copyLinkCodeBtn?.addEventListener("click", copyLinkCode);
  els.audioTestBtn?.addEventListener("click", startAudioTest);
  els.audioTestStopBtn?.addEventListener("click", stopAudioTest);
  els.permissionsBtn?.addEventListener("click", openPermissions);

  els.refreshHistoryBtn?.addEventListener("click", async () => {
    try {
      await syncAccountFromServer();
      await syncHistoryFromServer(els.historySearchInput?.value || "");
    } catch {
      renderHistory(await getCallHistory());
    }
  });

  els.historySearchBtn?.addEventListener("click", async () => {
    lastHistoryQuery = (els.historySearchInput?.value || "").trim();
    try {
      await syncHistoryFromServer(lastHistoryQuery);
    } catch (e) {
      await storageSet({ lastError: humanError(e) });
    }
  });

  els.historySearchInput?.addEventListener("keydown", async (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      els.historySearchBtn?.click();
    }
  });

  els.clearHistoryBtn?.addEventListener("click", clearHistory);
}

init().catch(console.error);

window.addEventListener("beforeunload", () => {
  stopRuntimePolling();
  stopAudioTest().catch(() => {});
});
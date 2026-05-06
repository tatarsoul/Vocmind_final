const OFFSCREEN_URL = "offscreen.html";
const BACKEND_URL = "http://localhost:8000";

let MIC_GAIN = 1.8;

function dbg(...args) {
  console.log("[sw]", ...args);
}

function warn(...args) {
  console.warn("[sw]", ...args);
}

function errlog(...args) {
  console.error("[sw]", ...args);
}

function clampGain(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return 1.8;
  return Math.max(0.2, Math.min(6.0, n));
}

function errToStr(e) {
  if (!e) return "Неизвестная ошибка";
  if (typeof e === "string") return e;
  if (e instanceof Error) return e.message || String(e);
  try {
    return JSON.stringify(e);
  } catch {
    return String(e);
  }
}

function storageGet(keys) {
  return new Promise((resolve) => {
    try {
      chrome.storage.local.get(keys, (res) => {
        const lastErr = chrome.runtime.lastError;
        if (lastErr) {
          warn("storageGet error:", lastErr.message);
          resolve({});
          return;
        }
        resolve(res || {});
      });
    } catch (e) {
      warn("storageGet exception:", e);
      resolve({});
    }
  });
}

function storageSet(obj) {
  return new Promise((resolve) => {
    try {
      chrome.storage.local.set(obj, () => {
        const lastErr = chrome.runtime.lastError;
        if (lastErr) warn("storageSet error:", lastErr.message);
        resolve();
      });
    } catch (e) {
      warn("storageSet exception:", e);
      resolve();
    }
  });
}

async function loadBackendConfig() {
  const stored = await storageGet(["micGain"]);
  if (typeof stored.micGain === "number" && isFinite(stored.micGain)) {
    MIC_GAIN = stored.micGain;
  }
  return {
    backendUrl: String(BACKEND_URL).replace(/\/$/, "")
  };
}

async function ensureOffscreen() {
  const exists = await chrome.offscreen.hasDocument?.();
  if (exists) return;

  await chrome.offscreen.createDocument({
    url: OFFSCREEN_URL,
    reasons: ["USER_MEDIA"],
    justification: "Record audio using offscreen document in MV3"
  });
}

async function sendToOffscreen(message) {
  await ensureOffscreen();

  return await new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (resp) => {
      const lastErr = chrome.runtime.lastError;
      if (lastErr) return reject(new Error(lastErr.message));
      resolve(resp);
    });
  });
}

async function getActiveRecordingState() {
  const st = await storageGet([
    "isRecording",
    "captureMode",
    "capturedTabId",
    "streamSessionId",
    "lastTranscript",
    "committedTranscript",
    "liveTranscriptPreview",
    "lastProtocol",
    "lastLive",
    "lastError",
    "linkedUserId",
    "linkedPlan",
    "lastFinishedMeeting"
  ]);

  return {
    isRecording: !!st.isRecording,
    captureMode: st.captureMode || "mic",
    capturedTabId:
      typeof st.capturedTabId === "number" ? st.capturedTabId : null,
    streamSessionId: st.streamSessionId || null,
    lastTranscript: st.lastTranscript || "",
    committedTranscript: st.committedTranscript || "",
    liveTranscriptPreview: st.liveTranscriptPreview || "",
    lastProtocol: st.lastProtocol || "",
    lastLive: st.lastLive || "",
    lastError: st.lastError || "",
    linkedUserId: st.linkedUserId || "",
    linkedPlan: st.linkedPlan || null,
    lastFinishedMeeting: st.lastFinishedMeeting || null
  };
}

async function getTabCaptureInfo() {
  return new Promise((resolve) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (chrome.runtime.lastError) {
        warn("tabs.query error:", chrome.runtime.lastError.message);
        return resolve({ tabId: null, streamId: null });
      }

      if (!tabs || !tabs.length || !tabs[0]?.id) {
        warn("No active tab for tab capture");
        return resolve({ tabId: null, streamId: null });
      }

      const activeTab = tabs[0];

      chrome.tabCapture.getMediaStreamId(
        { targetTabId: activeTab.id },
        (streamId) => {
          if (chrome.runtime.lastError) {
            warn("tabCapture error:", chrome.runtime.lastError.message);
            return resolve({ tabId: activeTab.id, streamId: null });
          }

          resolve({
            tabId: activeTab.id,
            streamId: streamId || null
          });
        }
      );
    });
  });
}

async function stopRecordingWithReason(reason = "") {
  const st = await getActiveRecordingState();
  if (!st.isRecording) return { ok: false, error: "Запись не активна." };

  try {
    await storageSet({
      isRecording: false,
      lastError: reason || "",
      stopRequestedAt: Date.now()
    });

    const resp = await sendToOffscreen({
      action: "OFFSCREEN_STOP",
      reason: reason || ""
    });

    return resp?.ok
      ? { ok: true }
      : { ok: false, error: resp?.error || "Не удалось остановить запись" };
  } catch (e) {
    await storageSet({ lastError: errToStr(e) });
    return { ok: false, error: errToStr(e) };
  }
}

async function handleStart(msg) {
  const st = await getActiveRecordingState();
  if (st.isRecording) {
    return { ok: false, error: "Запись уже запущена." };
  }

  const { backendUrl } = await loadBackendConfig();
  const stored = await storageGet([
    "deviceToken",
    "linkedUserId",
    "linkedPlan"
  ]);

  const deviceToken = stored.deviceToken || "";
  if (!deviceToken) {
    return {
      ok: false,
      error: "Расширение не подключено. Сначала введите код подключения."
    };
  }

  const captureMode = msg.captureMode || "mic";
  let tabStreamId = null;
  let capturedTabId = null;

  if (captureMode === "tab_mic") {
    const cap = await getTabCaptureInfo();
    tabStreamId = cap.streamId;
    capturedTabId = cap.tabId;

    if (!tabStreamId) {
      await storageSet({
        isRecording: false,
        captureMode: "mic",
        capturedTabId: null,
        lastError:
          "Не удалось захватить звук вкладки. Убедись, что активна вкладка созвона и попробуй снова."
      });

      return {
        ok: false,
        error:
          "Не удалось захватить звук вкладки. Убедись, что активна вкладка созвона и попробуй снова."
      };
    }
  }

  await storageSet({
    isRecording: false,
    captureMode,
    capturedTabId,
    lastError: "",
    lastTranscript: "",
    committedTranscript: "",
    liveTranscriptPreview: "",
    lastProtocol: "🧾 ПРОТОКОЛ ВСТРЕЧИ\n\n(Слушаю…)",
    lastLive: "Пока нет подсказок.",
    LAST_TRANSCRIPT: "",
    LAST_PROTOCOL: "🧾 ПРОТОКОЛ ВСТРЕЧИ\n\n(Слушаю…)",
    LAST_LIVE: "Пока нет подсказок.",
    stopRequestedAt: null,
    streamSessionId: null,
    lastFinishedMeeting: null
  });

  const resp = await sendToOffscreen({
    action: "OFFSCREEN_START",
    backendUrl,
    deviceToken,
    captureMode,
    meetingTitle: msg.meetingTitle || "",
    deviceId: msg.micDeviceId || "default",
    tabStreamId: tabStreamId || null,
    micGain: MIC_GAIN
  });

  if (!resp?.ok) {
    await storageSet({
      isRecording: false,
      captureMode: "mic",
      capturedTabId: null,
      lastError: resp?.error || "Не удалось запустить запись"
    });

    return {
      ok: false,
      error: resp?.error || "Не удалось запустить запись"
    };
  }

  await storageSet({
    isRecording: true,
    captureMode,
    capturedTabId
  });

  dbg("Recording started");
  return { ok: true };
}

async function ensureContextMenu() {
  try {
    await chrome.contextMenus.removeAll();

    chrome.contextMenus.create({
      id: "vocmind-stop-recording",
      title: "Остановить запись VocMind",
      contexts: ["action"]
    });
  } catch (e) {
    warn("ensureContextMenu failed:", e);
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    try {
      if (msg?.type === "AUDIO_LEVEL") {
        sendResponse({ ok: true });
        return;
      }

      if (msg?.action === "SET_MIC_GAIN") {
        const g = clampGain(msg.value);
        MIC_GAIN = g;

        await storageSet({ micGain: g });

        try {
          await sendToOffscreen({ action: "SET_MIC_GAIN", value: g });
        } catch (e) {
          warn("Forward SET_MIC_GAIN to offscreen failed:", e);
        }

        sendResponse({ ok: true, micGain: g });
        return;
      }

      if (msg?.action === "START") {
        const result = await handleStart(msg);
        sendResponse(result);
        return;
      }

      if (msg?.action === "STOP" || msg?.action === "STOP_RECORDING") {
        const result = await stopRecordingWithReason("");
        sendResponse(result);
        return;
      }

      if (msg?.action === "GET_STATE") {
        const st = await getActiveRecordingState();

        sendResponse({
          ok: true,
          state: st.isRecording ? "recording" : "idle",
          ...st
        });
        return;
      }

      if (msg?.action === "OFFSCREEN_SYNC_STATE") {
        const patch = msg.patch && typeof msg.patch === "object" ? msg.patch : {};
        if (Object.keys(patch).length) {
          await storageSet(patch);
        }
        sendResponse({ ok: true });
        return;
      }

      if (msg?.action === "OFFSCREEN_STARTED" || msg?.type === "OFFSCREEN_STARTED") {
        await storageSet({
          isRecording: true,
          lastError: "",
          startedAt: Date.now()
        });
        sendResponse({ ok: true });
        return;
      }

      if (msg?.action === "OFFSCREEN_STOPPED" || msg?.type === "OFFSCREEN_STOPPED") {
        await storageSet({
          isRecording: false,
          captureMode: "mic",
          capturedTabId: null,
          stopRequestedAt: null
        });
        sendResponse({ ok: true });
        return;
      }

      if (msg?.action === "OFFSCREEN_ERROR" || msg?.type === "OFFSCREEN_ERROR") {
        errlog("OFFSCREEN_ERROR:", msg.error);

        await storageSet({
          isRecording: false,
          captureMode: "mic",
          capturedTabId: null,
          lastError: msg.error || "Ошибка записи",
          stopRequestedAt: null
        });

        sendResponse({ ok: true });
        return;
      }

      sendResponse({ ok: false, error: "Unknown message" });
    } catch (e) {
      errlog("onMessage handler failed:", e);
      await storageSet({
        isRecording: false,
        captureMode: "mic",
        capturedTabId: null,
        lastError: errToStr(e),
        stopRequestedAt: null
      });
      sendResponse({ ok: false, error: errToStr(e) });
    }
  })();

  return true;
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  try {
    const st = await getActiveRecordingState();

    if (!st.isRecording) return;
    if (st.captureMode !== "tab_mic") return;
    if (!st.capturedTabId) return;
    if (tabId !== st.capturedTabId) return;

    warn("Captured tab was closed, stopping recording automatically");

    await stopRecordingWithReason(
      "Запись остановлена: закрыта вкладка, с которой захватывался звук."
    );
  } catch (e) {
    errlog("tabs.onRemoved handler failed:", e);
  }
});

chrome.commands.onCommand.addListener(async (command) => {
  try {
    if (command !== "stop-recording") return;

    const st = await getActiveRecordingState();
    if (!st.isRecording) return;

    dbg("commands.onCommand -> STOP");
    await stopRecordingWithReason("");
  } catch (e) {
    errlog("commands.onCommand failed:", e);
  }
});

chrome.contextMenus.onClicked.addListener(async (info) => {
  try {
    if (info.menuItemId !== "vocmind-stop-recording") return;

    const st = await getActiveRecordingState();
    if (!st.isRecording) return;

    dbg("context menu -> STOP");
    await stopRecordingWithReason("");
  } catch (e) {
    errlog("contextMenus.onClicked failed:", e);
  }
});

chrome.runtime.onInstalled.addListener(async () => {
  await storageSet({
    isRecording: false,
    captureMode: "mic",
    capturedTabId: null,
    streamSessionId: null,
    lastTranscript: "",
    committedTranscript: "",
    liveTranscriptPreview: "",
    lastProtocol: "",
    lastLive: "",
    LAST_TRANSCRIPT: "",
    LAST_PROTOCOL: "",
    LAST_LIVE: "",
    lastError: "",
    stopRequestedAt: null,
    lastFinishedMeeting: null
  });

  await ensureContextMenu();
});

chrome.runtime.onStartup.addListener(async () => {
  await ensureContextMenu();
});
let micStream = null;
let tabStream = null;
let audioCtx = null;

let micSource = null;
let tabSource = null;

let micGainNode = null;
let silentGainNode = null;
let tabMonitorGainNode = null;

let micProcessor = null;
let tabProcessor = null;

let isRunning = false;
let isStopping = false;
let micGain = 1.8;

let micParts = [];
let micLen = 0;

let tabParts = [];
let tabLen = 0;

const CHUNK_MS = 700;
let lastMicChunkAt = 0;
let lastTabChunkAt = 0;

let BACKEND_BASE_URL = null;
let DEVICE_TOKEN = null;
let CAPTURE_MODE = "mic";
let MEETING_TITLE = "";

let STREAM_SESSION_ID = null;
let STREAM_QUEUE = [];
let STREAM_UPLOADING = false;
let STREAM_FLUSH_PROMISE = null;
let STOP_REASON = "";

let LOCAL_COMMITTED_TRANSCRIPT = "";
let LOCAL_LIVE_TRANSCRIPT = "";
let LOCAL_LAST_PROTOCOL = "";
let LOCAL_LAST_LIVE = "";

let CURRENT_RUN_ID = 0;
let HAS_FINALIZED_CURRENT_RUN = false;

function dbg(...args) {
  console.log("[offscreen]", ...args);
}

function warn(...args) {
  console.warn("[offscreen]", ...args);
}

function err(...args) {
  console.error("[offscreen]", ...args);
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

async function sendPatchToWorker(patch) {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage(
        { action: "OFFSCREEN_SYNC_STATE", patch },
        () => resolve()
      );
    } catch {
      resolve();
    }
  });
}

function normalizeText(str) {
  return String(str || "")
    .toLowerCase()
    .replace(/[.,!?;:«»"']/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeLine(line) {
  return normalizeText(String(line || "").replace(/^(ME|THEM):\s*/i, "$1: "));
}

function splitLines(text) {
  return String(text || "")
    .split(/\r?\n/)
    .map((x) => String(x || "").trim())
    .filter(Boolean);
}

function mergeLineList(lines, rawLine) {
  const line = String(rawLine || "").trim();
  if (!line) return lines;

  const nLine = normalizeLine(line);
  if (!nLine) return lines;

  const start = Math.max(0, lines.length - 10);
  for (let i = start; i < lines.length; i++) {
    const old = lines[i];
    const nOld = normalizeLine(old);
    if (!nOld) continue;

    const oldSpeaker = (old.match(/^(ME|THEM):/i) || [""])[0].toUpperCase();
    const newSpeaker = (line.match(/^(ME|THEM):/i) || [""])[0].toUpperCase();
    const sameSpeaker = oldSpeaker && newSpeaker && oldSpeaker === newSpeaker;

    if (!sameSpeaker) continue;

    if (nLine === nOld) return lines;

    if (nLine.startsWith(nOld) && nLine.length > nOld.length) {
      lines[i] = line;
      return lines;
    }

    if (nOld.startsWith(nLine)) {
      return lines;
    }
  }

  lines.push(line);
  return lines;
}

function mergeTranscripts(baseText, addText) {
  const merged = [];

  for (const line of splitLines(baseText)) {
    mergeLineList(merged, line);
  }

  for (const line of splitLines(addText)) {
    mergeLineList(merged, line);
  }

  return merged.join("\n").trim();
}

function buildDisplayedTranscript(committedText, liveWindowText) {
  const committed = String(committedText || "").trim();
  const live = String(liveWindowText || "").trim();

  if (!committed && !live) return "";
  if (!committed) return live;
  if (!live) return committed;

  return mergeTranscripts(committed, live);
}

function protocolToText(p) {
  if (!p || typeof p !== "object") {
    return "🧾 ПРОТОКОЛ ВСТРЕЧИ\n\n(Пока нет данных для сводки.)";
  }

  const clean = (s) => (typeof s === "string" ? s.trim() : "");
  const safeArr = (a) =>
    Array.isArray(a)
      ? a.map((x) => (typeof x === "string" ? x.trim() : "")).filter(Boolean)
      : [];

  const summary = clean(p.summary);
  const decisions = safeArr(p.decisions);
  const ideas = safeArr(p.ideas);
  const risks = safeArr(p.risks);
  const nextSteps = safeArr(p.next_steps);

  const actionItems = Array.isArray(p.action_items) ? p.action_items : [];
  const tasks = actionItems
    .map((it) => {
      const task = clean(it?.task);
      const assignee = clean(it?.assignee);
      const due = clean(it?.due);
      if (!task) return null;

      let line = `- ${task}`;
      const meta = [];
      if (assignee) meta.push(`ответственный: ${assignee}`);
      if (due) meta.push(`срок: ${due}`);
      if (meta.length) line += ` (${meta.join(", ")})`;

      return line;
    })
    .filter(Boolean);

  const out = ["🧾 ПРОТОКОЛ ВСТРЕЧИ", ""];

  if (summary) {
    out.push("Кратко:");
    out.push(summary);
    out.push("");
  }

  if (decisions.length) {
    out.push("Решения:");
    out.push(decisions.map((d) => `- ${d}`).join("\n"));
    out.push("");
  }

  if (tasks.length) {
    out.push("Задачи:");
    out.push(tasks.join("\n"));
    out.push("");
  }

  if (ideas.length) {
    out.push("Идеи:");
    out.push(ideas.map((x) => `- ${x}`).join("\n"));
    out.push("");
  }

  if (risks.length) {
    out.push("Риски:");
    out.push(risks.map((x) => `- ${x}`).join("\n"));
    out.push("");
  }

  if (nextSteps.length) {
    out.push("Следующие шаги:");
    out.push(nextSteps.map((x) => `- ${x}`).join("\n"));
    out.push("");
  }

  const txt = out.join("\n").trim();
  return txt === "🧾 ПРОТОКОЛ ВСТРЕЧИ"
    ? "🧾 ПРОТОКОЛ ВСТРЕЧИ\n\n(Пока нет данных для сводки.)"
    : txt;
}

function insightsToText(insights) {
  if (!Array.isArray(insights) || !insights.length) return "Пока нет подсказок.";

  const icon = (t) => {
    const x = String(t || "");
    if (x.includes("risk")) return "⚠️";
    if (x.includes("interest")) return "🔥";
    if (x.includes("budget")) return "💰";
    if (x.includes("evasion")) return "❓";
    if (x.includes("decision")) return "📌";
    if (x.includes("action")) return "✅";
    return "💡";
  };

  return insights
    .slice(-20)
    .map((it) => {
      const title = it?.title || "";
      const detail = it?.detail || "";
      const c =
        typeof it?.confidence === "number"
          ? ` (${Math.round(it.confidence * 100)}%)`
          : "";
      return `${icon(it?.type)} ${title}${c}\n${detail}`;
    })
    .join("\n\n");
}

function floatTo16BitPCM(float32) {
  const out = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    let s = Math.max(-1, Math.min(1, float32[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

function downsampleBuffer(buffer, sampleRate, outSampleRate) {
  if (sampleRate === outSampleRate) return buffer;

  const ratio = sampleRate / outSampleRate;
  const newLength = Math.round(buffer.length / ratio);
  const out = new Float32Array(newLength);

  let offsetResult = 0;
  let offsetBuffer = 0;

  while (offsetResult < out.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
    let acc = 0;
    let count = 0;

    for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
      acc += buffer[i];
      count++;
    }

    out[offsetResult] = acc / (count || 1);
    offsetResult++;
    offsetBuffer = nextOffsetBuffer;
  }

  return out;
}

function encodeWavPCM16(samplesInt16, sampleRate) {
  const numChannels = 1;
  const bytesPerSample = 2;
  const blockAlign = numChannels * bytesPerSample;
  const byteRate = sampleRate * blockAlign;
  const dataSize = samplesInt16.length * bytesPerSample;

  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);

  function writeString(offset, str) {
    for (let i = 0; i < str.length; i++) {
      view.setUint8(offset + i, str.charCodeAt(i));
    }
  }

  writeString(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, dataSize, true);

  let offset = 44;
  for (let i = 0; i < samplesInt16.length; i++, offset += 2) {
    view.setInt16(offset, samplesInt16[i], true);
  }

  return buffer;
}

function sendLevel(float32) {
  let sum = 0;
  for (let i = 0; i < float32.length; i++) {
    sum += float32[i] * float32[i];
  }
  const rms = Math.sqrt(sum / (float32.length || 1));
  const level = Math.max(0, Math.min(1, rms * 2.2));

  chrome.runtime.sendMessage({ type: "AUDIO_LEVEL", level }, () => {
    if (chrome.runtime.lastError) {}
  });
}

function appendPart(source, part) {
  if (source === "mic") {
    micParts.push(part);
    micLen += part.length;
  } else {
    tabParts.push(part);
    tabLen += part.length;
  }
}

async function updateChunkResponseState(data, runId) {
  if (!data || typeof data !== "object") return;
  if (runId !== CURRENT_RUN_ID) return;
  if (HAS_FINALIZED_CURRENT_RUN) return;

  if (data.partial_transcript) {
    LOCAL_COMMITTED_TRANSCRIPT = mergeTranscripts(
      LOCAL_COMMITTED_TRANSCRIPT,
      data.partial_transcript
    );
  }

  if (data.window_transcript !== undefined) {
    LOCAL_LIVE_TRANSCRIPT = String(data.window_transcript || "").trim();
  }

  const displayedTranscript = buildDisplayedTranscript(
    LOCAL_COMMITTED_TRANSCRIPT,
    LOCAL_LIVE_TRANSCRIPT
  );

  const patch = {
    committedTranscript: LOCAL_COMMITTED_TRANSCRIPT,
    liveTranscriptPreview: LOCAL_LIVE_TRANSCRIPT
  };

  if (displayedTranscript) {
    patch.lastTranscript = displayedTranscript;
    patch.LAST_TRANSCRIPT = displayedTranscript;
  }

  if (data.state) {
    LOCAL_LAST_PROTOCOL = protocolToText(data.state);
    LOCAL_LAST_LIVE = insightsToText(data.state.insights);

    patch.lastProtocol = LOCAL_LAST_PROTOCOL;
    patch.LAST_PROTOCOL = LOCAL_LAST_PROTOCOL;
    patch.lastLive = LOCAL_LAST_LIVE;
    patch.LAST_LIVE = LOCAL_LAST_LIVE;
  }

  if (data.error) {
    patch.lastError = String(data.error);
  }

  await sendPatchToWorker(patch);
}

async function startStreamSession() {
  if (STREAM_SESSION_ID) return STREAM_SESSION_ID;

  if (!BACKEND_BASE_URL) throw new Error("BACKEND_BASE_URL is not set");
  if (!DEVICE_TOKEN) throw new Error("DEVICE_TOKEN is not set");

  dbg("Calling /stream/start", {
    backend: BACKEND_BASE_URL,
    captureMode: CAPTURE_MODE,
    meetingTitle: MEETING_TITLE
  });

  const resp = await fetch(`${BACKEND_BASE_URL}/stream/start`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
    },
    body: new URLSearchParams({
      device_token: DEVICE_TOKEN,
      capture_mode: CAPTURE_MODE || "mic",
      title: MEETING_TITLE || ""
    })
  });

  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`stream/start failed: ${resp.status} ${text}`);
  }

  const data = await resp.json();
  STREAM_SESSION_ID = data.session_id || null;

  await sendPatchToWorker({
    streamSessionId: STREAM_SESSION_ID,
    linkedUserId: data.user_id || "",
    linkedPlan: data.plan || null
  });

  dbg("streamStart ok:", data);
  return STREAM_SESSION_ID;
}

async function uploadChunk(item) {
  if (!STREAM_SESSION_ID) {
    await startStreamSession();
  }

  const requestRunId = item.runId;

  const blob = new Blob([item.buffer], {
    type: item.mimeType || "audio/wav"
  });

  const fd = new FormData();
  fd.append("session_id", STREAM_SESSION_ID);
  fd.append("source", item.source || "mic");
  fd.append("file", blob, "chunk.wav");

  const resp = await fetch(`${BACKEND_BASE_URL}/stream/chunk`, {
    method: "POST",
    body: fd
  });

  const text = await resp.text().catch(() => "");
  let data = {};

  try {
    data = text ? JSON.parse(text) : {};
  } catch (e) {
    warn("stream/chunk JSON parse failed:", e, "raw=", text);
  }

  if (!resp.ok) {
    const isUnknown =
      resp.status === 404 &&
      (/Unknown session_id/i.test(text || "") ||
        /"detail":"Unknown session_id"/i.test(text || ""));

    if (isUnknown) {
      warn("Unknown session_id from backend, restarting session");
      STREAM_SESSION_ID = null;
      await sendPatchToWorker({ streamSessionId: null });
      await startStreamSession();
      return await uploadChunk(item);
    }

    throw new Error(`stream/chunk failed: ${resp.status} ${text}`);
  }

  if (!HAS_FINALIZED_CURRENT_RUN && requestRunId === CURRENT_RUN_ID) {
    await updateChunkResponseState(data, requestRunId);
  }

  if (data.should_stop && isRunning && !isStopping && requestRunId === CURRENT_RUN_ID) {
    STOP_REASON = data.stop_reason || "Достигнут лимит тарифа";
    await sendPatchToWorker({
      lastError: STOP_REASON,
      isRecording: false
    });
    setTimeout(() => {
      stopAndFinalize(STOP_REASON).catch((e) => {
        err("stopAndFinalize after should_stop failed:", e);
      });
    }, 0);
  }

  return data;
}

function runFlushLoop() {
  if (STREAM_FLUSH_PROMISE) return STREAM_FLUSH_PROMISE;

  STREAM_FLUSH_PROMISE = (async () => {
    if (STREAM_UPLOADING) {
      while (STREAM_UPLOADING) {
        await new Promise((r) => setTimeout(r, 20));
      }
      return;
    }

    STREAM_UPLOADING = true;
    try {
      while (STREAM_QUEUE.length > 0) {
        const item = STREAM_QUEUE.shift();

        if (!item?.buffer || item.buffer.byteLength === 0) {
          continue;
        }

        await uploadChunk(item);
      }
    } finally {
      STREAM_UPLOADING = false;
      STREAM_FLUSH_PROMISE = null;
    }
  })();

  return STREAM_FLUSH_PROMISE;
}

async function flushQueue() {
  await runFlushLoop();
}

function enqueueChunk(source, wavBuf) {
  if (HAS_FINALIZED_CURRENT_RUN) return;

  STREAM_QUEUE.push({
    source,
    buffer: wavBuf,
    mimeType: "audio/wav",
    runId: CURRENT_RUN_ID
  });

  runFlushLoop().catch(async (e) => {
    err("flushQueue failed:", e);
    await sendPatchToWorker({ lastError: errToStr(e) });
  });
}

function flushIfNeeded(source, force = false) {
  if (HAS_FINALIZED_CURRENT_RUN) return;

  const now = Date.now();

  if (source === "mic") {
    if (!force && now - lastMicChunkAt < CHUNK_MS) return;

    if (micLen === 0) {
      lastMicChunkAt = now;
      return;
    }

    const merged = new Int16Array(micLen);
    let pos = 0;
    for (const p of micParts) {
      merged.set(p, pos);
      pos += p.length;
    }

    micParts = [];
    micLen = 0;
    lastMicChunkAt = now;

    dbg("flush mic:", merged.length, "samples");
    enqueueChunk("mic", encodeWavPCM16(merged, 16000));
    return;
  }

  if (!force && now - lastTabChunkAt < CHUNK_MS) return;

  if (tabLen === 0) {
    lastTabChunkAt = now;
    return;
  }

  const merged = new Int16Array(tabLen);
  let pos = 0;
  for (const p of tabParts) {
    merged.set(p, pos);
    pos += p.length;
  }

  tabParts = [];
  tabLen = 0;
  lastTabChunkAt = now;

  dbg("flush tab:", merged.length, "samples");
  enqueueChunk("tab", encodeWavPCM16(merged, 16000));
}

function stopTracks(stream) {
  try {
    if (stream) {
      stream.getTracks().forEach((t) => {
        try {
          t.stop();
        } catch {}
      });
    }
  } catch {}
}

async function safeCloseAudioContext() {
  try {
    if (audioCtx && audioCtx.state !== "closed") {
      await audioCtx.close();
    }
  } catch (e) {
    warn("audioCtx close failed:", e);
  }
}

async function finishStream() {
  if (!STREAM_SESSION_ID) {
    dbg("finishStream skipped: no session id");
    return;
  }

  const currentSessionId = STREAM_SESSION_ID;

  const fd = new FormData();
  fd.append("session_id", currentSessionId);

  const resp = await fetch(`${BACKEND_BASE_URL}/stream/finish`, {
    method: "POST",
    body: fd
  });

  const data = await resp.json().catch(() => ({}));

  HAS_FINALIZED_CURRENT_RUN = true;
  STREAM_SESSION_ID = null;
  STREAM_QUEUE = [];
  STREAM_UPLOADING = false;
  STREAM_FLUSH_PROMISE = null;

  const finalTranscript = String(
    data.transcript ||
    data.transcript_text ||
    data.final_transcript ||
    LOCAL_COMMITTED_TRANSCRIPT ||
    ""
  ).trim();

  const finalProtocolText = String(
    data.protocol_text ||
    data.protocol?.text ||
    ""
  ).trim();

  const finalProtocolObject = data.protocol || null;
  const finalMeetingId = data.meeting_id || "";
  const finalProtocolRendered =
    finalProtocolText ||
    (finalProtocolObject ? protocolToText(finalProtocolObject) : LOCAL_LAST_PROTOCOL || "");
  const finalLive =
    insightsToText(finalProtocolObject?.insights) || LOCAL_LAST_LIVE || "Пока нет подсказок.";

  if (finalTranscript) {
    LOCAL_COMMITTED_TRANSCRIPT = finalTranscript;
    LOCAL_LIVE_TRANSCRIPT = "";
  }

  if (finalProtocolRendered) {
    LOCAL_LAST_PROTOCOL = finalProtocolRendered;
  }

  if (finalLive) {
    LOCAL_LAST_LIVE = finalLive;
  }

  const patch = {
    streamSessionId: null,
    liveTranscriptPreview: "",
    committedTranscript: LOCAL_COMMITTED_TRANSCRIPT,
    lastError: data.protocol_error
      ? String(data.protocol_error)
      : STOP_REASON || ""
  };

  const finalVisibleTranscript =
    finalTranscript ||
    buildDisplayedTranscript(LOCAL_COMMITTED_TRANSCRIPT, "");

  patch.lastTranscript = finalVisibleTranscript;
  patch.LAST_TRANSCRIPT = finalVisibleTranscript;

  if (finalProtocolRendered) {
    patch.lastProtocol = finalProtocolRendered;
    patch.LAST_PROTOCOL = finalProtocolRendered;
  }

  if (finalLive) {
    patch.lastLive = finalLive;
    patch.LAST_LIVE = finalLive;
  }

  patch.lastFinishedMeeting = {
    id: finalMeetingId,
    transcript: finalVisibleTranscript || "",
    protocol: finalProtocolRendered || "",
    analytics: data.analytics || null
  };

  await sendPatchToWorker(patch);

  dbg("finishStream saved final data", {
    transcriptLen: String(finalVisibleTranscript || "").length,
    protocolLen: String(finalProtocolRendered || "").length,
    meetingId: finalMeetingId
  });
}

async function resetMediaState() {
  try {
    if (micProcessor) micProcessor.disconnect();
  } catch {}
  try {
    if (tabProcessor) tabProcessor.disconnect();
  } catch {}
  try {
    if (micGainNode) micGainNode.disconnect();
  } catch {}
  try {
    if (silentGainNode) silentGainNode.disconnect();
  } catch {}
  try {
    if (tabMonitorGainNode) tabMonitorGainNode.disconnect();
  } catch {}
  try {
    if (micSource) micSource.disconnect();
  } catch {}
  try {
    if (tabSource) tabSource.disconnect();
  } catch {}

  await safeCloseAudioContext();

  stopTracks(micStream);
  stopTracks(tabStream);

  micStream = null;
  tabStream = null;
  audioCtx = null;

  micSource = null;
  tabSource = null;

  micGainNode = null;
  silentGainNode = null;
  tabMonitorGainNode = null;

  micProcessor = null;
  tabProcessor = null;

  micParts = [];
  micLen = 0;
  tabParts = [];
  tabLen = 0;
}

async function initCapture(deviceId, tabStreamId, captureMode) {
  micParts = [];
  micLen = 0;
  tabParts = [];
  tabLen = 0;
  lastMicChunkAt = Date.now();
  lastTabChunkAt = Date.now();

  LOCAL_COMMITTED_TRANSCRIPT = "";
  LOCAL_LIVE_TRANSCRIPT = "";
  LOCAL_LAST_PROTOCOL = "🧾 ПРОТОКОЛ ВСТРЕЧИ\n\n(Слушаю...)";
  LOCAL_LAST_LIVE = "Пока нет подсказок.";

  CURRENT_RUN_ID += 1;
  HAS_FINALIZED_CURRENT_RUN = false;

  audioCtx = new (window.AudioContext || window.webkitAudioContext)({
    latencyHint: "interactive"
  });

  if (audioCtx.state !== "running") {
    try {
      await audioCtx.resume();
    } catch (e) {
      err("audioCtx resume failed:", e);
    }
  }

  silentGainNode = audioCtx.createGain();
  silentGainNode.gain.value = 0.0;
  silentGainNode.connect(audioCtx.destination);

  tabMonitorGainNode = audioCtx.createGain();
  tabMonitorGainNode.gain.value = 1.0;
  tabMonitorGainNode.connect(audioCtx.destination);

  if (captureMode === "mic" || captureMode === "tab_mic") {
    const micAudioConstraints =
      captureMode === "tab_mic"
        ? {
            deviceId:
              deviceId && deviceId !== "default"
                ? { exact: deviceId }
                : undefined,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: false,
            channelCount: { ideal: 1 }
          }
        : {
            deviceId:
              deviceId && deviceId !== "default"
                ? { exact: deviceId }
                : undefined,
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false,
            channelCount: { ideal: 1 }
          };

    try {
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: micAudioConstraints,
        video: false
      });

      micSource = audioCtx.createMediaStreamSource(micStream);
    } catch (e) {
      warn("Mic capture failed:", e);
      micSource = null;
    }
  }

  if (captureMode === "tab_mic") {
    if (!tabStreamId) {
      warn("No tabStreamId received");
    } else {
      try {
        tabStream = await navigator.mediaDevices.getUserMedia({
          audio: {
            mandatory: {
              chromeMediaSource: "tab",
              chromeMediaSourceId: tabStreamId
            }
          },
          video: false
        });

        tabSource = audioCtx.createMediaStreamSource(tabStream);
      } catch (e) {
        warn("Tab capture failed:", e);
        tabSource = null;
      }
    }
  }

  if (!micSource && !tabSource) {
    throw new Error("Не удалось захватить ни микрофон, ни звук вкладки.");
  }

  const myRunId = CURRENT_RUN_ID;

  if (micSource) {
    micGainNode = audioCtx.createGain();
    micGainNode.gain.value = micGain;

    micProcessor = audioCtx.createScriptProcessor(2048, 1, 1);
    micProcessor.onaudioprocess = (e) => {
      if (!isRunning || isStopping) return;
      if (!audioCtx || audioCtx.state !== "running") return;
      if (myRunId !== CURRENT_RUN_ID) return;
      if (HAS_FINALIZED_CURRENT_RUN) return;

      const input = e.inputBuffer.getChannelData(0);
      const boosted = new Float32Array(input.length);

      for (let i = 0; i < input.length; i++) {
        let v = input[i] * micGain;
        if (v > 1) v = 1;
        if (v < -1) v = -1;
        boosted[i] = v;
      }

      sendLevel(boosted);

      const down = downsampleBuffer(boosted, audioCtx.sampleRate, 16000);
      const pcm16 = floatTo16BitPCM(down);

      appendPart("mic", pcm16);
      flushIfNeeded("mic", false);
    };

    micSource.connect(micGainNode);
    micGainNode.connect(micProcessor);
    micProcessor.connect(silentGainNode || audioCtx.destination);
  }

  if (tabSource) {
    tabProcessor = audioCtx.createScriptProcessor(2048, 1, 1);
    tabProcessor.onaudioprocess = (e) => {
      if (!isRunning || isStopping) return;
      if (!audioCtx || audioCtx.state !== "running") return;
      if (myRunId !== CURRENT_RUN_ID) return;
      if (HAS_FINALIZED_CURRENT_RUN) return;

      const input = e.inputBuffer.getChannelData(0);
      const down = downsampleBuffer(input, audioCtx.sampleRate, 16000);
      const pcm16 = floatTo16BitPCM(down);

      appendPart("tab", pcm16);
      flushIfNeeded("tab", false);
    };

    tabSource.connect(tabProcessor);
    tabProcessor.connect(silentGainNode || audioCtx.destination);

    try {
      tabSource.connect(tabMonitorGainNode || audioCtx.destination);
    } catch (e) {
      warn("tab monitor connect failed:", e);
    }
  }
}

async function startCapture({
  backendUrl,
  deviceToken,
  captureMode,
  meetingTitle,
  deviceId,
  tabStreamId,
  micGain: nextMicGain
}) {
  if (isRunning || isStopping) {
    throw new Error("Запись уже запущена.");
  }

  BACKEND_BASE_URL = String(backendUrl || "").replace(/\/$/, "");
  DEVICE_TOKEN = deviceToken || "";
  CAPTURE_MODE = captureMode || "mic";
  MEETING_TITLE = meetingTitle || "";
  micGain = Number.isFinite(Number(nextMicGain))
    ? Math.max(0.2, Math.min(6.0, Number(nextMicGain)))
    : 1.8;

  STOP_REASON = "";
  STREAM_SESSION_ID = null;
  STREAM_QUEUE = [];
  STREAM_UPLOADING = false;
  STREAM_FLUSH_PROMISE = null;

  if (!BACKEND_BASE_URL) throw new Error("Не задан backend URL");
  if (!DEVICE_TOKEN) throw new Error("Не задан device token");

  try {
    await initCapture(deviceId || "default", tabStreamId || null, CAPTURE_MODE);

    isRunning = true;
    isStopping = false;

    await sendPatchToWorker({
      isRecording: true,
      streamSessionId: null,
      captureMode: CAPTURE_MODE,
      lastError: "",
      lastTranscript: "",
      committedTranscript: "",
      liveTranscriptPreview: "",
      lastProtocol: "🧾 ПРОТОКОЛ ВСТРЕЧИ\n\n(Слушаю...)",
      lastLive: "Пока нет подсказок.",
      LAST_TRANSCRIPT: "",
      LAST_PROTOCOL: "🧾 ПРОТОКОЛ ВСТРЕЧИ\n\n(Слушаю...)",
      LAST_LIVE: "Пока нет подсказок.",
      lastFinishedMeeting: null
    });

    chrome.runtime.sendMessage({ action: "OFFSCREEN_STARTED" }, () => {
      if (chrome.runtime.lastError) {}
    });

    dbg("recording started");
  } catch (e) {
    isRunning = false;
    isStopping = false;
    await resetMediaState();
    STREAM_SESSION_ID = null;
    STREAM_QUEUE = [];
    STREAM_UPLOADING = false;
    STREAM_FLUSH_PROMISE = null;
    await sendPatchToWorker({ streamSessionId: null });
    throw e;
  }
}

async function stopAndFinalize(reason = "") {
  if ((!isRunning && !isStopping) || isStopping) {
    dbg("stopAndFinalize ignored");
    return;
  }

  isStopping = true;
  STOP_REASON = reason || STOP_REASON || "";

  dbg("stopAndFinalize begin", { reason: STOP_REASON });

  try {
    flushIfNeeded("mic", true);
  } catch (e) {
    warn("flush mic on stop failed:", e);
  }

  try {
    flushIfNeeded("tab", true);
  } catch (e) {
    warn("flush tab on stop failed:", e);
  }

  isRunning = false;

  await resetMediaState();

  try {
    await flushQueue();
  } catch (e) {
    err("flushQueue during stop failed:", e);
    await sendPatchToWorker({ lastError: errToStr(e) });
  }

  try {
    await finishStream();
  } catch (e) {
    err("finishStream failed:", e);
    await sendPatchToWorker({ lastError: errToStr(e) });
  }

  await sendPatchToWorker({
    isRecording: false,
    captureMode: "mic",
    streamSessionId: null
  });

  isStopping = false;

  chrome.runtime.sendMessage({ action: "OFFSCREEN_STOPPED" }, () => {
    if (chrome.runtime.lastError) {
      warn("OFFSCREEN_STOPPED send error:", chrome.runtime.lastError.message);
    }
  });

  dbg("stopAndFinalize end");
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const validActions = ["OFFSCREEN_START", "OFFSCREEN_STOP", "SET_MIC_GAIN"];
  if (!msg || !validActions.includes(msg.action)) return false;

  (async () => {
    try {
      if (msg.action === "OFFSCREEN_START") {
        await startCapture({
          backendUrl: msg.backendUrl,
          deviceToken: msg.deviceToken,
          captureMode: msg.captureMode || "mic",
          meetingTitle: msg.meetingTitle || "",
          deviceId: msg.deviceId || "default",
          tabStreamId: msg.tabStreamId || null,
          micGain: msg.micGain
        });

        sendResponse({ ok: true });
        return;
      }

      if (msg.action === "OFFSCREEN_STOP") {
        await stopAndFinalize(msg.reason || "");
        sendResponse({ ok: true });
        return;
      }

      if (msg.action === "SET_MIC_GAIN") {
        const v = Number(msg.value);
        micGain = Number.isFinite(v) ? Math.max(0.2, Math.min(6.0, v)) : 1.8;

        if (micGainNode) {
          micGainNode.gain.value = micGain;
        }

        dbg("micGain =", micGain);
        sendResponse({ ok: true, micGain });
        return;
      }

      sendResponse({ ok: false, error: "Unknown action" });
    } catch (e) {
      err("runtime handler failed:", e);

      await sendPatchToWorker({
        isRecording: false,
        lastError: e?.message || String(e),
        captureMode: "mic"
      });

      chrome.runtime.sendMessage(
        {
          action: "OFFSCREEN_ERROR",
          error: e?.message || String(e)
        },
        () => {}
      );

      sendResponse({ ok: false, error: e?.message || String(e) });
    }
  })();

  return true;
});
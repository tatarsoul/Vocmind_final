const statusEl = document.getElementById("status");
const btn = document.getElementById("grantBtn");

function setStatus(msg) {
  statusEl.textContent = msg;
}

btn.addEventListener("click", async () => {
  btn.disabled = true;
  try {
    setStatus("Запрашиваю доступ к микрофону…");
    const s = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    s.getTracks().forEach(t => t.stop());
    await chrome.storage.local.set({ micGranted: true, lastError: "" });
    setStatus("✅ Доступ к микрофону выдан. Можно закрыть вкладку.");
  } catch (e) {
    console.error("getUserMedia (permissions page) failed:", e);
    await chrome.storage.local.set({ micGranted: false, lastError: e?.message || String(e) });
    setStatus("❌ Ошибка: " + (e?.name ? e.name + ": " : "") + (e?.message || String(e)));
  } finally {
    btn.disabled = false;
  }
});

// Auto-attempt once on open (helps when user expects immediate prompt)
(async () => {
  try {
    const s = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    s.getTracks().forEach(t => t.stop());
    await chrome.storage.local.set({ micGranted: true, lastError: "" });
    setStatus("✅ Доступ уже выдан. Можно закрыть вкладку и вернуться в popup.");
  } catch (e) {
    // Don't spam; user can click the button.
    setStatus("Нажми «Разрешить микрофон» чтобы показать промпт.");
  }
})();

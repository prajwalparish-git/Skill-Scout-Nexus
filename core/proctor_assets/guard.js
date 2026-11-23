const KEEP = new WeakMap();
const CLEAR = new Set(["TAB_HIDDEN", "WINDOW_BLUR", "FULLSCREEN_EXIT"]);

function luma(video, canvas) {
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx || video.readyState < 2) return null;
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  const d = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
  let sum = 0;
  for (let i = 0; i < d.length; i += 4) sum += 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
  return { mean: sum / (d.length / 4), data: d };
}

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const $ = (s) => parentElement.querySelector(s);
  let k = KEEP.get(parentElement);
  if (!k) {
    k = { stream: null, note: "", asked: false, listening: false, queue: [], last: {}, undo: [], timers: [] };
    KEEP.set(parentElement, k);
  }
  const video = $("video");
  const canvas = $("canvas");

  const askCamera = () => {
    if (k.asked) return;
    k.asked = true;
    const done = (stream, note) => {
      if (k.stream || (k.note && !stream)) return;
      k.stream = stream; k.note = note || "";
      if (stream) { video.srcObject = stream; video.play().catch(() => {}); }
      else { video.hidden = true; const p = $(".nocam"); p.hidden = false;
        p.textContent = "No camera (" + k.note + "). Camera checks will be skipped and noted for review; the test still runs."; }
      $(".start").disabled = !$(".agree").checked;
    };
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return done(null, "no camera support in this browser");
    navigator.mediaDevices.getUserMedia({ video: { width: 320, height: 240 }, audio: false })
      .then((s) => done(s, ""))
      .catch((e) => done(null, e && e.name === "NotAllowedError" ? "camera permission denied" : "no camera found"));
    k.timers.push(setTimeout(() => { if (!k.stream && !k.note) done(null, "camera permission not answered"); }, 8000));
  };

  const flush = () => {
    if (!k.queue.length) return;
    setTriggerValue("events", k.queue.splice(0, 50));
  };
  const report = (kind, durationS) => {
    const now = performance.now();
    if (now - (k.last[kind] || -1e9) < (kind === "PASTE_BLOCKED" ? 10000 : 1500)) return;
    k.last[kind] = now;
    const elapsed = (now - k.base) / 1000;
    const at = durationS ? Math.max(0, elapsed - durationS) : elapsed;
    k.queue.push({ kind, at_s: Math.round(at * 10) / 10, duration_s: durationS ? Math.round(durationS) : null });
    clearTimeout(k.flushTimer);
    k.flushTimer = setTimeout(flush, CLEAR.has(kind) ? 0 : 1500);
  };

  const listen = () => {
    if (k.listening) return;
    k.listening = true;
    k.base = performance.now() - (data.elapsed_s || 0) * 1000;
    const on = (t, type, fn) => { t.addEventListener(type, fn, true); k.undo.push(() => t.removeEventListener(type, fn, true)); };
    on(document, "visibilitychange", () => { if (document.visibilityState === "hidden") report("TAB_HIDDEN"); });
    on(window, "blur", () => {
      clearTimeout(k.blur);
      // focus inside the page's own embedded frames keeps document.hasFocus() true: not a strike
      k.blur = setTimeout(() => { if (!document.hasFocus() && document.visibilityState === "visible") report("WINDOW_BLUR"); }, 2000);
    });
    on(window, "focus", () => clearTimeout(k.blur));
    on(document, "fullscreenchange", () => {
      const lost = !document.fullscreenElement;
      $(".back").hidden = !lost;
      if (lost) report("FULLSCREEN_EXIT");
    });
    const block = (e) => { e.preventDefault(); if (e.type === "paste") report("PASTE_BLOCKED"); };
    ["copy", "cut", "paste", "contextmenu", "dragstart", "drop"].forEach((t) => on(document, t, block));
    if (k.stream) {
      let dark = null, still = 0, prev = null, lostSent = false;
      const lost = () => { if (!lostSent) { lostSent = true; report("CAMERA_LOST"); } };
      k.stream.getVideoTracks().forEach((t) => t.addEventListener("ended", lost));
      k.timers.push(setInterval(() => {
        const r = luma(video, canvas);
        if (!r) return;
        const now = performance.now();
        if (r.mean < 40) dark ??= now;
        else if (dark !== null) { const s = (now - dark) / 1000; if (s >= 10) report("LOW_LIGHT", s); dark = null; }
        if (prev) {
          let diff = 0;
          for (let i = 0; i < r.data.length; i += 4) diff += Math.abs(r.data[i] - prev[i]);
          still = diff / (r.data.length / 4) < 0.4 ? still + 2 : 0;
          if (still >= 10) lost();
        }
        prev = new Uint8ClampedArray(r.data);
      }, 2000));
    }
  };

  const pre = $(".pre"), run = $(".run");
  if (data.mode === "precheck") {
    pre.hidden = false; run.hidden = true;
    $(".consent").textContent = data.consent_text;
    askCamera();
    $(".agree").onchange = (e) => { $(".start").disabled = !e.target.checked || (!k.stream && !k.note); };
    $(".start").onclick = () => {
      document.documentElement.requestFullscreen?.().catch(() => {});
      $(".start").disabled = true;
      setTriggerValue("start", { camera: k.stream ? "on" : "unavailable", note: k.note });
    };
    if (!k.lightTimer) k.lightTimer = setInterval(() => {
      const r = luma(video, canvas);
      if (r) $(".light").textContent = r.mean < 40 ? "Lighting: too dark. Face a window or turn on a light (a hint; you can start anyway)." : "Lighting: fine.";
    }, 800);
  } else {
    pre.hidden = true; run.hidden = false;
    if (k.lightTimer) { clearInterval(k.lightTimer); k.lightTimer = null; }
    listen();
    $(".state").textContent = "Proctored · strikes " + data.strikes + " of " + data.max;
    $(".camnote").textContent = k.stream ? "Camera checked on this device only" : "Camera checks skipped" + (k.note ? ": " + k.note : "");
    $(".back").onclick = () => document.documentElement.requestFullscreen?.().catch(() => {});
    if (!data.camera_on && k.stream) { k.stream.getTracks().forEach((t) => t.stop()); k.stream = null; }
  }

  return () => {
    flush();
    k.undo.forEach((u) => u());
    k.timers.forEach((t) => { clearInterval(t); clearTimeout(t); });
    if (k.lightTimer) clearInterval(k.lightTimer);
    if (k.stream) k.stream.getTracks().forEach((t) => t.stop());
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    KEEP.delete(parentElement);
  };
}

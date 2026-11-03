/* Browser-only capture and bounded uploads. No speech service or client API keys. */
"use strict";
window.SuperChatMedia = {
  createVAD(started, {threshold = .018, silenceMs = 1500, maxMs = 30000} = {}) {
    let last = started, lastVoice = started, speechMs = 0;
    return {
      get heard() { return speechMs >= 200; },
      update(rms, now) {
        if (rms >= threshold) { speechMs += Math.min(200, now - last); lastVoice = now; }
        last = now;
        return now - started >= maxMs || (speechMs >= 200 ? now - lastVoice >= silenceMs : now - started >= 7000);
      }
    };
  },
  wav(buffer) {
    const rate = 16000, count = Math.floor(buffer.duration * rate);
    const bytes = new ArrayBuffer(44 + count * 2), view = new DataView(bytes);
    const write = (at, text) => [...text].forEach((c, i) => view.setUint8(at + i, c.charCodeAt(0)));
    write(0, "RIFF"); view.setUint32(4, 36 + count * 2, true); write(8, "WAVEfmt ");
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true);
    view.setUint16(34, 16, true); write(36, "data"); view.setUint32(40, count * 2, true);
    const channels = Array.from({length: buffer.numberOfChannels}, (_, i) => buffer.getChannelData(i));
    for (let i = 0; i < count; i++) {
      const at = Math.min(buffer.length - 1, Math.floor(i * buffer.sampleRate / rate));
      const sample = Math.max(-1, Math.min(1, channels.reduce((n, c) => n + c[at], 0) / channels.length));
      view.setInt16(44 + i * 2, sample * (sample < 0 ? 32768 : 32767), true);
    }
    return new Blob([bytes], {type: "audio/wav"});
  }
};

window.SuperChatBonuses = (() => {
  const $ = id => document.getElementById(id), composer = window.SuperChatComposer;
  if (!$("image-button")) return {};
  const strings = {
    image: ["Identifying product…", "Məhsul müəyyənləşdirilir…", "Определяем товар…"],
    review: ["Review the suggested product, then search for similar offers.", "Təklif olunan məhsulu yoxlayıb oxşar təklifləri axtarın.", "Проверьте распознанный товар и найдите похожие предложения."],
    uncertain: ["The image is uncertain. Confirm or enter a product name before searching.", "Şəkil aydın deyil. Axtarışdan əvvəl məhsul adını təsdiqləyin və ya yazın.", "Товар распознан неуверенно. Уточните название перед поиском."],
    permission: ["Allow microphone access to start recording.", "Yazıya başlamaq üçün mikrofona icazə verin.", "Разрешите доступ к микрофону для записи."],
    listening: ["Listening… pauses stop recording automatically (30s maximum).", "Dinlənilir… fasilə zamanı yazı dayanır (maksimum 30 san).", "Слушаем… запись остановится после паузы (максимум 30 с)."],
    transcribing: ["Transcribing your recording…", "Səsiniz mətnə çevrilir…", "Распознаём вашу запись…"],
    transcript: ["Recognized text is in the message box. Edit it, then press Send.", "Tanınan mətn mesaj xanasındadır. Düzəldib Göndər düyməsini basın.", "Распознанный текст в поле сообщения. Отредактируйте и нажмите Отправить."],
    silence: ["No clear speech detected. Try again or type your message.", "Aydın nitq aşkarlanmadı. Yenidən cəhd edin və ya yazın.", "Чёткая речь не обнаружена. Повторите или введите сообщение."],
    denied: ["Microphone permission was denied. Allow it in browser settings or type instead.", "Mikrofona icazə verilmədi. Brauzer ayarlarından icazə verin və ya yazın.", "Доступ к микрофону запрещён. Разрешите его в настройках браузера или введите текст."],
    device: ["Microphone unavailable or in use. Check your device and try again.", "Mikrofon əlçatan deyil və ya istifadə olunur. Cihazı yoxlayıb yenidən cəhd edin.", "Микрофон недоступен или занят. Проверьте устройство и повторите."],
    unsupported: ["Microphone recording is unavailable. Use HTTPS and a supported browser.", "Səs yazısı əlçatan deyil. HTTPS və uyğun brauzerdən istifadə edin.", "Запись недоступна. Используйте HTTPS и поддерживаемый браузер."],
    format: ["Choose a JPEG, PNG or WebP image up to 4 MB.", "4 MB-a qədər JPEG, PNG və ya WebP şəkli seçin.", "Выберите JPEG, PNG или WebP размером до 4 МБ."],
    failed: ["Media processing failed. Try again or type your search.", "Media emalı alınmadı. Yenidən cəhd edin və ya axtarışı yazın.", "Не удалось обработать файл. Повторите или введите запрос."],
    timeout: ["Processing timed out. Try a shorter recording or a smaller image.", "Emal vaxtı bitdi. Daha qısa səs və ya kiçik şəkillə cəhd edin.", "Время обработки истекло. Используйте более короткую запись или небольшое изображение."],
    key: ["Gemini media is not configured on this server. Text search is available.", "Bu serverdə Gemini media konfiqurasiya edilməyib. Mətnlə axtarış işləyir.", "Gemini для файлов не настроен на сервере. Текстовый поиск доступен."],
    limited: ["Too many requests. Wait a moment and try again.", "Sorğu limiti aşılıb. Bir az gözləyib yenidən cəhd edin.", "Слишком много запросов. Подождите и повторите."],
    provider: ["Visual search requires the BuyWhere shopping provider.", "Şəkillə axtarış üçün BuyWhere provayderi lazımdır.", "Для поиска по фото нужен провайдер BuyWhere."]
  };
  let operation = null, allowed = composer.available, lastStatus = null, identification = null;
  const tr = key => strings[key][{en: 0, az: 1, ru: 2}[window.SuperChatUI.language] ?? 0];
  function status(key, error = false) {
    lastStatus = key; $("media-feedback").textContent = tr(key); $("media-feedback").hidden = false;
    $("media-feedback").classList.toggle("media-error", error);
  }
  function refresh() {
    $("image-button").disabled = !allowed || !!operation;
    $("voice-button").disabled = !allowed || (!!operation && !["recording", "permission"].includes(operation.phase));
    const recording = operation?.phase === "recording";
    $("voice-button").classList.toggle("recording", recording);
    $("voice-button").setAttribute("aria-pressed", String(recording));
    const label = recording ? "Stop recording" : "Voice input";
    $("voice-button").dataset.i18nAria = label;
    $("voice-button").setAttribute("aria-label", window.SuperChatUI.translate(label));
    $("voice-button").title = window.SuperChatUI.translate(label);
    $("visual-search").disabled = !allowed || !!operation || !$("visual-query").value.trim();
  }
  function cleanup(op) {
    clearInterval(op.timer); op.stream?.getTracks().forEach(t => t.stop());
    op.source?.disconnect(); op.analyser?.disconnect();
  }
  function finish(op) {
    cleanup(op); if (op.audio && op.audio.state !== "closed") op.audio.close().catch(() => {});
    if (operation !== op) return;
    operation = null; composer.lock(false); $("media-cancel").hidden = $("visual-review").hidden; refresh();
  }
  function begin(phase) {
    const op = {phase, context: composer.context, controller: new AbortController()};
    operation = op; composer.lock(true); $("visual-review").hidden = true;
    $("media-cancel").hidden = false; refresh(); return op;
  }
  function showFailure(error) {
    status(["NotAllowedError", "SecurityError"].includes(error.name) ? "denied" : ["NotFoundError", "NotReadableError"].includes(error.name) ? "device" : error.name === "AbortError" ? "timeout" :
      error.code === "gemini_not_configured" ? "key" : error.status === 429 ? "limited" :
      error.status === 413 || error.status === 415 ? "format" : error.status === 504 || error.status === 408 ? "timeout" :
      error.code === "visual_requires_buywhere" ? "provider" : "failed", true);
  }
  async function post(path, blob, op) {
    const timer = setTimeout(() => op.controller.abort(), 30000);
    try {
      const scope = op.context.sessionId ? "?session_id=" + encodeURIComponent(op.context.sessionId) : "";
      const response = await fetch(path + scope, {method: "POST", credentials: "same-origin", body: blob,
        headers: {"Content-Type": blob.type}, signal: op.controller.signal});
      const body = await response.json();
      if (!response.ok) { const error = new Error("Media request failed"); error.status = response.status; error.code = body.detail; throw error; }
      return body;
    } finally { clearTimeout(timer); }
  }
  function cancel() {
    const op = operation;
    if (op) {
      op.cancelled = true; op.controller.abort();
      if (op.recorder?.state === "recording") op.recorder.stop();
      finish(op);
    }
    $("visual-review").hidden = true; $("visual-preview").removeAttribute("src");
    $("media-feedback").hidden = true; $("media-cancel").hidden = true; identification = null;
  }
  $("media-cancel").addEventListener("click", cancel);
  $("image-button").addEventListener("click", () => { if (composer.available) $("image-upload").click(); });
  $("image-upload").addEventListener("change", async event => {
    const file = event.target.files[0]; event.target.value = "";
    if (!file || !composer.available) return;
    if (!/^(image\/jpeg|image\/png|image\/webp)$/.test(file.type) || file.size > 4 * 1024 * 1024) { status("format", true); return; }
    const op = begin("image"); status("image");
    try {
      const preview = new FileReader();
      preview.onload = () => { if (operation === op) $("visual-preview").src = preview.result; };
      preview.readAsDataURL(file);
      const result = await post("/api/shopping/visual", file, op);
      if (op.cancelled || composer.context.id !== op.context.id) return;
      identification = result;
      $("visual-query").value = result.identifiable ? result.query : "";
      $("visual-attributes").textContent = [result.product_type, result.brand, ...result.attributes].filter(Boolean).join(" · ");
      $("visual-confidence").textContent = window.SuperChatUI.translate("AI confidence") + ": " + Math.round(result.confidence * 100) + "%";
      $("visual-review").dataset.context = op.context.id;
      $("visual-review").hidden = false; status(result.status === "ready" ? "review" : "uncertain");
    } catch (error) { if (!op.cancelled) showFailure(error); }
    finally { finish(op); }
  });
  $("visual-query").addEventListener("input", refresh);
  $("visual-query").addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); $("visual-search").click(); } });
  $("visual-search").addEventListener("click", () => {
    if (!composer.available || !$("visual-query").value.trim()) return;
    const query = $("visual-query").value.trim(), id = $("visual-review").dataset.context;
    cancel(); composer.search(query, id);
  });
  function microphone(signal) {
    return new Promise((resolve, reject) => {
      let settled = false;
      const timer = setTimeout(() => fail(new DOMException("Permission timeout", "AbortError")), 15000);
      function fail(error) { if (!settled) { settled = true; clearTimeout(timer); reject(error); } }
      signal.addEventListener("abort", () => fail(new DOMException("Cancelled", "AbortError")), {once: true});
      navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true}, video: false}).then(stream => {
        if (settled || signal.aborted) { stream.getTracks().forEach(t => t.stop()); return; }
        settled = true; clearTimeout(timer); resolve(stream);
      }, fail);
    });
  }
  async function recorded(op) {
    cleanup(op);
    if (op.cancelled) { finish(op); return; }
    if (!op.vad.heard) { status("silence", true); finish(op); return; }
    op.phase = "transcribing"; refresh(); status("transcribing");
    try {
      let blob = new Blob(op.chunks, {type: op.recorder.mimeType});
      if (!/^(audio\/webm|audio\/ogg)(;|$)/.test(blob.type)) blob = window.SuperChatMedia.wav(await op.audio.decodeAudioData(await blob.arrayBuffer()));
      const result = await post("/api/media/transcribe", blob, op);
      if (op.cancelled || composer.context.id !== op.context.id) return;
      finish(op);
      if (result.speech_detected && result.text) { composer.draft(result.text, op.context.id, result.language); status("transcript"); }
      else status("silence", true);
    } catch (error) { if (!op.cancelled) showFailure(error); }
    finally { finish(op); }
  }
  $("voice-button").addEventListener("click", async () => {
    if (operation) {
      if (operation.recorder?.state === "recording") operation.recorder.stop();
      else if (operation.phase === "permission") cancel();
      return;
    }
    if (!composer.available) return;
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder || !Audio || !window.isSecureContext) { status("unsupported", true); return; }
    const op = begin("permission"); status("permission");
    try {
      // Start Web Audio during the user's click, including on Safari/iOS.
      op.audio = new Audio();
      const resumed = op.audio.resume().then(() => true, () => false);
      op.stream = await microphone(op.controller.signal);
      if (op.cancelled) { finish(op); return; }
      let timer;
      const audioReady = await Promise.race([resumed, new Promise(resolve => { timer = setTimeout(() => resolve(false), 3000); })]);
      clearTimeout(timer);
      if (!audioReady) throw new Error("Audio capture unavailable");
      op.source = op.audio.createMediaStreamSource(op.stream); op.analyser = op.audio.createAnalyser();
      op.analyser.fftSize = 1024; op.source.connect(op.analyser);
      const mime = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"].find(type => MediaRecorder.isTypeSupported(type));
      op.recorder = new MediaRecorder(op.stream, mime ? {mimeType: mime, audioBitsPerSecond: 64000} : {});
      op.chunks = []; op.vad = window.SuperChatMedia.createVAD(performance.now());
      op.recorder.ondataavailable = event => { if (event.data.size) op.chunks.push(event.data); };
      op.recorder.onstop = () => recorded(op);
      op.recorder.onerror = () => { op.cancelled = true; showFailure(new Error("Recording failed")); finish(op); };
      op.recorder.start(250); op.phase = "recording"; status("listening"); refresh();
      const samples = new Float32Array(op.analyser.fftSize);
      op.timer = setInterval(() => {
        if (op.recorder.state !== "recording") return;
        op.analyser.getFloatTimeDomainData(samples);
        const rms = Math.sqrt(samples.reduce((sum, value) => sum + value * value, 0) / samples.length);
        if (op.vad.update(rms, performance.now())) op.recorder.stop();
      }, 100);
    } catch (error) { if (!op.cancelled) showFailure(error); finish(op); }
  });
  window.addEventListener("pagehide", cancel);
  document.addEventListener("visibilitychange", () => { if (document.hidden && operation?.phase === "recording") cancel(); });
  $("page-language").addEventListener("change", () => {
    if (lastStatus && !$("media-feedback").hidden) $("media-feedback").textContent = tr(lastStatus);
    if (identification) $("visual-confidence").textContent = window.SuperChatUI.translate("AI confidence") + ": " + Math.round(identification.confidence * 100) + "%";
    refresh();
  });
  refresh();
  return {setAvailability(value) { allowed = value; refresh(); },
    contextChanged(id) { if (!$("visual-review").hidden && $("visual-review").dataset.context !== id) cancel(); }};
})();

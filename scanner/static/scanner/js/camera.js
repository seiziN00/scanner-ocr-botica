/* FarmaScan · captura con cámara (móvil).
 * Máximo N fotos, vista previa, eliminar/repetir, subida multipart a Django.
 * Las imágenes NUNCA salen del navegador hacia el LLM: solo hacia Django.
 */
(function () {
  "use strict";

  const card = document.getElementById("captureCard");
  if (!card) return;

  const MAX = parseInt(card.dataset.maxImages || "4", 10);
  const PROCESS_URL = card.dataset.processUrl;

  const video = document.getElementById("videoFeed");
  const canvas = document.getElementById("captureCanvas");
  const idle = document.getElementById("cameraIdle");
  const idleMsg = document.getElementById("cameraMessage");
  const frame = document.getElementById("cameraFrame");
  const shutterBar = document.getElementById("shutterBar");
  const thumbs = document.getElementById("thumbs");
  const btnStart = document.getElementById("btnStartCam");
  const btnGallery = document.getElementById("btnGallery");
  const fileInput = document.getElementById("fileInput");
  const btnShutter = document.getElementById("btnShutter");
  const btnStopCam = document.getElementById("btnStopCam");
  const btnProcess = document.getElementById("btnProcess");
  const photoCounter = document.getElementById("photoCounter");
  const shutterCount = document.getElementById("shutterCount");
  const processingBox = document.getElementById("processingBox");

  let stream = null;
  let captures = []; // {blob, url}
  let sending = false;

  /* ---------------- cámara ---------------- */
  async function startCamera() {
    idleMsg.textContent = "Solicitando permiso de cámara…";
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" },
        audio: false,
      });
    } catch (err) {
      stream = null;
      if (err && (err.name === "NotAllowedError" || err.name === "SecurityError")) {
        idleMsg.textContent =
          "No diste permiso a la cámara. Habilítalo en el navegador o usa «Subir desde galería».";
      } else {
        idleMsg.textContent =
          "No se pudo abrir la cámara de este equipo. Puedes usar «Subir desde galería».";
      }
      return;
    }
    video.srcObject = stream;
    video.hidden = false;
    frame.hidden = false;
    idle.hidden = true;
    shutterBar.hidden = false;
    updateUI();
  }

  function stopCamera() {
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
    }
    video.hidden = true;
    frame.hidden = true;
    shutterBar.hidden = true;
    idle.hidden = false;
    idleMsg.textContent =
      captures.length >= MAX
        ? "Ya tienes las " + MAX + " fotos. Procesa el comprobante o elimina alguna."
        : "Cámara apagada. Puedes seguir tomando fotos o subir desde la galería.";
  }

  /* ---------------- captura ---------------- */
  function addCapture(blob) {
    if (captures.length >= MAX) {
      FarmaScan.toast("Máximo " + MAX + " fotos por comprobante", "warn");
      return;
    }
    captures.push({ blob: blob, url: URL.createObjectURL(blob) });
    if (captures.length >= MAX) stopCamera();
    updateUI();
  }

  function capturePhoto() {
    if (!stream || captures.length >= MAX) return;
    const vw = video.videoWidth, vh = video.videoHeight;
    if (!vw || !vh) return;
    const scale = Math.min(1, 1600 / Math.max(vw, vh));
    canvas.width = Math.round(vw * scale);
    canvas.height = Math.round(vh * scale);
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    FarmaScan.flash();
    canvas.toBlob(
      (blob) => {
        if (blob) addCapture(blob);
        else FarmaScan.toast("No se pudo tomar la foto, inténtalo de nuevo", "err");
      },
      "image/jpeg",
      0.82
    );
  }

  function removeCapture(index) {
    const [removed] = captures.splice(index, 1);
    if (removed) URL.revokeObjectURL(removed.url);
    updateUI();
  }

  /* ---------------- UI ---------------- */
  function updateUI() {
    const n = captures.length;
    photoCounter.textContent = n + " de " + MAX + " fotos";
    shutterCount.textContent = n + "/" + MAX;
    btnShutter.disabled = n >= MAX;

    thumbs.hidden = n === 0;
    thumbs.innerHTML = "";
    captures.forEach((c, i) => {
      const fig = document.createElement("div");
      fig.className = "thumb";
      const img = document.createElement("img");
      img.src = c.url;
      img.alt = "Foto " + (i + 1);
      const del = document.createElement("button");
      del.type = "button";
      del.className = "del";
      del.textContent = "✕";
      del.setAttribute("aria-label", "Eliminar foto " + (i + 1));
      del.addEventListener("click", () => removeCapture(i));
      const num = document.createElement("span");
      num.className = "num";
      num.textContent = i + 1;
      fig.append(img, del, num);
      thumbs.appendChild(fig);
    });
    if (n > 0 && n < MAX) {
      const slot = document.createElement("div");
      slot.className = "thumb slot";
      slot.textContent = "+" + (MAX - n) + " disp.";
      thumbs.appendChild(slot);
    }

    btnProcess.disabled = n === 0 || sending;
    btnProcess.textContent =
      n === 0
        ? "Procesar comprobante"
        : "Procesar " + n + (n === 1 ? " foto" : " fotos");
  }

  /* ---------------- envío ---------------- */
  async function processCaptures() {
    if (!captures.length || sending) return;
    sending = true;
    updateUI();
    processingBox.hidden = false;
    processingBox.scrollIntoView({ behavior: "smooth", block: "center" });

    const formData = new FormData();
    captures.forEach((c, i) =>
      formData.append("images", c.blob, "foto-" + (i + 1) + ".jpg")
    );

    try {
      const resp = await fetch(PROCESS_URL, {
        method: "POST",
        headers: { "X-CSRFToken": FarmaScan.csrfToken() },
        body: formData,
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.ok && data.ok && data.session_url) {
        try {
          localStorage.setItem("farmascan_session", data.session_url);
        } catch (e) {}
        window.location.href = data.session_url;
        return;
      }
      FarmaScan.toast(
        data.error || "No se pudo procesar el comprobante. Inténtalo otra vez.",
        "err"
      );
    } catch (err) {
      FarmaScan.toast(
        "Falló la conexión con el servidor. Revisa tu internet e inténtalo otra vez.",
        "err"
      );
    }
    sending = false;
    processingBox.hidden = true;
    updateUI();
  }

  /* ---------------- eventos ---------------- */
  btnStart.addEventListener("click", startCamera);
  btnShutter.addEventListener("click", capturePhoto);
  btnStopCam.addEventListener("click", stopCamera);
  btnProcess.addEventListener("click", processCaptures);
  btnGallery.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    Array.from(fileInput.files || [])
      .slice(0, MAX - captures.length)
      .forEach((f) => {
        if (f.type.startsWith("image/")) addCapture(f);
      });
    fileInput.value = "";
  });
  window.addEventListener("pagehide", stopCamera);

  /* ofrecer volver a la última sesión del navegador */
  try {
    const last = localStorage.getItem("farmascan_session");
    if (last) {
      const hint = document.getElementById("resumeHint");
      const link = document.getElementById("resumeLink");
      if (hint && link) {
        link.href = last;
        hint.hidden = false;
      }
    }
  } catch (e) {}

  updateUI();
})();

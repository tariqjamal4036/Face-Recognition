(() => {
  const video = document.getElementById("camera-video");
  const canvas = document.getElementById("camera-overlay");
  const context = canvas.getContext("2d");
  const placeholder = document.getElementById("camera-placeholder");
  const start = document.getElementById("start-camera");
  const stop = document.getElementById("stop-camera");
  const result = document.getElementById("recognition-result");
  const panel = document.querySelector(".recognized-panel");
  let stream = null;
  let timer = null;
  let busy = false;
  let lastStudent = null;
  let stillImage = null;

  function displayFace(face) {
    panel.classList.remove("recognized");
    void panel.offsetWidth;
    panel.classList.add("recognized");
    const student = face.student;
    if (!student) {
      result.className = "recognition-result empty-result";
      result.innerHTML = '<span class="result-avatar"><i class="fa-solid fa-user-secret"></i></span><b>Unknown person</b><small>Snapshot saved for review. Please verify manually.</small>';
      document.getElementById("result-indicator").className = "result-indicator";
      lastStudent = null;
      return;
    }
    result.className = "recognition-result";
    const photo = student.photo_url ? `<img src="${window.escapeHtml(student.photo_url)}" alt="">` : '<i class="fa-solid fa-user"></i>';
    result.innerHTML = `<span class="result-avatar">${photo}</span><b>${window.escapeHtml(student.name)}</b><span class="pill"><span class="status-pulse"></span> MATCH SCORE ${window.escapeHtml(face.confidence)}%</span><div class="student-details"><div><small>REGISTRATION NO.</small><b>${window.escapeHtml(student.registration_no || "Not provided")}</b></div><div><small>ROOM</small><b>${window.escapeHtml(student.room_no || "Not provided")}</b></div><div><small>DEPARTMENT</small><b>${window.escapeHtml(student.department || "Not provided")}</b></div><div><small>PHONE</small><b>${window.escapeHtml(student.phone || "Not provided")}</b></div><div><small>GUARDIAN</small><b>${window.escapeHtml(student.guardian_contact || "Not provided")}</b></div></div>`;
    document.getElementById("result-indicator").className = "live-dot";
    if (lastStudent !== student.id) {
      window.showToast(`${student.name} recognized — attendance recorded.`, "success");
      lastStudent = student.id;
    }
  }

  function drawBoxes(faces, width, height) {
    canvas.width = width;
    canvas.height = height;
    context.clearRect(0, 0, width, height);
    for (const face of faces) {
      const [top, right, bottom, left] = face.box;
      context.strokeStyle = face.student ? "#57e7be" : "#ffad70";
      context.lineWidth = Math.max(2, width / 400);
      context.shadowColor = context.strokeStyle;
      context.shadowBlur = 13;
      context.strokeRect(left, top, right - left, bottom - top);
      context.shadowBlur = 0;
      context.font = `${Math.max(14, width / 42)}px DM Sans`;
      context.fillStyle = context.strokeStyle;
      context.fillText(face.student?.name || "Unknown", left, Math.max(20, top - 8));
    }
  }

  async function processImage(imageData, sourceWidth, sourceHeight) {
    if (busy) return;
    busy = true;
    try {
      const data = await window.apiFetch("/api/recognize", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ image: imageData }) });
      drawBoxes(data.faces, sourceWidth, sourceHeight);
      if (data.faces.length) displayFace(data.faces[0]);
    } catch (error) {
      window.showToast(error.message, "error");
      stopCamera();
    } finally {
      busy = false;
    }
  }

  async function captureFrame() {
    if (video.readyState < 2) return;
    const capture = document.createElement("canvas");
    capture.width = Math.min(video.videoWidth, 800);
    capture.height = Math.round(video.videoHeight * capture.width / video.videoWidth);
    capture.getContext("2d").drawImage(video, 0, 0, capture.width, capture.height);
    await processImage(capture.toDataURL("image/jpeg", .82), capture.width, capture.height);
  }

  async function startCamera() {
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" }, audio: false });
      video.srcObject = stream;
      stillImage?.remove();
      stillImage = null;
      video.classList.add("active");
      placeholder.classList.add("hidden");
      start.disabled = true;
      stop.disabled = false;
      timer = window.setInterval(captureFrame, 1800);
    } catch (error) {
      window.showToast(`Could not start camera: ${error.message}`, "error");
    }
  }

  function stopCamera() {
    if (timer) window.clearInterval(timer);
    timer = null;
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
    video.srcObject = null;
    video.classList.remove("active");
    stillImage?.remove();
    stillImage = null;
    context.clearRect(0, 0, canvas.width, canvas.height);
    placeholder.classList.remove("hidden");
    start.disabled = false;
    stop.disabled = true;
  }

  start.addEventListener("click", startCamera);
  stop.addEventListener("click", stopCamera);
  window.addEventListener("pagehide", stopCamera);
  document.getElementById("recognition-upload").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    const image = new Image();
    image.onload = async () => {
      const imageCanvas = document.createElement("canvas");
      imageCanvas.width = Math.min(image.naturalWidth, 800);
      imageCanvas.height = Math.round(image.naturalHeight * imageCanvas.width / image.naturalWidth);
      imageCanvas.getContext("2d").drawImage(image, 0, 0, imageCanvas.width, imageCanvas.height);
      placeholder.classList.add("hidden");
      video.classList.remove("active");
      stillImage?.remove();
      stillImage = document.createElement("img");
      stillImage.className = "camera-still";
      stillImage.alt = "Image being checked for a face";
      stillImage.src = image.src;
      document.getElementById("camera-frame").insertBefore(stillImage, canvas);
      await processImage(imageCanvas.toDataURL("image/jpeg", .86), imageCanvas.width, imageCanvas.height);
      URL.revokeObjectURL(image.src);
    };
    image.src = URL.createObjectURL(file);
    event.target.value = "";
  });
})();

(() => {
  const form = document.getElementById("add-student-form");
  const photoInput = document.getElementById("student-photo");
  const preview = document.getElementById("photo-preview");
  const previewImage = document.getElementById("photo-preview-image");
  const photoName = document.getElementById("photo-name");
  const captureWrap = document.getElementById("capture-wrap");
  const video = document.getElementById("capture-video");
  let cameraStream = null;
  let objectUrl = null;

  function showPhoto(file) {
    if (!file) return;
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(file);
    previewImage.src = objectUrl;
    photoName.textContent = file.name;
    preview.classList.remove("hidden");
  }
  photoInput.addEventListener("change", () => showPhoto(photoInput.files[0]));
  document.getElementById("clear-photo").addEventListener("click", () => {
    photoInput.value = "";
    preview.classList.add("hidden");
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  });
  document.getElementById("capture-photo").addEventListener("click", async () => {
    try {
      cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" }, audio: false });
      video.srcObject = cameraStream;
      captureWrap.classList.remove("hidden");
    } catch (error) {
      window.showToast(`Could not start camera: ${error.message}`, "error");
    }
  });
  document.getElementById("take-photo").addEventListener("click", () => {
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);
    canvas.toBlob((blob) => {
      if (!blob) {
        window.showToast("Could not capture photo.", "error");
        return;
      }
      const file = new File([blob], `student-${Date.now()}.jpg`, { type: "image/jpeg" });
      const transfer = new DataTransfer();
      transfer.items.add(file);
      photoInput.files = transfer.files;
      showPhoto(file);
      cameraStream?.getTracks().forEach((track) => track.stop());
      cameraStream = null;
      captureWrap.classList.add("hidden");
    }, "image/jpeg", .9);
  });
  window.addEventListener("pagehide", () => cameraStream?.getTracks().forEach((track) => track.stop()));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!photoInput.files.length) {
      window.showToast("Add or capture a face photo before saving.", "error");
      return;
    }
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    submit.innerHTML = '<span class="spinner"></span> Saving…';
    try {
      const result = await window.apiFetch("/api/students", { method: "POST", body: new FormData(form) });
      const warning = result.training?.issues?.length ? " Student saved, but encoding needs review." : " Face encoding is ready.";
      window.showToast(`${result.student.name} added.${warning}`, result.training?.issues?.length ? "error" : "success");
      window.location.assign("/students");
    } catch (error) {
      window.showToast(error.message, "error");
      submit.disabled = false;
      submit.innerHTML = '<i class="fa-solid fa-user-plus"></i> Save student';
    }
  });
})();

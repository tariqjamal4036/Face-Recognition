(() => {
  const date = document.getElementById("today-label");
  if (date) date.textContent = new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric" }).format(new Date());

  const toggle = document.getElementById("theme-toggle");
  const applyTheme = (light) => {
    document.body.classList.toggle("light-theme", light);
    if (toggle) toggle.innerHTML = light ? '<i class="fa-regular fa-moon"></i>' : '<i class="fa-regular fa-sun"></i>';
  };
  applyTheme(localStorage.getItem("hostel-theme") === "light");
  toggle?.addEventListener("click", () => {
    const light = !document.body.classList.contains("light-theme");
    localStorage.setItem("hostel-theme", light ? "light" : "dark");
    applyTheme(light);
  });

  document.querySelector(".mobile-menu")?.addEventListener("click", () => document.querySelector(".sidebar")?.classList.toggle("open"));

  window.showToast = (message, type = "success") => {
    const region = document.getElementById("toast-region");
    if (!region) return;
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = message;
    region.append(toast);
    window.setTimeout(() => toast.remove(), 3800);
  };
  window.escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  window.apiFetch = async (url, options = {}) => {
    const headers = new Headers(options.headers || {});
    headers.set("X-CSRF-Token", document.querySelector('meta[name="csrf-token"]')?.content || "");
    const response = await fetch(url, { ...options, headers });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
    return result;
  };
  document.querySelectorAll("[data-retrain]").forEach((button) => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      const oldText = button.innerHTML;
      button.innerHTML = '<span class="spinner"></span> Refreshing…';
      try {
        const result = await window.apiFetch("/api/retrain", { method: "POST" });
        const warning = result.issues?.length ? ` ${result.issues.length} photo issue(s) need attention.` : "";
        window.showToast(`${result.encoded} face encoding(s) refreshed.${warning}`, result.issues?.length ? "error" : "success");
        window.dispatchEvent(new CustomEvent("encodings-refreshed", { detail: result }));
      } catch (error) {
        window.showToast(error.message, "error");
      } finally {
        button.disabled = false;
        button.innerHTML = oldText;
      }
    });
  });
})();

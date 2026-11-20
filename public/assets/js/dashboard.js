(() => {
  const counter = (element, value) => {
    const target = Number(value || 0);
    const start = performance.now();
    const duration = 700;
    const tick = (now) => {
      const progress = Math.min((now - start) / duration, 1);
      element.textContent = String(Math.round(target * (1 - Math.pow(1 - progress, 3))));
      if (progress < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  };

  const relativeTime = (value) => {
    if (!value) return "";
    const seconds = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
    if (seconds < 60) return "just now";
    if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} hr ago`;
    return `${Math.floor(seconds / 86400)} days ago`;
  };
  const localDate = (value) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;

  async function loadDashboard() {
    const data = await window.apiFetch("/api/dashboard");
    document.querySelectorAll("[data-counter]").forEach((element) => counter(element, data[element.dataset.counter]));
    const list = document.getElementById("activity-list");
    if (data.activities.length) {
      list.innerHTML = data.activities.map((item) => `<div class="activity-item"><span class="activity-icon"><i class="fa-solid fa-bolt"></i></span><div><b>${window.escapeHtml(item.label)}</b><small>Hostel Vision activity</small></div><time class="activity-time">${window.escapeHtml(relativeTime(item.created_at))}</time></div>`).join("");
    } else {
      list.innerHTML = '<p class="muted">No activity yet. Start recognition to record attendance.</p>';
    }

    const quality = [...(data.data_quality?.unmatched_photos || []).map((name) => `Unmatched photo: ${name}`), ...(data.data_quality?.missing_photos || []).map((name) => `Missing photo for ${name}`), ...(data.data_quality?.duplicates || []).map((name) => `Duplicate row: ${name}`), ...(data.encoding_issues || [])];
    const warning = document.getElementById("quality-warning");
    if (quality.length) {
      warning.classList.remove("hidden");
      warning.innerHTML = `<b><i class="fa-solid fa-triangle-exclamation"></i> Data quality needs review</b><ul>${quality.map((item) => `<li>${window.escapeHtml(item)}</li>`).join("")}</ul><p>Registration number, room, department, and guardian contact were not present in the source dataset.</p>`;
    }

    const trend = new Map(data.attendance_trend.map((item) => [item.attendance_date, item.count]));
    const labels = Array.from({ length: 7 }, (_, index) => {
      const day = new Date();
      day.setDate(day.getDate() - 6 + index);
      return localDate(day);
    });
    const canvas = document.getElementById("attendance-chart");
    if (canvas && window.Chart) {
      const context = canvas.getContext("2d");
      const gradient = context.createLinearGradient(0, 0, 0, 220);
      gradient.addColorStop(0, "rgba(89, 221, 226, .28)");
      gradient.addColorStop(1, "rgba(89, 221, 226, 0)");
      new Chart(canvas, {
        type: "line",
        data: { labels: labels.map((value) => new Date(`${value}T12:00:00`).toLocaleDateString(undefined, { weekday: "short" })), datasets: [{ data: labels.map((value) => trend.get(value) || 0), fill: true, backgroundColor: gradient, borderColor: "#62dce5", borderWidth: 2, tension: .38, pointRadius: 3, pointBackgroundColor: "#8998ff" }] },
        options: { maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { displayColors: false } }, scales: { x: { grid: { display: false }, ticks: { color: "#8793ae", font: { size: 10 } } }, y: { beginAtZero: true, ticks: { precision: 0, color: "#8793ae", font: { size: 10 } }, grid: { color: "rgba(135,147,174,.1)" } } } }
      });
    }
  }
  loadDashboard().catch((error) => window.showToast(error.message, "error"));
})();

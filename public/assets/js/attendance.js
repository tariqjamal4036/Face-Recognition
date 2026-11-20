(() => {
  const dateInput = document.getElementById("attendance-date");
  const rows = document.getElementById("attendance-rows");
  const exportLink = document.getElementById("export-attendance");
  const printLink = document.getElementById("print-attendance");
  const now = new Date();
  dateInput.value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  printLink.addEventListener("click", (event) => {
    event.preventDefault();
    window.print();
  });

  async function loadAttendance() {
    const selected = dateInput.value;
    exportLink.href = `/api/attendance/export.csv?date=${encodeURIComponent(selected)}`;
    const records = await window.apiFetch(`/api/attendance?date=${encodeURIComponent(selected)}`);
    document.getElementById("attendance-count").textContent = `${records.length} check-in${records.length === 1 ? "" : "s"}`;
    rows.innerHTML = records.length ? records.map((record) => {
      const photo = record.photo_url ? `<img class="student-photo" src="${window.escapeHtml(record.photo_url)}" alt="">` : '<span class="student-placeholder"><i class="fa-solid fa-user"></i></span>';
      return `<tr><td><a class="student-cell" href="/students/${record.student_id}">${photo}<b>${window.escapeHtml(record.name)}</b></a></td><td>${window.escapeHtml(record.registration_no || "—")}</td><td>${window.escapeHtml(record.room_no || "—")}</td><td>${window.escapeHtml(record.department || "—")}</td><td>${window.escapeHtml(record.attendance_time)}</td><td><span class="encoding-ok"><i class="fa-solid fa-check"></i> Present</span></td></tr>`;
    }).join("") : '<tr><td class="table-empty" colspan="6">No attendance records for this date.</td></tr>';
  }
  dateInput.addEventListener("change", () => loadAttendance().catch((error) => window.showToast(error.message, "error")));
  loadAttendance().catch((error) => window.showToast(error.message, "error"));
})();

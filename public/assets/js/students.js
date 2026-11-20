(() => {
  const rows = document.getElementById("student-rows");
  const search = document.getElementById("student-search");
  const department = document.getElementById("department-filter");
  const dialog = document.getElementById("edit-student-dialog");
  const form = document.getElementById("edit-student-form");
  let students = [];
  let sortAscending = true;

  const render = () => {
    const query = search.value.trim().toLocaleLowerCase();
    const selectedDepartment = department.value;
    const filtered = students.filter((student) => {
      const text = [student.name, student.registration_no, student.room_no, student.department, student.phone].join(" ").toLocaleLowerCase();
      return text.includes(query) && (!selectedDepartment || student.department === selectedDepartment);
    });
    document.getElementById("student-count").textContent = `${filtered.length} student${filtered.length === 1 ? "" : "s"}`;
    rows.innerHTML = filtered.length ? filtered.map((student) => {
      const photo = student.photo_url ? `<img class="student-photo" src="${window.escapeHtml(student.photo_url)}" alt="">` : '<span class="student-placeholder"><i class="fa-solid fa-user"></i></span>';
      const encoded = student.encoding_available ? '<span class="encoding-ok"><i class="fa-solid fa-check"></i> Ready</span>' : '<span class="encoding-missing">No encoding</span>';
      return `<tr><td><a class="student-cell" href="/students/${student.id}">${photo}<span><b>${window.escapeHtml(student.name)}</b><small>Profile & attendance</small></span></a></td><td>${window.escapeHtml(student.registration_no || "—")}</td><td>${window.escapeHtml(student.room_no || "—")}</td><td>${window.escapeHtml(student.department || "—")}</td><td>${window.escapeHtml(student.phone || "—")}</td><td>${encoded}</td><td><div class="table-actions"><button class="icon-button edit-button" data-id="${student.id}" aria-label="Edit ${window.escapeHtml(student.name)}"><i class="fa-solid fa-pen"></i></button><button class="icon-button delete-button" data-id="${student.id}" aria-label="Delete ${window.escapeHtml(student.name)}"><i class="fa-regular fa-trash-can"></i></button></div></td></tr>`;
    }).join("") : '<tr><td class="table-empty" colspan="7">No students match your search.</td></tr>';
  };

  async function loadStudents() {
    students = await window.apiFetch("/api/students");
    const departments = [...new Set(students.map((student) => student.department).filter(Boolean))].sort();
    department.innerHTML = '<option value="">All departments</option>' + departments.map((item) => `<option>${window.escapeHtml(item)}</option>`).join("");
    render();
  }

  search.addEventListener("input", render);
  department.addEventListener("change", render);
  document.querySelector("[data-sort='name']").addEventListener("click", () => {
    students.sort((left, right) => left.name.localeCompare(right.name) * (sortAscending ? 1 : -1));
    sortAscending = !sortAscending;
    render();
  });
  rows.addEventListener("click", async (event) => {
    const edit = event.target.closest(".edit-button");
    const remove = event.target.closest(".delete-button");
    if (edit) {
      const student = students.find((item) => item.id === Number(edit.dataset.id));
      form.dataset.studentId = student.id;
      for (const [key, value] of Object.entries(student)) {
        const input = form.elements.namedItem(key);
        if (input && input.type !== "file") input.value = value || "";
      }
      form.elements.photo.value = "";
      dialog.showModal();
    }
    if (remove) {
      const student = students.find((item) => item.id === Number(remove.dataset.id));
      if (!window.confirm(`Remove ${student.name} from the student database? Their photo file will be kept.`)) return;
      try {
        await window.apiFetch(`/api/students/${student.id}`, { method: "DELETE" });
        window.showToast(`${student.name} removed from records.`);
        await loadStudents();
      } catch (error) {
        window.showToast(error.message, "error");
      }
    }
  });
  document.querySelectorAll("[data-close-dialog]").forEach((button) => button.addEventListener("click", () => dialog.close()));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const result = await window.apiFetch(`/api/students/${form.dataset.studentId}`, { method: "PUT", body: new FormData(form) });
      dialog.close();
      window.showToast(`Updated ${result.student.name}.`);
      await loadStudents();
    } catch (error) {
      window.showToast(error.message, "error");
    }
  });
  loadStudents().catch((error) => window.showToast(error.message, "error"));
})();

const schema = [
  "Line",
  "Booking No.",
  "Equipment",
  "Vessel Name",
  "Voyage No.",
  "Port of Loading",
  "Port of Discharge",
  "Final Dest.",
  "ETS POL / Sailing Date",
  "ETA POD / Arrival Date",
  "SI & VGM Cut Off (Calculated)",
  "Assigning Cut Off (Calculated)",
  "Gate In Cut Off (Calculated)",
];

let currentUser = null;
let rows = [];
let users = [];

const $ = (id) => document.getElementById(id);

function showLoader(show) {
  $("loader").classList.toggle("hidden", !show);
}

function toast(message, isError = false) {
  const el = $("toast");
  el.textContent = message;
  el.classList.toggle("error", isError);
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 3600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "include",
    headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}

function show(view) {
  ["loginView", "dashboardView"].forEach((id) => $(id).classList.add("hidden"));
  $(view).classList.remove("hidden");
}

function openModal(id) {
  $(id).classList.remove("hidden");
}

function closeModal(id) {
  $(id).classList.add("hidden");
}

function setUser(user) {
  currentUser = user;
  $("userBar").classList.remove("hidden");
  $("userIdentity").textContent = `${user.name || user.username} / ${user.role.toUpperCase()}`;
  $("adminTab").classList.toggle("hidden", !user.isAdmin);
  $("uploadLimitNote").textContent = user.isAdmin
    ? "Admin access: batch upload limit is unrestricted."
    : `Upload limit: ${user.uploadLimit} PDFs per extraction.`;
}

function renderTable() {
  $("resultHead").innerHTML = `<tr>${schema.map((h) => `<th>${headerLabel(h)}</th>`).join("")}</tr>`;
  $("resultBody").innerHTML = rows
    .map((row) => `<tr>${schema.map((h) => `<td class="${cellClass(h, row[h])}">${escapeHtml(row[h] || "")}</td>`).join("")}</tr>`)
    .join("");
  $("copyAllBtn").disabled = rows.length === 0;
  $("downloadCsvBtn").disabled = rows.length === 0;
  renderEmailCards();
}

function headerLabel(label) {
  const labels = {
    "SI & VGM Cut Off (Calculated)": ["SI & VGM Cut Off", "Calculated"],
    "Assigning Cut Off (Calculated)": ["Assigning Cut Off", "Calculated"],
    "Gate In Cut Off (Calculated)": ["Gate In Cut Off", "Calculated"],
    "ETS POL / Sailing Date": ["ETS POL", "Sailing Date"],
    "ETA POD / Arrival Date": ["ETA POD", "Arrival Date"],
  };
  if (!labels[label]) return escapeHtml(label);
  const [main, sub] = labels[label];
  return `${escapeHtml(main)}<span class="th-sub">${escapeHtml(sub)}</span>`;
}

function cellClass(label, value) {
  const classes = [];
  if (label === "Line") classes.push("cell-line");
  if (label.includes("Cut Off")) classes.push("cell-cut");
  if (String(value || "").toUpperCase() === "N/A") classes.push("cell-na");
  return classes.join(" ");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function rowValue(row, label) {
  return row[label] || "";
}

const emailFields = [
  ["Booking Number", (row) => rowValue(row, "Booking No.")],
  ["Equipment", (row) => rowValue(row, "Equipment")],
  ["Vessel Name", (row) => rowValue(row, "Vessel Name")],
  ["Voyage Number", (row) => rowValue(row, "Voyage No.")],
  ["Port of Loading", (row) => rowValue(row, "Port of Loading")],
  ["Port of Discharge", (row) => rowValue(row, "Port of Discharge")],
  ["Final Destination (if any)", (row) => rowValue(row, "Final Dest.") || "N/A"],
  ["ETS POL", (row) => rowValue(row, "ETS POL / Sailing Date")],
  ["ETA POD", (row) => rowValue(row, "ETA POD / Arrival Date")],
  ["SI & VGM Cut Off", (row) => rowValue(row, "SI & VGM Cut Off (Calculated)"), true],
  ["Container Assigning Cut Off", (row) => rowValue(row, "Assigning Cut Off (Calculated)"), true],
  ["Container Gate In Cut Off", (row) => rowValue(row, "Gate In Cut Off (Calculated)"), true],
];

function buildEmailTable(row) {
  const body = emailFields
    .map(([label, getter]) => {
      const value = escapeHtml(getter(row) || "");
      return `<tr>
        <td style="border:1px solid #000;padding:6px 12px;font-family:Arial,sans-serif;font-size:13px;font-weight:bold;background:#f5f5f5;white-space:nowrap;">${escapeHtml(label)}</td>
        <td style="border:1px solid #000;padding:6px 12px;font-family:Arial,sans-serif;font-size:13px;background:#ffffff;min-width:180px;">${value}</td>
      </tr>`;
    })
    .join("");
  return `<table style="border-collapse:collapse;border:1px solid #000;">${body}</table>`;
}

async function copyHtml(html) {
  if (window.ClipboardItem && navigator.clipboard?.write) {
    const htmlBlob = new Blob([html], { type: "text/html" });
    const textBlob = new Blob([html.replace(/<[^>]+>/g, " ")], { type: "text/plain" });
    await navigator.clipboard.write([new ClipboardItem({ "text/html": htmlBlob, "text/plain": textBlob })]);
    return;
  }
  const el = document.createElement("div");
  el.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0;";
  el.innerHTML = html;
  document.body.appendChild(el);
  const range = document.createRange();
  range.selectNodeContents(el);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  document.execCommand("copy");
  selection.removeAllRanges();
  document.body.removeChild(el);
}

function renderEmailCards() {
  const section = $("emailSection");
  const grid = $("emailGrid");
  if (!rows.length) {
    section.classList.add("hidden");
    grid.innerHTML = "";
    return;
  }
  section.classList.remove("hidden");
  grid.innerHTML = rows
    .map((row, index) => {
      const bookingNo = rowValue(row, "Booking No.") || "-";
      const line = rowValue(row, "Line");
      const tableRows = emailFields
        .map(([label, getter, isCut]) => {
          const value = getter(row) || "-";
          const cls = `${isCut ? "ec-cut" : ""} ${String(value).toUpperCase() === "N/A" ? "ec-na" : ""}`.trim();
          return `<tr><td>${escapeHtml(label)}</td><td class="${cls}">${escapeHtml(value)}</td></tr>`;
        })
        .join("");
      return `
        <div class="email-card">
          <div class="ec-head">
            <span class="ec-bkno">${escapeHtml(bookingNo)}</span>
            <span class="ec-line">${escapeHtml(line)}</span>
          </div>
          <table class="ec-table">${tableRows}</table>
          <div class="ec-foot">
            <button class="email-action primary-mini" type="button" data-copy-email="${index}">Copy for Email</button>
            <button class="email-action" type="button" data-preview-email="${index}">Preview</button>
          </div>
        </div>`;
    })
    .join("");
}

async function bootstrap() {
  renderTable();
  try {
    const { user } = await api("/api/me");
    setUser(user);
    show("dashboardView");
  } catch {
    show("loginView");
  }
}

$("loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  showLoader(true);
  try {
    const { user } = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        identifier: $("loginIdentifier").value.trim().toLowerCase(),
        password: $("loginPassword").value,
      }),
    });
    $("loginPassword").value = "";
    setUser(user);
    show("dashboardView");
    toast("Signed in");
  } catch (error) {
    toast(error.message, true);
  } finally {
    showLoader(false);
  }
});

$("logoutBtn").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" });
  location.reload();
});

$("changePasswordBtn").addEventListener("click", () => openModal("changePasswordModal"));

$("changePasswordForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify({
        currentPassword: $("currentPassword").value,
        newPassword: $("newPassword").value,
      }),
    });
    $("changePasswordForm").reset();
    closeModal("changePasswordModal");
    toast("Password updated");
  } catch (error) {
    toast(error.message, true);
  }
});

$("uploadForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const files = Array.from($("pdfInput").files || []);
  if (!files.length) return toast("Choose at least one PDF", true);
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  showLoader(true);
  try {
    const data = await api("/api/extract", { method: "POST", body: formData });
    rows = data.rows || [];
    renderTable();
    toast(`Extracted ${rows.length} PDF${rows.length === 1 ? "" : "s"}`);
  } catch (error) {
    toast(error.message, true);
  } finally {
    showLoader(false);
  }
});

$("downloadCsvBtn").addEventListener("click", () => {
  if (!rows.length) return;
  const csv = [schema.join(","), ...rows.map((row) => schema.map((h) => csvCell(row[h] || "")).join(","))].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `movanta-bookings-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
});

$("copyAllBtn").addEventListener("click", async () => {
  if (!rows.length) return;
  const headers = [
    "Line",
    "Booking No.",
    "Equipment",
    "Vessel Name",
    "Voyage No.",
    "Port of Loading",
    "Port of Discharge",
    "Final Destination",
    "ETS POL",
    "ETA POD",
    "SI & VGM Cut Off",
    "Container Assigning Cut Off",
    "Container Gate In Cut Off",
  ];
  const values = rows.map((row) =>
    [
      rowValue(row, "Line"),
      rowValue(row, "Booking No."),
      rowValue(row, "Equipment"),
      rowValue(row, "Vessel Name"),
      rowValue(row, "Voyage No."),
      rowValue(row, "Port of Loading"),
      rowValue(row, "Port of Discharge"),
      rowValue(row, "Final Dest.") || "N/A",
      rowValue(row, "ETS POL / Sailing Date"),
      rowValue(row, "ETA POD / Arrival Date"),
      rowValue(row, "SI & VGM Cut Off (Calculated)"),
      rowValue(row, "Assigning Cut Off (Calculated)"),
      rowValue(row, "Gate In Cut Off (Calculated)"),
    ].join("\t")
  );
  await navigator.clipboard.writeText([headers.join("\t"), ...values].join("\n"));
  toast("Table copied");
});

function csvCell(value) {
  const text = String(value).replaceAll('"', '""');
  return /[",\n]/.test(text) ? `"${text}"` : text;
}

$("emailGrid").addEventListener("click", async (event) => {
  const copyButton = event.target.closest("[data-copy-email]");
  const previewButton = event.target.closest("[data-preview-email]");
  const button = copyButton || previewButton;
  if (!button) return;

  const row = rows[Number(button.dataset.copyEmail ?? button.dataset.previewEmail)];
  if (!row) return;
  const html = buildEmailTable(row);

  if (copyButton) {
    try {
      await copyHtml(html);
      toast("Copied for email");
    } catch {
      toast("Copy failed. Use Preview.", true);
    }
    return;
  }

  $("modalPreview").innerHTML = html;
  $("modalTitle").textContent = `Booking ${rowValue(row, "Booking No.") || "-"}`;
  openModal("emailCopyModal");
  $("modalCopyBtn").onclick = async () => {
    try {
      await copyHtml(html);
      closeModal("emailCopyModal");
      toast("Copied");
    } catch {
      toast("Copy failed", true);
    }
  };
});

$("dashboardTab").addEventListener("click", () => setTab("dashboard"));
$("adminTab").addEventListener("click", async () => {
  setTab("admin");
  await loadUsers();
});

function setTab(tab) {
  $("extractPanel").classList.toggle("hidden", tab !== "dashboard");
  $("adminPanel").classList.toggle("hidden", tab !== "admin");
  $("dashboardTab").classList.toggle("active", tab === "dashboard");
  $("adminTab").classList.toggle("active", tab === "admin");
}

async function loadUsers() {
  try {
    const data = await api("/api/admin/users");
    users = data.users || [];
    renderUsers();
  } catch (error) {
    toast(error.message, true);
  }
}

function renderUsers() {
  $("userList").innerHTML = users
    .map((user) => {
      const created = user.createdAt ? new Date(user.createdAt).toLocaleDateString() : "-";
      const status = user.isDeleted ? "Deleted" : user.isActive ? "Active" : "Disabled";
      return `
        <tr>
          <td>
            <strong>${escapeHtml(user.name || "-")}</strong>
            <span>${escapeHtml(user.email)}</span>
            <small>@${escapeHtml(user.username)}</small>
          </td>
          <td>${escapeHtml(user.role)}</td>
          <td>${escapeHtml(user.uploadLimit)}</td>
          <td><span class="status-pill ${status.toLowerCase()}">${status}</span></td>
          <td>${created}</td>
          <td>
            <div class="action-row">
              <button class="ghost-btn" data-edit-user="${user.id}" type="button">Edit</button>
              <button class="ghost-btn" data-reset-user="${user.id}" type="button">Reset</button>
              <button class="ghost-btn danger" data-delete-user="${user.id}" type="button">Delete</button>
            </div>
          </td>
        </tr>`;
    })
    .join("");
}

$("openCreateUserBtn").addEventListener("click", () => openModal("createUserModal"));

$("createUserForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const data = await api("/api/admin/users", {
      method: "POST",
      body: JSON.stringify({
        name: $("newUserName").value.trim(),
        email: $("newUserEmail").value.trim().toLowerCase(),
        username: $("newUsername").value.trim().toLowerCase(),
        role: $("newUserRole").value,
        uploadLimit: Number($("newUserUploadLimit").value),
      }),
    });
    $("createUserForm").reset();
    $("newUserUploadLimit").value = "25";
    closeModal("createUserModal");
    await loadUsers();
    showGeneratedPassword(data.generatedPassword, `Password for ${data.user.username}`);
  } catch (error) {
    toast(error.message, true);
  }
});

$("userList").addEventListener("click", async (event) => {
  const edit = event.target.closest("[data-edit-user]");
  const reset = event.target.closest("[data-reset-user]");
  const del = event.target.closest("[data-delete-user]");
  if (edit) {
    const user = users.find((item) => item.id === Number(edit.dataset.editUser));
    if (!user) return;
    $("editUserId").value = user.id;
    $("editUserName").value = user.name || "";
    $("editUserRole").value = user.role;
    $("editUserUploadLimit").value = user.uploadLimit;
    $("editUserActive").checked = user.isActive;
    openModal("editUserModal");
  }
  if (reset) {
    if (!confirm("Reset this user's password?")) return;
    try {
      const data = await api(`/api/admin/users/${reset.dataset.resetUser}/reset-password`, { method: "POST" });
      await loadUsers();
      showGeneratedPassword(data.generatedPassword, `Reset password for ${data.user.username}`);
    } catch (error) {
      toast(error.message, true);
    }
  }
  if (del) {
    if (!confirm("Delete this user?")) return;
    try {
      await api(`/api/admin/users/${del.dataset.deleteUser}`, { method: "DELETE" });
      await loadUsers();
      toast("User deleted");
    } catch (error) {
      toast(error.message, true);
    }
  }
});

$("editUserForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api(`/api/admin/users/${$("editUserId").value}`, {
      method: "PATCH",
      body: JSON.stringify({
        name: $("editUserName").value.trim(),
        role: $("editUserRole").value,
        uploadLimit: Number($("editUserUploadLimit").value),
        isActive: $("editUserActive").checked,
      }),
    });
    closeModal("editUserModal");
    await loadUsers();
    toast("User updated");
  } catch (error) {
    toast(error.message, true);
  }
});

function showGeneratedPassword(password, title) {
  $("passwordModalTitle").textContent = title;
  $("generatedPassword").textContent = password;
  openModal("passwordModal");
}

$("copyGeneratedPasswordBtn").addEventListener("click", async () => {
  await navigator.clipboard.writeText($("generatedPassword").textContent);
  toast("Password copied");
});

document.querySelectorAll("[data-close-modal]").forEach((button) => {
  button.addEventListener("click", () => closeModal(button.dataset.closeModal));
});

document.querySelectorAll(".modal-overlay").forEach((modal) => {
  modal.addEventListener("click", (event) => {
    if (event.target === modal) closeModal(modal.id);
  });
});

bootstrap();

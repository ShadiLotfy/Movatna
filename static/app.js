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
let loaderProgress = 0;
let loaderTimer = null;

const $ = (id) => document.getElementById(id);

function setLoaderProgress(value, label) {
  loaderProgress = Math.max(0, Math.min(100, Math.round(value)));
  const labelEl = $("loaderLabel");
  const percentEl = $("loaderPercent");
  const barEl = $("loaderBar");
  const shipEl = $("loaderShip");
  const trackEl = document.querySelector(".ship-track");
  if (label && labelEl) labelEl.textContent = label;
  if (percentEl) percentEl.textContent = `${loaderProgress}%`;
  if (barEl) barEl.style.transform = `scaleX(${loaderProgress / 100})`;
  if (shipEl && trackEl) {
    const travel = Math.max(0, trackEl.clientWidth - shipEl.clientWidth);
    shipEl.style.transform = `translateX(${Math.round((travel * loaderProgress) / 100)}px)`;
  }
}

function startLoaderDrift(limit = 92, label = "Processing") {
  window.clearInterval(loaderTimer);
  loaderTimer = window.setInterval(() => {
    if (loaderProgress >= limit) return;
    const step = loaderProgress < 65 ? 3 : 1;
    setLoaderProgress(Math.min(limit, loaderProgress + step), label);
  }, 420);
}

function showLoader(show, label = "Loading content") {
  const loader = $("loader");
  if (!loader) return;
  if (show) {
    window.clearInterval(loaderTimer);
    loader.classList.remove("hidden");
    setLoaderProgress(0, label);
    startLoaderDrift(88, label);
    return;
  }
  window.clearInterval(loaderTimer);
  setLoaderProgress(100, "Ready to explore");
  window.setTimeout(() => loader.classList.add("hidden"), 360);
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

function uploadExtraction(formData) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/extract");
    xhr.withCredentials = true;
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) return;
      setLoaderProgress(Math.min(68, (event.loaded / event.total) * 68), "Uploading PDFs");
    };
    xhr.onreadystatechange = () => {
      if (xhr.readyState === XMLHttpRequest.HEADERS_RECEIVED) {
        startLoaderDrift(94, "Processing PDFs");
      }
    };
    xhr.onload = () => {
      let data = {};
      try {
        data = JSON.parse(xhr.responseText || "{}");
      } catch {
        data = {};
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(data);
        return;
      }
      reject(new Error(data.error || "Request failed"));
    };
    xhr.onerror = () => reject(new Error("Network error while uploading PDFs"));
    xhr.ontimeout = () => reject(new Error("PDF processing timed out"));
    xhr.timeout = 180000;
    setLoaderProgress(4, "Preparing upload");
    xhr.send(formData);
  });
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
  const line = escapeHtml(rowValue(row, "Line") || "");
  const body = emailFields
    .map(([label, getter]) => {
      const value = escapeHtml(getter(row) || "");
      return `<tr>
        <td style="border:1px solid #000;padding:8px 14px;font-family:Arial,sans-serif;font-size:18px;font-weight:bold;background:#f1f1f1;width:58%;">${escapeHtml(label)}</td>
        <td style="border:1px solid #000;padding:8px 14px;font-family:Arial,sans-serif;font-size:18px;background:#ffffff;width:42%;">${value}</td>
      </tr>`;
    })
    .join("");
  return `<table style="border-collapse:collapse;border:1px solid #000;width:752px;max-width:100%;table-layout:fixed;">
    <tr>
      <th colspan="2" style="border:1px solid #000;padding:10px 14px;font-family:Arial,sans-serif;font-size:18px;font-weight:bold;text-align:center;background:#f1f1f1;">${line}</th>
    </tr>
    ${body}
  </table>`;
}

function buildEmailTables(selectedRows) {
  return selectedRows.map((row) => buildEmailTable(row)).join('<div style="height:16px;line-height:16px;">&nbsp;</div>');
}

function buildEmailPlainText(row) {
  const line = rowValue(row, "Line") || "";
  const fields = emailFields.map(([label, getter]) => `${label}\t${getter(row) || ""}`).join("\n");
  return `${line}\n${fields}`;
}

function buildEmailPlainTextList(selectedRows) {
  return selectedRows.map((row) => buildEmailPlainText(row)).join("\n\n");
}

async function copyHtml(html, text = "") {
  if (window.ClipboardItem && navigator.clipboard?.write) {
    const htmlBlob = new Blob([html], { type: "text/html" });
    const textBlob = new Blob([text || html.replace(/<[^>]+>/g, " ")], { type: "text/plain" });
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
  showLoader(true, "Loading content");
  renderTable();
  try {
    const { user } = await api("/api/me");
    setUser(user);
    show("dashboardView");
  } catch {
    show("loginView");
  } finally {
    showLoader(false);
  }
}

$("loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  showLoader(true, "Signing in");
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
  showLoader(true, "Signing out");
  try {
    await api("/api/auth/logout", { method: "POST" });
    location.reload();
  } catch (error) {
    showLoader(false);
    toast(error.message, true);
  }
});

$("changePasswordBtn").addEventListener("click", () => openModal("changePasswordModal"));

$("changePasswordForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  showLoader(true, "Updating password");
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
  } finally {
    showLoader(false);
  }
});

$("uploadForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const files = Array.from($("pdfInput").files || []);
  if (!files.length) return toast("Choose at least one PDF", true);
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  showLoader(true, "Preparing upload");
  try {
    const data = await uploadExtraction(formData);
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
  await copyHtml(buildEmailTables(rows), buildEmailPlainTextList(rows));
  toast("Email table copied");
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
      await copyHtml(html, buildEmailPlainText(row));
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
      await copyHtml(html, buildEmailPlainText(row));
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

async function loadUsers(showProgress = true) {
  if (showProgress) showLoader(true, "Loading users");
  try {
    const data = await api("/api/admin/users");
    users = data.users || [];
    renderUsers();
  } catch (error) {
    toast(error.message, true);
  } finally {
    if (showProgress) showLoader(false);
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
  showLoader(true, "Creating user");
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
    await loadUsers(false);
    showGeneratedPassword(data.generatedPassword, `Password for ${data.user.username}`);
  } catch (error) {
    toast(error.message, true);
  } finally {
    showLoader(false);
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
    showLoader(true, "Resetting password");
    try {
      const data = await api(`/api/admin/users/${reset.dataset.resetUser}/reset-password`, { method: "POST" });
      await loadUsers(false);
      showGeneratedPassword(data.generatedPassword, `Reset password for ${data.user.username}`);
    } catch (error) {
      toast(error.message, true);
    } finally {
      showLoader(false);
    }
  }
  if (del) {
    if (!confirm("Delete this user?")) return;
    showLoader(true, "Deleting user");
    try {
      await api(`/api/admin/users/${del.dataset.deleteUser}`, { method: "DELETE" });
      await loadUsers(false);
      toast("User deleted");
    } catch (error) {
      toast(error.message, true);
    } finally {
      showLoader(false);
    }
  }
});

$("editUserForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  showLoader(true, "Saving user");
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
    await loadUsers(false);
    toast("User updated");
  } catch (error) {
    toast(error.message, true);
  } finally {
    showLoader(false);
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

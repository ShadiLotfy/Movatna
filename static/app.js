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

let pendingEmail = "";
let rows = [];

const $ = (id) => document.getElementById(id);

function toast(message, isError = false) {
  const el = $("toast");
  el.textContent = message;
  el.classList.toggle("border-red-500", isError);
  el.classList.toggle("text-red-200", isError);
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 3500);
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
  ["loginView", "otpView", "dashboardView"].forEach((id) => $(id).classList.add("hidden"));
  $(view).classList.remove("hidden");
}

function setLoginMode(mode) {
  const isAdmin = mode === "admin";
  $("emailForm").classList.toggle("hidden", isAdmin);
  $("adminLoginForm").classList.toggle("hidden", !isAdmin);
  $("userLoginTab").classList.toggle("active", !isAdmin);
  $("adminLoginTab").classList.toggle("active", isAdmin);
  $("loginHelp").textContent = isAdmin
    ? "Admins sign in with email and password. Admin OTP login is disabled."
    : "Enter your authorized email to receive a one-time password.";
}

function setUser(user) {
  $("userBar").classList.remove("hidden");
  $("userBar").classList.add("flex");
  $("userEmail").textContent = user.email;
  $("adminTab").classList.toggle("hidden", !user.isAdmin);
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
  const cutLabels = {
    "SI & VGM Cut Off (Calculated)": ["SI & VGM Cut Off", "calculated"],
    "Assigning Cut Off (Calculated)": ["Assigning Cut Off", "calculated"],
    "Gate In Cut Off (Calculated)": ["Gate In Cut Off", "calculated"],
    "ETS POL / Sailing Date": ["ETS POL", "Sailing Date"],
    "ETA POD / Arrival Date": ["ETA POD", "Arrival Date"],
  };
  if (!cutLabels[label]) return escapeHtml(label);
  const [main, sub] = cutLabels[label];
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
            <button class="email-action bg-blue-600 font-semibold hover:bg-blue-500" type="button" data-copy-email="${index}">Copy for email</button>
            <button class="email-action border border-slate-700 hover:bg-slate-800" type="button" data-preview-email="${index}">Preview</button>
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

$("emailForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  pendingEmail = $("emailInput").value.trim().toLowerCase();
  try {
    await api("/api/auth/request-otp", {
      method: "POST",
      body: JSON.stringify({ email: pendingEmail }),
    });
    $("otpEmail").textContent = pendingEmail;
    show("otpView");
    toast("OTP sent");
  } catch (error) {
    toast(error.message, true);
  }
});

$("adminLoginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const { user } = await api("/api/auth/admin-login", {
      method: "POST",
      body: JSON.stringify({
        email: $("adminEmailInput").value.trim().toLowerCase(),
        password: $("adminPasswordInput").value,
      }),
    });
    $("adminPasswordInput").value = "";
    setUser(user);
    show("dashboardView");
    toast("Logged in");
  } catch (error) {
    toast(error.message, true);
  }
});

$("otpForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const { user } = await api("/api/auth/verify-otp", {
      method: "POST",
      body: JSON.stringify({ email: pendingEmail, otp: $("otpInput").value.trim() }),
    });
    setUser(user);
    show("dashboardView");
    toast("Logged in");
  } catch (error) {
    toast(error.message, true);
  }
});

$("userLoginTab").addEventListener("click", () => setLoginMode("user"));
$("adminLoginTab").addEventListener("click", () => setLoginMode("admin"));
$("backToEmail").addEventListener("click", () => show("loginView"));

$("logoutBtn").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" });
  location.reload();
});

$("uploadForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const files = Array.from($("pdfInput").files || []);
  if (!files.length) return toast("Choose at least one PDF", true);
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  try {
    const data = await api("/api/extract", { method: "POST", body: formData });
    rows = data.rows || [];
    renderTable();
    toast(`Extracted ${rows.length} PDF${rows.length === 1 ? "" : "s"}`);
  } catch (error) {
    toast(error.message, true);
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
      toast("Copied! Paste into Outlook or Gmail");
    } catch {
      toast("Copy failed. Use Preview to copy manually.", true);
    }
    return;
  }

  $("modalPreview").innerHTML = html;
  $("modalTitle").textContent = `Booking ${rowValue(row, "Booking No.") || "-"}`;
  $("modalOverlay").classList.add("show");
  $("modalCopyBtn").onclick = async () => {
    try {
      await copyHtml(html);
      $("modalOverlay").classList.remove("show");
      toast("Copied!");
    } catch {
      toast("Copy failed", true);
    }
  };
});

$("modalClose").addEventListener("click", () => $("modalOverlay").classList.remove("show"));
$("modalOverlay").addEventListener("click", (event) => {
  if (event.target === $("modalOverlay")) $("modalOverlay").classList.remove("show");
});

function csvCell(value) {
  const text = String(value).replaceAll('"', '""');
  return /[",\n]/.test(text) ? `"${text}"` : text;
}

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
    const { users } = await api("/api/admin/users");
    $("userList").innerHTML = users
      .map(
        (user) => `
          <div class="flex items-center justify-between gap-3 px-4 py-3">
            <div>
              <div class="font-medium">${escapeHtml(user.email)}</div>
              <div class="text-xs text-slate-500">${user.isAdmin ? "Admin" : "User"} · ${user.isActive ? "Active" : "Revoked"}</div>
            </div>
            ${user.isAdmin ? "" : `<button class="rounded-md border border-red-500/60 px-3 py-2 text-sm text-red-200 hover:bg-red-950" data-delete="${user.id}">Revoke</button>`}
          </div>
        `
      )
      .join("");
  } catch (error) {
    toast(error.message, true);
  }
}

$("addUserForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/admin/users", {
      method: "POST",
      body: JSON.stringify({ email: $("newUserEmail").value.trim().toLowerCase() }),
    });
    $("newUserEmail").value = "";
    await loadUsers();
    toast("User added");
  } catch (error) {
    toast(error.message, true);
  }
});

$("userList").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-delete]");
  if (!button) return;
  try {
    await api(`/api/admin/users/${button.dataset.delete}`, { method: "DELETE" });
    await loadUsers();
    toast("User revoked");
  } catch (error) {
    toast(error.message, true);
  }
});

bootstrap();

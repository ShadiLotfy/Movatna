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
  $("resultHead").innerHTML = `<tr>${schema.map((h) => `<th>${escapeHtml(h)}</th>`).join("")}</tr>`;
  $("resultBody").innerHTML = rows
    .map((row) => `<tr class="hover:bg-slate-800/50">${schema.map((h) => `<td>${escapeHtml(row[h] || "")}</td>`).join("")}</tr>`)
    .join("");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
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
  const csv = [schema.join(","), ...rows.map((row) => schema.map((h) => csvCell(row[h] || "")).join(","))].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `movanta-bookings-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
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

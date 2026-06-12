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
  "Client",
  "Comments",
];

let currentUser = null;
let rows = [];
let users = [];
let analytics = null;
let activeTab = "dashboard";
let analyticsPollTimer = null;
let selectedFiles = [];
let loaderProgress = 0;
let loaderTimer = null;
let loaderHideTimer = null;
const revealTimers = new WeakMap();
const revealChars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";

const homeSections = {
  future: {
    kicker: "Future",
    headline: "Limitless\nLogistics.\nIntelligent\nShipping.",
    intro: "Movanta transforms booking PDFs into clear maritime intelligence for teams moving cargo across complex global routes.",
  },
  innovation: {
    kicker: "Innovation",
    headline: "From booking PDFs to usable data.",
    intro: "A refined extraction workspace helps teams review vessel, voyage, port, and cut-off details without manual retyping.",
  },
  automation: {
    kicker: "Automation",
    headline: "Less document friction. More movement.",
    intro: "Upload booking confirmations, inspect structured outputs, and prepare operational handoffs with fewer repetitive steps.",
  },
  accuracy: {
    kicker: "Accuracy",
    headline: "Clear tables for critical shipping moments.",
    intro: "Movanta keeps extracted fields visible, reviewable, and ready for email workflows without changing your existing process.",
  },
  logistics: {
    kicker: "Logistics",
    headline: "Built around the rhythm of shipments.",
    intro: "The interface prioritizes fast upload, clear review, and confident export for teams coordinating containers and timelines.",
  },
  legacy: {
    kicker: "Legacy",
    headline: "A sharper operating layer for tomorrow.",
    intro: "Movanta brings a high-end intelligence surface to everyday documentation work while preserving trusted extraction behavior.",
  },
};

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
    window.clearTimeout(loaderHideTimer);
    window.clearInterval(loaderTimer);
    loader.classList.remove("hidden");
    setLoaderProgress(0, label);
    startLoaderDrift(88, label);
    return;
  }
  window.clearInterval(loaderTimer);
  setLoaderProgress(100, "Ready to explore");
  loaderHideTimer = window.setTimeout(() => loader.classList.add("hidden"), 520);
}

function withTimeout(promise, ms = 8000, message = "Request timed out") {
  let timeoutId;
  const timeout = new Promise((_, reject) => {
    timeoutId = window.setTimeout(() => reject(new Error(message)), ms);
  });
  return Promise.race([promise, timeout]).finally(() => window.clearTimeout(timeoutId));
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
  document.body.classList.remove("view-home", "view-login", "view-dashboard");
  document.body.classList.add(view === "dashboardView" ? "view-dashboard" : view === "loginView" ? "view-login" : "view-home");
  if (view === "loginView") {
    $("homeView").classList.remove("hidden");
    $("dashboardView").classList.add("hidden");
    $("loginView").classList.remove("hidden");
  } else {
    ["homeView", "loginView", "dashboardView"].forEach((id) => $(id).classList.add("hidden"));
    $(view).classList.remove("hidden");
  }
  const isLoggedIn = Boolean(currentUser);
  $("publicNav").classList.remove("hidden");
  $("publicNavRight").classList.toggle("hidden", isLoggedIn);
  $("userBar").classList.toggle("hidden", !isLoggedIn);
  document.body.classList.toggle("is-authenticated", isLoggedIn);
  if (view === "homeView" || view === "loginView") initHeroReveal();
}

function closeLoginModal() {
  $("loginView").classList.add("hidden");
  if (!currentUser && $("dashboardView").classList.contains("hidden")) {
    $("homeView").classList.remove("hidden");
    document.body.classList.remove("view-login", "view-dashboard");
    document.body.classList.add("view-home");
  }
}

function openLuxuryMenu() {
  $("luxuryMenu").classList.remove("hidden");
  $("luxuryMenu").setAttribute("aria-hidden", "false");
}

function closeLuxuryMenu() {
  $("luxuryMenu").classList.add("hidden");
  $("luxuryMenu").setAttribute("aria-hidden", "true");
}

function closeToolsDropdown() {
  $("toolsDropdown").classList.add("hidden");
  $("toolsDropdownBtn").setAttribute("aria-expanded", "false");
}

function toggleToolsDropdown() {
  const willOpen = $("toolsDropdown").classList.contains("hidden");
  $("toolsDropdown").classList.toggle("hidden", !willOpen);
  $("toolsDropdownBtn").setAttribute("aria-expanded", String(willOpen));
}

function initHeroReveal() {
  const headline = $("homeHeadline");
  if (!headline) return;
  if (window.sessionStorage.getItem("movantaHeroRevealed") === "true") {
    headline.classList.add("hero-clear");
    return;
  }
  headline.classList.add("hero-blur-reveal");
  window.sessionStorage.setItem("movantaHeroRevealed", "true");
}

function openModal(id) {
  $(id).classList.remove("hidden");
}

function closeModal(id) {
  $(id).classList.add("hidden");
}

function enhanceRollingText() {
  // The reference direction now uses underline hover only; keep this as a no-op for existing calls.
  return;
}

function randomizeText(finalText, progress) {
  return Array.from(finalText)
    .map((char, index) => {
      if (char === " ") return " ";
      if (index < progress) return char;
      return revealChars[Math.floor(Math.random() * revealChars.length)];
    })
    .join("");
}

function runLetterReveal(element) {
  const finalText = element.dataset.revealText || element.getAttribute("aria-label") || "";
  if (!finalText) return;
  window.clearInterval(revealTimers.get(element));
  const target = element.querySelector(".reveal-text");
  if (!target) return;

  let tick = 0;
  const maxTicks = Math.max(8, finalText.length + 4);
  const timer = window.setInterval(() => {
    tick += 1;
    const progress = Math.max(0, tick - 3);
    const value = tick >= maxTicks ? finalText : randomizeText(finalText, progress);
    target.textContent = value;
    if (tick >= maxTicks) {
      window.clearInterval(timer);
      target.textContent = finalText;
    }
  }, 28);
  revealTimers.set(element, timer);
}

function setHomeSection(sectionKey) {
  const section = homeSections[sectionKey] || homeSections.future;
  $("homeSectionKicker").textContent = section.kicker;
  $("homeHeadline").textContent = section.headline;
  $("homeIntro").textContent = section.intro;
  document.querySelectorAll("[data-home-section]").forEach((button) => {
    button.classList.toggle("active", button.dataset.homeSection === sectionKey);
  });
  document.querySelectorAll("#homeSectionKicker, #homeHeadline, #homeIntro").forEach((el) => {
    delete el.dataset.rollEnhanced;
    el.classList.remove("text-swap");
    void el.offsetWidth;
    el.classList.add("text-swap");
  });
  enhanceRollingText();
}

function setUser(user) {
  currentUser = user;
  $("userIdentity").textContent = `${user.name || user.username} / ${user.role.toUpperCase()}`;
  $("adminTab").classList.toggle("hidden", !user.isAdmin);
  $("userAdminBtn").classList.toggle("hidden", !user.isAdmin);
  $("uploadLimitNote").textContent = user.isAdmin
    ? "Admin access: batch upload limit is unrestricted."
    : `Upload limit: ${user.uploadLimit} PDFs per extraction.`;
  updateUploadLimitCard();
}

function signOutUser() {
  currentUser = null;
  stopAnalyticsPolling();
  rows = [];
  selectedFiles = [];
  $("pdfInput").value = "";
  $("adminTab").classList.add("hidden");
  $("userAdminBtn").classList.add("hidden");
  updateFileCount();
  renderTable();
  updateUploadLimitCard();
}

function openBookingTool() {
  if (currentUser) {
    show("dashboardView");
    setTab("dashboard");
    return;
  }
  show("loginView");
  $("loginIdentifier").focus();
  toast("Login or request access to use the Booking Extraction Tool.");
}

function showComingSoon(toolName) {
  toast(`${toolName} is coming soon. Contact Movanta for early access.`);
}

function updateUploadLimitCard() {
  const card = $("uploadLimitCard");
  if (!card) return;
  const title = $("uploadLimitTitle");
  const meter = $("uploadLimitMeter");
  const message = $("uploadLimitMessage");
  const submit = $("extractSubmitBtn");
  const selected = getSelectedFiles().length;

  card.classList.remove("warning", "blocked", "ready");
  if (!currentUser) {
    title.textContent = "Login required";
    message.textContent = "Login to see your upload capacity.";
    meter.style.transform = "scaleX(0)";
    if (submit) submit.disabled = true;
    return;
  }

  if (currentUser.isAdmin) {
    title.textContent = selected ? `${selected} selected` : "Admin access";
    message.textContent = "Admin uploads are unrestricted for batch processing.";
    meter.style.transform = selected ? "scaleX(1)" : "scaleX(0.18)";
    if (submit) submit.disabled = false;
    card.classList.add("ready");
    return;
  }

  const limit = Number(currentUser.uploadLimit || 0);
  const remaining = Math.max(0, limit - selected);
  const usedRatio = limit > 0 ? Math.min(1, selected / limit) : 1;
  title.textContent = `You have ${remaining} upload${remaining === 1 ? "" : "s"} remaining`;
  meter.style.transform = `scaleX(${usedRatio})`;

  if (limit < 1) {
    card.classList.add("blocked");
    message.textContent = "Your upload limit has been reached. Contact Movanta to continue.";
    if (submit) submit.disabled = true;
    return;
  }
  if (selected > limit) {
    card.classList.add("blocked");
    message.textContent = `You selected ${selected} PDFs, which exceeds your limit. Remove files or contact Movanta.`;
    if (submit) submit.disabled = true;
    return;
  }
  if (selected > 0 && remaining <= 3) {
    card.classList.add("warning");
    message.textContent = remaining === 0
      ? "This batch uses your full upload capacity."
      : `Upload capacity is low: ${remaining} upload${remaining === 1 ? "" : "s"} left in this batch.`;
    if (submit) submit.disabled = false;
    return;
  }
  card.classList.add("ready");
  message.textContent = selected
    ? `${selected} PDF${selected === 1 ? "" : "s"} selected for extraction.`
    : "Choose PDFs to see remaining upload slots.";
  if (submit) submit.disabled = false;
}

function updateFileCount() {
  const input = $("pdfInput");
  const label = $("fileCountLabel");
  if (!input || !label) return;
  const files = getSelectedFiles();
  const count = files.length;
  const names = files.slice(0, 3).map((file) => file.name).join(", ");
  label.textContent = count ? `${count} file${count === 1 ? "" : "s"} selected${names ? `: ${names}${count > 3 ? ", ..." : ""}` : ""}` : "No files selected";
}

function getSelectedFiles() {
  return selectedFiles.length ? selectedFiles : Array.from($("pdfInput")?.files || []);
}

function setSelectedFiles(files) {
  selectedFiles = Array.from(files || []).filter((file) => /\.pdf$/i.test(file.name || "") || file.type === "application/pdf");
  updateFileCount();
  updateUploadLimitCard();
}

function renderTable() {
  $("resultHead").innerHTML = `<tr>${schema.map((h) => `<th>${headerLabel(h)}</th>`).join("")}</tr>`;
  $("resultBody").innerHTML = rows
    .map((row) => `<tr>${schema.map((h) => `<td class="${cellClass(h, row[h])}">${escapeHtml(row[h] || "")}</td>`).join("")}</tr>`)
    .join("");
  $("copyAllBtn").disabled = rows.length === 0;
  $("downloadCsvBtn").disabled = rows.length === 0;
  renderEmailCards();
  enhanceRollingText();
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
    show("homeView");
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
    await withTimeout(api("/api/auth/logout", { method: "POST" }), 6000, "Sign out timed out");
    signOutUser();
    show("homeView");
    toast("Signed out");
  } catch (error) {
    toast(error.message, true);
  } finally {
    showLoader(false);
  }
});

$("menuNavBtn").addEventListener("click", openLuxuryMenu);
$("homeNavBtn").addEventListener("click", () => {
  closeToolsDropdown();
  show("homeView");
  window.scrollTo({ top: 0, behavior: "smooth" });
});
$("toolsDropdownBtn").addEventListener("click", (event) => {
  event.stopPropagation();
  toggleToolsDropdown();
});
$("bookingNavBtn").addEventListener("click", () => {
  closeToolsDropdown();
  openBookingTool();
});
$("ratesNavBtn").addEventListener("click", () => {
  closeToolsDropdown();
  showComingSoon("Rates Comparison");
});
$("docsNavBtn").addEventListener("click", () => {
  closeToolsDropdown();
  showComingSoon("Documentation Accuracy Checker");
});
$("contactNavBtn").addEventListener("click", () => {
  window.location.href = "mailto:movantaa@outlook.com";
});
$("searchNavBtn").addEventListener("click", () => showComingSoon("Search"));
$("loginNavBtn").addEventListener("click", () => show("loginView"));
$("heroToolBtn").addEventListener("click", openBookingTool);
$("registerLinkBtn").addEventListener("click", () => {
  window.location.href = "mailto:movantaa@outlook.com?subject=Movanta%20Access%20Request";
});
$("forgotPasswordBtn").addEventListener("click", () => {
  window.location.href = "mailto:movantaa@outlook.com?subject=Movanta%20Password%20Help";
});
$("userHomeBtn").addEventListener("click", () => {
  show("homeView");
  window.scrollTo({ top: 0, behavior: "smooth" });
});
$("userContactBtn").addEventListener("click", () => {
  window.location.href = "mailto:movantaa@outlook.com";
});
$("userSearchBtn").addEventListener("click", () => showComingSoon("Search"));
$("userDashboardBtn").addEventListener("click", () => {
  show("dashboardView");
  setTab("dashboard");
});
$("userAdminBtn").addEventListener("click", async () => {
  show("dashboardView");
  setTab("admin");
  await loadUsers();
});
$("closeLoginBtn").addEventListener("click", closeLoginModal);
$("closeMenuBtn").addEventListener("click", closeLuxuryMenu);
$("luxuryMenu").addEventListener("click", (event) => {
  if (event.target === $("luxuryMenu")) closeLuxuryMenu();
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".tools-dropdown")) closeToolsDropdown();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeToolsDropdown();
});

document.querySelectorAll("[data-menu-action]").forEach((button) => {
  button.addEventListener("click", async () => {
    const action = button.dataset.menuAction;
    closeLuxuryMenu();
    if (action === "home") {
      show("homeView");
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
    if (action === "tools") {
      show("homeView");
      $("toolsSection").scrollIntoView({ behavior: "smooth" });
    }
    if (action === "dashboard") openBookingTool();
    if (action === "admin") {
      if (!currentUser?.isAdmin) {
        show("loginView");
        toast("Admin access requires login.");
        return;
      }
      show("dashboardView");
      setTab("admin");
      await loadUsers();
    }
    if (action === "contact") window.location.href = "mailto:movantaa@outlook.com";
    if (action === "login") {
      if (currentUser) $("logoutBtn").click();
      else show("loginView");
    }
  });
});

document.querySelectorAll("[data-tool]").forEach((button) => {
  button.addEventListener("click", () => {
    const tool = button.dataset.tool;
    if (tool === "booking") {
      openBookingTool();
      return;
    }
    showComingSoon(tool === "rates" ? "Rates Comparison" : "Documentation Accuracy Checker");
  });
});

document.querySelectorAll("[data-home-section]").forEach((button) => {
  button.addEventListener("click", () => setHomeSection(button.dataset.homeSection));
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
  const files = getSelectedFiles();
  if (!files.length) return toast("Choose at least one PDF", true);
  if (!currentUser?.isAdmin && files.length > Number(currentUser?.uploadLimit || 0)) {
    updateUploadLimitCard();
    return toast("Upload limit exceeded. Contact Movanta or remove files.", true);
  }
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  showLoader(true, "Preparing upload");
  try {
    const data = await uploadExtraction(formData);
    rows = data.rows || [];
    renderTable();
    const summary = data.summary || { processed: rows.length, skipped: 0, failed: 0 };
    const skipped = data.skipped || [];
    if (skipped.length) {
      const first = skipped[0];
      const detail = first.bookingNo ? ` Booking ${first.bookingNo}` : "";
      toast(`${summary.processed} processed, ${summary.skipped} skipped.${detail} has already been processed before.`, summary.processed === 0);
    } else {
      toast(`Extracted ${rows.length} PDF${rows.length === 1 ? "" : "s"}`);
    }
  } catch (error) {
    toast(error.message, true);
  } finally {
    showLoader(false);
  }
});

$("pdfInput").addEventListener("change", () => {
  selectedFiles = [];
  updateFileCount();
  updateUploadLimitCard();
});

$("fileDropZone").addEventListener("dragover", (event) => {
  event.preventDefault();
  $("fileDropZone").classList.add("dragging");
});

$("fileDropZone").addEventListener("dragleave", () => {
  $("fileDropZone").classList.remove("dragging");
});

$("fileDropZone").addEventListener("drop", (event) => {
  event.preventDefault();
  $("fileDropZone").classList.remove("dragging");
  setSelectedFiles(event.dataTransfer?.files || []);
});

$("downloadCsvBtn").addEventListener("click", () => {
  if (!rows.length) return;
  renderExportColumns();
  openModal("exportColumnsModal");
});

$("confirmExportBtn").addEventListener("click", () => {
  const selectedColumns = Array.from(document.querySelectorAll("[data-export-column]:checked")).map((input) => input.value);
  if (!selectedColumns.length) return toast("Select at least one column to export.", true);
  closeModal("exportColumnsModal");
  downloadCsv(selectedColumns);
});

function renderExportColumns() {
  $("exportColumnList").innerHTML = schema
    .map(
      (column) => `
        <label class="checkbox-row export-column">
          <input data-export-column type="checkbox" value="${escapeHtml(column)}" checked />
          <span>${escapeHtml(column)}</span>
        </label>`
    )
    .join("");
}

function downloadCsv(columns) {
  const csv = [columns.join(","), ...rows.map((row) => columns.map((h) => csvCell(row[h] || "")).join(","))].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `movanta-bookings-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

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
  activeTab = tab;
  $("extractPanel").classList.toggle("hidden", tab !== "dashboard");
  $("adminPanel").classList.toggle("hidden", tab !== "admin");
  $("dashboardTab").classList.toggle("active", tab === "dashboard");
  $("adminTab").classList.toggle("active", tab === "admin");
  if (tab === "admin") {
    startAnalyticsPolling();
  } else {
    stopAnalyticsPolling();
  }
}

function setAnalyticsLiveStatus(state, message) {
  const el = $("analyticsLiveStatus");
  if (!el) return;
  el.className = `live-status ${state || ""}`.trim();
  el.textContent = message;
}

function startAnalyticsPolling() {
  if (analyticsPollTimer || !currentUser?.isAdmin) return;
  setAnalyticsLiveStatus("loading", "Syncing");
  analyticsPollTimer = window.setInterval(() => {
    if (activeTab === "admin" && currentUser?.isAdmin) loadUsers(false, true);
  }, 10000);
}

function stopAnalyticsPolling() {
  window.clearInterval(analyticsPollTimer);
  analyticsPollTimer = null;
}

async function loadUsers(showProgress = true, quiet = false) {
  if (showProgress) showLoader(true, "Loading users");
  try {
    setAnalyticsLiveStatus("loading", showProgress ? "Loading" : "Syncing");
    const [userData, analyticsData] = await Promise.all([api("/api/admin/users"), api("/api/admin/analytics")]);
    const data = userData;
    users = data.users || [];
    analytics = analyticsData;
    renderUsers();
    renderAnalytics();
    setAnalyticsLiveStatus("live", "Live");
  } catch (error) {
    setAnalyticsLiveStatus("error", "Offline");
    if (!quiet) toast(error.message, true);
  } finally {
    if (showProgress) showLoader(false);
  }
}

function renderAnalytics() {
  if (!analytics) return;
  const kpis = analytics.kpis || {};
  const mostLine = kpis.mostUsedShippingLine || { line: "No data", count: 0 };
  const cards = [
    ["Total Users", kpis.totalUsers ?? 0],
    ["Active Users", kpis.activeUsers ?? 0],
    ["Disabled / Deleted", kpis.disabledDeletedUsers ?? 0],
    ["Total Uploads", kpis.totalUploadsProcessed ?? 0],
    ["Today", kpis.uploadsToday ?? 0],
    ["This Month", kpis.uploadsThisMonth ?? 0],
    ["Most Used Line", `${mostLine.line} (${mostLine.count})`],
    ["No Uploads Left", kpis.usersWithNoUploadsLeft ?? 0],
  ];
  $("adminKpiGrid").innerHTML = cards
    .map(([label, value]) => `<div class="kpi-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join("");

  const maxLineCount = Math.max(1, ...(analytics.shippingLines || []).map((item) => item.count || 0));
  $("shippingLineChart").innerHTML = (analytics.shippingLines || []).length
    ? analytics.shippingLines
        .map(
          (item) => `
            <div class="line-row">
              <div><strong>${escapeHtml(item.line)}</strong><span>${escapeHtml(item.count)} bookings</span></div>
              <i style="transform:scaleX(${Math.max(0.04, (item.count || 0) / maxLineCount)})"></i>
            </div>`
        )
        .join("")
    : `<div class="empty-state">No upload history yet.</div>`;

  $("userUsageList").innerHTML = (analytics.users || [])
    .map((user) => {
      if (user.isUnlimited || user.isAdmin) {
        return `
          <div class="usage-row unlimited">
            <div class="usage-main">
              <strong>${escapeHtml(user.name || user.username || "-")}</strong>
              <span>${escapeHtml(user.email)} / ${escapeHtml(user.role)} / Admin</span>
            </div>
            <div class="usage-meta">
              <span>Unlimited</span>
            </div>
          </div>`;
      }
      const status = user.isDeleted ? "Deleted" : user.isActive ? "Active" : "Disabled";
      const remaining = Number(user.uploadsRemaining || 0);
      const cls = remaining === 0 ? "empty" : remaining <= 3 ? "low" : "";
      return `
        <div class="usage-row ${cls}">
          <div class="usage-main">
            <strong>${escapeHtml(user.name || user.username || "-")}</strong>
            <span>${escapeHtml(user.email)} / ${escapeHtml(user.role)} / ${status}</span>
          </div>
          <div class="usage-meta">
            <span>${escapeHtml(user.uploadsUsed || 0)} used</span>
            <span>${escapeHtml(user.uploadLimit || 0)} limit</span>
            <span>${escapeHtml(remaining)} left</span>
          </div>
          <div class="usage-bar"><i style="transform:scaleX(${Math.min(1, Math.max(0, (user.usagePercent || 0) / 100))})"></i></div>
        </div>`;
    })
    .join("");

  $("recentUploadList").innerHTML = (analytics.recentUploads || []).length
    ? analytics.recentUploads
        .map((item) => {
          const date = item.createdAt ? new Date(item.createdAt).toLocaleString() : "-";
          const status = String(item.status || "").toLowerCase();
          return `
            <div class="recent-row ${status}">
              <div>
                <strong>${escapeHtml(item.fileName || "-")}</strong>
                <span>${escapeHtml(item.userName || "-")} / ${escapeHtml(item.userEmail || "-")}</span>
              </div>
              <div>
                <b>${escapeHtml(item.bookingNo || item.line || "Unknown")}</b>
                <span>${escapeHtml(item.line || "Unknown")} / ${escapeHtml(status || "-")} / ${escapeHtml(date)}</span>
              </div>
            </div>`;
        })
        .join("")
    : `<div class="empty-state">No upload activity yet.</div>`;
  enhanceRollingText();
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
          <td>${escapeHtml(user.isAdmin ? "Unlimited" : user.uploadLimit)}</td>
          <td><span class="status-pill ${status.toLowerCase()}">${status}</span></td>
          <td>${created}</td>
          <td>
            <div class="action-row">
              <button class="admin-action action-edit" data-edit-user="${user.id}" type="button">Edit</button>
              <button class="admin-action action-reset" data-reset-user="${user.id}" type="button">Reset Password</button>
              <button class="admin-action action-delete" data-delete-user="${user.id}" type="button">Delete / Disable</button>
            </div>
          </td>
        </tr>`;
    })
    .join("");
  enhanceRollingText();
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

enhanceRollingText();
setHomeSection("future");
updateFileCount();
bootstrap();

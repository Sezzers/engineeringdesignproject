// Small helpers shared by the student and advisor pages.

async function api(url, options = {}) {
  const opts = { ...options };
  if (opts.json !== undefined) {
    opts.method = opts.method || "POST";
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(opts.json);
    delete opts.json;
  }
  const response = await fetch(url, opts);
  if (response.status === 401) { window.location.href = "/login"; throw new Error("Not signed in"); }
  let data = null;
  try { data = await response.json(); } catch (e) { /* no body */ }
  if (!response.ok) throw new Error((data && data.error) || "Something went wrong.");
  return data;
}

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  for (const c of children) node.append(c);
  return node;
}

function showMessage(box, text, kind) {
  box.textContent = text;
  box.className = "msg " + (kind || "");
}

function statusBadge(status) {
  const labels = { pending: "Pending", approved: "Approved", rejected: "Rejected" };
  return el("span", { className: "badge " + status, textContent: labels[status] || status });
}

function formatSize(bytes) {
  return bytes < 1024 * 1024 ? Math.round(bytes / 1024) + " KB" : (bytes / 1048576).toFixed(1) + " MB";
}

// Renders the file list + upload control of one appointment into `container`.
async function renderFiles(container, appointmentId) {
  container.replaceChildren();
  const list = await api("/api/appointments/" + appointmentId + "/files");
  const msg = el("div", { className: "msg" });

  for (const f of list) {
    container.append(el("div", {},
      f.original_name + " (" + formatSize(f.size_bytes) + ") - " + f.uploader_name + ", " + f.uploaded_at + " ",
      el("a", { href: "/api/files/" + f.id + "/download", textContent: "Download" })));
  }
  if (list.length === 0) container.append(el("div", { className: "muted", textContent: "No files yet." }));

  const input = el("input", { type: "file", accept: "application/pdf,.pdf" });
  const button = el("button", { textContent: "Upload", type: "button" });
  button.onclick = async () => {
    if (!input.files.length) { showMessage(msg, "Please choose a PDF file.", "error"); return; }
    const body = new FormData();
    body.append("file", input.files[0]);
    button.disabled = true;
    try {
      await api("/api/appointments/" + appointmentId + "/files", { method: "POST", body });
      await renderFiles(container, appointmentId);
    } catch (err) {
      showMessage(msg, err.message, "error");
    } finally {
      button.disabled = false;
    }
  };
  container.append(el("div", { className: "row" }, input, button), msg);
}

async function setupLogout() {
  document.getElementById("logout").onclick = async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/login";
  };
}

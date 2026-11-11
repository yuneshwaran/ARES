const STATUS_OPTIONS = [
  "new",
  "scored",
  "ready_to_apply",
  "applied",
  "interview",
  "offer",
  "rejected",
  "skipped",
];

async function apiGet(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function apiPost(url, body = {}) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || data.message || `HTTP ${res.status}`);
  return data;
}

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderOverview(data) {
  const counts = data.counts || {};
  document.getElementById("kpiTotal").textContent = data.total_jobs ?? 0;
  document.getElementById("kpiReady").textContent =
    (counts.scored || 0) + (counts.ready_to_apply || 0);
  document.getElementById("kpiApplied").textContent = counts.applied || 0;
  document.getElementById("kpiInterview").textContent = counts.interview || 0;
  document.getElementById("kpiOffer").textContent = counts.offer || 0;
  document.getElementById("kpiQuota").textContent = `${data.daily_applied || 0} / ${data.max_daily_applications || 25}`;
  document.getElementById("applyPolicyBadge").textContent =
    `Apply Mode: ${data.apply_mode || "review"} (${data.apply_enabled ? "enabled" : "manual/disabled"})`;

  const total = Math.max(data.total_jobs || 1, 1);
  const funnel = document.getElementById("funnelBars");
  funnel.innerHTML = STATUS_OPTIONS.map((status) => {
    const count = counts[status] || 0;
    const pct = Math.round((count / total) * 100);
    return `
      <div class="funnel-item">
        <div class="funnel-top">
          <span>${status.replace(/_/g, " ")}</span>
          <strong>${count} (${pct}%)</strong>
        </div>
        <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
      </div>
    `;
  }).join("");

  renderTaskBanner(data.task || {});
}

function renderTaskBanner(task) {
  const dot = document.getElementById("taskDot");
  const text = document.getElementById("taskStatusText");
  const outBox = document.getElementById("taskOutputBox");

  if (task.running) {
    dot.className = "dot running";
    text.textContent = `Running '${task.action}' since ${task.started_at}...`;
  } else if (task.action) {
    dot.className = task.exit_code === 0 ? "dot ok" : "dot err";
    text.textContent = `Last run '${task.action}' exited with ${task.exit_code} at ${task.finished_at}`;
  } else {
    dot.className = "dot idle";
    text.textContent = "Idle — ready for commands";
  }

  if (task.output) {
    outBox.textContent = task.output;
  }
}

async function loadJobs() {
  const status = document.getElementById("statusFilter").value;
  const minScore = document.getElementById("minScoreInput").value;
  const q = document.getElementById("searchInput").value.trim();

  const params = new URLSearchParams({ status, min_score: minScore, q });
  const data = await apiGet(`/api/jobs?${params.toString()}`);
  const tbody = document.getElementById("jobsTableBody");

  if (!data.jobs || data.jobs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty">No matching jobs found.</td></tr>`;
    return;
  }

  tbody.innerHTML = data.jobs
    .map((job) => {
      const score = job.match_score;
      const scoreClass = score >= 80 ? "score-high" : score >= 60 ? "score-mid" : "score-low";
      const scoreDisplay = score !== null && score !== undefined ? `${Math.round(score)}%` : "—";
      const selectOpts = STATUS_OPTIONS.map(
        (s) => `<option value="${s}" ${s === job.status ? "selected" : ""}>${s}</option>`
      ).join("");

      return `
        <tr>
          <td><span class="score-pill ${scoreClass}">${scoreDisplay}</span></td>
          <td><button class="role-link" data-job-id="${job.id}">${escapeHtml(job.title)}</button></td>
          <td>${escapeHtml(job.company)}</td>
          <td>${escapeHtml(job.location)}</td>
          <td>${escapeHtml(job.source)}</td>
          <td><span class="badge badge-${escapeHtml(job.status)}">${escapeHtml(job.status)}</span></td>
          <td>
            <select class="status-updater" data-job-id="${job.id}">
              ${selectOpts}
            </select>
          </td>
          <td>${job.url ? `<a class="ext-link" href="${escapeHtml(job.url)}" target="_blank" rel="noopener">Open</a>` : "—"}</td>
        </tr>
      `;
    })
    .join("");
}

async function loadEmails() {
  const data = await apiGet("/api/emails");
  const tbody = document.getElementById("emailsTableBody");
  if (!data.emails || data.emails.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty">No recruiter emails recorded yet.</td></tr>`;
    return;
  }

  tbody.innerHTML = data.emails
    .map(
      (e) => `
      <tr>
        <td>${escapeHtml((e.date_received || "").slice(0, 10))}</td>
        <td>${escapeHtml(e.sender)}</td>
        <td>${escapeHtml(e.subject)}</td>
        <td><span class="badge badge-${escapeHtml(e.classified_status)}">${escapeHtml(e.classified_status)}</span></td>
        <td>${escapeHtml(e.snippet)}</td>
      </tr>
    `
    )
    .join("");
}

async function loadRunsAndLogs() {
  const [runsData, logsData] = await Promise.all([apiGet("/api/runs"), apiGet("/api/logs")]);
  const tbody = document.getElementById("runsTableBody");

  if (!runsData.runs || runsData.runs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty">No run history recorded yet.</td></tr>`;
  } else {
    tbody.innerHTML = runsData.runs
      .map(
        (r) => `
        <tr>
          <td>${escapeHtml(r.run_type)}</td>
          <td><span class="badge ${r.status === "completed" ? "badge-interview" : r.status === "failed" ? "badge-rejected" : "badge-scored"}">${escapeHtml(r.status)}</span></td>
          <td>${r.jobs_found}</td>
          <td>${r.jobs_applied}</td>
          <td>${escapeHtml((r.started_at || "").replace("T", " ").slice(0, 19))}</td>
        </tr>
      `
      )
      .join("");
  }

  const logTailBox = document.getElementById("logTailBox");
  logTailBox.textContent = (logsData.lines || []).join("\n") || "Log file is empty.";
}

async function loadConfigHealth() {
  const data = await apiGet("/api/config-health");
  const grid = document.getElementById("healthGrid");
  grid.innerHTML = (data.checks || [])
    .map(
      (c) => `
      <div class="health-item">
        <div class="health-top">
          <strong>${escapeHtml(c.name)}</strong>
          <span class="${c.ok ? "pill-ok" : "pill-warn"}">${c.ok ? "OK" : "CHECK"}</span>
        </div>
        <div class="muted">${escapeHtml(c.detail)}</div>
      </div>
    `
    )
    .join("");
}

async function refreshAll() {
  try {
    const overview = await apiGet("/api/overview");
    renderOverview(overview);
    await Promise.all([loadJobs(), loadEmails(), loadRunsAndLogs(), loadConfigHealth()]);
  } catch (err) {
    console.error("Refresh failed:", err);
  }
}

// Event bindings
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(btn.dataset.tab).classList.add("active");
  });
});

document.querySelectorAll("[data-action]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    try {
      const res = await apiPost(`/api/actions/${btn.dataset.action}`);
      renderTaskBanner(res.task || {});
    } catch (err) {
      alert(err.message);
    }
  });
});

document.getElementById("refreshBtn").addEventListener("click", refreshAll);
document.getElementById("statusFilter").addEventListener("change", loadJobs);
document.getElementById("searchInput").addEventListener("input", loadJobs);
document.getElementById("minScoreInput").addEventListener("input", (e) => {
  document.getElementById("minScoreLabel").textContent = `${e.target.value}%`;
  loadJobs();
});

document.getElementById("jobsTableBody").addEventListener("change", async (e) => {
  if (!e.target.classList.contains("status-updater")) return;
  const id = Number(e.target.dataset.jobId);
  const status = e.target.value;
  try {
    await apiPost("/api/jobs/status", { id, status });
    await refreshAll();
  } catch (err) {
    alert(`Failed to update status: ${err.message}`);
  }
});

document.getElementById("jobsTableBody").addEventListener("click", async (e) => {
  const btn = e.target.closest(".role-link");
  if (!btn) return;
  const data = await apiGet(`/api/jobs/${btn.dataset.jobId}`);
  const job = data.job;
  document.getElementById("modalTitle").textContent = job.title;
  document.getElementById("modalSub").textContent = `${job.company} • ${job.location} • ${job.source}`;
  document.getElementById("modalMeta").innerHTML = `
    <span class="badge badge-${escapeHtml(job.status)}">${escapeHtml(job.status)}</span>
    <span class="muted"> Match: ${job.match_score ?? "—"}%</span>
  `;
  document.getElementById("modalReasoning").textContent = job.score_reasoning || "Not scored yet.";
  document.getElementById("modalDescription").textContent = job.description || "No description saved.";
  document.getElementById("jobModal").classList.remove("hidden");
});

document.getElementById("closeModalBtn").addEventListener("click", () => {
  document.getElementById("jobModal").classList.add("hidden");
});

document.getElementById("runLiveTestsBtn").addEventListener("click", async (e) => {
  const btn = e.target;
  btn.disabled = true;
  btn.textContent = "Testing...";
  try {
    const res = await apiPost("/api/test-config", { gemini: true, discord: true });
    const container = document.getElementById("liveResults");
    container.innerHTML = Object.entries(res.results || {})
      .map(
        ([key, val]) => `
        <div class="health-item">
          <div class="health-top">
            <strong>Live Test: ${escapeHtml(key.toUpperCase())}</strong>
            <span class="${val.ok ? "pill-ok" : "pill-warn"}">${val.ok ? "PASS" : "FAIL"}</span>
          </div>
          <div class="muted">${escapeHtml(val.detail)}</div>
        </div>
      `
      )
      .join("");
  } catch (err) {
    alert(`Test failed: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Run Live API & Discord Test";
  }
});

setInterval(() => {
  if (document.getElementById("autoRefresh").checked) {
    refreshAll();
  }
}, 10000);

refreshAll();

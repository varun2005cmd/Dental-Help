// Dental Help — Frontend App

function esc(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-US",{month:"short",day:"numeric",hour:"2-digit",minute:"2-digit",timeZone:"UTC"})+" UTC";
  } catch { return iso; }
}
function pill(v) { return `<span class="pill pill-${esc(v.toLowerCase())}">${esc(v)}</span>`; }

class App {
  constructor() {
    this.agentId = "";
    this.timer = null;
    this.lines = [];
    this.doctors = [];
    this.init();
  }

  async init() {
    if (window.DEMODENTAL_CONFIG?.agentId) {
      this.agentId = window.DEMODENTAL_CONFIG.agentId;
    } else {
      try {
        const r = await fetch("/api/config");
        if (r.ok) this.agentId = (await r.json()).agent_id;
      } catch {}
    }
    // Load doctors list
    try {
      const r = await fetch("/api/doctors");
      if (r.ok) this.doctors = (await r.json()).doctors ?? [];
    } catch {}

    this.mountWidget();
    await this.refreshData();
    this.setStatus("online","Connected");
    this.timer = setInterval(() => this.refreshData(), 10000);
  }

  mountWidget() {
    const loading = document.getElementById("widget-loading");
    const mount   = document.getElementById("elevenlabs-widget-mount");
    if (!this.agentId) {
      if (loading) loading.innerHTML = "<span style='color:#f87171;font-size:.8rem'>Agent not configured — run setup_agent.py first</span>";
      this.setStatus("error","Not configured");
      return;
    }
    if (loading) loading.classList.add("hidden");
    const w = document.createElement("elevenlabs-convai");
    w.setAttribute("agent-id", this.agentId);
    mount?.appendChild(w);

    document.addEventListener("elevenlabs-convai:call",   () => this.onCallStart());
    document.addEventListener("elevenlabs-convai:message", (e) => this.onMessage(e.detail));
    document.addEventListener("elevenlabs-convai:disconnect", () => this.onCallEnd());
  }

  onCallStart() {
    this.lines = [];
    this.currentConvId = null;
    const sec = document.getElementById("transcript-section");
    const box = document.getElementById("live-transcript");
    if (sec) sec.classList.remove("hidden");
    if (box) box.innerHTML = "";
    const banner = document.getElementById("booking-banner");
    if (banner) { banner.className = "booking-banner hidden"; }
    this.setStatus("online","Call in progress");
  }

  onMessage(detail) {
    // Capture conversation_id from initiation metadata
    if (detail?.type === "conversation_initiation_metadata") {
      this.currentConvId = detail?.conversation_initiation_metadata_event?.conversation_id
        || detail?.conversation_id || null;
    }
    const role    = detail?.message?.role ?? "";
    const content = detail?.message?.content ?? "";
    if (!content) return;
    const cls   = role === "agent" ? "t-agent" : "t-user";
    const label = role === "agent" ? "Aria" : "You";
    this.lines.push(`<div class="${cls}"><strong>${label}:</strong> ${esc(content)}</div>`);
    const box = document.getElementById("live-transcript");
    if (box) { box.innerHTML = this.lines.join(""); box.scrollTop = box.scrollHeight; }
  }

  onCallEnd() {
    this.setStatus("online","Call ended — saving");
    // 4s: appointment should already be in DB (booked live during call)
    setTimeout(() => { this.refreshData(false); }, 4000);
    // 20s: sync from ElevenLabs API in case webhook was slow/missed
    setTimeout(() => { this.refreshData(true); this.setStatus("online","Connected"); }, 20000);
    // 60s: final sync for slow ElevenLabs processing
    setTimeout(() => { this.refreshData(true); }, 60000);
  }

  async refreshData(sync = false) {
    if (sync) {
      // Pull any missing transcripts directly from ElevenLabs API
      try { await fetch("/api/sync", { method: "POST" }); } catch {}
    }
    try {
      const [cr, ar] = await Promise.all([fetch("/api/conversations"), fetch("/api/appointments")]);
      if (cr.ok) this.renderConvs((await cr.json()).conversations ?? []);
      if (ar.ok) this.renderAppts((await ar.json()).appointments ?? []);
      const note = document.getElementById("refresh-note");
      if (note) note.textContent = "Last updated " + new Date().toLocaleTimeString("en-US");
    } catch {}
  }

  renderConvs(data) {
    const badge = document.getElementById("conv-count");
    const tbody = document.getElementById("conv-body");
    if (badge) badge.textContent = data.length;
    if (!tbody) return;
    if (!data.length) { tbody.innerHTML = `<tr><td colspan="5" class="empty">No conversations yet</td></tr>`; return; }
    tbody.innerHTML = data.map(c => `<tr>
      <td class="id-cell">${esc(c.caller_id.slice(0,16))}</td>
      <td class="clip">${esc((c.transcript||c.summary||"").slice(0,100))}</td>
      <td><div class="audio-wrap" data-cid="${esc(c.caller_id)}">${this._audioCell(c.caller_id)}</div></td>
      <td>${pill(c.booking_status)}</td>
      <td style="white-space:nowrap">${fmtDate(c.created_at)}</td>
    </tr>`).join("");
    this.showBanner(data[0]);
  }

  _audioCell(cid) {
    return `<button class="audio-load-btn" onclick="window.app.loadAudio('${esc(cid)}')">▶ Play Recording</button>`;
  }

  async loadAudio(cid) {
    const wrap = document.querySelector(`.audio-wrap[data-cid="${cid}"]`);
    if (!wrap) return;
    wrap.innerHTML = `<span class="audio-checking">Checking…</span>`;
    try {
      const check = await fetch(`/api/conversations/${cid}/audio`, { method: "HEAD" });
      if (check.ok) {
        wrap.innerHTML = `<audio class="audio-player" controls src="/api/conversations/${encodeURIComponent(cid)}/audio"></audio>`;
      } else {
        wrap.innerHTML = `<span class="no-audio">Still processing…
          <button class="audio-retry-btn" onclick="window.app.loadAudio('${esc(cid)}')">Retry</button>
        </span>`;
      }
    } catch {
      wrap.innerHTML = `<button class="audio-load-btn" onclick="window.app.loadAudio('${esc(cid)}')">▶ Play Recording</button>`;
    }
  }

  renderAppts(data) {
    const badge = document.getElementById("appt-count");
    const tbody = document.getElementById("appt-body");
    if (badge) badge.textContent = data.length;
    if (!tbody) return;
    if (!data.length) { tbody.innerHTML = `<tr><td colspan="6" class="empty">No appointments yet</td></tr>`; return; }
    const doctorOptions = this.doctors.map(d =>
      `<option value="${esc(d.name)}">${esc(d.name)}</option>`
    ).join("");

    tbody.innerHTML = data.map(a => {
      const options = this.doctors.map(d =>
        `<option value="${esc(d.name)}" ${a.doctor === d.name ? "selected" : ""}>${esc(d.name)}</option>`
      ).join("");
      return `<tr data-id="${esc(a.id)}">
        <td><strong style="color:#f0f0f0">${esc(a.patient_name)}</strong></td>
        <td>${esc(a.service_type)}</td>
        <td>
          <select class="doctor-select" data-id="${esc(a.id)}" onchange="window.app.updateDoctor('${esc(a.id)}', this.value)">
            <option value="Unassigned" ${(!a.doctor || a.doctor==='Unassigned') ? 'selected' : ''}>Unassigned</option>
            ${options}
          </select>
        </td>
        <td style="white-space:nowrap">${fmtDate(a.appointment_time)}</td>
        <td>${pill(a.status)}</td>
        <td>
          <button class="delete-btn" onclick="window.app.deleteAppointment('${esc(a.id)}')" title="Delete appointment">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>
          </button>
        </td>
      </tr>`;
    }).join("");
  }

  async deleteAppointment(id) {
    if (!confirm("Delete this appointment?")) return;
    try {
      const r = await fetch(`/api/appointments/${id}`, { method: "DELETE" });
      if (r.ok) {
        const row = document.querySelector(`tr[data-id="${id}"]`);
        if (row) row.remove();
        const badge = document.getElementById("appt-count");
        if (badge) badge.textContent = Math.max(0, parseInt(badge.textContent || "0") - 1);
      }
    } catch {}
  }

  async updateDoctor(id, doctor) {
    try {
      await fetch(`/api/appointments/${id}/doctor`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doctor }),
      });
    } catch {}
  }

  showBanner(conv) {
    if (!conv) return;
    const banner = document.getElementById("booking-banner");
    const icon   = document.getElementById("booking-icon");
    const text   = document.getElementById("booking-text");
    if (!banner||!icon||!text) return;
    if (conv.booking_status === "success") {
      banner.className = "booking-banner success";
      icon.textContent = "";
      text.textContent = "Last call: appointment confirmed!";
    } else if (conv.booking_status === "failed") {
      banner.className = "booking-banner failed";
      icon.textContent = "";
      text.textContent = "Last call: booking attempt failed.";
    } else {
      banner.classList.add("hidden");
    }
  }

  setStatus(state, text) {
    const dot   = document.getElementById("status-dot");
    const label = document.getElementById("status-text");
    if (dot)   dot.className = `nav-dot ${state}`;
    if (label) label.textContent = text;
  }
}

window.addEventListener("DOMContentLoaded", () => { window.app = new App(); });


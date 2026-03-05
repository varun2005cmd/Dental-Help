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
    const sec = document.getElementById("transcript-section");
    const box = document.getElementById("live-transcript");
    if (sec) sec.classList.remove("hidden");
    if (box) box.innerHTML = "";
    const banner = document.getElementById("booking-banner");
    if (banner) { banner.className = "booking-banner hidden"; }
    this.setStatus("online","Call in progress");
  }

  onMessage(detail) {
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
    setTimeout(() => { this.refreshData(); this.setStatus("online","Connected"); }, 5000);
  }

  async refreshData() {
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
    if (!data.length) { tbody.innerHTML = `<tr><td colspan="4" class="empty">No conversations yet</td></tr>`; return; }
    tbody.innerHTML = data.map(c => `<tr>
      <td class="id-cell">${esc(c.caller_id.slice(0,16))}</td>
      <td class="clip">${esc((c.transcript||c.summary||"").slice(0,100))}</td>
      <td>${pill(c.booking_status)}</td>
      <td style="white-space:nowrap">${fmtDate(c.created_at)}</td>
    </tr>`).join("");
    this.showBanner(data[0]);
  }

  renderAppts(data) {
    const badge = document.getElementById("appt-count");
    const tbody = document.getElementById("appt-body");
    if (badge) badge.textContent = data.length;
    if (!tbody) return;
    if (!data.length) { tbody.innerHTML = `<tr><td colspan="4" class="empty">No appointments yet</td></tr>`; return; }
    tbody.innerHTML = data.map(a => `<tr>
      <td><strong style="color:#f0f0f0">${esc(a.patient_name)}</strong></td>
      <td>${esc(a.service_type)}</td>
      <td style="white-space:nowrap">${fmtDate(a.appointment_time)}</td>
      <td>${pill(a.status)}</td>
    </tr>`).join("");
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

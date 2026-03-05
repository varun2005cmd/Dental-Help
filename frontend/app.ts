/**
 * BrightSmile Dental Clinic — Frontend App
 * TypeScript source (compiled to app.js by tsc — see tsconfig.json)
 */

// ── Types ──────────────────────────────────────────────────────────────────

interface Conversation {
  id: string;
  caller_id: string;
  transcript: string;
  booking_status: "success" | "failed" | "incomplete";
  call_duration_secs?: number;
  created_at: string;
  summary?: string;
}

interface Appointment {
  id: string;
  conversation_id: string;
  patient_name: string;
  service_type: string;
  appointment_time: string;
  status: "confirmed" | "rejected";
  created_at: string;
}

interface ApiConfig {
  agent_id: string;
  clinic_name: string;
}

declare global {
  interface Window {
    DEMODENTAL_CONFIG?: { agentId: string };
    app?: App;
  }
}

// ── Utilities ─────────────────────────────────────────────────────────────

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatDate(iso: string): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-US", {
      year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit", timeZone: "UTC",
    }) + " UTC";
  } catch {
    return iso;
  }
}

function pillHtml(value: string): string {
  const cls = `pill pill-${value.toLowerCase()}`;
  return `<span class="${cls}">${escapeHtml(value)}</span>`;
}

function truncate(str: string, max = 200): string {
  if (str.length <= max) return str;
  return str.slice(0, max) + "…";
}

// ── App Class ─────────────────────────────────────────────────────────────

class App {
  private agentId: string = "";
  private autoRefreshTimer: number | null = null;
  private liveTranscriptLines: string[] = [];

  constructor() {
    this.init();
  }

  async init(): Promise<void> {
    // Get agent_id — prefer runtime config.js, fall back to /api/config
    if (window.DEMODENTAL_CONFIG?.agentId) {
      this.agentId = window.DEMODENTAL_CONFIG.agentId;
    } else {
      try {
        const res = await fetch("/api/config");
        if (res.ok) {
          const cfg: ApiConfig = await res.json();
          this.agentId = cfg.agent_id;
        }
      } catch {
        console.warn("Could not fetch /api/config");
      }
    }

    this.mountWidget();
    this.setupAutoRefresh();
    await this.refreshData();
    this.setStatus("online", "Backend connected");
  }

  // ── Widget ────────────────────────────────────────────────────────────────

  mountWidget(): void {
    const placeholder = document.getElementById("widget-placeholder");
    const mount = document.getElementById("elevenlabs-widget-mount");

    if (!this.agentId) {
      if (placeholder) {
        placeholder.innerHTML =
          "<p>⚠️ Agent ID not configured.<br/>" +
          "<small>Run <code>python scripts/setup_agent.py</code> to create the agent " +
          "and regenerate <code>frontend/config.js</code>.</small></p>";
      }
      this.setStatus("error", "Agent not configured");
      return;
    }

    if (placeholder) placeholder.classList.add("hidden");

    // Create the ElevenLabs custom element
    const widget = document.createElement("elevenlabs-convai");
    widget.setAttribute("agent-id", this.agentId);
    mount?.appendChild(widget);

    // Listen for call events to show live transcript
    document.addEventListener("elevenlabs-convai:call", (event: Event) => {
      const ce = event as CustomEvent;
      this.handleCallStart(ce.detail);
    });

    document.addEventListener("elevenlabs-convai:message", (event: Event) => {
      const ce = event as CustomEvent;
      this.handleMessage(ce.detail);
    });

    document.addEventListener("elevenlabs-convai:disconnect", () => {
      this.handleCallEnd();
    });
  }

  handleCallStart(_detail: unknown): void {
    this.liveTranscriptLines = [];
    const box = document.getElementById("live-transcript-box");
    const content = document.getElementById("live-transcript-content");
    if (box) box.classList.remove("hidden");
    if (content) content.innerHTML = "";

    const bookingResult = document.getElementById("booking-result");
    if (bookingResult) {
      bookingResult.className = "booking-result hidden";
      bookingResult.classList.add("hidden");
    }

    this.setStatus("online", "Call in progress…");
  }

  handleMessage(detail: { message?: { role?: string; content?: string } }): void {
    const role = detail?.message?.role ?? "";
    const content = detail?.message?.content ?? "";
    if (!content) return;

    const cls = role === "agent" ? "agent-line" : "user-line";
    const label = role === "agent" ? "Aria" : "You";
    const line = `<div class="${cls}"><strong>${label}:</strong> ${escapeHtml(content)}</div>`;
    this.liveTranscriptLines.push(line);

    const contentEl = document.getElementById("live-transcript-content");
    if (contentEl) {
      contentEl.innerHTML = this.liveTranscriptLines.join("");
      contentEl.scrollTop = contentEl.scrollHeight;
    }
  }

  handleCallEnd(): void {
    this.setStatus("online", "Call ended — fetching results…");
    // Wait 5 seconds for the webhook to fire and be processed, then refresh
    setTimeout(() => {
      this.refreshData();
      this.setStatus("online", "Backend connected");
    }, 5000);
  }

  // ── Data Fetching ─────────────────────────────────────────────────────────

  async refreshData(): Promise<void> {
    const btn = document.getElementById("refresh-btn");
    if (btn) btn.textContent = "⏳ Loading…";

    try {
      const [convRes, apptRes] = await Promise.all([
        fetch("/api/conversations"),
        fetch("/api/appointments"),
      ]);

      if (convRes.ok) {
        const data = await convRes.json();
        this.renderConversations(data.conversations ?? []);
      }

      if (apptRes.ok) {
        const data = await apptRes.json();
        this.renderAppointments(data.appointments ?? []);
      }

      const now = new Date().toLocaleTimeString("en-US");
      const lastRefreshEl = document.getElementById("last-refresh");
      if (lastRefreshEl) lastRefreshEl.textContent = `Last refreshed: ${now}`;
    } catch (err) {
      console.error("Failed to fetch data:", err);
      this.setStatus("error", "Fetch error — retrying…");
    } finally {
      if (btn) btn.textContent = "🔄 Refresh Data";
    }
  }

  // ── Render Conversations ──────────────────────────────────────────────────

  renderConversations(conversations: Conversation[]): void {
    const tbody = document.getElementById("conversations-body");
    const badge = document.getElementById("conv-count");
    if (!tbody) return;

    if (badge) badge.textContent = String(conversations.length);

    if (conversations.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No conversations yet. Make a call!</td></tr>`;
      return;
    }

    tbody.innerHTML = conversations.map((c) => `
      <tr>
        <td class="id-cell" title="${escapeHtml(c.caller_id)}">${escapeHtml(c.caller_id.slice(0, 20))}…</td>
        <td>
          <div class="transcript-cell">${escapeHtml(truncate(c.transcript || c.summary || "(no transcript)", 200))}</div>
        </td>
        <td>${pillHtml(c.booking_status)}</td>
        <td>${c.call_duration_secs != null ? c.call_duration_secs + "s" : "—"}</td>
        <td>${formatDate(c.created_at)}</td>
      </tr>
    `).join("");

    // Show booking result banner from the most recent conversation
    this.showBookingBanner(conversations[0]);
  }

  showBookingBanner(conv: Conversation | undefined): void {
    if (!conv) return;
    const banner = document.getElementById("booking-result");
    const icon = document.getElementById("booking-icon");
    const msg = document.getElementById("booking-message");
    if (!banner || !icon || !msg) return;

    if (conv.booking_status === "success") {
      banner.className = "booking-result success";
      icon.textContent = "✅";
      msg.textContent = "Last booking: Appointment successfully confirmed!";
    } else if (conv.booking_status === "failed") {
      banner.className = "booking-result failed";
      icon.textContent = "❌";
      msg.textContent = "Last booking: Booking attempt failed (slot may be taken or info incomplete).";
    } else {
      banner.classList.add("hidden");
      return;
    }
  }

  // ── Render Appointments ───────────────────────────────────────────────────

  renderAppointments(appointments: Appointment[]): void {
    const tbody = document.getElementById("appointments-body");
    const badge = document.getElementById("appt-count");
    if (!tbody) return;

    if (badge) badge.textContent = String(appointments.length);

    if (appointments.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No appointments yet.</td></tr>`;
      return;
    }

    tbody.innerHTML = appointments.map((a) => `
      <tr>
        <td><strong>${escapeHtml(a.patient_name)}</strong></td>
        <td>${escapeHtml(a.service_type)}</td>
        <td>${formatDate(a.appointment_time)}</td>
        <td>${pillHtml(a.status)}</td>
        <td>${formatDate(a.created_at)}</td>
      </tr>
    `).join("");
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  setStatus(state: "online" | "offline" | "error", text: string): void {
    const dot = document.getElementById("status-dot");
    const label = document.getElementById("status-text");
    if (dot) dot.className = `status-dot ${state}`;
    if (label) label.textContent = text;
  }

  setupAutoRefresh(): void {
    const toggle = document.getElementById("auto-refresh-toggle") as HTMLInputElement | null;
    const startTimer = (): void => {
      this.stopAutoRefresh();
      this.autoRefreshTimer = window.setInterval(() => this.refreshData(), 10_000);
    };

    startTimer(); // start immediately

    toggle?.addEventListener("change", () => {
      if (toggle.checked) {
        startTimer();
      } else {
        this.stopAutoRefresh();
      }
    });
  }

  stopAutoRefresh(): void {
    if (this.autoRefreshTimer !== null) {
      clearInterval(this.autoRefreshTimer);
      this.autoRefreshTimer = null;
    }
  }
}

// ── Bootstrap ─────────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", () => {
  window.app = new App();
});

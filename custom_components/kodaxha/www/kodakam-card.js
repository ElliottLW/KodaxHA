// =============================================================================
//  KodaxHA Card  v1.1.0
//  Home Assistant Lovelace custom card for Kodak Smart Home cameras.
//  https://github.com/anthonycmain/kodakam
//
//  Usage:
//    type: custom:kodaxha-card
//    camera_ip: 192.168.178.36
// =============================================================================

const CARD_VERSION = "1.1.0";

// ── Entity key helpers ────────────────────────────────────────────────────────
// The integration sets unique_ids as  kodaxha_{ip_slug}_{key}
// We discover them via hass.entities (registry) so we never have to hard-code
// generated entity IDs (which HA slugifies in unpredictable ways).

function ipSlug(ip) {
  return ip.replace(/\./g, "_");
}

function uniqueIdPrefix(ip) {
  return `kodaxha_${ipSlug(ip)}_`;
}

// =============================================================================
class KodaxHACard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass          = null;
    this._config        = null;
    this._entityMap     = null;   // { key → entity_id }
    this._pending       = {};     // optimistic UI: { key → { state, expires } }
    this._refreshTimer  = null;
    this._rendered      = false;
  }

  // ── Lovelace card protocol ────────────────────────────────────────────────

  static getStubConfig() {
    return { camera_ip: "192.168.x.x" };
  }

  setConfig(config) {
    if (!config || !config.camera_ip) {
      throw new Error("[kodaxha-card] camera_ip is required.  Example:\n  type: custom:kodaxha-card\n  camera_ip: 192.168.178.36");
    }
    this._config    = config;
    this._entityMap = null;
    this._render();
  }

  set hass(hass) {
    this._hass      = hass;
    this._entityMap = null;   // rebuild on every hass update (handles re-login)
    this._render();
  }

  getCardSize() { return 9; }

  // ── Lifecycle ─────────────────────────────────────────────────────────────

  connectedCallback() {
    // Refresh the camera snapshot image every 5 s
    this._refreshTimer = setInterval(() => this._tickImage(), 5000);
  }

  disconnectedCallback() {
    clearInterval(this._refreshTimer);
    this._refreshTimer = null;
  }

  // ── Entity discovery via registry ─────────────────────────────────────────

  _buildEntityMap() {
    if (!this._hass || !this._config) return {};
    const prefix = uniqueIdPrefix(this._config.camera_ip);
    const map = {};
    const registry = this._hass.entities || {};
    for (const entry of Object.values(registry)) {
      if (entry.platform === "kodaxha" && entry.unique_id && entry.unique_id.startsWith(prefix)) {
        const key = entry.unique_id.slice(prefix.length);
        map[key] = entry.entity_id;
      }
    }
    return map;
  }

  _emap() {
    if (!this._entityMap) this._entityMap = this._buildEntityMap();
    return this._entityMap;
  }

  _eid(key) {
    return this._emap()[key];
  }

  _haState(key) {
    const id = this._eid(key);
    return id ? (this._hass.states[id] || null) : null;
  }

  // Optimistic-aware state read
  _stateVal(key, fallback = "—") {
    const p = this._pending[key];
    if (p && p.expires > Date.now()) return p.state;
    if (p) delete this._pending[key];
    return this._haState(key)?.state ?? fallback;
  }

  _attrVal(key, attr, fallback = null) {
    return this._haState(key)?.attributes?.[attr] ?? fallback;
  }

  // ── HA service calls ──────────────────────────────────────────────────────

  _toggle(key) {
    const id = this._eid(key);
    if (!id) return;
    const on = this._stateVal(key) === "on";
    this._pending[key] = { state: on ? "off" : "on", expires: Date.now() + 6000 };
    this._hass.callService("switch", on ? "turn_off" : "turn_on", { entity_id: id });
    this._patchToggle(key, !on);
  }

  _selectOption(key, option) {
    const id = this._eid(key);
    if (!id) return;
    this._hass.callService("select", "select_option", { entity_id: id, option });
  }

  _pressButton(key) {
    const id = this._eid(key);
    if (!id) return;
    this._hass.callService("button", "press", { entity_id: id });
    // Brief visual feedback
    const btn = this.shadowRoot.querySelector(`[data-key="${key}"]`);
    if (btn) {
      btn.classList.add("btn-active");
      setTimeout(() => btn.classList.remove("btn-active"), 600);
    }
  }

  // Patch a toggle in-place without full re-render for snappier UX
  _patchToggle(key, isOn) {
    const btn = this.shadowRoot.querySelector(`.toggle[data-key="${key}"]`);
    if (btn) btn.classList.toggle("on", isOn);
  }

  // Refresh camera image src (append timestamp to bust cache)
  _tickImage() {
    const img = this.shadowRoot.querySelector(".cam-img");
    if (img && img.dataset.base) {
      img.src = img.dataset.base + "&_t=" + Date.now();
    }
  }

  // ── Rendering ─────────────────────────────────────────────────────────────

  _render() {
    if (!this._config || !this._hass) return;

    const ip  = this._config.camera_ip;
    const em  = this._emap();

    // ── Sensor values ──
    const battery    = this._stateVal("bat");
    const wifi       = this._stateVal("wifi");
    const temp       = this._stateVal("tem_float");
    const hum        = this._stateVal("hum_float");
    const charging   = this._stateVal("charge") === "on";
    const sdcap      = this._stateVal("sdcap");
    const sdfree     = this._stateVal("sdfree");

    // ── Switch states ──
    const motionOn   = this._stateVal("motion_detection") === "on";
    const soundOn    = this._stateVal("sound_detection")  === "on";
    const ledOn      = this._stateVal("blue_led")         === "on";

    // ── Select states and options ──
    const nightVis   = this._stateVal("night_vision",        "auto");
    const nvOpts     = this._attrVal("night_vision",  "options", ["auto", "on", "off"]);
    const res        = this._stateVal("resolution",          "720p (HD)");
    const resOpts    = this._attrVal("resolution",    "options", ["480p (Standard)", "720p (HD)"]);
    const sens       = this._stateVal("motion_sensitivity",  "medium");
    const sensOpts   = this._attrVal("motion_sensitivity", "options", ["low", "medium", "high"]);
    const orient     = this._stateVal("orientation",         "normal");
    const orientOpts = this._attrVal("orientation",  "options", ["normal", "ceiling_mount"]);

    // ── Camera entity ──
    const camEid     = em["camera"];
    const camBase    = camEid ? `/api/camera_proxy/${camEid}` : null;
    const camSrc     = camBase ? camBase + "&_t=" + Date.now() : null;

    // ── Availability ──
    const available  = Object.keys(em).length > 0;

    // ── Helpers ──
    const fmtOpt = (o) => o.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    const selectHtml = (key, val, opts) => `
      <select class="ha-select" data-action="select" data-key="${key}">
        ${opts.map(o => `<option value="${o}"${o === val ? " selected" : ""}>${fmtOpt(o)}</option>`).join("")}
      </select>`;
    const toggleHtml = (key, on, icon, label) => `
      <div class="toggle-row">
        <span class="toggle-label">${icon} ${label}</span>
        <button class="toggle${on ? " on" : ""}" data-action="toggle" data-key="${key}" title="${on ? "Turn Off" : "Turn On"}">
          <div class="toggle-track"></div>
          <div class="toggle-thumb"></div>
        </button>
      </div>`;
    const statHtml = (icon, value, label) => `
      <div class="stat">
        <div class="stat-icon">${icon}</div>
        <div class="stat-value">${value}</div>
        <div class="stat-label">${label}</div>
      </div>`;

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }

        ha-card {
          overflow: hidden;
          display: flex;
          flex-direction: column;
        }

        /* ── Header ── */
        .header {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 14px 16px 12px;
          border-bottom: 1px solid var(--divider-color, rgba(0,0,0,.12));
        }
        .header-title {
          flex: 1;
          font-size: 16px;
          font-weight: 600;
          color: var(--primary-text-color);
        }
        .header-ip {
          font-size: 11px;
          color: var(--secondary-text-color);
          font-family: monospace;
        }
        .header-status {
          width: 8px; height: 8px;
          border-radius: 50%;
          background: ${available ? "var(--success-color, #4caf50)" : "var(--error-color, #f44336)"};
        }

        /* ── Camera feed ── */
        .cam-wrap {
          position: relative;
          background: #000;
          width: 100%;
          aspect-ratio: 16/9;
          overflow: hidden;
        }
        .cam-img {
          width: 100%; height: 100%;
          object-fit: cover;
          display: block;
        }
        .cam-placeholder {
          width: 100%; height: 100%;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 8px;
          color: rgba(128,128,128,0.6);
          font-size: 13px;
        }
        .cam-icon { font-size: 44px; opacity: .35; }

        /* ── Stats row ── */
        .stats {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          border-bottom: 1px solid var(--divider-color, rgba(0,0,0,.12));
        }
        .stat {
          padding: 10px 6px;
          text-align: center;
          border-right: 1px solid var(--divider-color, rgba(0,0,0,.08));
        }
        .stat:last-child { border-right: none; }
        .stat-icon { font-size: 17px; margin-bottom: 3px; }
        .stat-value {
          font-size: 14px; font-weight: 700;
          color: var(--primary-text-color);
        }
        .stat-label {
          font-size: 10px; text-transform: uppercase; letter-spacing: .4px;
          color: var(--secondary-text-color);
          margin-top: 2px;
        }

        /* ── SD card bar ── */
        .sd-bar-wrap {
          padding: 0 16px 10px;
          display: ${parseInt(sdcap) > 0 ? "block" : "none"};
        }
        .sd-label {
          font-size: 11px; color: var(--secondary-text-color);
          display: flex; justify-content: space-between;
          margin-bottom: 4px;
        }
        .sd-bar {
          height: 4px;
          border-radius: 2px;
          background: var(--divider-color, rgba(0,0,0,.12));
          overflow: hidden;
        }
        .sd-fill {
          height: 100%;
          border-radius: 2px;
          background: var(--primary-color, #03a9f4);
          width: ${sdcap && sdfree && parseInt(sdcap) > 0
                    ? Math.round((1 - parseInt(sdfree) / parseInt(sdcap)) * 100)
                    : 0}%;
          transition: width 0.4s;
        }

        /* ── Sections ── */
        .section {
          padding: 12px 16px 8px;
          border-bottom: 1px solid var(--divider-color, rgba(0,0,0,.08));
        }
        .section:last-child { border-bottom: none; padding-bottom: 14px; }
        .section-title {
          font-size: 10px; font-weight: 700;
          text-transform: uppercase; letter-spacing: .7px;
          color: var(--secondary-text-color);
          margin-bottom: 10px;
        }

        /* ── Toggle rows ── */
        .toggle-row {
          display: flex; align-items: center;
          justify-content: space-between;
          padding: 5px 0;
        }
        .toggle-label {
          font-size: 14px;
          color: var(--primary-text-color);
          display: flex; align-items: center; gap: 8px;
        }
        .toggle {
          position: relative; width: 44px; height: 24px;
          cursor: pointer; border: none; background: none; padding: 0; flex-shrink: 0;
        }
        .toggle-track {
          position: absolute; inset: 0; border-radius: 12px;
          background: var(--switch-unchecked-color, rgba(0,0,0,.2));
          transition: background .18s;
        }
        .toggle.on .toggle-track { background: var(--primary-color, #03a9f4); }
        .toggle-thumb {
          position: absolute; top: 3px; left: 3px;
          width: 18px; height: 18px; border-radius: 50%;
          background: #fff;
          box-shadow: 0 1px 3px rgba(0,0,0,.3);
          transition: transform .18s;
        }
        .toggle.on .toggle-thumb { transform: translateX(20px); }

        /* ── Select rows ── */
        .select-row {
          display: flex; align-items: center;
          justify-content: space-between;
          padding: 5px 0;
        }
        .select-label {
          font-size: 14px;
          color: var(--primary-text-color);
          display: flex; align-items: center; gap: 8px;
        }
        .ha-select {
          background: var(--secondary-background-color, rgba(0,0,0,.06));
          border: 1px solid var(--divider-color, rgba(0,0,0,.2));
          border-radius: 6px;
          color: var(--primary-text-color);
          font-size: 13px;
          padding: 5px 8px;
          cursor: pointer;
          min-width: 140px;
          appearance: auto;
        }

        /* ── Melody buttons ── */
        .melody-grid {
          display: grid;
          grid-template-columns: repeat(6, 1fr);
          gap: 8px;
        }
        .melody-btn {
          background: var(--secondary-background-color, rgba(0,0,0,.06));
          border: 1px solid var(--divider-color, rgba(0,0,0,.12));
          border-radius: 8px;
          color: var(--primary-text-color);
          font-size: 14px; font-weight: 700;
          padding: 10px 4px;
          cursor: pointer; text-align: center;
          transition: background .12s, transform .1s;
        }
        .melody-btn:hover { background: var(--primary-color, #03a9f4); color: #fff; }
        .btn-active { transform: scale(.92) !important; }
        .stop-btn { font-size: 18px; }
        .stop-btn:hover { background: var(--error-color, #f44336); color: #fff; }

        /* ── Restart ── */
        .danger-row {
          display: flex; justify-content: flex-end; padding-top: 4px;
        }
        .restart-btn {
          background: transparent;
          border: 1px solid var(--error-color, #f44336);
          border-radius: 8px;
          color: var(--error-color, #f44336);
          font-size: 13px; font-weight: 600;
          padding: 8px 16px;
          cursor: pointer;
          display: flex; align-items: center; gap: 6px;
          transition: background .15s;
        }
        .restart-btn:hover {
          background: var(--error-color, #f44336);
          color: #fff;
        }

        /* ── Offline overlay ── */
        .offline {
          pointer-events: none;
          opacity: .45;
          filter: grayscale(.6);
        }
        .offline-badge {
          text-align: center;
          font-size: 12px;
          color: var(--error-color, #f44336);
          padding: 6px 16px;
          font-weight: 600;
        }
      </style>

      <ha-card>
        <!-- Header -->
        <div class="header">
          <span style="font-size:20px">📷</span>
          <span class="header-title">Kodak Camera</span>
          <span class="header-ip">${ip}</span>
          <div class="header-status" title="${available ? "Online" : "Offline"}"></div>
        </div>

        ${!available ? `<div class="offline-badge">⚠️ No entities found — check integration is loaded</div>` : ""}

        <!-- Camera feed -->
        <div class="cam-wrap">
          ${camSrc
            ? `<img class="cam-img" data-base="${camBase}" src="${camSrc}" alt="Camera feed" />`
            : `<div class="cam-placeholder">
                 <div class="cam-icon">📷</div>
                 <div>No stream configured</div>
                 <div style="font-size:11px;opacity:.6">Settings → Integrations → KodaxHA → Configure</div>
               </div>`}
        </div>

        <!-- Stats row -->
        <div class="stats ${available ? "" : "offline"}">
          ${statHtml(charging ? "⚡" : "🔋", battery !== "—" ? battery + "%" : "—", "Battery")}
          ${statHtml("📶", wifi !== "—" ? wifi + "%" : "—", "WiFi")}
          ${statHtml("🌡️", temp !== "—" && parseFloat(temp) > -273 ? parseFloat(temp).toFixed(1) + "°C" : "—", "Temp")}
          ${statHtml("💧", hum !== "—" && parseFloat(hum) > -1 ? parseFloat(hum).toFixed(0) + "%" : "—", "Humidity")}
        </div>

        <!-- SD card usage -->
        <div class="sd-bar-wrap">
          <div class="sd-label">
            <span>💾 SD Card</span>
            <span>${sdfree !== "—" ? sdfree + " MB free" : ""}</span>
          </div>
          <div class="sd-bar"><div class="sd-fill"></div></div>
        </div>

        <!-- Detection controls -->
        <div class="section ${available ? "" : "offline"}">
          <div class="section-title">Detection</div>
          ${toggleHtml("motion_detection", motionOn, "🔍", "Motion Detection")}
          ${toggleHtml("sound_detection",  soundOn,  "🎤", "Sound Detection")}
          <div class="select-row">
            <span class="select-label">📊 Sensitivity</span>
            ${selectHtml("motion_sensitivity", sens, sensOpts)}
          </div>
        </div>

        <!-- Camera settings -->
        <div class="section ${available ? "" : "offline"}">
          <div class="section-title">Camera Settings</div>
          <div class="select-row">
            <span class="select-label">🌙 Night Vision</span>
            ${selectHtml("night_vision", nightVis, nvOpts)}
          </div>
          <div class="select-row">
            <span class="select-label">🎬 Resolution</span>
            ${selectHtml("resolution", res, resOpts)}
          </div>
          <div class="select-row">
            <span class="select-label">↕️ Orientation</span>
            ${selectHtml("orientation", orient, orientOpts)}
          </div>
          ${toggleHtml("blue_led", ledOn, "💡", "Blue LED")}
        </div>

        <!-- Melodies -->
        <div class="section ${available ? "" : "offline"}">
          <div class="section-title">Melodies</div>
          <div class="melody-grid">
            ${[1,2,3,4,5].map(n =>
              `<button class="melody-btn" data-action="button" data-key="melody${n}" title="Play melody ${n}">${n}</button>`
            ).join("")}
            <button class="melody-btn stop-btn" data-action="button" data-key="melody_stop" title="Stop melody">■</button>
          </div>
        </div>

        <!-- System -->
        <div class="section ${available ? "" : "offline"}">
          <div class="danger-row">
            <button class="restart-btn" data-action="button" data-key="restart">🔄 Restart Camera</button>
          </div>
        </div>
      </ha-card>
    `;

    // ── Event listeners ────────────────────────────────────────────────────
    this.shadowRoot.querySelectorAll("[data-action]").forEach(el => {
      const action = el.dataset.action;
      const key    = el.dataset.key;

      if (action === "toggle") {
        el.addEventListener("click", () => this._toggle(key));
      } else if (action === "button") {
        el.addEventListener("click", () => this._pressButton(key));
      } else if (action === "select") {
        el.addEventListener("change", e => this._selectOption(key, e.target.value));
      }
    });

    this._rendered = true;
  }
}

// ── Registration ──────────────────────────────────────────────────────────────
customElements.define("kodaxha-card", KodaxHACard);

window.customCards = window.customCards || [];
if (!window.customCards.find(c => c.type === "kodaxha-card")) {
  window.customCards.push({
    type: "kodaxha-card",
    name: "KodaxHA Camera Card",
    description: "Control panel for Kodak Smart Home cameras",
    preview: false,
    documentationURL: "https://github.com/anthonycmain/kodakam",
  });
}

console.info(
  `%c KODAXHA CARD %c v${CARD_VERSION} `,
  "background:#ED0000;color:#fff;font-weight:bold;padding:2px 6px;border-radius:3px 0 0 3px",
  "background:#333;color:#fff;font-weight:bold;padding:2px 6px;border-radius:0 3px 3px 0"
);

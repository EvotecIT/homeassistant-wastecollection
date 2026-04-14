class WasteCollectionScheduleEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._loaded = false;
    this._state = null;
    this._draftEntries = [];
    this._selectedEntryId = null;
    this._busy = false;
    this._status = "";
    this._error = "";
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._loaded) {
      this._loaded = true;
      this._loadData();
      return;
    }
    this._render();
  }

  connectedCallback() {
    if (this._hass && !this._loaded) {
      this._loaded = true;
      this._loadData();
    } else {
      this._render();
    }
  }

  async _loadData() {
    if (!this._hass) {
      return;
    }
    this._busy = true;
    this._error = "";
    this._render();
    try {
      this._state = await this._hass.callWS({
        type: "waste_collection_schedule/editor/get_data",
      });
      this._draftEntries = JSON.parse(JSON.stringify(this._state.entries));
      if (
        !this._selectedEntryId ||
        !this._draftEntries.some((entry) => entry.entry_id === this._selectedEntryId)
      ) {
        this._selectedEntryId = this._draftEntries[0]?.entry_id ?? null;
      }
    } catch (err) {
      this._error = this._messageFromError(err);
    } finally {
      this._busy = false;
      this._render();
    }
  }

  _messageFromError(err) {
    if (!err) {
      return "Unknown error";
    }
    if (typeof err === "string") {
      return err;
    }
    return err.body?.message || err.message || "Unknown error";
  }

  _currentEntry() {
    return this._draftEntries.find((entry) => entry.entry_id === this._selectedEntryId);
  }

  _sourceEntry() {
    return this._state?.entries?.find((entry) => entry.entry_id === this._selectedEntryId);
  }

  _findSensor(entry, originalName) {
    return entry?.sensors?.find((sensor) => sensor.original_name === originalName);
  }

  _findType(entry, rawType) {
    return entry?.types?.find((type) => type.raw_type === rawType);
  }

  _updateSensorField(originalName, field, value) {
    const sensor = this._findSensor(this._currentEntry(), originalName);
    if (!sensor) {
      return;
    }
    sensor.config[field] = value;
    if (field === "name" && !sensor.config.name) {
      sensor.config.name = "";
    }
    sensor.preview_error = "";
    this._render();
  }

  _updateTypeField(rawType, field, value) {
    const typeConfig = this._findType(this._currentEntry(), rawType);
    if (!typeConfig) {
      return;
    }
    typeConfig.config[field] = value;
    this._render();
  }

  _matchPreset(template, presets) {
    if (!template) {
      return "__default__";
    }
    const matched = Object.entries(presets).find(([, value]) => value === template);
    return matched ? matched[0] : "__custom__";
  }

  _escape(text) {
    return String(text ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  _renderStatus() {
    if (this._error) {
      return `<div class="banner error">${this._escape(this._error)}</div>`;
    }
    if (this._status) {
      return `<div class="banner success">${this._escape(this._status)}</div>`;
    }
    return "";
  }

  _renderEntryPicker() {
    if (!this._draftEntries.length) {
      return "";
    }
    if (this._draftEntries.length === 1) {
      return `<div class="entry-chip">${this._escape(this._draftEntries[0].title)}</div>`;
    }

    const options = this._draftEntries
      .map(
        (entry) =>
          `<option value="${this._escape(entry.entry_id)}" ${
            entry.entry_id === this._selectedEntryId ? "selected" : ""
          }>${this._escape(entry.title)}</option>`
      )
      .join("");

    return `
      <label class="field">
        <span>Waste source</span>
        <select data-action="select-entry">${options}</select>
      </label>
    `;
  }

  _renderSensor(sensor) {
    const presets = this._state.presets;
    const statePreset = this._matchPreset(
      sensor.config.value_template || "",
      presets.value_templates
    );
    const datePreset = this._matchPreset(
      sensor.config.date_template || "",
      presets.date_templates
    );

    const displayOptions = presets.details_formats
      .map(
        (option) =>
          `<option value="${this._escape(option.value)}" ${
            option.value === (sensor.config.details_format || "upcoming") ? "selected" : ""
          }>${this._escape(option.label)}</option>`
      )
      .join("");

    const statePresetOptions = [
      `<option value="__default__" ${statePreset === "__default__" ? "selected" : ""}>Default</option>`,
      ...Object.keys(presets.value_templates).map(
        (label) =>
          `<option value="${this._escape(label)}" ${
            statePreset === label ? "selected" : ""
          }>${this._escape(label)}</option>`
      ),
      `<option value="__custom__" ${statePreset === "__custom__" ? "selected" : ""}>Custom</option>`,
    ].join("");

    const datePresetOptions = [
      `<option value="__default__" ${datePreset === "__default__" ? "selected" : ""}>Default</option>`,
      ...Object.keys(presets.date_templates).map(
        (label) =>
          `<option value="${this._escape(label)}" ${
            datePreset === label ? "selected" : ""
          }>${this._escape(label)}</option>`
      ),
      `<option value="__custom__" ${datePreset === "__custom__" ? "selected" : ""}>Custom</option>`,
    ].join("");

    const previewLines = (sensor.preview?.detail_lines || [])
      .map(
        (line) =>
          `<div class="preview-line"><span>${this._escape(line.label)}</span><strong>${this._escape(
            line.value
          )}</strong></div>`
      )
      .join("");

    return `
      <details class="editor-card" open>
        <summary>
          <div>
            <div class="summary-title">${this._escape(sensor.config.name || sensor.original_name)}</div>
            <div class="summary-subtitle">${this._escape(sensor.preview?.state || "-")}</div>
          </div>
        </summary>
        <div class="editor-body">
          <div class="grid two">
            <label class="field">
              <span>Sensor name</span>
              <input data-kind="sensor" data-original-name="${this._escape(
                sensor.original_name
              )}" data-field="name" value="${this._escape(sensor.config.name || "")}" />
            </label>
            <label class="field">
              <span>More-info layout</span>
              <select data-kind="sensor" data-original-name="${this._escape(
                sensor.original_name
              )}" data-field="details_format">${displayOptions}</select>
            </label>
          </div>

          <div class="grid two">
            <label class="field">
              <span>State text preset</span>
              <select data-kind="sensor-preset" data-template-kind="value" data-original-name="${this._escape(
                sensor.original_name
              )}">${statePresetOptions}</select>
            </label>
            <label class="field checkbox">
              <span>Expose days-to value</span>
              <input type="checkbox" data-kind="sensor" data-original-name="${this._escape(
                sensor.original_name
              )}" data-field="add_days_to" ${
                sensor.config.add_days_to ? "checked" : ""
              } />
            </label>
          </div>

          <label class="field">
            <span>Custom state text</span>
            <textarea rows="3" data-kind="sensor" data-original-name="${this._escape(
              sensor.original_name
            )}" data-field="value_template" placeholder="{{ value.types|join(', ') }} in {{ value.daysTo }} days">${this._escape(
      sensor.config.value_template || ""
    )}</textarea>
            <small>Use Home Assistant template syntax. Leave empty for the built-in default.</small>
          </label>

          <label class="field">
            <span>Date display preset</span>
            <select data-kind="sensor-preset" data-template-kind="date" data-original-name="${this._escape(
              sensor.original_name
            )}">${datePresetOptions}</select>
          </label>

          <label class="field">
            <span>Custom date display</span>
            <textarea rows="2" data-kind="sensor" data-original-name="${this._escape(
              sensor.original_name
            )}" data-field="date_template" placeholder="{{ value.date.strftime('%d.%m.%Y') }}">${this._escape(
      sensor.config.date_template || ""
    )}</textarea>
            <small>This affects the detailed upcoming list shown in more-info.</small>
          </label>

          <div class="preview-box">
            <div class="preview-title">Preview</div>
            <div class="preview-state">${this._escape(sensor.preview?.state || "-")}</div>
            ${
              sensor.preview_error
                ? `<div class="inline-error">${this._escape(sensor.preview_error)}</div>`
                : previewLines || '<div class="muted">No extra details.</div>'
            }
          </div>

          <div class="actions">
            <button data-action="preview-sensor" data-original-name="${this._escape(
              sensor.original_name
            )}">Preview</button>
            <button data-action="reset-sensor" data-original-name="${this._escape(
              sensor.original_name
            )}">Reset</button>
            <button class="primary" data-action="save-sensor" data-original-name="${this._escape(
              sensor.original_name
            )}">Save</button>
          </div>
        </div>
      </details>
    `;
  }

  _renderType(typeConfig) {
    return `
      <details class="editor-card" open>
        <summary>
          <div>
            <div class="summary-title">${this._escape(typeConfig.display_name)}</div>
            <div class="summary-subtitle">${this._escape(typeConfig.raw_type)}</div>
          </div>
        </summary>
        <div class="editor-body">
          <div class="grid two">
            <label class="field">
              <span>Display name</span>
              <input data-kind="type" data-raw-type="${this._escape(
                typeConfig.raw_type
              )}" data-field="alias" value="${this._escape(typeConfig.config.alias || "")}" />
            </label>
            <label class="field checkbox">
              <span>Visible</span>
              <input type="checkbox" data-kind="type" data-raw-type="${this._escape(
                typeConfig.raw_type
              )}" data-field="show" ${typeConfig.config.show ? "checked" : ""} />
            </label>
          </div>
          <div class="actions">
            <button data-action="reset-type" data-raw-type="${this._escape(
              typeConfig.raw_type
            )}">Reset</button>
            <button class="primary" data-action="save-type" data-raw-type="${this._escape(
              typeConfig.raw_type
            )}">Save</button>
          </div>
        </div>
      </details>
    `;
  }

  _render() {
    const entry = this._currentEntry();
    const sensors = entry?.sensors || [];
    const types = entry?.types || [];

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          min-height: 100%;
          background: var(--lovelace-background, var(--primary-background-color));
          color: var(--primary-text-color);
        }
        .page {
          padding: 24px;
          max-width: 1400px;
          margin: 0 auto;
        }
        .hero {
          display: flex;
          justify-content: space-between;
          align-items: end;
          gap: 16px;
          margin-bottom: 20px;
        }
        .hero h1 {
          margin: 0;
          font-size: 2rem;
        }
        .hero p {
          margin: 8px 0 0;
          color: var(--secondary-text-color);
        }
        .banner {
          border-radius: 12px;
          padding: 12px 16px;
          margin-bottom: 18px;
        }
        .banner.error {
          background: color-mix(in srgb, var(--error-color) 18%, transparent);
          color: var(--error-color);
        }
        .banner.success {
          background: color-mix(in srgb, var(--success-color, #2e7d32) 18%, transparent);
          color: var(--success-color, #2e7d32);
        }
        .entry-chip,
        select,
        input,
        textarea,
        button {
          font: inherit;
        }
        .entry-chip {
          padding: 12px 16px;
          border-radius: 999px;
          background: var(--card-background-color);
          border: 1px solid var(--divider-color);
        }
        .layout {
          display: grid;
          grid-template-columns: 1.4fr 1fr;
          gap: 20px;
        }
        .section {
          background: var(--card-background-color);
          border-radius: 20px;
          border: 1px solid var(--divider-color);
          padding: 18px;
        }
        .section h2 {
          margin: 0 0 6px;
          font-size: 1.25rem;
        }
        .section p {
          margin: 0 0 18px;
          color: var(--secondary-text-color);
        }
        .stack {
          display: grid;
          gap: 14px;
        }
        .editor-card {
          border: 1px solid var(--divider-color);
          border-radius: 16px;
          overflow: hidden;
          background: color-mix(in srgb, var(--card-background-color) 70%, black 8%);
        }
        summary {
          list-style: none;
          cursor: pointer;
          padding: 16px 18px;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        summary::-webkit-details-marker {
          display: none;
        }
        .summary-title {
          font-size: 1.05rem;
          font-weight: 600;
        }
        .summary-subtitle {
          margin-top: 4px;
          color: var(--secondary-text-color);
        }
        .editor-body {
          border-top: 1px solid var(--divider-color);
          padding: 18px;
          display: grid;
          gap: 14px;
        }
        .grid {
          display: grid;
          gap: 12px;
        }
        .grid.two {
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }
        .field {
          display: grid;
          gap: 8px;
        }
        .field > span {
          font-size: 0.92rem;
          color: var(--secondary-text-color);
        }
        .field.checkbox {
          align-content: end;
        }
        .field.checkbox input {
          width: 18px;
          height: 18px;
        }
        input,
        select,
        textarea {
          width: 100%;
          border-radius: 12px;
          border: 1px solid var(--divider-color);
          background: var(--input-fill-color, rgba(255,255,255,0.04));
          color: var(--primary-text-color);
          padding: 12px 14px;
          box-sizing: border-box;
        }
        textarea {
          resize: vertical;
          min-height: 72px;
        }
        small,
        .muted {
          color: var(--secondary-text-color);
        }
        .preview-box {
          border-radius: 14px;
          padding: 14px;
          background: color-mix(in srgb, var(--card-background-color) 75%, black 12%);
          border: 1px dashed var(--divider-color);
        }
        .preview-title {
          font-size: 0.9rem;
          color: var(--secondary-text-color);
          margin-bottom: 8px;
        }
        .preview-state {
          font-size: 1.1rem;
          font-weight: 600;
          margin-bottom: 10px;
        }
        .preview-line {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          padding: 6px 0;
          border-top: 1px solid color-mix(in srgb, var(--divider-color) 70%, transparent);
        }
        .preview-line:first-of-type {
          border-top: none;
        }
        .preview-line span {
          color: var(--secondary-text-color);
        }
        .inline-error {
          color: var(--error-color);
        }
        .actions {
          display: flex;
          gap: 10px;
          justify-content: end;
          flex-wrap: wrap;
        }
        button {
          border: 1px solid var(--divider-color);
          background: transparent;
          color: var(--primary-text-color);
          padding: 10px 14px;
          border-radius: 999px;
          cursor: pointer;
        }
        button.primary {
          background: var(--primary-color);
          color: var(--text-primary-color, white);
          border-color: var(--primary-color);
        }
        .empty {
          padding: 28px;
          text-align: center;
          color: var(--secondary-text-color);
          border: 1px dashed var(--divider-color);
          border-radius: 16px;
        }
        @media (max-width: 1100px) {
          .layout {
            grid-template-columns: 1fr;
          }
        }
        @media (max-width: 720px) {
          .page {
            padding: 16px;
          }
          .hero {
            flex-direction: column;
            align-items: stretch;
          }
          .grid.two {
            grid-template-columns: 1fr;
          }
        }
      </style>
      <div class="page">
        <div class="hero">
          <div>
            <h1>Waste Schedule Editor</h1>
            <p>Edit sensor text and collection type names in one place, with preview before saving.</p>
          </div>
          ${this._renderEntryPicker()}
        </div>
        ${this._renderStatus()}
        ${
          this._busy
            ? '<div class="empty">Loading editor…</div>'
            : !entry
            ? '<div class="empty">No waste collection entries are available yet.</div>'
            : `
              <div class="layout">
                <section class="section">
                  <h2>Sensors</h2>
                  <p>Rename each sensor, tweak its display text, and preview the result before saving.</p>
                  <div class="stack">
                    ${sensors.length ? sensors.map((sensor) => this._renderSensor(sensor)).join("") : '<div class="empty">No sensors configured for this source.</div>'}
                  </div>
                </section>
                <section class="section">
                  <h2>Collection Types</h2>
                  <p>Set friendlier labels such as turning raw provider names into clean names like Bio.</p>
                  <div class="stack">
                    ${types.length ? types.map((type) => this._renderType(type)).join("") : '<div class="empty">No collection types available yet.</div>'}
                  </div>
                </section>
              </div>
            `
        }
      </div>
    `;

    this.shadowRoot.querySelectorAll("[data-kind='sensor']").forEach((el) => {
      const originalName = el.dataset.originalName;
      const field = el.dataset.field;
      const eventName = el.tagName === "SELECT" || el.type === "checkbox" ? "change" : "input";
      el.addEventListener(eventName, (event) => {
        const value = event.target.type === "checkbox" ? event.target.checked : event.target.value;
        this._updateSensorField(originalName, field, value);
      });
    });

    this.shadowRoot.querySelectorAll("[data-kind='type']").forEach((el) => {
      const rawType = el.dataset.rawType;
      const field = el.dataset.field;
      const eventName = el.type === "checkbox" ? "change" : "input";
      el.addEventListener(eventName, (event) => {
        const value = event.target.type === "checkbox" ? event.target.checked : event.target.value;
        this._updateTypeField(rawType, field, value);
      });
    });

    this.shadowRoot.querySelectorAll("[data-kind='sensor-preset']").forEach((el) => {
      el.addEventListener("change", (event) => {
        const originalName = event.target.dataset.originalName;
        const templateKind = event.target.dataset.templateKind;
        const selected = event.target.value;
        const presetMap =
          templateKind === "value"
            ? this._state.presets.value_templates
            : this._state.presets.date_templates;
        const field = templateKind === "value" ? "value_template" : "date_template";

        if (selected === "__default__") {
          this._updateSensorField(originalName, field, "");
          return;
        }
        if (selected === "__custom__") {
          return;
        }
        this._updateSensorField(originalName, field, presetMap[selected]);
      });
    });

    const entrySelect = this.shadowRoot.querySelector("[data-action='select-entry']");
    if (entrySelect) {
      entrySelect.addEventListener("change", (event) => {
        this._selectedEntryId = event.target.value;
        this._status = "";
        this._error = "";
        this._render();
      });
    }

    this.shadowRoot.querySelectorAll("[data-action='preview-sensor']").forEach((button) => {
      button.addEventListener("click", () => this._previewSensor(button.dataset.originalName));
    });
    this.shadowRoot.querySelectorAll("[data-action='save-sensor']").forEach((button) => {
      button.addEventListener("click", () => this._saveSensor(button.dataset.originalName));
    });
    this.shadowRoot.querySelectorAll("[data-action='reset-sensor']").forEach((button) => {
      button.addEventListener("click", () => this._resetSensor(button.dataset.originalName));
    });
    this.shadowRoot.querySelectorAll("[data-action='save-type']").forEach((button) => {
      button.addEventListener("click", () => this._saveType(button.dataset.rawType));
    });
    this.shadowRoot.querySelectorAll("[data-action='reset-type']").forEach((button) => {
      button.addEventListener("click", () => this._resetType(button.dataset.rawType));
    });
  }

  async _previewSensor(originalName) {
    const entry = this._currentEntry();
    const sensor = this._findSensor(entry, originalName);
    if (!entry || !sensor) {
      return;
    }
    this._status = "";
    this._error = "";
    sensor.preview_error = "";
    this._render();
    try {
      sensor.preview = await this._hass.callWS({
        type: "waste_collection_schedule/editor/preview_sensor",
        entry_id: entry.entry_id,
        sensor: sensor.config,
      });
    } catch (err) {
      sensor.preview_error = this._messageFromError(err);
    }
    this._render();
  }

  async _saveSensor(originalName) {
    const entry = this._currentEntry();
    const sensor = this._findSensor(entry, originalName);
    if (!entry || !sensor) {
      return;
    }
    this._status = "";
    this._error = "";
    this._render();
    try {
      await this._hass.callWS({
        type: "waste_collection_schedule/editor/save_sensor",
        entry_id: entry.entry_id,
        original_name: originalName,
        sensor: sensor.config,
      });
      this._status = `Saved ${sensor.config.name || originalName}.`;
      await this._loadData();
    } catch (err) {
      sensor.preview_error = this._messageFromError(err);
      this._render();
    }
  }

  _resetSensor(originalName) {
    const sourceSensor = this._findSensor(this._sourceEntry(), originalName);
    const draftSensor = this._findSensor(this._currentEntry(), originalName);
    if (!sourceSensor || !draftSensor) {
      return;
    }
    draftSensor.config = JSON.parse(JSON.stringify(sourceSensor.config));
    draftSensor.preview = JSON.parse(JSON.stringify(sourceSensor.preview));
    draftSensor.preview_error = "";
    this._status = "";
    this._error = "";
    this._render();
  }

  async _saveType(rawType) {
    const entry = this._currentEntry();
    const typeConfig = this._findType(entry, rawType);
    if (!entry || !typeConfig) {
      return;
    }
    this._status = "";
    this._error = "";
    this._render();
    try {
      await this._hass.callWS({
        type: "waste_collection_schedule/editor/save_type",
        entry_id: entry.entry_id,
        waste_type: rawType,
        customize: typeConfig.config,
      });
      this._status = `Saved ${typeConfig.display_name}.`;
      await this._loadData();
    } catch (err) {
      this._error = this._messageFromError(err);
      this._render();
    }
  }

  _resetType(rawType) {
    const sourceType = this._findType(this._sourceEntry(), rawType);
    const draftType = this._findType(this._currentEntry(), rawType);
    if (!sourceType || !draftType) {
      return;
    }
    draftType.config = JSON.parse(JSON.stringify(sourceType.config));
    this._status = "";
    this._error = "";
    this._render();
  }
}

customElements.define(
  "waste-collection-schedule-editor",
  WasteCollectionScheduleEditor
);

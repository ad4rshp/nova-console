  const PARAM_KEYS = ['num_ctx', 'num_predict', 'temperature', 'top_k', 'top_p', 'repeat_penalty'];
  const fmt = n => Number(n || 0).toLocaleString();
  let chatHistory = [];
  let currentLimits = {};

  // Toasts with Hover-Pause
  function showToast({ title, message, type = 'info', duration = 8000 }) {
    const container = document.querySelector('#toastContainer');
    const toast = document.createElement('div');
    toast.className = 'toast';

    const icons = {
      success: `<svg class="icon" style="color:var(--ok);width:16px;height:16px;flex-shrink:0;" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>`,
      error: `<svg class="icon" style="color:var(--bad);width:16px;height:16px;flex-shrink:0;" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
      warning: `<svg class="icon" style="color:var(--warn);width:16px;height:16px;flex-shrink:0;" viewBox="0 0 24 24"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
      info: `<svg class="icon" style="color:var(--accent-blue);width:16px;height:16px;flex-shrink:0;" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`
    };

    const barColor = type === 'error' ? 'var(--bad)' : type === 'warning' ? 'var(--warn)' : type === 'success' ? 'var(--ok)' : 'var(--accent-blue)';

    toast.innerHTML = `
      ${icons[type] || icons.info}
      <div style="flex:1;">
        <div class="toast-title">${title}</div>
        ${message ? `<div class="toast-desc">${message}</div>` : ''}
      </div>
      <button class="toast-close" title="Dismiss">×</button>
      <div class="toast-bar" style="animation-duration:${duration}ms;background:${barColor}"></div>
    `;

    container.appendChild(toast);

    let dismissTimeout;
    const startDismiss = () => {
      dismissTimeout = setTimeout(() => {
        toast.classList.add('out');
        setTimeout(() => toast.remove(), 200);
      }, duration);
    };

    startDismiss();
    toast.addEventListener('mouseenter', () => clearTimeout(dismissTimeout));
    toast.addEventListener('mouseleave', () => startDismiss());
    toast.querySelector('.toast-close').addEventListener('click', () => {
      clearTimeout(dismissTimeout);
      toast.classList.add('out');
      setTimeout(() => toast.remove(), 150);
    });
  }

  async function postJson(url, payload) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    return res.json();
  }

  // Generate In-Card SVG Sparkline Paths
  function generateSparkline(values, width = 72, height = 36) {
    if (!values || values.length === 0) {
      return { line: `M0,${height * 0.7} Q${width/2},${height * 0.3} ${width},${height * 0.6}`, fill: `M0,${height} L0,${height * 0.7} Q${width/2},${height * 0.3} ${width},${height * 0.6} L${width},${height} Z` };
    }
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = (max - min) || 1;
    const step = width / Math.max(values.length - 1, 1);
    
    const points = values.map((v, i) => {
      const x = i * step;
      const y = height - 4 - ((v - min) / range) * (height - 8);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });

    const line = `M ` + points.join(' L ');
    const fill = `M 0,${height} L ` + points.join(' L ') + ` L ${width},${height} Z`;
    return { line, fill };
  }

  let latestDashboardData = null;

  // Load Dashboard Data & Update Radial Gauges + Sparklines
  async function loadDashboard() {
    try {
      const data = await fetch('/api/dashboard').then(r => r.json());
      latestDashboardData = data;
      const u = data.usage || {};
      const r = data.ram || {};
      const g = data.gpu;

      // Status Pill
      const statusPill = document.querySelector('#statusPill');
      const statusText = document.querySelector('#statusText');
      const engineName = (data.engine && data.engine.name) || 'Engine';
      const badge = document.querySelector('#backendTypeBadge');
      if (badge) badge.textContent = `Live ${engineName} ps`;

      if (data.status === 'online') {
        statusPill.className = 'neu-pill ok';
        statusText.textContent = `${engineName} Online`;
      } else {
        statusPill.className = 'neu-pill bad';
        statusText.textContent = `${engineName} Offline`;
      }

      // Release Updater Notification (Zero background RAM)
      const updatePill = document.querySelector('#updatePill');
      const updatePillText = document.querySelector('#updatePillText');
      if (updatePill && data.update && data.update.has_update) {
        updatePill.style.display = 'inline-flex';
        updatePill.href = data.update.release_url || 'https://github.com/nova-console/nova-console/releases';
        if (updatePillText) {
          updatePillText.textContent = `New: v${data.update.latest_version}`;
        }
      } else if (updatePill) {
        updatePill.style.display = 'none';
      }

      // Advanced Hardware & System Diagnostics Engine
      const diagBar = document.querySelector('#diagnosticBar');
      if (data.diagnostics && data.diagnostics.length > 0) {
        diagBar.innerHTML = data.diagnostics.map(d => {
          const isRebuildAction = d.title && (d.title.includes('Pending') || d.title.includes('Rebuild') || d.title.includes('Hardware') || d.title.includes('Context'));
          const suggestedArg = d.suggested_ctx ? `'${d.suggested_ctx}'` : '';
          const presetArg = d.suggested_preset ? `'${d.suggested_preset}'` : '';
          const levelClass = d.level === 'error' ? 'level-error' : d.level === 'info' ? 'level-info' : 'level-warning';
          
          let actionButtons = '';
          if (d.suggested_preset) {
            actionButtons += `<button class="btn btn-sm btn-primary" onclick="applyPreset(${presetArg}); openRebuildModal(${suggestedArg})" style="font-size:11px; padding:4px 10px;">Apply ${d.suggested_preset.toUpperCase()} &amp; Rebuild</button>`;
          } else if (isRebuildAction) {
            actionButtons += `<button class="btn btn-sm btn-primary" onclick="openRebuildModal(${suggestedArg})" style="font-size:11px; padding:4px 10px;">Rebuild Now</button>`;
          }

          return `
            <div class="diagnostic-item ${levelClass}">
              <div style="flex:1; min-width:260px;">
                <div style="font-weight:800; font-size:13px; color:var(--ink); margin-bottom:3px; display:flex; align-items:center; gap:6px;">
                  <span>${d.level === 'error' ? '🚨' : d.level === 'info' ? '⚡' : '⚠️'}</span>
                  <span>${escapeHtml(d.title)}</span>
                </div>
                <div style="font-size:12px; color:var(--ink-muted); line-height:1.45;">${escapeHtml(d.message)}</div>
              </div>
              <div style="display:flex; align-items:center; gap:10px; flex-shrink:0; flex-wrap:wrap;">
                ${d.action ? `<span style="font-weight:600;font-size:11.5px;color:var(--accent-blue);">${escapeHtml(d.action)}</span>` : ''}
                ${actionButtons}
              </div>
            </div>
          `;
        }).join('');
        diagBar.className = 'diagnostic-bar active';
      } else {
        diagBar.innerHTML = '';
        diagBar.className = 'diagnostic-bar';
      }

      // 1. RAM: Radial Gauge (No duplicate tag)
      const ramPct = r.percent || 0;
      document.querySelector('#ramVal').textContent = `${r.used_gb || 0} GB`;
      document.querySelector('#ramSub').textContent = `${r.total_gb || 0} GB total`;
      const ramGauge = document.querySelector('#ramGauge');
      ramGauge.setAttribute('stroke-dasharray', `${ramPct}, 100`);
      ramGauge.setAttribute('stroke', ramPct > 85 ? 'var(--bad)' : ramPct > 75 ? 'var(--warn)' : 'var(--accent-blue)');
      document.querySelector('#ramGaugeText').textContent = `${ramPct}%`;

      // 2. GPU: Radial Gauge (No duplicate 0% tag; displays GPU chip badge)
      if (g) {
        const usedMb = parseFloat(g.used_mb || 0);
        const totalMb = parseFloat(g.total_mb || 1);
        const vramPct = Math.round((usedMb / totalMb) * 100);
        document.querySelector('#gpuVal').textContent = `${fmt(usedMb)} MB`;
        document.querySelector('#gpuSub').textContent = `${fmt(totalMb)} MB total`;
        document.querySelector('#gpuTag').textContent = g.name ? g.name.replace('NVIDIA GeForce ', '') : 'GPU';
        const gpuGauge = document.querySelector('#gpuGauge');
        gpuGauge.setAttribute('stroke-dasharray', `${vramPct}, 100`);
        gpuGauge.setAttribute('stroke', vramPct > 85 ? 'var(--bad)' : vramPct > 70 ? 'var(--warn)' : 'var(--accent-blue)');
        document.querySelector('#gpuGaugeText').textContent = `${vramPct}%`;
      } else {
        document.querySelector('#gpuVal').textContent = 'Integrated';
        document.querySelector('#gpuSub').textContent = 'No Nvidia GPU';
        document.querySelector('#gpuTag').textContent = 'N/A';
        document.querySelector('#gpuGauge').setAttribute('stroke-dasharray', '0, 100');
        document.querySelector('#gpuGaugeText').textContent = '0%';
      }

      // 3. Storage: Radial Gauge (No duplicate text)
      const modelGb = data.storage?.model_dir_gb || 0;
      const diskFreeGb = data.storage?.disk_free_gb || 1;
      const storagePct = Math.min(Math.round((modelGb / (modelGb + diskFreeGb)) * 100), 100);
      document.querySelector('#storageVal').textContent = `${modelGb} GB`;
      document.querySelector('#diskFreeVal').textContent = `${diskFreeGb} GB free`;
      document.querySelector('#modelsTag').textContent = `${data.models ? data.models.length : 0} models`;
      document.querySelector('#storageGauge').setAttribute('stroke-dasharray', `${Math.max(storagePct, 4)}, 100`);

      // 4. Speed (TPS): Sparkline Trend
      document.querySelector('#tpsVal').textContent = `${u.avg_tps || 0} tps`;
      document.querySelector('#latencyVal').textContent = `${u.average_latency_s || 0}s latency`;

      // 5. Requests & Tokens: Sparkline Trend
      document.querySelector('#requestsVal').textContent = fmt(u.requests);
      document.querySelector('#tokensVal').textContent = `${fmt(u.prompt_tokens)} in · ${fmt(u.output_tokens)} out`;

      // Load History to Plot Sparklines
      const history = await fetch('/api/history').then(r => r.json()).catch(() => []);
      if (history.length > 0) {
        const recent = history.slice(-12);
        const tpsPoints = recent.map(h => h.tps || 0);
        const tpsPaths = generateSparkline(tpsPoints);
        document.querySelector('#tpsSparkLine').setAttribute('d', tpsPaths.line);
        document.querySelector('#tpsSparkFill').setAttribute('d', tpsPaths.fill);

        const outPoints = recent.map(h => h.output_tokens || 0);
        const reqPaths = generateSparkline(outPoints);
        document.querySelector('#reqSparkLine').setAttribute('d', reqPaths.line);
        document.querySelector('#reqSparkFill').setAttribute('d', reqPaths.fill);
      }

      // Populate Model Select Dropdown dynamically
      const models = data.models || [];
      const chatSelect = document.querySelector('#chatModelSelect');
      const hasNova = models.some(m => m.name === 'nova:latest');

      if (models.length > 0) {
        const defaultChoice = hasNova ? 'nova:latest' : models[0].name;
        const currentSelected = chatSelect.value || defaultChoice;
        
        chatSelect.innerHTML = models.map(m => 
          `<option value="${m.name}" ${m.name === currentSelected ? 'selected' : ''}>${m.name}</option>`
        ).join('');

        const activeChoice = chatSelect.value || defaultChoice;
        document.querySelector('#chatModelBadge').textContent = activeChoice;
      } else {
        chatSelect.innerHTML = `<option value="">No models installed</option>`;
        document.querySelector('#chatModelBadge').textContent = 'No models found';
      }

      // Settings Sync from SQLite
      const thinkVal = Boolean(data.settings?.think);
      const td = document.querySelector('#thinkDefault');
      if (td) td.checked = thinkVal;
      const ct = document.querySelector('#chatThinkToggle');
      if (ct) ct.checked = thinkVal;
      if (data.settings?.preview_thinking) {
        const pSel = document.querySelector('#previewThinkingSelect');
        if (pSel) pSel.value = data.settings.preview_thinking;
      }
      if (typeof data.settings?.save_chat_history !== 'undefined') {
        const sToggle = document.querySelector('#saveChatToggle');
        if (sToggle) sToggle.checked = Boolean(data.settings.save_chat_history);
      }

      // Loaded Models Table (6 columns: Model, VRAM, Active Context, Saved Modelfile, Rebuild Status, Actions)
      const loadedBody = document.querySelector('#loadedBody');
      if (data.loaded && data.loaded.length > 0) {
        loadedBody.innerHTML = data.loaded.map(m => {
          const isNova = (m.name === 'nova:latest' || m.model === 'nova:latest');
          const savedCtx = data.modelfile_status?.saved_context;
          const isPending = isNova && data.modelfile_status?.pending_rebuild;
          return `
            <tr id="row_${m.name.replace(/[^a-zA-Z0-9]/g, '_')}">
              <td><strong>${m.name}</strong></td>
              <td><span class="tag-neu">${m.size_vram ? (m.size_vram / 1024**2).toFixed(0) + ' MB VRAM' : (m.details?.parameter_size || 'In Memory')}</span></td>
              <td><strong>${m.context_length ? fmt(m.context_length) + ' tokens' : 'Default'}</strong></td>
              <td>${isNova && savedCtx ? fmt(savedCtx) + ' tokens' : '—'}</td>
              <td>${isPending ? '<span class="neu-pill bad" style="font-size:10.5px;">⚠️ Rebuild Required</span>' : '<span class="neu-pill ok" style="font-size:10.5px;">✓ Synced</span>'}</td>
              <td>
                <button class="btn btn-danger btn-sm" onclick="unloadModel('${m.name}', this)">
                  <svg class="icon" viewBox="0 0 24 24"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg>
                  Evict
                </button>
              </td>
            </tr>
          `;
        }).join('');
      } else {
        loadedBody.innerHTML = '<tr><td colspan="6" style="color:var(--ink-muted);text-align:center;padding:12px;">No models currently loaded in GPU VRAM. Memory is free.</td></tr>';
      }

      // Modelfile Parameters & System Prompt
      if (data.modelfile) {
        renderModelfile(data.modelfile);
      }

      // Render History Table
      renderHistoryTable(history);

    } catch (err) {
      console.error('Failed to load dashboard:', err);
    }
  }

  function renderModelfile(mf) {
    const params = mf.parameters || {};
    currentLimits = mf.limits || {};
    const container = document.querySelector('#paramsContainer');
    
    // Update Context & Status Banner
    const status = latestDashboardData?.modelfile_status;
    const savedCtx = status?.saved_context || params.num_ctx || 8192;
    const loadedCtx = status?.loaded_context;
    const isPending = status?.pending_rebuild;

    const bannerSaved = document.querySelector('#bannerSavedCtx');
    const bannerActive = document.querySelector('#bannerActiveCtx');
    const bannerNotice = document.querySelector('#bannerRebuildNotice');

    if (bannerSaved) bannerSaved.textContent = `${fmt(savedCtx)} tokens (on disk)`;
    if (bannerActive) {
      if (loadedCtx) {
        bannerActive.textContent = `${fmt(loadedCtx)} tokens (${status.loaded_model_name || 'nova'})`;
        bannerActive.className = isPending ? 'neu-pill bad' : 'neu-pill ok';
      } else {
        bannerActive.textContent = 'None currently in VRAM';
        bannerActive.className = 'neu-pill';
      }
    }
    if (bannerNotice) {
      if (isPending) {
        bannerNotice.innerHTML = `⚠️ Saved context (<strong>${fmt(savedCtx)}</strong>) != Active in VRAM (<strong>${fmt(loadedCtx)}</strong>). Click <strong>Rebuild Nova</strong> to apply.`;
        bannerNotice.style.color = '#d97706';
      } else if (loadedCtx) {
        bannerNotice.innerHTML = `✓ Active model in VRAM matches saved Modelfile (${fmt(savedCtx)} tokens).`;
        bannerNotice.style.color = '#10b981';
      } else {
        bannerNotice.innerHTML = `✓ Saved Modelfile configured for ${fmt(savedCtx)} tokens (idle).`;
        bannerNotice.style.color = '#10b981';
      }
    }

    if (!document.querySelector('#systemPrompt').matches(':focus')) {
      document.querySelector('#systemPrompt').value = mf.system_prompt || '';
    }

    if (container.children.length === 0) {
      container.innerHTML = PARAM_KEYS.map(key => {
        const [min, max] = currentLimits[key] || [0, 100];
        const step = (key === 'temperature' || key === 'top_p' || key === 'repeat_penalty') ? '0.05' : '1';
        return `
          <div class="param-box">
            <div class="param-header">
              <span class="param-title">${key}</span>
              <span class="param-limits">${min}–${max}</span>
            </div>
            <input id="input_${key}" type="number" min="${min}" max="${max}" step="${step}" value="${params[key] || ''}">
          </div>
        `;
      }).join('');

      // Add listener to each input for auto-preset detection
      PARAM_KEYS.forEach(key => {
        const input = document.querySelector('#input_' + key);
        if (input) {
          input.addEventListener('input', detectActivePreset);
        }
      });
    }

    // Auto-detect preset on initial render
    detectActivePreset();
  }

  // Model Tuning Studio: Hardware-Aware Presets
  const HARDWARE_PRESETS = {
    low: {
      num_ctx: 2048,
      num_predict: 1024,
      temperature: 0.2,
      top_k: 20,
      top_p: 0.90,
      repeat_penalty: 1.10,
      label: 'Low (2K) Profile',
      desc: 'Optimized for laptops and GPUs with <6 GB VRAM to eliminate paging & split offload'
    },
    medium: {
      num_ctx: 4096,
      num_predict: 2048,
      temperature: 0.4,
      top_k: 40,
      top_p: 0.95,
      repeat_penalty: 1.05,
      label: 'Medium (4K) Profile',
      desc: 'Balanced profile for 6-8 GB VRAM systems providing optimal speed and context'
    },
    high: {
      num_ctx: 8192,
      num_predict: 4096,
      temperature: 0.7,
      top_k: 60,
      top_p: 0.95,
      repeat_penalty: 1.05,
      label: 'High (8K) Profile',
      desc: 'Heavy 8K context profile for 12+ GB VRAM rigs with deep reasoning'
    }
  };

  function applyPreset(presetKey) {
    const preset = HARDWARE_PRESETS[presetKey];
    if (!preset) return;

    PARAM_KEYS.forEach(k => {
      const el = document.querySelector('#input_' + k);
      if (el && preset[k] !== undefined) {
        el.value = preset[k];
      }
    });

    updatePresetUI(presetKey);
    showToast({
      title: `${preset.label} Applied`,
      message: `${preset.desc}. Click 'Save' or 'Rebuild Nova' to compile.`,
      type: 'info'
    });
  }

  function detectActivePreset() {
    const values = {};
    PARAM_KEYS.forEach(k => {
      const el = document.querySelector('#input_' + k);
      if (el) values[k] = parseFloat(el.value);
    });

    let matchedKey = null;
    for (const [key, preset] of Object.entries(HARDWARE_PRESETS)) {
      const isMatch = (
        values.num_ctx === preset.num_ctx &&
        values.num_predict === preset.num_predict &&
        Math.abs(values.temperature - preset.temperature) < 0.01 &&
        values.top_k === preset.top_k &&
        Math.abs(values.top_p - preset.top_p) < 0.01 &&
        Math.abs(values.repeat_penalty - preset.repeat_penalty) < 0.01
      );
      if (isMatch) {
        matchedKey = key;
        break;
      }
    }

    updatePresetUI(matchedKey);
  }

  function updatePresetUI(activeKey) {
    ['low', 'medium', 'high'].forEach(key => {
      const btn = document.querySelector(`#preset${key.charAt(0).toUpperCase() + key.slice(1)}Btn`);
      if (btn) {
        if (key === activeKey) {
          btn.classList.add('active');
        } else {
          btn.classList.remove('active');
        }
      }
    });

    const badge = document.querySelector('#activePresetBadge');
    if (badge) {
      if (activeKey && HARDWARE_PRESETS[activeKey]) {
        badge.textContent = HARDWARE_PRESETS[activeKey].label;
        badge.className = 'neu-pill ok';
      } else {
        badge.textContent = 'Custom Profile';
        badge.className = 'neu-pill';
      }
    }
  }

  // Trust & Privacy Audit Modal
  function openTrustModal() {
    const modal = document.querySelector('#trustModal');
    if (modal) modal.style.display = 'flex';
  }

  function closeTrustModal() {
    const modal = document.querySelector('#trustModal');
    if (modal) modal.style.display = 'none';
  }

  window.applyPreset = applyPreset;
  window.detectActivePreset = detectActivePreset;
  window.openTrustModal = openTrustModal;
  window.closeTrustModal = closeTrustModal;

  let cachedHistory = [];
  let isHistoryExpanded = false;
  let isHistorySectionCollapsed = false;

  function toggleHistoryCollapse(e) {
    if (e && e.target && e.target.closest('button') && e.target.closest('button').id !== 'historyCollapseBtn') {
      return;
    }
    isHistorySectionCollapsed = !isHistorySectionCollapsed;
    const content = document.querySelector('#historyContentWrap');
    const chevron = document.querySelector('#historyChevron');
    const label = document.querySelector('#historyCollapseLabel');
    if (content) {
      content.style.display = isHistorySectionCollapsed ? 'none' : 'block';
    }
    if (chevron) {
      chevron.style.transform = isHistorySectionCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)';
    }
    if (label) {
      label.textContent = isHistorySectionCollapsed ? 'Expand' : 'Collapse';
    }
  }

  function toggleHistoryViewMore() {
    isHistoryExpanded = !isHistoryExpanded;
    renderHistoryRows();
  }

  function renderHistoryTable(history) {
    cachedHistory = history || [];
    const countBadge = document.querySelector('#historyRowCountBadge');
    if (countBadge) {
      countBadge.textContent = `${cachedHistory.length} request${cachedHistory.length === 1 ? '' : 's'}`;
    }
    renderHistoryRows();
  }

  function renderHistoryRows() {
    const body = document.querySelector('#historyBody');
    const viewMoreWrap = document.querySelector('#historyViewMoreWrap');
    const viewMoreLabel = document.querySelector('#historyViewMoreLabel');
    const viewMoreChevron = document.querySelector('#historyViewMoreChevron');

    if (!cachedHistory || cachedHistory.length === 0) {
      body.innerHTML = '<tr><td colspan="7" style="color:var(--ink-muted);text-align:center;padding:12px;">No requests recorded yet. Configure your client to <code>http://127.0.0.1:8080/v1</code>.</td></tr>';
      if (viewMoreWrap) viewMoreWrap.style.display = 'none';
      return;
    }

    const reversed = [...cachedHistory].reverse();
    // Show 4 recent rows by default, or all if expanded
    const visibleRows = isHistoryExpanded ? reversed : reversed.slice(0, 4);

    body.innerHTML = visibleRows.map(row => `
      <tr>
        <td style="color:var(--ink-muted);font-family:ui-monospace,monospace;font-size:11.5px;">${row.time}</td>
        <td><strong>${row.model || 'unknown'}</strong></td>
        <td><span class="tag-neu">${row.path || '/v1'}</span></td>
        <td>${fmt(row.prompt_tokens)}</td>
        <td>${fmt(row.output_tokens)}</td>
        <td>${row.latency_s}s</td>
        <td><strong style="color:var(--ink);">${row.tps ? row.tps + ' tps' : '—'}</strong></td>
      </tr>
    `).join('');

    if (reversed.length > 4) {
      if (viewMoreWrap) viewMoreWrap.style.display = 'block';
      if (viewMoreLabel) {
        viewMoreLabel.textContent = isHistoryExpanded 
          ? 'Show Less' 
          : `View More (${reversed.length - 4} older requests)`;
      }
      if (viewMoreChevron) {
        viewMoreChevron.style.transform = isHistoryExpanded ? 'rotate(180deg)' : 'rotate(0deg)';
      }
    } else {
      if (viewMoreWrap) viewMoreWrap.style.display = 'none';
    }
  }

  async function unloadModel(name, btn) {
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = 'Evicting…';
    }
    try {
      const res = await postJson('/api/unload', { model: name });
      if (res.ok) {
        showToast({ title: 'Model Evicted', message: `${name} unloaded from GPU VRAM. Memory freed.`, type: 'success', duration: 5000 });
        loadDashboard();
      } else {
        showToast({ title: 'Eviction Failed', message: res.error, type: 'error', duration: 8000 });
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = `<svg class="icon" viewBox="0 0 24 24"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg> Evict`;
        }
      }
    } catch (err) {
      showToast({ title: 'Network Error', message: String(err), type: 'error', duration: 8000 });
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = `<svg class="icon" viewBox="0 0 24 24"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg> Evict`;
      }
    }
  }

  /* Chat Sidebar Controls */
  const chatSidebar = document.querySelector('#chatSidebar');
  const chatBackdrop = document.querySelector('#chatBackdrop');

  function openChat() {
    chatSidebar.classList.add('open');
    chatBackdrop.classList.add('active');
    setTimeout(() => document.querySelector('#chatInput').focus(), 250);
  }

  function closeChat() {
    chatSidebar.classList.remove('open');
    chatBackdrop.classList.remove('active');
  }

  const headerChatBtn = document.querySelector('#headerChatBtn');
  if (headerChatBtn) headerChatBtn.addEventListener('click', openChat);
  const openSidebarBtn = document.querySelector('#openSidebarBtn');
  if (openSidebarBtn) openSidebarBtn.addEventListener('click', openChat);
  const fabChatBtn = document.querySelector('#fabChatBtn');
  if (fabChatBtn) fabChatBtn.addEventListener('click', openChat);
  const closeChatBtn = document.querySelector('#closeChatBtn');
  if (closeChatBtn) closeChatBtn.addEventListener('click', closeChat);
  chatBackdrop.addEventListener('click', closeChat);

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && chatSidebar.classList.contains('open')) {
      closeChat();
    }
  });

  document.querySelector('#chatModelSelect').addEventListener('change', (e) => {
    document.querySelector('#chatModelBadge').textContent = e.target.value;
  });

  async function syncThinking(checked) {
    const tdEl = document.querySelector('#thinkDefault');
    if (tdEl) tdEl.checked = checked;
    const ctEl = document.querySelector('#chatThinkToggle');
    if (ctEl) ctEl.checked = checked;
    await postJson('/api/settings', { think: checked });
    showToast({
      title: checked ? 'Thinking Mode Enabled' : 'Thinking Mode Disabled',
      message: checked ? 'Reasoning models will emit chain-of-thought tokens.' : 'Reasoning generation skipped for direct replies.',
      type: 'info',
      duration: 5000
    });
  }

  const tdInput = document.querySelector('#thinkDefault');
  if (tdInput) tdInput.addEventListener('change', e => syncThinking(e.target.checked));
  const ctInput = document.querySelector('#chatThinkToggle');
  if (ctInput) ctInput.addEventListener('change', e => syncThinking(e.target.checked));

  document.querySelector('#clearChatBtn').addEventListener('click', () => {
    if (chatHistory.length === 0) return;
    chatHistory = [];
    renderChatMessages();
    showToast({ title: 'Cleared', message: 'Chat history reset.', type: 'info', duration: 4000 });
  });

  function renderChatMessages() {
    const container = document.querySelector('#chatMessages');
    if (chatHistory.length === 0) {
      container.innerHTML = `
        <div id="chatEmptyState" style="text-align:center; margin:auto; max-width:280px; padding:16px 0;">
          <h3 style="font-size:15px; font-weight:800; margin-bottom:4px; color:var(--ink);">Welcome to Nova Chat</h3>
          <p style="font-size:12px; color:var(--ink-muted); margin-bottom:14px;">Local AI conversation with reasoning & command execution.</p>
          <div style="display:flex; flex-direction:column; gap:8px;">
            <button class="btn btn-sm" style="text-align:left; justify-content:flex-start;" onclick="sendStarterPrompt('resources')">Explain system resources</button>
            <button class="btn btn-sm" style="text-align:left; justify-content:flex-start;" onclick="sendStarterPrompt('script')">Write Python AI script</button>
          </div>
        </div>
      `;
      return;
    }

    container.innerHTML = chatHistory.map((msg, idx) => {
      const isUser = msg.role === 'user';
      let contentHtml = '';
      if (isUser) {
        let imgHtml = '';
        if (msg.images && msg.images.length) {
          imgHtml = `<div class="msg-images-grid">` + msg.images.map(img => {
            const src = img.startsWith('data:') ? img : `data:image/jpeg;base64,${img}`;
            return `<img src="${src}" class="msg-img-thumb" alt="Attachment" onclick="window.open('${src}')">`;
          }).join('') + `</div>`;
        }
        contentHtml = `${imgHtml}<div class="msg-bubble">${formatMarkdown(msg.content)}</div>`;
      } else {
        let thinkBlock = '';
        if (msg.thinking) {
          const previewMode = document.querySelector('#previewThinkingSelect')?.value || latestDashboardData?.settings?.preview_thinking || 'summary';
          if (previewMode === 'full') {
            thinkBlock = `
              <details class="thinking-box" open>
                <summary>🧠 Planning & Reasoning (${msg.thinking.length} chars)</summary>
                <pre style="white-space:pre-wrap; margin:0;">${escapeHtml(msg.thinking)}</pre>
              </details>
            `;
          } else if (previewMode === 'summary') {
            thinkBlock = `
              <details class="thinking-box">
                <summary>🧠 Planning & Reasoning (${msg.thinking.length} chars · click to view)</summary>
                <pre style="white-space:pre-wrap; margin:0;">${escapeHtml(msg.thinking)}</pre>
              </details>
            `;
          }
        }
        contentHtml = `
          <div class="msg-bubble">
            ${thinkBlock}
            <div>${formatMarkdown(msg.content || 'No response returned.')}</div>
          </div>
          <div class="msg-actions">
            <button class="msg-action-btn" onclick="copyMessage(this, ${idx})" title="Copy message text">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
              <span>Copy text</span>
            </button>
          </div>
        `;
      }
      return `
        <div class="msg ${isUser ? 'user' : 'assistant'}">
          ${contentHtml}
          <div class="msg-meta">${isUser ? 'You' : 'Nova'}</div>
        </div>
      `;
    }).join('');

    container.scrollTop = container.scrollHeight;
  }

  function escapeHtml(str) {
    return (str || '').replace(/[&<>'"]/g, tag => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      "'": '&#39;',
      '"': '&quot;'
    }[tag] || tag));
  }

  function formatMarkdown(raw) {
    if (!raw) return '';
    const codeBlocks = [];
    const inlineCodes = [];

    // 1. Extract fenced code blocks
    let text = raw.replace(/```([a-zA-Z0-9_\-\+]*)\r?\n?([\s\S]*?)```/g, (match, lang, code) => {
      const idx = codeBlocks.length;
      codeBlocks.push({
        lang: (lang || 'code').trim(),
        code: code.replace(/\r?\n$/, '')
      });
      return `\n@@@CODEBLOCK_${idx}@@@\n`;
    });

    // 2. Extract inline code
    text = text.replace(/`([^`\r\n]+)`/g, (match, code) => {
      const idx = inlineCodes.length;
      inlineCodes.push(escapeHtml(code));
      return `@@@INLINECODE_${idx}@@@`;
    });

    // 3. Process line by line
    const lines = text.split(/\r?\n/);
    const htmlOut = [];
    let inUl = false;
    let inOl = false;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      // Code block placeholder
      const cbMatch = line.trim().match(/^@@@CODEBLOCK_(\d+)@@@$/);
      if (cbMatch) {
        if (inUl) { htmlOut.push('</ul>'); inUl = false; }
        if (inOl) { htmlOut.push('</ol>'); inOl = false; }
        const cb = codeBlocks[Number(cbMatch[1])];
        const safeCode = escapeHtml(cb.code);
        const l = (cb.lang || '').toLowerCase();
        const isCmd = ['bash', 'sh', 'cmd', 'powershell', 'ps1', 'shell', 'terminal', 'bat'].includes(l);
        const isPython = ['python', 'py'].includes(l);
        const escapedForAttr = cb.code.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        const pythonCmd = isPython ? `python -c "${cb.code.replace(/"/g, '\\"').replace(/\r?\n/g, '; ')}"` : '';
        const escapedPythonCmd = pythonCmd.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        htmlOut.push(`
          <div class="code-box">
            <div class="code-box-header">
              <span class="code-box-lang">${escapeHtml(cb.lang)}</span>
              <div style="display:flex; align-items:center; gap:6px;">
                ${isCmd ? `
                  <button class="code-exec-btn" onclick="requestCommandExecution(this)" data-cmd="${escapedForAttr}" title="Execute in terminal with approval">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
                    <span>Run</span>
                  </button>
                ` : ''}
                ${isPython ? `
                  <button class="code-exec-btn" onclick="requestCommandExecution(this)" data-cmd="${escapedPythonCmd}" title="Run Python script in terminal sandbox">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
                    <span>Run Python</span>
                  </button>
                ` : ''}
                <button class="code-copy-btn" onclick="copyCode(this)" title="Copy Code">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                  <span>Copy</span>
                </button>
              </div>
            </div>
            <pre><code class="code-box-content">${safeCode}</code></pre>
          </div>
        `);
        continue;
      }

      // Check for Markdown Table: current line has pipe and next line is a separator (e.g. |---|---|)
      if (line.includes('|') && i + 1 < lines.length && /^\s*\|?\s*:?-+:?\s*(\|:?-+:?\s*)+\|?\s*$/.test(lines[i + 1])) {
        if (inUl) { htmlOut.push('</ul>'); inUl = false; }
        if (inOl) { htmlOut.push('</ol>'); inOl = false; }

        const parseRow = str => {
          let s = str.trim();
          if (s.startsWith('|')) s = s.slice(1);
          if (s.endsWith('|')) s = s.slice(0, -1);
          return s.split('|').map(c => c.trim());
        };

        const headers = parseRow(line);
        const separators = parseRow(lines[i + 1]);
        const aligns = separators.map(s => {
          if (s.startsWith(':') && s.endsWith(':')) return 'center';
          if (s.endsWith(':')) return 'right';
          return 'left';
        });

        let tbl = '<div class="md-table-wrap"><table class="md-table"><thead><tr>';
        for (let c = 0; c < headers.length; c++) {
          let h = escapeHtml(headers[c] || '');
          h = h.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
          tbl += `<th style="text-align:${aligns[c] || 'left'};">${h}</th>`;
        }
        tbl += '</tr></thead><tbody>';

        i += 1; // skip separator row

        while (i + 1 < lines.length && lines[i + 1].includes('|') && !lines[i + 1].trim().match(/^@@@CODEBLOCK_/)) {
          i += 1;
          const rowCells = parseRow(lines[i]);
          tbl += '<tr>';
          for (let c = 0; c < headers.length; c++) {
            let val = escapeHtml(rowCells[c] || '');
            val = val.replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>');
            val = val.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
            val = val.replace(/\*(.*?)\*/g, '<em>$1</em>');
            tbl += `<td style="text-align:${aligns[c] || 'left'};">${val}</td>`;
          }
          tbl += '</tr>';
        }

        tbl += '</tbody></table></div>';
        htmlOut.push(tbl);
        continue;
      }

      // Escape line text for safety
      let safeLine = escapeHtml(line);

      // Markdown bold & italic
      safeLine = safeLine.replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>');
      safeLine = safeLine.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
      safeLine = safeLine.replace(/\*(.*?)\*/g, '<em>$1</em>');

      // Headings
      if (/^### (.*)$/.test(safeLine)) {
        if (inUl) { htmlOut.push('</ul>'); inUl = false; }
        if (inOl) { htmlOut.push('</ol>'); inOl = false; }
        htmlOut.push(`<div class="md-h4">${safeLine.replace(/^### /, '')}</div>`);
        continue;
      }
      if (/^## (.*)$/.test(safeLine)) {
        if (inUl) { htmlOut.push('</ul>'); inUl = false; }
        if (inOl) { htmlOut.push('</ol>'); inOl = false; }
        htmlOut.push(`<div class="md-h3">${safeLine.replace(/^## /, '')}</div>`);
        continue;
      }
      if (/^# (.*)$/.test(safeLine)) {
        if (inUl) { htmlOut.push('</ul>'); inUl = false; }
        if (inOl) { htmlOut.push('</ol>'); inOl = false; }
        htmlOut.push(`<div class="md-h2">${safeLine.replace(/^# /, '')}</div>`);
        continue;
      }

      // Blockquote
      if (/^(&gt;|>) (.*)$/.test(safeLine)) {
        if (inUl) { htmlOut.push('</ul>'); inUl = false; }
        if (inOl) { htmlOut.push('</ol>'); inOl = false; }
        htmlOut.push(`<div class="md-quote">${safeLine.replace(/^(&gt;|>) /, '')}</div>`);
        continue;
      }

      // Unordered list (* or -)
      const ulMatch = safeLine.match(/^[-*]\s+(.*)$/);
      if (ulMatch) {
        if (inOl) { htmlOut.push('</ol>'); inOl = false; }
        if (!inUl) { htmlOut.push('<ul class="md-ul">'); inUl = true; }
        htmlOut.push(`<li class="md-li">${ulMatch[1]}</li>`);
        continue;
      }

      // Ordered list (1. 2. etc)
      const olMatch = safeLine.match(/^(\d+)\.\s+(.*)$/);
      if (olMatch) {
        if (inUl) { htmlOut.push('</ul>'); inUl = false; }
        if (!inOl) { htmlOut.push('<ol class="md-ol">'); inOl = true; }
        htmlOut.push(`<li class="md-oli">${olMatch[2]}</li>`);
        continue;
      }

      // Blank line
      if (!safeLine.trim()) {
        if (inUl) { htmlOut.push('</ul>'); inUl = false; }
        if (inOl) { htmlOut.push('</ol>'); inOl = false; }
        continue;
      }

      // Normal paragraph
      if (inUl) { htmlOut.push('</ul>'); inUl = false; }
      if (inOl) { htmlOut.push('</ol>'); inOl = false; }
      htmlOut.push(`<div class="md-p">${safeLine}</div>`);
    }

    if (inUl) htmlOut.push('</ul>');
    if (inOl) htmlOut.push('</ol>');

    let result = htmlOut.join('\n');

    // Re-inject inline code
    result = result.replace(/@@@INLINECODE_(\d+)@@@/g, (m, idx) => {
      return `<code class="md-inline-code">${inlineCodes[Number(idx)]}</code>`;
    });

    return result;
  }

  function copyCode(btn) {
    const codeEl = btn.closest('.code-box')?.querySelector('.code-box-content');
    if (!codeEl) return;
    const text = codeEl.innerText || codeEl.textContent;
    navigator.clipboard.writeText(text).then(() => {
      const span = btn.querySelector('span');
      const oldText = span ? span.textContent : 'Copy';
      if (span) span.textContent = '✓ Copied!';
      btn.style.color = '#10b981';
      setTimeout(() => {
        if (span) span.textContent = oldText;
        btn.style.color = '';
      }, 2000);
    }).catch(err => {
      showToast({ title: 'Copy failed', message: String(err), type: 'error' });
    });
  }

  function copyMessage(btn, index) {
    const msg = chatHistory[index];
    if (!msg || !msg.content) return;
    navigator.clipboard.writeText(msg.content).then(() => {
      const span = btn.querySelector('span');
      const oldText = span ? span.textContent : 'Copy text';
      if (span) span.textContent = '✓ Copied!';
      btn.style.color = 'var(--accent-blue)';
      setTimeout(() => {
        if (span) span.textContent = oldText;
        btn.style.color = '';
      }, 2000);
    }).catch(err => {
      showToast({ title: 'Copy failed', message: String(err), type: 'error' });
    });
  }

  function sendStarterPrompt(promptType) {
    if (promptType === 'resources') {
      const ramText = latestDashboardData?.ram ? `${latestDashboardData.ram.used_gb} GB / ${latestDashboardData.ram.total_gb} GB (${latestDashboardData.ram.percent}%)` : 'RAM active';
      const gpuText = latestDashboardData?.gpu ? `${latestDashboardData.gpu.vram_used_mb} MB / ${latestDashboardData.gpu.vram_total_mb} MB (${latestDashboardData.gpu.percent}%) - ${latestDashboardData.gpu.name || 'GPU'}` : 'VRAM active';
      const modelsText = (latestDashboardData?.models || []).map(m => m.name).join(', ') || 'nova:latest';
      const prompt = `Explain current memory and GPU usage based on live system stats:\n- System RAM: ${ramText}\n- GPU VRAM: ${gpuText}\n- Loaded Models: ${modelsText}\nProvide a concise analysis of this system load.`;
      document.querySelector('#chatInput').value = prompt;
      sendChatMessage();
    } else if (promptType === 'script') {
      document.querySelector('#chatInput').value = 'Write a concise Python script using urllib to query the local /v1/chat/completions endpoint.';
      sendChatMessage();
    } else {
      document.querySelector('#chatInput').value = promptType;
      sendChatMessage();
    }
  }

  async function sendChatMessage() {
    const textarea = document.querySelector('#chatInput');
    const text = textarea.value.trim();
    if (!text && !pendingImage) return;

    const sendBtn = document.querySelector('#chatSendBtn');
    textarea.value = '';
    textarea.style.height = 'auto';

    if (text.startsWith('/cmd ') || text.startsWith('/run ')) {
      const command = text.replace(/^\/(cmd|run)\s+/, '').trim();
      chatHistory.push({ role: 'user', content: text });
      renderChatMessages();
      openCommandApproval(command);
      return;
    }

    sendBtn.disabled = true;

    const activeImage = pendingImage ? pendingImage.base64 : null;
    clearAttachment();

    const userMsg = { role: 'user', content: text || '(Attached image)' };
    if (activeImage) userMsg.images = [activeImage];
    chatHistory.push(userMsg);
    renderChatMessages();

    const container = document.querySelector('#chatMessages');
    const assistantIndex = chatHistory.length;
    chatHistory.push({ role: 'assistant', content: '', thinking: '' });

    const msgEl = document.createElement('div');
    msgEl.className = 'msg assistant';
    msgEl.id = 'chatMsgStreaming';
    msgEl.innerHTML = `
      <div class="msg-bubble">
        <div class="typing-wave" id="streamingWave">
          <div class="wave-dot"></div>
          <div class="wave-dot"></div>
          <div class="wave-dot"></div>
          <span style="font-size:12px; color:var(--ink-muted); margin-left:6px; font-weight:700;">Nova is connecting…</span>
        </div>
        <div id="streamingThink" style="display:none;"></div>
        <div id="streamingContent"></div>
      </div>
      <div class="msg-meta">Nova</div>
    `;
    container.appendChild(msgEl);
    container.scrollTop = container.scrollHeight;

    let accumulatedContent = '';
    let accumulatedThinking = '';

    // Progressive status updates while model warms up
    const waveSpan = msgEl.querySelector('#streamingWave span');
    const statusTimers = [
      setTimeout(() => { if (waveSpan) waveSpan.textContent = 'Nova is loading model into memory…'; }, 3000),
      setTimeout(() => { if (waveSpan) waveSpan.textContent = 'Allocating VRAM / system buffers…'; }, 8000),
      setTimeout(() => { if (waveSpan) waveSpan.textContent = 'Cold start in progress… generating first token…'; }, 16000)
    ];
    const clearStatusTimers = () => statusTimers.forEach(t => clearTimeout(t));

    try {
      const model = document.querySelector('#chatModelSelect').value || 'nova:latest';
      const think = document.querySelector('#chatThinkToggle').checked;
      const payloadMessages = chatHistory.slice(0, -1).map(m => {
        const item = { role: m.role, content: m.content };
        if (m.images && m.images.length) item.images = m.images;
        return item;
      });

      const reqBody = {
        model,
        messages: payloadMessages,
        think,
        stream: true
      };
      if (activeImage) reqBody.images = [activeImage];

      const res = await fetch('/api/dashboard-chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(reqBody)
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';
      let hasReceivedFirstToken = false;

      const thinkEl = document.getElementById('streamingThink');
      const contentEl = document.getElementById('streamingContent');
      const waveEl = document.getElementById('streamingWave');

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.trim()) continue;
          let data;
          try {
            data = JSON.parse(line);
          } catch (e) {
            continue;
          }

          if (data.error) {
            clearStatusTimers();
            throw new Error(data.error);
          }

          if (data.message) {
            clearStatusTimers();
            if (data.message.thinking) {
              accumulatedThinking += data.message.thinking;
              const pMode = document.querySelector('#previewThinkingSelect')?.value || latestDashboardData?.settings?.preview_thinking || 'summary';
              if (thinkEl && pMode !== 'hidden') {
                if (waveEl) waveEl.style.display = 'none';
                thinkEl.style.display = 'block';
                const isOpen = pMode === 'full' ? 'open' : '';
                thinkEl.innerHTML = `
                  <details class="thinking-box" ${isOpen}>
                    <summary>🧠 Planning & Reasoning (${accumulatedThinking.length} chars)</summary>
                    <pre style="white-space:pre-wrap; margin:0;">${escapeHtml(accumulatedThinking)}</pre>
                  </details>
                `;
              } else if (pMode === 'hidden' && waveEl) {
                const statusSpan = waveEl.querySelector('span');
                if (statusSpan) statusSpan.textContent = 'Nova is thinking…';
              }
            }

            if (data.message.content) {
              if (waveEl) waveEl.style.display = 'none';
              accumulatedContent += data.message.content;
              if (contentEl) {
                contentEl.innerHTML = formatMarkdown(accumulatedContent);
              }
            }
            container.scrollTop = container.scrollHeight;
          }
        }
      }

      clearStatusTimers();
      chatHistory[assistantIndex].content = accumulatedContent;
      chatHistory[assistantIndex].thinking = accumulatedThinking;
      renderChatMessages();

    } catch (err) {
      clearStatusTimers();
      if (msgEl) msgEl.remove();
      showToast({ title: 'Request Failed', message: String(err.message || err), type: 'error', duration: 10000 });
      chatHistory[assistantIndex] = {
        role: 'assistant',
        content: `⚠️ **Inference Connection Notice**\n\n${err.message || err}\n\n*Tip: If Ollama isn't running, run \`ollama serve\` or select an active model in the top-right dropdown.*`
      };
      renderChatMessages();
    } finally {
      clearStatusTimers();
      sendBtn.disabled = false;
      loadDashboard();
      document.querySelector('#chatInput').focus();
    }
  }

  const chatInput = document.querySelector('#chatInput');
  chatInput.addEventListener('input', () => {
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
  });

  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendChatMessage();
    }
  });

  document.querySelector('#chatSendBtn').addEventListener('click', sendChatMessage);

  document.querySelector('#proxyPill').addEventListener('click', () => {
    navigator.clipboard.writeText('http://127.0.0.1:8080/v1');
    showToast({ title: 'Proxy Copied', message: 'http://127.0.0.1:8080/v1 copied to clipboard.', type: 'success', duration: 4000 });
  });

  document.querySelector('#saveModelBtn').addEventListener('click', async () => {
    const payload = {
      system_prompt: document.querySelector('#systemPrompt').value
    };
    PARAM_KEYS.forEach(key => {
      const el = document.querySelector('#input_' + key);
      if (el) payload[key] = el.value;
    });

    const res = await postJson('/api/modelfile', payload);
    if (res.error) {
      showToast({ title: 'Validation Error', message: res.error, type: 'error', duration: 10000 });
    } else {
      showToast({ title: 'Saved', message: 'Modelfile saved to disk. Click Rebuild Nova to compile and apply.', type: 'success', duration: 6000 });
      loadDashboard();
    }
  });

  // Rebuild Nova Confirmation Modal Flow
  function openRebuildModal(suggestedCtx) {
    const modal = document.querySelector('#rebuildModal');
    if (!modal) return;
    if (suggestedCtx) {
      const paramInput = document.querySelector('#param_num_ctx');
      if (paramInput) {
        paramInput.value = suggestedCtx;
        paramInput.dispatchEvent(new Event('input'));
      }
    }
    const mf = latestDashboardData?.modelfile;
    const status = latestDashboardData?.modelfile_status;
    document.querySelector('#modalCtxLen').textContent = fmt(suggestedCtx || status?.saved_context || mf?.parameters?.num_ctx || 8192);
    document.querySelector('#modalActiveCtx').textContent = status?.loaded_context ? fmt(status.loaded_context) : 'None in VRAM';
    modal.style.display = 'flex';
  }

  function closeRebuildModal() {
    const modal = document.querySelector('#rebuildModal');
    if (modal) modal.style.display = 'none';
  }

  async function confirmRebuildNova() {
    const confirmBtn = document.querySelector('#modalConfirmBtn');
    const rebuildBtn = document.querySelector('#rebuildBtn');
    if (confirmBtn) {
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Compiling…';
    }
    if (rebuildBtn) {
      rebuildBtn.disabled = true;
      rebuildBtn.textContent = 'Rebuilding…';
    }
    showToast({ title: 'Rebuilding Nova', message: 'Re-compiling model layers via local engine…', type: 'info', duration: 10000 });

    try {
      const res = await postJson('/api/rebuild-nova', {});
      closeRebuildModal();
      if (res.ok) {
        showToast({ title: 'Rebuilt Successfully', message: 'nova:latest recompiled with updated Modelfile parameters.', type: 'success', duration: 7000 });
      } else {
        showToast({ title: 'Rebuild Failed', message: res.output || 'Compilation failed.', type: 'error', duration: 10000 });
      }
    } catch (err) {
      closeRebuildModal();
      showToast({ title: 'Error', message: String(err), type: 'error', duration: 10000 });
    } finally {
      if (confirmBtn) {
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Confirm & Rebuild';
      }
      if (rebuildBtn) {
        rebuildBtn.disabled = false;
        rebuildBtn.innerHTML = '<svg class="icon" viewBox="0 0 24 24"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg> Rebuild Nova';
      }
      loadDashboard();
    }
  }

  document.querySelector('#rebuildBtn').addEventListener('click', openRebuildModal);

  // System Terminal Command Execution Flow (Permission-Gated)
  let pendingCommandToRun = null;

  async function requestCommandExecution(btn) {
    let cmd = btn.getAttribute('data-cmd');
    if (!cmd) {
      const codeEl = btn.closest('.code-box')?.querySelector('.code-box-content');
      cmd = codeEl ? codeEl.innerText.trim() : '';
    }
    if (!cmd) return;
    openCommandApproval(cmd);
  }

  async function openCommandApproval(cmd) {
    pendingCommandToRun = cmd;
    const modal = document.querySelector('#cmdApprovalModal');
    const codeEl = document.querySelector('#cmdModalCode');
    const badgeEl = document.querySelector('#cmdRiskBadge');
    const warnEl = document.querySelector('#cmdRiskWarning');

    codeEl.textContent = cmd;
    badgeEl.textContent = 'Analyzing…';
    badgeEl.className = 'neu-pill';
    warnEl.textContent = 'Checking command safety with server…';
    modal.style.display = 'flex';

    try {
      const res = await postJson('/api/terminal/propose', { command: cmd });
      if (res.risk) {
        badgeEl.textContent = `${res.risk} RISK`;
        badgeEl.className = res.risk === 'CRITICAL' ? 'neu-pill bad' : res.risk === 'HIGH' ? 'neu-pill bad' : res.risk === 'LOW' ? 'neu-pill ok' : 'neu-pill';
        warnEl.textContent = res.warning || '';
        warnEl.style.color = res.color || 'var(--ink)';
      }
    } catch (_) {
      badgeEl.textContent = 'USER REVIEW';
      warnEl.textContent = 'Ensure this command is safe before approving.';
    }
  }

  function closeCmdApprovalModal() {
    const modal = document.querySelector('#cmdApprovalModal');
    if (modal) modal.style.display = 'none';
    pendingCommandToRun = null;
  }

  async function confirmCmdExecution() {
    if (!pendingCommandToRun) return;
    const cmd = pendingCommandToRun;
    closeCmdApprovalModal();

    showToast({ title: 'Running Command', message: `Executing: ${cmd.slice(0, 40)}…`, type: 'info', duration: 3500 });

    const assistantIndex = chatHistory.length;
    chatHistory.push({
      role: 'assistant',
      content: `⚡ **Running Command:** \`${cmd}\`\n*Executing in local terminal…*`
    });
    renderChatMessages();

    try {
      const res = await postJson('/api/terminal/execute', { command: cmd, approved: true });
      const statusEmoji = res.ok ? '✓' : '⚠️';
      const outputText = res.output ? res.output.trim() : '(Command completed with no output)';
      
      chatHistory[assistantIndex] = {
        role: 'assistant',
        content: `### ${statusEmoji} Command: \`${cmd}\`\n- **Status:** ${res.ok ? 'Success' : 'Failed (Exit Code: ' + res.return_code + ')'}\n- **Duration:** ${res.execution_time_s}s\n- **Target Directory:** \`${res.working_dir || 'Project Root'}\`\n\n\`\`\`terminal\n${outputText}\n\`\`\``
      };
      renderChatMessages();

      if (res.ok) {
        showToast({ title: 'Command Succeeded', message: `Exit code: ${res.return_code} (${res.execution_time_s}s)`, type: 'success', duration: 4000 });
      } else {
        showToast({ title: 'Command Error', message: `Exit code: ${res.return_code}`, type: 'error', duration: 7000 });
      }
    } catch (err) {
      chatHistory[assistantIndex] = {
        role: 'assistant',
        content: `⚠️ Execution failed: ${err.message || err}`
      };
      renderChatMessages();
      showToast({ title: 'Execution Failed', message: String(err), type: 'error', duration: 7000 });
    }
  }

  // Chat Sidebar Resizer Slider Grip
  const chatResizer = document.querySelector('#chatResizer');
  let isResizing = false;

  const savedWidth = localStorage.getItem('nova_chat_width');
  if (savedWidth && Number(savedWidth) >= 340 && Number(savedWidth) <= window.innerWidth * 0.95) {
    chatSidebar.style.width = `${savedWidth}px`;
  }

  if (chatResizer) {
    chatResizer.addEventListener('mousedown', (e) => {
      isResizing = true;
      chatSidebar.classList.add('resizing');
      chatResizer.classList.add('active');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    });

    window.addEventListener('mousemove', (e) => {
      if (!isResizing) return;
      const newWidth = window.innerWidth - e.clientX;
      const minW = 340;
      const maxW = Math.min(window.innerWidth * 0.94, 1200);
      if (newWidth >= minW && newWidth <= maxW) {
        chatSidebar.style.width = `${newWidth}px`;
      }
    });

    window.addEventListener('mouseup', () => {
      if (isResizing) {
        isResizing = false;
        chatSidebar.classList.remove('resizing');
        chatResizer.classList.remove('active');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        localStorage.setItem('nova_chat_width', parseInt(chatSidebar.style.width));
      }
    });
  }

  // Multimodal File/Image Attachment Handler
  let pendingImage = null; // { base64: '...', dataUrl: '...', name: '...', size: '...' }
  const fileInput = document.querySelector('#chatFileInput');
  const attachBtn = document.querySelector('#chatAttachBtn');
  const previewWrap = document.querySelector('#chatAttachmentPreview');
  const thumbEl = document.querySelector('#chatAttachmentThumb');
  const nameEl = document.querySelector('#chatAttachmentName');
  const sizeEl = document.querySelector('#chatAttachmentSize');
  const removeBtn = document.querySelector('#removeAttachmentBtn');

  if (attachBtn && fileInput) {
    attachBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => {
      const file = e.target.files?.[0];
      if (file) handleImageFile(file);
    });
  }

  if (removeBtn) {
    removeBtn.addEventListener('click', () => clearAttachment());
  }

  function handleImageFile(file) {
    if (!file.type.startsWith('image/')) {
      showToast({ title: 'Attachment', message: 'Only image files (PNG, JPG, WebP) are supported for multimodal models.', type: 'bad' });
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      showToast({ title: 'Attachment', message: 'Image exceeds 10MB limit.', type: 'bad' });
      return;
    }
    const reader = new FileReader();
    reader.onload = (e) => {
      const dataUrl = e.target.result;
      const base64Data = dataUrl.split(',')[1];
      pendingImage = {
        base64: base64Data,
        dataUrl: dataUrl,
        name: file.name,
        size: (file.size / 1024).toFixed(1) + ' KB'
      };
      if (thumbEl) thumbEl.src = dataUrl;
      if (nameEl) nameEl.textContent = file.name;
      if (sizeEl) sizeEl.textContent = pendingImage.size;
      if (previewWrap) previewWrap.style.display = 'flex';
    };
    reader.readAsDataURL(file);
  }

  function clearAttachment() {
    pendingImage = null;
    if (fileInput) fileInput.value = '';
    if (previewWrap) previewWrap.style.display = 'none';
  }

  // Support Ctrl+V pasting images from clipboard directly into chat!
  document.querySelector('#chatInput')?.addEventListener('paste', (e) => {
    const items = (e.clipboardData || e.originalEvent?.clipboardData)?.items;
    if (!items) return;
    for (const item of items) {
      if (item.type.indexOf('image') !== -1) {
        const blob = item.getAsFile();
        if (blob) handleImageFile(blob);
      }
    }
  });

  // Web Speech API Voice Input (Speech-to-Text)
  let speechRecognizer = null;
  let isListening = false;
  const voiceBtn = document.querySelector('#chatVoiceBtn');

  if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    speechRecognizer = new SpeechRecognition();
    speechRecognizer.continuous = false;
    speechRecognizer.interimResults = true;
    speechRecognizer.lang = 'en-US';

    speechRecognizer.onstart = () => {
      isListening = true;
      voiceBtn?.classList.add('recording');
      const input = document.querySelector('#chatInput');
      if (input) input.placeholder = 'Listening... Speak into your microphone...';
    };

    speechRecognizer.onresult = (event) => {
      let transcript = '';
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        transcript += event.results[i][0].transcript;
      }
      if (transcript) {
        const textarea = document.querySelector('#chatInput');
        textarea.value = transcript;
        textarea.style.height = 'auto';
        textarea.style.height = `${Math.min(textarea.scrollHeight, 120)}px`;
      }
    };

    speechRecognizer.onerror = (event) => {
      console.warn('Speech recognition error:', event.error);
      stopListening();
      if (event.error !== 'no-speech') {
        showToast({ title: 'Voice Input', message: `Microphone error: ${event.error}`, type: 'bad' });
      }
    };

    speechRecognizer.onend = () => {
      stopListening();
    };
  }

  function stopListening() {
    isListening = false;
    voiceBtn?.classList.remove('recording');
    const textarea = document.querySelector('#chatInput');
    if (textarea) textarea.placeholder = 'Message Nova or attach an image...';
  }

  if (voiceBtn) {
    voiceBtn.addEventListener('click', () => {
      if (!speechRecognizer) {
        showToast({ title: 'Voice Input', message: 'Speech recognition is not supported in this browser.', type: 'bad' });
        return;
      }
      if (isListening) {
        speechRecognizer.stop();
        stopListening();
      } else {
        try {
          speechRecognizer.start();
        } catch (err) {
          console.warn('Speech recognition start failed:', err);
        }
      }
    });
  }

  // SQLite Settings Listeners
  const previewThinkingSelect = document.querySelector('#previewThinkingSelect');
  if (previewThinkingSelect) {
    previewThinkingSelect.addEventListener('change', async (e) => {
      await postJson('/api/settings', { preview_thinking: e.target.value });
      renderChatMessages();
    });
  }

  const saveChatToggle = document.querySelector('#saveChatToggle');
  if (saveChatToggle) {
    saveChatToggle.addEventListener('change', async (e) => {
      await postJson('/api/settings', { save_chat_history: e.target.checked });
      showToast({
        title: e.target.checked ? 'Chat History Saved' : 'Privacy Mode Active',
        message: e.target.checked ? 'Conversations are stored in SQLite (nova-dashboard.db).' : 'Conversations stay in local session memory only.',
        type: 'info'
      });
    });
  }

  // Theme Switching Logic
  function updateThemeUI(theme) {
    const label = document.querySelector('#themeToggleLabel');
    const btn = document.querySelector('#themeToggleBtn');
    if (label) {
      label.textContent = theme === 'dark' ? 'Light' : 'Dark';
    }
    if (btn) {
      btn.title = theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode';
    }
  }

  async function toggleTheme() {
    const doc = document.documentElement;
    const current = doc.getAttribute('data-theme') || 'light';
    const next = current === 'dark' ? 'light' : 'dark';

    doc.classList.add('theme-transition');
    doc.setAttribute('data-theme', next);
    localStorage.setItem('nova_theme', next);
    updateThemeUI(next);

    setTimeout(() => {
      doc.classList.remove('theme-transition');
    }, 350);

    try {
      await postJson('/api/settings', { theme: next });
    } catch (_) {}

    showToast({
      title: next === 'dark' ? 'Dark Mode' : 'Light Mode',
      message: next === 'dark' ? 'Deep gunmetal neumorphic theme enabled.' : 'Daylight soft-grey neumorphic theme enabled.',
      type: 'info',
      duration: 3000
    });
  }

  const themeToggleBtn = document.querySelector('#themeToggleBtn');
  if (themeToggleBtn) {
    themeToggleBtn.addEventListener('click', toggleTheme);
    updateThemeUI(document.documentElement.getAttribute('data-theme') || 'light');
  }

  document.querySelector('#refreshBtn').addEventListener('click', () => {
    loadDashboard();
    showToast({ title: 'Refreshed', message: 'Metrics updated.', type: 'info', duration: 2500 });
  });

  loadDashboard();
  setInterval(loadDashboard, 4000);

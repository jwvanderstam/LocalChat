// Extracted verbatim from templates/settings.html so the Content-Security-Policy can drop
// 'unsafe-inline' for scripts (audit M6). The template carried no Jinja
// interpolation here, so this is the same code in a file the browser fetches
// from this origin, loaded at the point the inline block used to run.

async function refreshStats() {
    try {
        const r = await fetch('/api/settings/stats');
        if (!r.ok) return;
        const d = await r.json();
        document.getElementById('last-refreshed').textContent =
            'Updated: ' + d.system.timestamp.slice(0, 19).replace('T', ' ');
        document.getElementById('uptime-cell').textContent =
            (d.metrics.uptime_seconds / 3600).toFixed(1) + ' h';
        await loadMetrics();
    } catch (e) { console.warn('Settings refresh failed', e); }
}

async function loadMetrics() {
    try {
        const r = await fetch('/api/metrics.json');
        if (!r.ok) return;
        const d = await r.json();
        renderMetricsTable({ metrics: d });
    } catch (e) { console.warn('Metrics load failed', e); }
}

let _requestsChart = null;

function _accent(alpha) {
    const rgb = getComputedStyle(document.documentElement)
        .getPropertyValue('--lc-accent-rgb').trim() || '56, 126, 130';
    return `rgba(${rgb}, ${alpha})`;
}

function renderMetricsTable(data) {
    const counters   = data?.metrics?.counters   ?? data?.counters   ?? {};
    const histograms = data?.metrics?.histograms ?? data?.histograms ?? {};
    const container  = document.getElementById('metrics-table-container');

    if (!Object.keys(counters).length && !Object.keys(histograms).length) {
        container.innerHTML = '<p class="text-muted small">No metrics data yet.</p>';
        return;
    }

    // Aggregate http_requests_total by endpoint (sum across methods / status codes)
    const endpointTotals = {};
    for (const [k, v] of Object.entries(counters)) {
        const m = k.match(/http_requests_total\{.*?endpoint="([^"]+)"/);
        if (m) endpointTotals[m[1]] = (endpointTotals[m[1]] || 0) + v;
    }

    // Latency table — sorted slowest-first by p99
    const latencyRows = Object.entries(histograms)
        .sort((a, b) => (b[1].p99 || 0) - (a[1].p99 || 0))
        .map(([k, s]) => `
            <tr>
                <td class="text-monospace small">${k}</td>
                <td class="text-end">${(s.p50 * 1000).toFixed(1)}</td>
                <td class="text-end">${(s.p95 * 1000).toFixed(1)}</td>
                <td class="text-end fw-semibold ${s.p99 > 1 ? 'text-danger' : 'text-body'}">${(s.p99 * 1000).toFixed(1)}</td>
                <td class="text-end text-muted">${s.count}</td>
            </tr>`)
        .join('');

    // Counter table
    const counterRows = Object.entries(counters)
        .sort((a, b) => b[1] - a[1])
        .map(([k, v]) => `<tr><td class="text-monospace small">${k}</td><td class="text-end">${v}</td></tr>`)
        .join('');

    container.innerHTML = `
        ${latencyRows ? `
        <h6 class="text-muted small fw-semibold text-uppercase mb-1 mt-2">Latency (ms)</h6>
        <table class="table table-sm table-hover mb-3">
            <thead><tr><th>Metric</th><th class="text-end">p50</th><th class="text-end">p95</th><th class="text-end">p99</th><th class="text-end">n</th></tr></thead>
            <tbody>${latencyRows}</tbody>
        </table>` : ''}
        ${counterRows ? `
        <h6 class="text-muted small fw-semibold text-uppercase mb-1">Counters</h6>
        <table class="table table-sm table-hover mb-0">
            <thead><tr><th>Metric</th><th class="text-end">Value</th></tr></thead>
            <tbody>${counterRows}</tbody>
        </table>` : ''}`;

    // Bar chart — requests per endpoint
    const chartCanvas = document.getElementById('requests-chart');
    if (!chartCanvas || !Object.keys(endpointTotals).length) return;
    const sorted  = Object.entries(endpointTotals).sort((a, b) => b[1] - a[1]);
    const labels  = sorted.map(([ep]) => ep);
    const values  = sorted.map(([, v]) => v);
    if (_requestsChart) {
        _requestsChart.data.labels = labels;
        _requestsChart.data.datasets[0].data = values;
        _requestsChart.update();
    } else {
        _requestsChart = new Chart(chartCanvas, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    label: 'Requests',
                    data: values,
                    // Read from the stylesheet rather than hardcoding: the chart
                    // then follows the theme, dark mode and the alternate accents
                    // instead of staying Bootstrap blue on a page that has none.
                    backgroundColor: _accent(0.7),
                    borderColor: _accent(1),
                    borderWidth: 1,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { font: { size: 11 } } },
                    y: { beginAtZero: true, ticks: { precision: 0 } }
                }
            }
        });
    }
}

// Load on page open, refresh every 30 s
loadMetrics();
setInterval(() => { refreshStats(); loadMetrics(); }, 30000);

// ── Memory tab ────────────────────────────────────────────────────────────────

const TYPE_COLORS = {
    fact:       'bg-primary',
    preference: 'bg-success',
    decision:   'bg-warning text-dark',
    entity:     'bg-info text-dark',
};

async function loadMemories() {
    try {
        const res = await fetch('/api/memory/');
        const data = await res.json();
        const list = document.getElementById('memory-list');
        const count = document.getElementById('memory-count');
        if (!data.success) { list.innerHTML = `<p class="text-danger p-3">${data.message}</p>`; return; }
        count.textContent = data.count;
        if (!data.memories.length) {
            list.innerHTML = '<p class="text-muted p-3 mb-0">No memories stored yet. Click "Extract from conversations" to get started.</p>';
            return;
        }
        list.innerHTML = data.memories.map(m => {
            const badge = TYPE_COLORS[m.memory_type] || 'bg-secondary';
            const date = m.created_at ? new Date(m.created_at).toLocaleDateString() : '';
            return `<div class="d-flex align-items-start gap-2 px-3 py-2 border-bottom">
                <span class="badge ${badge} flex-shrink-0 mt-1" style="font-size:0.65rem">${m.memory_type}</span>
                <span class="flex-grow-1 small">${escapeHtml(m.content)}</span>
                <span class="text-muted" style="font-size:0.7rem;white-space:nowrap">${date}</span>
                <button class="btn btn-link btn-sm p-0 text-danger flex-shrink-0" data-delete-memory="${m.id}" title="Delete">
                    <i class="bi bi-x-circle"></i>
                </button>
            </div>`;
        }).join('');
    } catch (e) {
        document.getElementById('memory-list').innerHTML = `<p class="text-danger p-3">${e.message}</p>`;
    }
}

function escapeHtml(str) {
    return String(str).replace(/[<>&"']/g, c =>
        ({  '<':'&lt;', '>':'&gt;', '&':'&amp;', '"':'&quot;', "'":'&#39;' }[c]));
}

async function extractMemories() {
    const status = document.getElementById('memory-action-status');
    status.textContent = 'Extracting…';
    try {
        const res = await fetch('/api/memory/extract', { method: 'POST', headers: {'Content-Type':'application/json'}, body: '{}' });
        const data = await res.json();
        if (data.success) {
            status.textContent = `Done — ${data.new_memories} new memories from ${data.conversations_processed} conversations.`;
        } else {
            status.textContent = 'Error: ' + data.message;
        }
        loadMemories();
    } catch (e) { status.textContent = 'Error: ' + e.message; }
}

async function deleteMemory(id) {
    const ok = await window.localchatConfirm({
        title: 'Delete memory',
        body: 'This memory will be retired and stop informing answers.',
        confirmText: 'Delete',
    });
    if (!ok) return;
    await fetch(`/api/memory/${id}`, { method: 'DELETE' });
    loadMemories();
}

async function clearAllMemories() {
    const ok = await window.localchatConfirm({
        title: 'Clear all memories',
        body: 'Every stored memory in this workspace will be retired. Answers will stop drawing on them.',
        confirmText: 'Clear all',
    });
    if (!ok) return;
    const status = document.getElementById('memory-action-status');
    status.textContent = 'Clearing…';
    const res = await fetch('/api/memory/', { method: 'DELETE' });
    const data = await res.json();
    status.textContent = data.success ? `Cleared ${data.deleted} memories.` : 'Error: ' + data.message;
    loadMemories();
}

// Load memories when the tab is shown
document.getElementById('memory-tab').addEventListener('shown.bs.tab', loadMemories);

// ── RAG Parameters tab ────────────────────────────────────────────────────────

async function loadRagParams() {
    try {
        const res = await fetch('/api/settings/rag');
        if (!res.ok) return;
        const d = await res.json();
        if (!d.success) return;
        const p = d.params;
        const set = (id, badgeId, val, toFixed) => {
            const el = document.getElementById(id);
            const badge = document.getElementById(badgeId);
            if (!el) return;
            el.value = val;
            if (badge) badge.textContent = toFixed != null ? parseFloat(val).toFixed(toFixed) : val;
        };
        set('input-top-k',      'badge-top-k',      p.TOP_K_RESULTS.value,       null);
        set('input-rerank-k',   'badge-rerank-k',   p.RERANK_TOP_K.value,        null);
        set('input-diversity',  'badge-diversity',  p.DIVERSITY_THRESHOLD.value,  2);
        set('input-semantic-w', 'badge-semantic-w', p.SEMANTIC_WEIGHT.value,      2);
    } catch (e) { console.warn('RAG params load failed', e); }
}

async function saveRagParams() {
    const status = document.getElementById('rag-save-status');
    status.className = 'badge bg-secondary';
    status.textContent = 'Saving…';
    try {
        const body = {
            TOP_K_RESULTS:       parseInt(document.getElementById('input-top-k').value),
            RERANK_TOP_K:        parseInt(document.getElementById('input-rerank-k').value),
            DIVERSITY_THRESHOLD: parseFloat(document.getElementById('input-diversity').value),
            SEMANTIC_WEIGHT:     parseFloat(document.getElementById('input-semantic-w').value),
        };
        const res = await fetch('/api/settings/rag', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body),
        });
        const d = await res.json();
        if (d.success) {
            status.className = 'badge bg-success';
            status.textContent = 'Saved';
            setTimeout(() => { status.textContent = ''; }, 3000);
        } else {
            status.className = 'badge bg-danger';
            status.textContent = (d.errors || ['Error']).join('; ');
        }
    } catch (e) {
        document.getElementById('rag-save-status').className = 'badge bg-danger';
        document.getElementById('rag-save-status').textContent = e.message;
    }
}

// Load RAG params when the tab is shown
document.getElementById('rag-tab').addEventListener('shown.bs.tab', loadRagParams);

// If arriving via /settings#rag-params, activate that tab immediately
if (window.location.hash === '#rag-params') {
    const tab = document.getElementById('rag-tab');
    if (tab) { bootstrap.Tab.getOrCreateInstance(tab).show(); }
}

// ── Event wiring ──────────────────────────────────────────────────────────────
// Replaces the inline `on*=` attributes a strict CSP blocks (audit M6).
document.getElementById('refresh-stats-btn')?.addEventListener('click', () => refreshStats());
document.getElementById('extract-memories-btn')?.addEventListener('click', () => extractMemories());
document.getElementById('clear-memories-btn')?.addEventListener('click', () => clearAllMemories());
document.getElementById('save-rag-params-btn')?.addEventListener('click', () => saveRagParams());
document.getElementById('reset-rag-params-btn')?.addEventListener('click', () => loadRagParams());

// Every RAG slider updates a badge as it moves. One listener, driven by the
// data-badge attribute, replaces four near-identical oninput expressions.
document.querySelectorAll('input[data-badge]').forEach((slider) => {
    slider.addEventListener('input', () => {
        const badge = document.getElementById(slider.dataset.badge);
        if (!badge) return;
        const decimals = slider.dataset.badgeDecimals;
        badge.textContent = decimals
            ? parseFloat(slider.value).toFixed(Number(decimals))
            : slider.value;
    });
});

// The memory list is re-rendered on every load, so this is delegated.
document.getElementById('memory-list')?.addEventListener('click', (event) => {
    const btn = event.target.closest('[data-delete-memory]');
    if (btn) deleteMemory(btn.dataset.deleteMemory);
});

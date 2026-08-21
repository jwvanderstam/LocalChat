/*
 * Admin log viewer — Settings → Logs.
 *
 * Reads GET /api/logs, which returns one record per line with the JSON fields
 * already split out when LOG_FORMAT=json, and the raw text when it is not. Both
 * shapes are rendered; a text-format line simply has no timestamp or logger.
 */
(function () {
'use strict';

const LEVEL_CLASS = {
    DEBUG: 'text-muted',
    INFO: 'text-body',
    WARNING: 'text-warning-emphasis',
    ERROR: 'text-danger',
    CRITICAL: 'text-danger fw-bold',
};

// Log lines carry text this application never authored — a filename an
// attacker chose, a header they sent. It reaches the DOM as text, never markup.
function esc(value) {
    return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function shortTime(timestamp) {
    if (!timestamp) return '—';
    // "2026-08-21T10:00:00.123456+00:00" -> "08-21 10:00:00"
    const match = /^\d{4}-(\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})/.exec(timestamp);
    return match ? `${match[1]} ${match[2]}` : timestamp;
}

function renderRow(record) {
    const level = record.level || '';
    const cls = LEVEL_CLASS[level] || 'text-body';
    // An unparsed line has no fields to spread across columns, so its whole text
    // goes in the message cell rather than inventing values for the others.
    const logger = record.parsed ? esc(record.logger || '') : '';
    return `<tr class="${cls}">
        <td class="font-monospace small text-nowrap">${esc(shortTime(record.timestamp))}</td>
        <td class="small">${esc(level || '—')}</td>
        <td class="small text-truncate" style="max-width:14rem" title="${logger}">${logger || '—'}</td>
        <td class="small font-monospace" style="white-space:pre-wrap; word-break:break-word">${esc(record.message)}</td>
    </tr>`;
}

function initLogs() {
    const rows = document.getElementById('log-rows');
    const summary = document.getElementById('log-summary');
    const alertBox = document.getElementById('log-alert');
    const levelEl = document.getElementById('log-level');
    const queryEl = document.getElementById('log-query');
    const limitEl = document.getElementById('log-limit');
    const refreshEl = document.getElementById('log-refresh');
    if (!rows) return;

    function notify(message, kind) {
        alertBox.className = `alert py-2 small alert-${kind}`;
        alertBox.textContent = message;
        alertBox.classList.remove('d-none');
    }

    async function load() {
        const params = new URLSearchParams({ limit: limitEl.value });
        if (levelEl.value) params.set('level', levelEl.value);
        if (queryEl.value.trim()) params.set('q', queryEl.value.trim());

        let body;
        try {
            const response = await fetch(`/api/logs?${params}`);
            if (!response.ok) {
                notify(`Could not read the log (HTTP ${response.status}).`, 'danger');
                return;
            }
            body = await response.json();
        } catch (e) {
            notify('Could not reach the server.', 'danger');
            return;
        }

        if (!body.available) {
            rows.innerHTML = '';
            summary.textContent = '';
            // The file sink can be absent by configuration, not only by failure.
            notify(`No log to show: ${body.reason}. Check that 'file' is in LOG_SINKS.`, 'warning');
            return;
        }

        alertBox.classList.add('d-none');
        // Newest first reads better on screen; the API returns oldest-first.
        rows.innerHTML = body.records.slice().reverse().map(renderRow).join('');
        summary.textContent = body.records.length
            ? `${body.records.length} lines shown, ${body.scanned} scanned.`
            : 'Nothing matched that filter.';
    }

    refreshEl.addEventListener('click', load);
    levelEl.addEventListener('change', load);
    limitEl.addEventListener('change', load);
    let timer = null;
    queryEl.addEventListener('input', () => {
        clearTimeout(timer);
        timer = setTimeout(load, 300);
    });

    start(load);
}

async function start(load) {
    const tabItem = document.getElementById('logs-tab-item');
    if (!tabItem) return;
    try {
        const me = await (await fetch('/api/users/me')).json();
        if (me.role !== 'admin') return;  // leave the tab hidden
    } catch (e) {
        return;  // a failed check must not reveal an admin surface
    }
    tabItem.classList.remove('d-none');
    // Loaded on reveal, matching users.js. The read is a bounded tail rather than a
    // whole-file scan, so it costs about the same as the stats this page already pulls.
    await load();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initLogs);
} else {
    initLogs();
}
})();

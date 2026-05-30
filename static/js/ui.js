/**
 * ui.js — Pure rendering utilities. No mutable state; no side-effects beyond
 * building DOM nodes. Import this from conversation.js, streaming.js, and chat.js.
 */

export function escapeHtml(str) {
    return String(str).replace(/[<>&"']/g, (char) => {
        switch (char) {
            case '<': return '&lt;';
            case '>': return '&gt;';
            case '&': return '&amp;';
            case '"': return '&quot;';
            case "'": return '&#39;';
            default:  return char;
        }
    });
}

export function formatTime(timestamp) {
    const date = timestamp instanceof Date ? timestamp : new Date(timestamp);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function scrollToBottom() {
    const el = document.getElementById('chat-messages');
    if (el) el.scrollTop = el.scrollHeight;
}

function isTableSeparator(line) {
    return /^[\s|:\-]+$/.test(line) && line.includes('-') && line.includes('|');
}

function renderTable(lines) {
    const rows = lines.map(l =>
        l.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map(c => c.trim())
    );
    const header = rows[0];
    const body   = rows.slice(2);
    const ths = header.map(h => `<th>${escapeHtml(h)}</th>`).join('');
    const trs = body.map(row => {
        const tds = row.map(c => `<td>${escapeHtml(c)}</td>`).join('');
        return `<tr>${tds}</tr>`;
    }).join('');
    return `<div class="table-responsive my-2"><table class="table table-sm table-bordered table-striped mb-0"><thead class="table-light"><tr>${ths}</tr></thead><tbody>${trs}</tbody></table></div>`;
}

function formatInline(text) {
    text = text.replace(/[<>&]/g, (char) => {
        switch (char) {
            case '<': return '&lt;';
            case '>': return '&gt;';
            case '&': return '&amp;';
            default:  return char;
        }
    });
    text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/\*(.+?)\*/g,     '<em>$1</em>');
    text = text.replace(/`(.+?)`/g,       '<code>$1</code>');
    return text;
}

export function formatMessageText(text) {
    const lines  = text.replace(/\r\n?/g, '\n').split('\n');
    const output = [];
    let i = 0;

    while (i < lines.length) {
        if (lines[i].includes('|') && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
            const tableLines = [];
            while (i < lines.length) {
                if (lines[i].includes('|')) {
                    tableLines.push(lines[i++]);
                } else if (lines[i].trim() === '' && i + 1 < lines.length && lines[i + 1].includes('|')) {
                    i++;
                } else {
                    break;
                }
            }
            output.push(renderTable(tableLines));
        } else {
            output.push(formatInline(lines[i++]));
        }
    }

    return output.join('<br>');
}

export function updateModeBadge() {
    const modeBadge    = document.getElementById('mode-badge');
    const ragToggle    = document.getElementById('rag-toggle');
    const enhanceToggle = document.getElementById('enhance-toggle');
    if (!modeBadge || !ragToggle) return;

    const isRag      = ragToggle.checked;
    const isEnhanced = enhanceToggle && enhanceToggle.checked;

    if (isEnhanced) {
        modeBadge.textContent = 'RAG + Web Enhanced';
        modeBadge.className   = 'badge bg-success';
    } else if (isRag) {
        modeBadge.textContent = 'RAG Mode: ON';
        modeBadge.className   = 'badge bg-primary';
    } else {
        modeBadge.textContent = 'Direct LLM Mode';
        modeBadge.className   = 'badge bg-secondary';
    }
}

export function buildSourcesPanel(sources) {
    const byFile = new Map();
    sources.forEach(src => {
        if (!byFile.has(src.filename)) byFile.set(src.filename, { chunk_id: src.chunk_id, pages: new Set() });
        if (src.page_number) byFile.get(src.filename).pages.add(src.page_number);
    });

    const fileCount = byFile.size;
    const details   = document.createElement('details');
    details.className = 'sources-panel mt-2';

    const summary = document.createElement('summary');
    summary.className   = 'text-muted small';
    summary.textContent = `${fileCount} source${fileCount !== 1 ? 's' : ''}`;
    details.appendChild(summary);

    const list = document.createElement('ul');
    list.className = 'list-unstyled mb-0 mt-1';

    byFile.forEach(({ chunk_id, pages }, filename) => {
        const li = document.createElement('li');
        li.className = 'small text-muted mb-1';

        let label = escapeHtml(filename);
        if (pages.size > 0) {
            const sorted = [...pages].sort((a, b) => a - b);
            label += ` <span class="opacity-75">p.${sorted.join(', ')}</span>`;
        }
        li.innerHTML = label;

        if (chunk_id) {
            const link       = document.createElement('a');
            link.href        = '#';
            link.className   = 'ms-2 text-decoration-none opacity-75';
            link.textContent = 'view';

            const contextDiv       = document.createElement('div');
            contextDiv.className   = 'chunk-context mt-1 d-none';

            link.addEventListener('click', async (e) => {
                e.preventDefault();
                if (!contextDiv.classList.contains('d-none')) {
                    contextDiv.classList.add('d-none');
                    link.textContent = 'view';
                    return;
                }
                link.textContent = '…';
                try {
                    const resp = await fetch(`/api/documents/chunks/${chunk_id}/context?window=1`);
                    const data = await resp.json();
                    if (data.success && data.chunks.length > 0) {
                        const pre = document.createElement('pre');
                        pre.className   = 'chunk-context-text p-2 rounded';
                        pre.textContent = data.chunks.map(c => c.chunk_text).join('\n\n---\n\n');
                        contextDiv.innerHTML = '';
                        contextDiv.appendChild(pre);
                        contextDiv.classList.remove('d-none');
                        link.textContent = 'hide';
                    } else {
                        link.textContent = 'view';
                    }
                } catch (_) {
                    link.textContent = 'view';
                }
            });

            li.appendChild(link);
            li.appendChild(contextDiv);
        }
        list.appendChild(li);
    });

    details.appendChild(list);
    return details;
}

export function buildFeedbackBar(messageId, conversationId, sourceChunkIds) {
    const bar = document.createElement('div');
    bar.className = 'feedback-bar mt-2';

    const label       = document.createElement('span');
    label.className   = 'text-muted small me-2';
    label.textContent = 'Helpful?';
    bar.appendChild(label);

    const makeBtn = (rating, icon, title) => {
        const btn         = document.createElement('button');
        btn.className     = 'btn btn-sm feedback-btn me-1';
        btn.innerHTML     = icon;
        btn.title         = title;
        btn.dataset.rating = rating;
        btn.addEventListener('click', async () => {
            if (bar.dataset.voted) return;
            bar.dataset.voted = '1';
            btn.classList.add('active');
            try {
                await fetch('/api/feedback', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ rating, message_id: messageId, conversation_id: conversationId, source_chunk_ids: sourceChunkIds }),
                });
            } catch (_) { /* non-critical */ }
            bar.querySelectorAll('.feedback-btn').forEach(b => { if (b !== btn) b.classList.add('dimmed'); });
        });
        return btn;
    };

    bar.appendChild(makeBtn(1,  '👍', 'Good answer'));
    bar.appendChild(makeBtn(-1, '👎', 'Bad answer'));
    return bar;
}

export function buildPlanTrace(plan) {
    const INTENT_COLORS = {
        factual_lookup: 'bg-primary',
        comparison:     'bg-info text-dark',
        synthesis:      'bg-warning text-dark',
        general:        'bg-secondary',
    };
    const intentColor = INTENT_COLORS[plan.intent] || 'bg-secondary';

    const details     = document.createElement('details');
    details.className = 'plan-trace mb-2';

    const summary   = document.createElement('summary');
    summary.className = 'text-muted small d-flex align-items-center gap-2';
    summary.innerHTML =
        `<span class="badge ${intentColor}" style="font-size:0.65rem">${escapeHtml(plan.intent)}</span>` +
        `<span>Reasoning trace</span>` +
        (plan.estimated_hops > 1
            ? `<span class="badge bg-light text-dark border" style="font-size:0.65rem">${escapeHtml(String(plan.estimated_hops))}-hop</span>`
            : '');
    details.appendChild(summary);

    const body = document.createElement('div');
    body.className = 'plan-trace-body mt-1 ps-2';

    if (plan.sub_questions && plan.sub_questions.length > 0) {
        const ql = document.createElement('ul');
        ql.className = 'list-unstyled mb-1';
        plan.sub_questions.forEach(q => {
            const li = document.createElement('li');
            li.className = 'small text-muted';
            li.innerHTML = `<span class="me-1">→</span>${escapeHtml(q)}`;
            ql.appendChild(li);
        });
        body.appendChild(ql);
    }

    if (plan.tools && plan.tools.length > 0) {
        const toolsDiv = document.createElement('div');
        toolsDiv.className = 'small text-muted';
        toolsDiv.innerHTML = plan.tools.map(t =>
            `<span class="badge bg-light text-dark border me-1" style="font-size:0.6rem">${escapeHtml(t)}</span>`
        ).join('');
        body.appendChild(toolsDiv);
    }

    details.appendChild(body);
    return details;
}

export function copyChatToClipboard(chatHistory) {
    if (chatHistory.length === 0) { alert('No chat history to copy'); return; }

    let text = 'LocalChat Conversation\n' + '='.repeat(50) + '\n\n';
    chatHistory.forEach(msg => {
        const ts   = new Date(msg.timestamp).toLocaleString();
        const role = msg.role === 'user' ? 'You' : 'Assistant';
        text += `[${ts}] ${role}:\n${msg.content}\n\n`;
    });
    text += '='.repeat(50) + `\nTotal messages: ${chatHistory.length}\nExported: ${new Date().toLocaleString()}`;

    const btn = document.getElementById('copy-chat-btn');
    navigator.clipboard.writeText(text).then(() => {
        if (!btn) return;
        const orig = btn.innerHTML;
        btn.innerHTML = '<i class="bi bi-check me-1"></i>Copied!';
        btn.classList.replace('btn-outline-primary', 'btn-success');
        setTimeout(() => { btn.innerHTML = orig; btn.classList.replace('btn-success', 'btn-outline-primary'); }, 2000);
    }).catch(() => alert('Failed to copy to clipboard. Please try again.'));
}

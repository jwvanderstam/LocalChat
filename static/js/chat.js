/**
 * Chat functionality with persistent conversation memory
 */

// Chat state
let chatHistory = [];
let isStreaming = false;
let currentConversationId = localStorage.getItem('currentConversationId') || null;
let conversations = [];
let renameTargetId = null;

// DOM elements
const chatMessages = document.getElementById('chat-messages');
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');
const ragToggle = document.getElementById('rag-toggle');
const enhanceToggle = document.getElementById('enhance-toggle');
const temperatureSlider = document.getElementById('temperature-slider');
const temperatureValue = document.getElementById('temperature-value');
const modeBadge = document.getElementById('mode-badge');
const copyChatBtn = document.getElementById('copy-chat-btn');
const newChatBtn = document.getElementById('new-chat-btn');
const newChatHeaderBtn = document.getElementById('new-chat-header-btn');
const clearHistoryBtn = document.getElementById('clear-history-btn');
const conversationsList = document.getElementById('conversations-list');
const renameInput = document.getElementById('rename-input');
const renameConfirmBtn = document.getElementById('rename-confirm-btn');

// Templates
const userMessageTemplate = document.getElementById('user-message-template');
const assistantMessageTemplate = document.getElementById('assistant-message-template');
const loadingTemplate = document.getElementById('loading-template');

// ============================================================================
// MODE BADGE
// ============================================================================

function updateModeBadge() {
    if (!modeBadge) return;
    const isRag = ragToggle.checked;
    const isEnhanced = enhanceToggle && enhanceToggle.checked;
    if (isEnhanced) {
        modeBadge.textContent = 'RAG + Web Enhanced';
        modeBadge.className = 'badge bg-success';
    } else if (isRag) {
        modeBadge.textContent = 'RAG Mode: ON';
        modeBadge.className = 'badge bg-primary';
    } else {
        modeBadge.textContent = 'Direct LLM Mode';
        modeBadge.className = 'badge bg-secondary';
    }
}

// Initialize
function init() {
    // Temperature slider
    if (temperatureSlider) {
        temperatureSlider.addEventListener('input', () => {
            const val = parseFloat(temperatureSlider.value);
            if (temperatureValue) temperatureValue.textContent = val.toFixed(1);
        });
    }

    // RAG toggle
    ragToggle.addEventListener('change', () => updateModeBadge());
    if (enhanceToggle) {
        enhanceToggle.addEventListener('change', () => {
            // Enhanced only makes sense with RAG on
            if (enhanceToggle.checked && !ragToggle.checked) {
                ragToggle.checked = true;
            }
            updateModeBadge();
        });
    }

    // New chat buttons
    if (newChatBtn) newChatBtn.addEventListener('click', startNewChat);
    if (newChatHeaderBtn) newChatHeaderBtn.addEventListener('click', startNewChat);
    if (clearHistoryBtn) clearHistoryBtn.addEventListener('click', deleteAllConversations);

    // Copy chat
    if (copyChatBtn) copyChatBtn.addEventListener('click', copyChatToClipboard);

    // Rename confirm
    if (renameConfirmBtn) renameConfirmBtn.addEventListener('click', confirmRename);

    // Allow Enter in rename input
    if (renameInput) {
        renameInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') confirmRename();
        });
    }

    // Form submit
    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        await sendMessage();
    });

    // Load sidebar conversations and restore last session
    loadConversations();
    if (currentConversationId) {
        loadConversation(currentConversationId);
    }
}

// ============================================================================
// CONVERSATION SIDEBAR
// ============================================================================

async function loadConversations() {
    try {
        const response = await fetch('/api/conversations');
        if (!response.ok) return;
        const data = await response.json();
        conversations = data.conversations || [];
        renderConversationList();
    } catch (err) {
        console.error('Failed to load conversations:', err);
    }
}

function renderConversationList() {
    if (!conversationsList) return;

    conversationsList.innerHTML = '';

    if (conversations.length === 0) {
        const placeholder = document.createElement('div');
        placeholder.className = 'text-center text-muted py-4 small';
        placeholder.id = 'conversations-placeholder';
        placeholder.innerHTML = 'No conversations yet.<br>Start chatting!';
        conversationsList.appendChild(placeholder);
        return;
    }

    conversations.forEach(conv => {
        const isActive = conv.id === currentConversationId;
        const title = conv.title || 'Untitled';

        // --- outer item div ---
        const item = document.createElement('div');
        item.className = 'conversation-item d-flex align-items-center px-2 py-2 border-bottom'
            + (isActive ? ' bg-primary bg-opacity-10 fw-semibold' : '');
        item.style.cursor = 'pointer';
        item.addEventListener('click', () => loadConversation(conv.id));

        // --- title span (user content via textContent — never innerHTML) ---
        const titleSpan = document.createElement('span');
        titleSpan.className = 'flex-grow-1 text-truncate small';
        titleSpan.title = title;
        titleSpan.textContent = title;

        // --- action buttons ---
        const actionsSpan = document.createElement('span');
        actionsSpan.className = 'ms-1 d-flex gap-1 flex-shrink-0';

        const renameBtn = document.createElement('button');
        renameBtn.className = 'btn btn-link btn-sm p-0 text-secondary';
        renameBtn.title = 'Rename';
        renameBtn.innerHTML = '<i class="bi bi-pencil" style="font-size:0.75rem;"></i>';
        renameBtn.addEventListener('click', e => {
            e.stopPropagation();
            openRenameModal(conv.id, title);
        });

        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'btn btn-link btn-sm p-0 text-danger';
        deleteBtn.title = 'Delete';
        deleteBtn.innerHTML = '<i class="bi bi-trash" style="font-size:0.75rem;"></i>';
        deleteBtn.addEventListener('click', e => {
            e.stopPropagation();
            deleteConversation(conv.id);
        });

        actionsSpan.append(renameBtn, deleteBtn);
        item.append(titleSpan, actionsSpan);
        conversationsList.appendChild(item);
    });
}

function startNewChat() {
    currentConversationId = null;
    localStorage.removeItem('currentConversationId');
    chatHistory = [];
    renderChatHistory();
    renderConversationList();
    chatInput.focus();
}

async function loadConversation(id) {
    try {
        const response = await fetch(`/api/conversations/${id}`);
        if (!response.ok) {
            if (response.status === 404) {
                conversations = conversations.filter(c => c.id !== id);
                if (currentConversationId === id) startNewChat();
                renderConversationList();
            }
            return;
        }
        const data = await response.json();
        currentConversationId = id;
        localStorage.setItem('currentConversationId', id);

        chatHistory = (data.messages || []).map(m => ({
            role: m.role,
            content: m.content,
            timestamp: m.created_at
        }));

        renderChatHistory();
        renderConversationList();
    } catch (err) {
        console.error('Failed to load conversation:', err);
    }
}

async function deleteConversation(id) {
    if (!confirm('Delete this conversation and all its messages?')) return;
    try {
        const response = await fetch(`/api/conversations/${id}`, { method: 'DELETE' });
        if (response.ok) {
            conversations = conversations.filter(c => c.id !== id);
            if (currentConversationId === id) startNewChat();
            renderConversationList();
        }
    } catch (err) {
        console.error('Failed to delete conversation:', err);
    }
}

async function deleteAllConversations() {
    if (!confirm('Delete all conversations and chat history? This cannot be undone.')) return;
    try {
        const response = await fetch('/api/conversations', { method: 'DELETE' });
        if (response.ok) {
            conversations = [];
            startNewChat();
        }
    } catch (err) {
        console.error('Failed to delete all conversations:', err);
    }
}

function openRenameModal(id, currentTitle) {
    renameTargetId = id;
    if (renameInput) renameInput.value = currentTitle;
    const modal = new bootstrap.Modal(document.getElementById('renameModal'));
    modal.show();
    setTimeout(() => renameInput && renameInput.select(), 300);
}

async function confirmRename() {
    const title = renameInput ? renameInput.value.trim() : '';
    if (!title || !renameTargetId) return;

    try {
        const response = await fetch(`/api/conversations/${renameTargetId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title })
        });
        if (response.ok) {
            const conv = conversations.find(c => c.id === renameTargetId);
            if (conv) conv.title = title;
            renderConversationList();
        }
    } catch (err) {
        console.error('Failed to rename conversation:', err);
    } finally {
        bootstrap.Modal.getInstance(document.getElementById('renameModal'))?.hide();
        renameTargetId = null;
    }
}

// ============================================================================
// CHAT HISTORY RENDERING
// ============================================================================

function renderChatHistory() {
    chatMessages.innerHTML = '';

    if (chatHistory.length === 0) {
        chatMessages.innerHTML = `
            <div class="text-center text-muted" id="chat-empty-state">
                <i class="bi bi-chat-dots fs-1"></i>
                <p class="mt-2">Start a conversation...</p>
                <p class="small">
                    <span class="badge bg-primary" id="mode-badge">RAG Mode: ON</span>
                </p>
            </div>`;
        return;
    }

    chatHistory.forEach(msg => {
        if (msg.role === 'user') {
            addUserMessage(msg.content, msg.timestamp, false);
        } else if (msg.role === 'assistant') {
            addAssistantMessage(msg.content, msg.timestamp, false);
        }
    });

    scrollToBottom();
}

// ============================================================================
// MESSAGE HELPERS
// ============================================================================

function addUserMessage(text, timestamp = null, save = true) {
    const template = userMessageTemplate.content.cloneNode(true);
    const messageText = template.querySelector('.message-text');
    const messageTime = template.querySelector('.message-time');

    messageText.textContent = text;
    messageTime.textContent = formatTime(timestamp || new Date());

    chatMessages.appendChild(template);

    if (save) {
        chatHistory.push({ role: 'user', content: text, timestamp: (timestamp || new Date()).toISOString() });
    }

    scrollToBottom();
}

function addAssistantMessage(text, timestamp = null, save = true) {
    const template = assistantMessageTemplate.content.cloneNode(true);
    const messageText = template.querySelector('.message-text');
    const messageTime = template.querySelector('.message-time');

    messageText.innerHTML = formatMessageText(text);
    messageTime.textContent = formatTime(timestamp || new Date());

    chatMessages.appendChild(template);

    if (save) {
        chatHistory.push({ role: 'assistant', content: text, timestamp: (timestamp || new Date()).toISOString() });
    }

    scrollToBottom();
}

function addLoadingIndicator() {
    const template = loadingTemplate.content.cloneNode(true);
    chatMessages.appendChild(template);
    scrollToBottom();
    return chatMessages.querySelector('.loading-message');
}

function removeLoadingIndicator() {
    const loader = chatMessages.querySelector('.loading-message');
    if (loader) loader.remove();
}

// ============================================================================
// SEND MESSAGE
// ============================================================================

async function sendMessage() {
    const message = chatInput.value.trim();
    if (!message || isStreaming) return;

    const historySnapshot = chatHistory.slice(-10).filter(m => m.role !== 'system');

    chatInput.value = '';
    addUserMessage(message);

    const loader = addLoadingIndicator();
    isStreaming = true;
    sendBtn.disabled = true;

    try {
        const useRag = ragToggle.checked;
        const useEnhance = enhanceToggle ? enhanceToggle.checked : false;
        const temperature = temperatureSlider ? parseFloat(temperatureSlider.value) : 0.7;
        const body = {
            message,
            use_rag: useRag,
            enhance: useEnhance,
            history: historySnapshot,
            temperature,
        };
        if (currentConversationId) body.conversation_id = currentConversationId;

        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });

        if (!response.ok) {
            removeLoadingIndicator();
            try {
                const errorData = await response.json();
                let errorMessage = errorData.message || 'An error occurred';
                if (errorData.details && errorData.details.help) {
                    errorMessage += '\n\n\u{1F4A1} ' + errorData.details.help;
                }
                addAssistantMessage('\u274C Error: ' + errorMessage, new Date(), false);
            } catch (_) {
                throw new Error(`Server error: ${response.status} ${response.statusText}`);
            }
            return;
        }

        removeLoadingIndicator();

        const template = assistantMessageTemplate.content.cloneNode(true);
        chatMessages.appendChild(template);

        const messageTextElement = chatMessages.querySelector('.assistant-message:last-child .message-text');
        const messageTimeElement = chatMessages.querySelector('.assistant-message:last-child .message-time');

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let assistantResponse = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const text = decoder.decode(value);
            const lines = text.split('\n').filter(line => line.startsWith('data: '));

            for (const line of lines) {
                const data = JSON.parse(line.substring(6));

                if (data.error) {
                    if (messageTextElement) {
                        messageTextElement.innerHTML = formatMessageText('❌ ' + (data.message || 'An error occurred'));
                        messageTextElement.classList.add('error-message');
                    }
                    if (messageTimeElement) messageTimeElement.textContent = formatTime(new Date());
                    scrollToBottom();
                    break;
                }

                if (data.plan) {
                    const messageContent = chatMessages.querySelector('.assistant-message:last-child .message-content');
                    if (messageContent) {
                        const planPanel = buildPlanTrace(data.plan);
                        const msgText = messageContent.querySelector('.message-text');
                        messageContent.insertBefore(planPanel, msgText);
                        scrollToBottom();
                    }
                }

                if (data.content) {
                    assistantResponse += data.content;
                    if (messageTextElement) {
                        messageTextElement.innerHTML = formatMessageText(assistantResponse);
                    }
                    scrollToBottom();
                }

                if (data.done) {
                    if (messageTimeElement) messageTimeElement.textContent = formatTime(new Date());

                    if (data.conversation_id) {
                        const isNew = !currentConversationId;
                        currentConversationId = data.conversation_id;
                        localStorage.setItem('currentConversationId', currentConversationId);
                        if (isNew) {
                            await loadConversations();
                        }
                    }

                    if (data.sources && data.sources.length > 0) {
                        const messageContent = chatMessages.querySelector('.assistant-message:last-child .message-content');
                        if (messageContent) {
                            messageContent.appendChild(buildSourcesPanel(data.sources));
                        }
                    }

                    if (data.model_used === 'cloud') {
                        const msgText = chatMessages.querySelector('.assistant-message:last-child .message-text');
                        if (msgText) {
                            const badge = document.createElement('span');
                            badge.className = 'badge bg-warning text-dark me-1 align-middle';
                            badge.style.fontSize = '0.7rem';
                            badge.textContent = '⚡ cloud';
                            msgText.insertBefore(badge, msgText.firstChild);
                        }
                    }

                    chatHistory.push({
                        role: 'assistant',
                        content: assistantResponse,
                        timestamp: new Date().toISOString()
                    });
                }
            }
        }

    } catch (error) {
        removeLoadingIndicator();
        addAssistantMessage('\u274C Unexpected error: ' + error.message, new Date(), false);
    } finally {
        isStreaming = false;
        sendBtn.disabled = false;
        chatInput.focus();
    }
}

// ============================================================================
// UTILITIES
// ============================================================================

function formatMessageText(text) {
    text = text.replace(/[<>&]/g, (char) => {
        switch (char) {
            case '<': return '&lt;';
            case '>': return '&gt;';
            case '&': return '&amp;';
            default: return char;
        }
    });
    text = text.replace(/\n/g, '<br>');
    text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/\*(.+?)\*/g, '<em>$1</em>');
    text = text.replace(/`(.+?)`/g, '<code>$1</code>');
    return text;
}

function escapeHtml(str) {
    return String(str).replace(/[<>&"']/g, (char) => {
        switch (char) {
            case '<': return '&lt;';
            case '>': return '&gt;';
            case '&': return '&amp;';
            case '"': return '&quot;';
            case "'": return '&#39;';
            default: return char;
        }
    });
}

function formatTime(timestamp) {
    const date = timestamp instanceof Date ? timestamp : new Date(timestamp);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function buildSourcesPanel(sources) {
    const details = document.createElement('details');
    details.className = 'sources-panel mt-2';

    const summary = document.createElement('summary');
    summary.className = 'text-muted small';
    summary.textContent = `${sources.length} source${sources.length !== 1 ? 's' : ''}`;
    details.appendChild(summary);

    const list = document.createElement('ul');
    list.className = 'list-unstyled mb-0 mt-1';

    sources.forEach((src, i) => {
        const li = document.createElement('li');
        li.className = 'small text-muted mb-1';

        const parts = [escapeHtml(src.filename)];
        if (src.page_number) parts.push(`p.${src.page_number}`);
        if (src.section_title) parts.push(escapeHtml(src.section_title));

        li.innerHTML = `<span class="me-1">📄</span>${parts.join(' · ')}`;

        if (src.chunk_id) {
            const link = document.createElement('a');
            link.href = '#';
            link.className = 'ms-2 text-decoration-none';
            link.textContent = 'View context';
            link.dataset.chunkId = src.chunk_id;

            const contextDiv = document.createElement('div');
            contextDiv.className = 'chunk-context mt-1 d-none';

            link.addEventListener('click', async (e) => {
                e.preventDefault();
                if (!contextDiv.classList.contains('d-none')) {
                    contextDiv.classList.add('d-none');
                    link.textContent = 'View context';
                    return;
                }
                link.textContent = 'Loading…';
                try {
                    const resp = await fetch(`/api/documents/chunks/${src.chunk_id}/context?window=1`);
                    const data = await resp.json();
                    if (data.success && data.chunks.length > 0) {
                        const pre = document.createElement('pre');
                        pre.className = 'chunk-context-text p-2 rounded';
                        pre.textContent = data.chunks.map(c => c.chunk_text).join('\n\n---\n\n');
                        contextDiv.innerHTML = '';
                        contextDiv.appendChild(pre);
                        contextDiv.classList.remove('d-none');
                        link.textContent = 'Hide context';
                    } else {
                        link.textContent = 'View context';
                    }
                } catch (_) {
                    link.textContent = 'View context';
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

function buildPlanTrace(plan) {
    const INTENT_COLORS = {
        factual_lookup: 'bg-primary',
        comparison:     'bg-info text-dark',
        synthesis:      'bg-warning text-dark',
        general:        'bg-secondary',
    };
    const intentColor = INTENT_COLORS[plan.intent] || 'bg-secondary';

    const details = document.createElement('details');
    details.className = 'plan-trace mb-2';

    const summary = document.createElement('summary');
    summary.className = 'text-muted small d-flex align-items-center gap-2';
    summary.innerHTML =
        `<span class="badge ${intentColor}" style="font-size:0.65rem">${escapeHtml(plan.intent)}</span>` +
        `<span>Reasoning trace</span>` +
        (plan.estimated_hops > 1 ? `<span class="badge bg-light text-dark border" style="font-size:0.65rem">${plan.estimated_hops}-hop</span>` : '');
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

function copyChatToClipboard() {
    if (chatHistory.length === 0) {
        alert('No chat history to copy');
        return;
    }

    let chatText = 'LocalChat Conversation\n';
    chatText += '='.repeat(50) + '\n\n';

    chatHistory.forEach((msg) => {
        const timestamp = new Date(msg.timestamp).toLocaleString();
        const role = msg.role === 'user' ? 'You' : 'Assistant';
        chatText += `[${timestamp}] ${role}:\n`;
        chatText += msg.content + '\n\n';
    });

    chatText += '='.repeat(50) + '\n';
    chatText += `Total messages: ${chatHistory.length}\n`;
    chatText += `Exported: ${new Date().toLocaleString()}`;

    navigator.clipboard.writeText(chatText).then(() => {
        const originalText = copyChatBtn.innerHTML;
        copyChatBtn.innerHTML = '<i class="bi bi-check me-1"></i>Copied!';
        copyChatBtn.classList.remove('btn-outline-primary');
        copyChatBtn.classList.add('btn-success');
        setTimeout(() => {
            copyChatBtn.innerHTML = originalText;
            copyChatBtn.classList.remove('btn-success');
            copyChatBtn.classList.add('btn-outline-primary');
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy:', err);
        alert('Failed to copy to clipboard. Please try again.');
    });
}

// Initialize on page load
init();

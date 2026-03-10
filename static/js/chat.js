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

    if (conversations.length === 0) {
        conversationsList.innerHTML = `
            <div class="text-center text-muted py-4 small" id="conversations-placeholder">
                No conversations yet.<br>Start chatting!
            </div>`;
        return;
    }

    conversationsList.innerHTML = conversations.map(conv => {
        const isActive = conv.id === currentConversationId;
        const title = escapeHtml(conv.title || 'Untitled');
        return `
            <div class="conversation-item d-flex align-items-center px-2 py-2 border-bottom ${isActive ? 'bg-primary bg-opacity-10 fw-semibold' : ''}"
                 style="cursor:pointer;" onclick="loadConversation('${conv.id}')">
                <span class="flex-grow-1 text-truncate small" title="${title}">${title}</span>
                <span class="ms-1 d-flex gap-1 flex-shrink-0">
                    <button class="btn btn-link btn-sm p-0 text-secondary" title="Rename"
                            onclick="event.stopPropagation(); openRenameModal('${conv.id}', '${title}')">
                        <i class="bi bi-pencil" style="font-size:0.75rem;"></i>
                    </button>
                    <button class="btn btn-link btn-sm p-0 text-danger" title="Delete"
                            onclick="event.stopPropagation(); deleteConversation('${conv.id}')">
                        <i class="bi bi-trash" style="font-size:0.75rem;"></i>
                    </button>
                </span>
            </div>`;
    }).join('');
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
        const body = {
            message,
            use_rag: useRag,
            enhance: useEnhance,
            history: historySnapshot
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

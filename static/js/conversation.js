/**
 * conversation.js — Conversation state and all chat-history DOM mutations.
 * Owns: chatHistory, currentConversationId, conversations, renameTargetId.
 */

import {
    formatTime, formatMessageText, scrollToBottom,
} from './ui.js';

let chatHistory = [];
let currentConversationId = localStorage.getItem('currentConversationId') || null;
let conversations = [];
let renameTargetId = null;

// ---- state accessors -------------------------------------------------------

export function getChatHistory() { return chatHistory; }
export function getCurrentConversationId() { return currentConversationId; }

export function setCurrentConversationId(id) {
    currentConversationId = id;
    if (id) {
        localStorage.setItem('currentConversationId', id);
    } else {
        localStorage.removeItem('currentConversationId');
    }
}

// ---- workspace header helper -----------------------------------------------

export function _wsHeaders(extra) {
    const id = localStorage.getItem('localchat_active_workspace_id');
    const base = id ? { 'X-Workspace-ID': id } : {};
    return Object.assign(base, extra || {});
}

// ---- conversation sidebar --------------------------------------------------

export async function loadConversations() {
    try {
        const response = await fetch('/api/conversations', { headers: _wsHeaders() });
        if (!response.ok) return;
        const data = await response.json();
        conversations = data.conversations || [];
        renderConversationList();
    } catch (err) {
        console.error('Failed to load conversations:', err);
    }
}

export function renderConversationList() {
    const conversationsList = document.getElementById('conversations-list');
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

        const item = document.createElement('div');
        item.className = 'conversation-item d-flex align-items-center px-2 py-2 border-bottom'
            + (isActive ? ' bg-primary bg-opacity-10 fw-semibold' : '');
        item.style.cursor = 'pointer';
        item.addEventListener('click', () => loadConversation(conv.id));

        const titleSpan = document.createElement('span');
        titleSpan.className = 'flex-grow-1 text-truncate small';
        titleSpan.title = title;
        titleSpan.textContent = title;

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

export function startNewChat() {
    setCurrentConversationId(null);
    chatHistory = [];
    renderChatHistory();
    renderConversationList();
    const chatInput = document.getElementById('chat-input');
    if (chatInput) chatInput.focus();
}

export async function loadConversation(id) {
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
        setCurrentConversationId(id);
        chatHistory = (data.messages || []).map(m => ({
            role: m.role,
            content: m.content,
            timestamp: m.created_at,
        }));
        renderChatHistory();
        renderConversationList();
    } catch (err) {
        console.error('Failed to load conversation:', err);
    }
}

export async function deleteConversation(id) {
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

export async function deleteAllConversations() {
    if (!confirm('Delete all conversations and chat history? This cannot be undone.')) return;
    try {
        const response = await fetch('/api/conversations', { method: 'DELETE', headers: _wsHeaders() });
        if (response.ok) {
            conversations = [];
            startNewChat();
        }
    } catch (err) {
        console.error('Failed to delete all conversations:', err);
    }
}

export function openRenameModal(id, currentTitle) {
    renameTargetId = id;
    const renameInput = document.getElementById('rename-input');
    if (renameInput) renameInput.value = currentTitle;
    const modal = new bootstrap.Modal(document.getElementById('renameModal'));
    modal.show();
    setTimeout(() => {
        const inp = document.getElementById('rename-input');
        if (inp) inp.select();
    }, 300);
}

export async function confirmRename() {
    const renameInput = document.getElementById('rename-input');
    const title = renameInput ? renameInput.value.trim() : '';
    if (!title || !renameTargetId) return;
    try {
        const response = await fetch(`/api/conversations/${renameTargetId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title }),
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

// ---- chat history rendering ------------------------------------------------

export function renderChatHistory() {
    const chatMessages = document.getElementById('chat-messages');
    if (!chatMessages) return;
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

// ---- message helpers -------------------------------------------------------

export function addUserMessage(text, timestamp = null, save = true) {
    const chatMessages = document.getElementById('chat-messages');
    const template = document.getElementById('user-message-template');
    if (!chatMessages || !template) return;
    const node = template.content.cloneNode(true);
    node.querySelector('.message-text').textContent = text;
    node.querySelector('.message-time').textContent = formatTime(timestamp || new Date());
    chatMessages.appendChild(node);
    if (save) {
        chatHistory.push({ role: 'user', content: text, timestamp: (timestamp || new Date()).toISOString() });
    }
    scrollToBottom();
}

export function addAssistantMessage(text, timestamp = null, save = true) {
    const chatMessages = document.getElementById('chat-messages');
    const template = document.getElementById('assistant-message-template');
    if (!chatMessages || !template) return;
    const node = template.content.cloneNode(true);
    node.querySelector('.message-text').innerHTML = formatMessageText(text);
    node.querySelector('.message-time').textContent = formatTime(timestamp || new Date());
    chatMessages.appendChild(node);
    if (save) {
        chatHistory.push({ role: 'assistant', content: text, timestamp: (timestamp || new Date()).toISOString() });
    }
    scrollToBottom();
}

export function addLoadingIndicator() {
    const chatMessages = document.getElementById('chat-messages');
    const template = document.getElementById('loading-template');
    if (!chatMessages || !template) return null;
    chatMessages.appendChild(template.content.cloneNode(true));
    scrollToBottom();
    return chatMessages.querySelector('.loading-message');
}

export function removeLoadingIndicator() {
    const loader = document.querySelector('#chat-messages .loading-message');
    if (loader) loader.remove();
}

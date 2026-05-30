/**
 * chat.js — Orchestrator (~90 lines). Wires UI events to modules.
 * Business logic lives in conversation.js, streaming.js, and ui.js.
 */

import { updateModeBadge, copyChatToClipboard } from './ui.js';
import {
    getChatHistory, getCurrentConversationId, setCurrentConversationId,
    loadConversations, startNewChat, loadConversation,
    deleteAllConversations, confirmRename,
} from './conversation.js';
import { sendMessage } from './streaming.js';

function init() {
    const ragToggle        = document.getElementById('rag-toggle');
    const enhanceToggle    = document.getElementById('enhance-toggle');
    const temperatureSlider = document.getElementById('temperature-slider');
    const temperatureValue  = document.getElementById('temperature-value');
    const modelOverrideInput = document.getElementById('model-override-input');
    const chatForm         = document.getElementById('chat-form');
    const newChatBtn       = document.getElementById('new-chat-btn');
    const newChatHeaderBtn = document.getElementById('new-chat-header-btn');
    const clearHistoryBtn  = document.getElementById('clear-history-btn');
    const copyChatBtn      = document.getElementById('copy-chat-btn');
    const renameConfirmBtn = document.getElementById('rename-confirm-btn');
    const renameInput      = document.getElementById('rename-input');

    if (temperatureSlider) {
        temperatureSlider.addEventListener('input', () => {
            const val = parseFloat(temperatureSlider.value);
            if (temperatureValue) temperatureValue.textContent = val.toFixed(1);
        });
    }

    if (modelOverrideInput) {
        const saved = localStorage.getItem('lc-model-override');
        if (saved) modelOverrideInput.value = saved;
        modelOverrideInput.addEventListener('input', () => {
            const val = modelOverrideInput.value.trim();
            if (val) localStorage.setItem('lc-model-override', val);
            else     localStorage.removeItem('lc-model-override');
        });
    }

    if (ragToggle) ragToggle.addEventListener('change', () => updateModeBadge());
    if (enhanceToggle) {
        enhanceToggle.addEventListener('change', () => {
            if (enhanceToggle.checked && ragToggle && !ragToggle.checked) {
                ragToggle.checked = true;
            }
            updateModeBadge();
        });
    }

    if (newChatBtn)       newChatBtn.addEventListener('click', startNewChat);
    if (newChatHeaderBtn) newChatHeaderBtn.addEventListener('click', startNewChat);
    if (clearHistoryBtn)  clearHistoryBtn.addEventListener('click', deleteAllConversations);

    if (copyChatBtn) {
        copyChatBtn.addEventListener('click', () => copyChatToClipboard(getChatHistory()));
    }

    if (renameConfirmBtn) renameConfirmBtn.addEventListener('click', confirmRename);
    if (renameInput) {
        renameInput.addEventListener('keydown', e => { if (e.key === 'Enter') confirmRename(); });
    }

    if (chatForm) {
        chatForm.addEventListener('submit', async e => {
            e.preventDefault();
            await sendMessage();
        });
    }

    loadConversations();
    const convId = getCurrentConversationId();
    if (convId) loadConversation(convId);

    document.addEventListener('workspace-switched', () => {
        setCurrentConversationId(null);
        const el = document.getElementById('chat-messages');
        if (el) el.innerHTML = '';
        loadConversations();
    });
}

init();

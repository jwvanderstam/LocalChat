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

    // Both toggles survive navigation, like the model override above. They were the
    // only chat settings that did not: switching to Documents and back silently
    // dropped web-enhanced mode and turned RAG back on, so the next answer came from
    // a different configuration than the one on screen a moment earlier.
    //
    // Restored before the listeners are attached, so restoring does not fire the
    // change handler and write back what it just read.
    function restoreToggle(el, key, fallback) {
        if (!el) return;
        const saved = localStorage.getItem(key);
        el.checked = saved === null ? fallback : saved === 'true';
    }
    restoreToggle(ragToggle, 'lc-rag-enabled', true);
    restoreToggle(enhanceToggle, 'lc-enhance-enabled', false);
    // Enhanced implies RAG (see the handler below); a stored pair that disagrees --
    // from an older build, or hand-edited storage -- is reconciled the same way
    // rather than left to produce a mode the badge cannot describe.
    if (enhanceToggle && enhanceToggle.checked && ragToggle) ragToggle.checked = true;
    updateModeBadge();

    if (ragToggle) {
        ragToggle.addEventListener('change', () => {
            localStorage.setItem('lc-rag-enabled', String(ragToggle.checked));
            // Turning RAG off cannot leave web-enhanced on: enhanced is RAG plus the
            // web, so the stored pair would describe a mode that does not exist.
            if (!ragToggle.checked && enhanceToggle && enhanceToggle.checked) {
                enhanceToggle.checked = false;
                localStorage.setItem('lc-enhance-enabled', 'false');
            }
            updateModeBadge();
        });
    }
    if (enhanceToggle) {
        enhanceToggle.addEventListener('change', () => {
            if (enhanceToggle.checked && ragToggle && !ragToggle.checked) {
                ragToggle.checked = true;
                localStorage.setItem('lc-rag-enabled', 'true');
            }
            localStorage.setItem('lc-enhance-enabled', String(enhanceToggle.checked));
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

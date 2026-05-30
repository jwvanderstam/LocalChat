/**
 * streaming.js — SSE event loop and sendMessage(). Owns the isStreaming flag.
 */

import {
    formatMessageText, scrollToBottom,
    buildSourcesPanel, buildFeedbackBar, buildPlanTrace, formatTime,
} from './ui.js';
import {
    getChatHistory, getCurrentConversationId, setCurrentConversationId,
    addUserMessage, addAssistantMessage, addLoadingIndicator, removeLoadingIndicator,
    loadConversations, _wsHeaders,
} from './conversation.js';

let isStreaming = false;

export function getIsStreaming() { return isStreaming; }

export async function sendMessage() {
    const chatInput       = document.getElementById('chat-input');
    const sendBtn         = document.getElementById('send-btn');
    const ragToggle       = document.getElementById('rag-toggle');
    const enhanceToggle   = document.getElementById('enhance-toggle');
    const tempSlider      = document.getElementById('temperature-slider');
    const modelOverride   = document.getElementById('model-override-input');

    const message = chatInput ? chatInput.value.trim() : '';
    if (!message || isStreaming) return;

    const historySnapshot = getChatHistory().slice(-10).filter(m => m.role !== 'system');

    if (chatInput) chatInput.value = '';
    addUserMessage(message);
    addLoadingIndicator();

    isStreaming = true;
    if (sendBtn) sendBtn.disabled = true;

    try {
        const body = {
            message,
            use_rag:     ragToggle     ? ragToggle.checked              : false,
            enhance:     enhanceToggle ? enhanceToggle.checked          : false,
            temperature: tempSlider    ? parseFloat(tempSlider.value)   : 0.7,
            history:     historySnapshot,
        };
        const overrideVal = modelOverride ? modelOverride.value.trim() : '';
        if (overrideVal)                body.model_override    = overrideVal;
        const convId = getCurrentConversationId();
        if (convId)                     body.conversation_id   = convId;

        const response = await fetch('/api/chat', {
            method:  'POST',
            headers: _wsHeaders({ 'Content-Type': 'application/json' }),
            body:    JSON.stringify(body),
        });

        if (!response.ok) {
            removeLoadingIndicator();
            try {
                const err = await response.json();
                let msg = err.message || 'An error occurred';
                if (err.details && err.details.help) msg += '\n\n\u{1F4A1} ' + err.details.help;
                addAssistantMessage('❌ Error: ' + msg, new Date(), false);
            } catch (_) {
                throw new Error(`Server error: ${response.status} ${response.statusText}`);
            }
            return;
        }

        removeLoadingIndicator();

        const tpl         = document.getElementById('assistant-message-template');
        const chatMessages = document.getElementById('chat-messages');
        if (!tpl || !chatMessages) return;

        chatMessages.appendChild(tpl.content.cloneNode(true));

        const msgText = chatMessages.querySelector('.assistant-message:last-child .message-text');
        const msgTime = chatMessages.querySelector('.assistant-message:last-child .message-time');

        const reader  = response.body.getReader();
        const decoder = new TextDecoder();
        let assistantResponse = '';

        // eslint-disable-next-line no-constant-condition
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value);
            const lines = chunk.split('\n').filter(l => l.startsWith('data: '));

            for (const line of lines) {
                const data = JSON.parse(line.substring(6));

                if (data.error) {
                    if (msgText) {
                        msgText.innerHTML = formatMessageText('❌ ' + (data.message || 'An error occurred'));
                        msgText.classList.add('error-message');
                    }
                    if (msgTime) msgTime.textContent = formatTime(new Date());
                    scrollToBottom();
                    break;
                }

                if (data.plan) {
                    const mc = chatMessages.querySelector('.assistant-message:last-child .message-content');
                    if (mc) {
                        mc.insertBefore(buildPlanTrace(data.plan), mc.querySelector('.message-text'));
                        scrollToBottom();
                    }
                }

                if (data.content) {
                    assistantResponse += data.content;
                    if (msgText) msgText.innerHTML = formatMessageText(assistantResponse);
                    scrollToBottom();
                }

                if (data.done) {
                    if (msgTime) msgTime.textContent = formatTime(new Date());

                    if (data.conversation_id) {
                        const isNew = !getCurrentConversationId();
                        setCurrentConversationId(data.conversation_id);
                        if (isNew) await loadConversations();
                    }

                    const mc = chatMessages.querySelector('.assistant-message:last-child .message-content');

                    if (data.sources && data.sources.length > 0 && mc) {
                        mc.appendChild(buildSourcesPanel(data.sources));
                    }

                    if (data.model_used === 'cloud' && msgText) {
                        const badge = document.createElement('span');
                        badge.className   = 'badge bg-warning text-dark me-1 align-middle';
                        badge.style.fontSize = '0.7rem';
                        badge.textContent = '⚡ cloud';
                        msgText.insertBefore(badge, msgText.firstChild);
                    }

                    if (data.routed_model && msgText) {
                        const badge = document.createElement('span');
                        badge.className      = 'badge model-routed-badge me-1 align-middle';
                        badge.style.fontSize = '0.65rem';
                        badge.title          = data.routed_rationale || '';
                        badge.textContent    = data.routed_model;
                        msgText.insertBefore(badge, msgText.firstChild);
                    }

                    if (data.message_id && data.sources && data.sources.length > 0 && mc) {
                        mc.appendChild(buildFeedbackBar(
                            data.message_id,
                            data.conversation_id || null,
                            data.source_chunk_ids || [],
                        ));
                    }

                    getChatHistory().push({
                        role:      'assistant',
                        content:   assistantResponse,
                        timestamp: new Date().toISOString(),
                    });
                }
            }
        }

    } catch (error) {
        removeLoadingIndicator();
        addAssistantMessage('❌ Unexpected error: ' + error.message, new Date(), false);
    } finally {
        isStreaming = false;
        if (sendBtn) sendBtn.disabled = false;
        const inp = document.getElementById('chat-input');
        if (inp) inp.focus();
    }
}

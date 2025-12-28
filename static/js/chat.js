/**
 * Chat functionality with streaming support
 */

// Chat state
let chatHistory = [];
let isStreaming = false;

// DOM elements
const chatMessages = document.getElementById('chat-messages');
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');
const ragToggle = document.getElementById('rag-toggle');
const modeBadge = document.getElementById('mode-badge');
const clearChatBtn = document.getElementById('clear-chat-btn');
const copyChatBtn = document.getElementById('copy-chat-btn');

// Templates
const userMessageTemplate = document.getElementById('user-message-template');
const assistantMessageTemplate = document.getElementById('assistant-message-template');
const loadingTemplate = document.getElementById('loading-template');

// Initialize
function init() {
    // Load chat history from localStorage
    const savedHistory = localStorage.getItem('chatHistory');
    if (savedHistory) {
        chatHistory = JSON.parse(savedHistory);
        renderChatHistory();
    }
    
    // RAG toggle
    ragToggle.addEventListener('change', () => {
        const isRagMode = ragToggle.checked;
        modeBadge.textContent = isRagMode ? 'RAG Mode: ON' : 'Direct LLM Mode';
        modeBadge.className = isRagMode ? 'badge bg-primary' : 'badge bg-secondary';
    });
    
    // Clear chat
    clearChatBtn.addEventListener('click', () => {
        if (confirm('Are you sure you want to clear the chat history?')) {
            chatHistory = [];
            localStorage.removeItem('chatHistory');
            renderChatHistory();
        }
    });
    
    // Copy chat
    copyChatBtn.addEventListener('click', () => {
        copyChatToClipboard();
    });
    
    // Form submit
    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        await sendMessage();
    });
}

// Render chat history
function renderChatHistory() {
    // Clear existing messages
    chatMessages.innerHTML = '';
    
    if (chatHistory.length === 0) {
        chatMessages.innerHTML = `
            <div class="text-center text-muted">
                <i class="bi bi-chat-dots fs-1"></i>
                <p class="mt-2">Start a conversation...</p>
                <p class="small">
                    <span class="badge bg-primary" id="mode-badge">RAG Mode: ON</span>
                </p>
            </div>
        `;
        return;
    }
    
    // Render each message
    chatHistory.forEach(msg => {
        if (msg.role === 'user') {
            addUserMessage(msg.content, msg.timestamp, false);
        } else if (msg.role === 'assistant') {
            addAssistantMessage(msg.content, msg.timestamp, false);
        }
    });
    
    // Scroll to bottom
    scrollToBottom();
}

// Add user message
function addUserMessage(text, timestamp = null, save = true) {
    const template = userMessageTemplate.content.cloneNode(true);
    const messageText = template.querySelector('.message-text');
    const messageTime = template.querySelector('.message-time');
    
    messageText.textContent = text;
    messageTime.textContent = formatTime(timestamp || new Date());
    
    chatMessages.appendChild(template);
    
    if (save) {
        chatHistory.push({
            role: 'user',
            content: text,
            timestamp: timestamp || new Date().toISOString()
        });
        saveChatHistory();
    }
    
    scrollToBottom();
}

// Add assistant message
function addAssistantMessage(text, timestamp = null, save = true) {
    const template = assistantMessageTemplate.content.cloneNode(true);
    const messageText = template.querySelector('.message-text');
    const messageTime = template.querySelector('.message-time');
    
    // Support markdown-style formatting
    messageText.innerHTML = formatMessageText(text);
    messageTime.textContent = formatTime(timestamp || new Date());
    
    chatMessages.appendChild(template);
    
    if (save) {
        chatHistory.push({
            role: 'assistant',
            content: text,
            timestamp: timestamp || new Date().toISOString()
        });
        saveChatHistory();
    }
    
    scrollToBottom();
}

// Add loading indicator
function addLoadingIndicator() {
    const template = loadingTemplate.content.cloneNode(true);
    chatMessages.appendChild(template);
    scrollToBottom();
    return chatMessages.querySelector('.loading-message');
}

// Remove loading indicator
function removeLoadingIndicator() {
    const loader = chatMessages.querySelector('.loading-message');
    if (loader) {
        loader.remove();
    }
}

// Send message
async function sendMessage() {
    const message = chatInput.value.trim();
    if (!message || isStreaming) return;
    
    // Clear input
    chatInput.value = '';
    
    // Add user message
    addUserMessage(message);
    
    // Show loading
    const loader = addLoadingIndicator();
    isStreaming = true;
    sendBtn.disabled = true;
    
    try {
        // Prepare request
        const useRag = ragToggle.checked;
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                message: message,
                use_rag: useRag,
                history: chatHistory.slice(-10).filter(m => m.role !== 'system') // Last 10 messages
            })
        });
        
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        
        // Remove loading indicator
        removeLoadingIndicator();
        
        // Create assistant message container
        const template = assistantMessageTemplate.content.cloneNode(true);
        const messageElement = template.querySelector('.message');
        const messageText = template.querySelector('.message-text');
        const messageTime = template.querySelector('.message-time');
        
        chatMessages.appendChild(template);
        
        // Get references after appending
        const messageTextElement = chatMessages.querySelector('.assistant-message:last-child .message-text');
        const messageTimeElement = chatMessages.querySelector('.assistant-message:last-child .message-time');
        
        // Stream response
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let assistantResponse = '';
        
        while (true) {
            const {done, value} = await reader.read();
            if (done) break;
            
            const text = decoder.decode(value);
            const lines = text.split('\n').filter(line => line.startsWith('data: '));
            
            for (const line of lines) {
                const data = JSON.parse(line.substring(6));
                
                if (data.content) {
                    assistantResponse += data.content;
                    messageTextElement.innerHTML = formatMessageText(assistantResponse);
                    scrollToBottom();
                }
                
                if (data.done) {
                    messageTimeElement.textContent = formatTime(new Date());
                    
                    // Save to history
                    chatHistory.push({
                        role: 'assistant',
                        content: assistantResponse,
                        timestamp: new Date().toISOString()
                    });
                    saveChatHistory();
                }
            }
        }
        
    } catch (error) {
        removeLoadingIndicator();
        addAssistantMessage('Error: ' + error.message);
    } finally {
        isStreaming = false;
        sendBtn.disabled = false;
        chatInput.focus();
    }
}

// Format message text (simple markdown support)
function formatMessageText(text) {
    // Escape HTML
    text = text.replace(/[<>&]/g, (char) => {
        switch (char) {
            case '<': return '&lt;';
            case '>': return '&gt;';
            case '&': return '&amp;';
            default: return char;
        }
    });
    
    // Convert newlines to <br>
    text = text.replace(/\n/g, '<br>');
    
    // Bold **text**
    text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    
    // Italic *text*
    text = text.replace(/\*(.+?)\*/g, '<em>$1</em>');
    
    // Code `text`
    text = text.replace(/`(.+?)`/g, '<code>$1</code>');
    
    return text;
}

// Format timestamp
function formatTime(timestamp) {
    const date = timestamp instanceof Date ? timestamp : new Date(timestamp);
    return date.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
}

// Scroll to bottom
function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// Save chat history
function saveChatHistory() {
    localStorage.setItem('chatHistory', JSON.stringify(chatHistory));
}

// Copy chat to clipboard
function copyChatToClipboard() {
    if (chatHistory.length === 0) {
        alert('No chat history to copy');
        return;
    }
    
    // Format chat history as text
    let chatText = 'LocalChat Conversation\n';
    chatText += '='.repeat(50) + '\n\n';
    
    chatHistory.forEach((msg, index) => {
        const timestamp = new Date(msg.timestamp).toLocaleString();
        const role = msg.role === 'user' ? 'You' : 'Assistant';
        
        chatText += `[${timestamp}] ${role}:\n`;
        chatText += msg.content + '\n\n';
    });
    
    chatText += '='.repeat(50) + '\n';
    chatText += `Total messages: ${chatHistory.length}\n`;
    chatText += `Exported: ${new Date().toLocaleString()}`;
    
    // Copy to clipboard
    navigator.clipboard.writeText(chatText).then(() => {
        // Visual feedback
        const originalText = copyChatBtn.innerHTML;
        copyChatBtn.innerHTML = '<i class="bi bi-check me-1"></i>Copied!';
        copyChatBtn.classList.remove('btn-outline-primary');
        copyChatBtn.classList.add('btn-success');
        
        // Reset after 2 seconds
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

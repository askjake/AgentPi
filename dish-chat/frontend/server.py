#!/usr/bin/env python3
"""
frontend/server.py  —  DishChat Flask front-end server (port 3000)

Fixed:
  - All API calls now use the correct /rest/api/v1/ prefix
  - POST /rest/api/v1/chats          create conversation
  - GET  /rest/api/v1/chats          list conversations
  - DELETE /rest/api/v1/chats/{id}   delete conversation
  - GET  /rest/api/v1/chats/{id}     load conversation history
  - POST /rest/api/v1/chats/{id}/messages   send message (SSE stream)
  - Agent mode uses the same endpoint; agent_mode flag sent in message_config
Added:
  - Left sidebar: conversation list, "New chat" button, delete
  - Conversation switching / history loading
  - Streaming SSE response rendering
"""
from flask import Flask, render_template_string, request
from flask_cors import CORS
import os

app = Flask(__name__)
CORS(app)

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <title>DishChat</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            height: 100vh;
            display: flex;
            flex-direction: column;
            background: #0f0f1a;
            color: #e2e8f0;
        }

        /* ── TOP HEADER ── */
        .header {
            background: #16162a;
            border-bottom: 1px solid #2d2d44;
            padding: 12px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-shrink: 0;
            z-index: 10;
        }
        .header h1 { font-size: 18px; font-weight: 700; color: #e2e8f0; letter-spacing: -0.3px; }
        .header-right { display: flex; align-items: center; gap: 14px; }

        /* Mode toggle */
        .mode-toggle { display: flex; align-items: center; gap: 7px; background: #1e1e36; padding: 5px 11px; border-radius: 20px; border: 1px solid #2d2d44; cursor: default; }
        .mode-toggle label { font-size: 11px; color: #94a3b8; font-weight: 500; }
        .toggle-switch { position: relative; width: 42px; height: 22px; background: #334155; border-radius: 11px; cursor: pointer; transition: background 0.25s; flex-shrink: 0; }
        .toggle-switch.active { background: #22c55e; }
        .toggle-slider { position: absolute; top: 2px; left: 2px; width: 18px; height: 18px; background: #fff; border-radius: 50%; transition: transform 0.25s; box-shadow: 0 1px 4px rgba(0,0,0,.3); }
        .toggle-switch.active .toggle-slider { transform: translateX(20px); }
        .mode-badge { font-size: 11px; padding: 3px 9px; border-radius: 10px; font-weight: 600; }
        .mode-simple { background: #334155; color: #94a3b8; }
        .mode-agent  { background: #14532d; color: #86efac; }
        .online-badge { font-size: 11px; padding: 3px 9px; background: #14532d; color: #86efac; border-radius: 10px; font-weight: 600; }

        /* ── BODY ROW: sidebar + chat ── */
        .body-row { display: flex; flex: 1; overflow: hidden; }

        /* ── SIDEBAR ── */
        .sidebar {
            width: 260px;
            min-width: 220px;
            flex-shrink: 0;
            background: #12121f;
            border-right: 1px solid #2d2d44;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .sidebar-header { padding: 12px 10px 8px; flex-shrink: 0; }
        .new-chat-btn {
            width: 100%;
            padding: 9px 14px;
            background: #2563eb;
            color: #fff;
            border: none;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 7px;
            transition: background 0.15s;
        }
        .new-chat-btn:hover { background: #1d4ed8; }
        .new-chat-btn:disabled { background: #334155; cursor: not-allowed; }
        .convo-list { flex: 1; overflow-y: auto; padding: 4px 6px 12px; }
        .convo-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 9px;
            margin-bottom: 2px;
            border-radius: 7px;
            cursor: pointer;
            border: 1px solid transparent;
            transition: background 0.12s;
            gap: 6px;
        }
        .convo-item:hover { background: #1e1e36; }
        .convo-item.active { background: #1e2a4a; border-color: #3b4f7d; }
        .convo-title {
            flex: 1;
            font-size: 12.5px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            color: #cbd5e1;
        }
        .convo-item.active .convo-title { color: #e2e8f0; font-weight: 600; }
        .convo-date { font-size: 10.5px; color: #475569; margin-top: 1px; }
        .convo-del {
            background: transparent; border: none; cursor: pointer;
            color: #475569; font-size: 13px; padding: 1px 3px; border-radius: 4px;
            flex-shrink: 0; line-height: 1;
        }
        .convo-del:hover { color: #ef4444; }
        .sidebar-empty { color: #475569; font-size: 12px; text-align: center; padding: 24px 10px; }

        /* ── CHAT AREA ── */
        .chat-area {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            background: #0f0f1a;
        }
        .chat-title-bar {
            padding: 10px 20px;
            border-bottom: 1px solid #1e1e36;
            font-size: 13px;
            color: #64748b;
            flex-shrink: 0;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .messages-wrap {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 14px;
        }
        .message { display: flex; gap: 9px; animation: slideIn 0.25s ease-out; }
        @keyframes slideIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        .message.user { justify-content: flex-end; }
        .msg-bubble {
            max-width: 72%;
            padding: 11px 15px;
            border-radius: 12px;
            word-break: break-word;
            line-height: 1.55;
            font-size: 14px;
        }
        .message.user .msg-bubble { background: #2563eb; color: #fff; }
        .message.assistant .msg-bubble { background: #1a1a2e; color: #e2e8f0; border: 1px solid #2d2d44; }
        /* markdown inside assistant bubble */
        .message.assistant .msg-bubble h1,
        .message.assistant .msg-bubble h2,
        .message.assistant .msg-bubble h3 { margin: 14px 0 6px; color: #e2e8f0; font-weight: 600; }
        .message.assistant .msg-bubble p { margin: 6px 0; }
        .message.assistant .msg-bubble ul,
        .message.assistant .msg-bubble ol { margin: 6px 0; padding-left: 22px; }
        .message.assistant .msg-bubble li { margin: 3px 0; }
        .message.assistant .msg-bubble code { background: #0f172a; color: #7dd3fc; padding: 1px 5px; border-radius: 4px; font-size: 12.5px; font-family: monospace; }
        .message.assistant .msg-bubble pre { background: #0f172a; padding: 11px; border-radius: 7px; overflow-x: auto; margin: 7px 0; }
        .message.assistant .msg-bubble pre code { background: transparent; padding: 0; color: #7dd3fc; }
        .message.assistant .msg-bubble strong { font-weight: 600; color: #f1f5f9; }
        .message.assistant .msg-bubble a { color: #60a5fa; }
        .message.assistant .msg-bubble table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 13px; }
        .message.assistant .msg-bubble th,
        .message.assistant .msg-bubble td { border: 1px solid #2d2d44; padding: 6px 10px; }
        .message.assistant .msg-bubble th { background: #1e1e36; font-weight: 600; }
        .msg-avatar { width: 34px; height: 34px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 17px; flex-shrink: 0; align-self: flex-end; }
        .message.user .msg-avatar { background: #2563eb; }
        .message.assistant .msg-avatar { background: #1e1e36; }
        .thinking-indicator { display: inline-block; animation: pulse 1.4s infinite; }
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }

        /* Input bar */
        .input-bar {
            padding: 14px 18px;
            background: #12121f;
            border-top: 1px solid #2d2d44;
            display: flex;
            gap: 10px;
            flex-shrink: 0;
        }
        #msgInput {
            flex: 1;
            padding: 10px 14px;
            background: #1a1a2e;
            border: 1.5px solid #2d2d44;
            border-radius: 8px;
            font-size: 14px;
            color: #e2e8f0;
            outline: none;
            resize: none;
            min-height: 42px;
            max-height: 140px;
            line-height: 1.45;
        }
        #msgInput:focus { border-color: #3b82f6; }
        #msgInput::placeholder { color: #475569; }
        #sendBtn {
            padding: 10px 20px;
            background: #2563eb;
            color: #fff;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.15s;
            align-self: flex-end;
        }
        #sendBtn:hover { background: #1d4ed8; }
        #sendBtn:disabled { background: #334155; cursor: not-allowed; }
    </style>
</head>
<body>
    <!-- HEADER -->
    <div class="header">
        <h1>🤖 DishChat</h1>
        <div class="header-right">
            <div class="mode-toggle">
                <label>Simple</label>
                <div class="toggle-switch" id="modeToggle" onclick="toggleMode()">
                    <div class="toggle-slider"></div>
                </div>
                <label>Agent</label>
            </div>
            <span class="mode-badge mode-simple" id="modeBadge">SIMPLE MODE</span>
            <span class="online-badge">● Online</span>
        </div>
    </div>

    <!-- BODY -->
    <div class="body-row">
        <!-- SIDEBAR -->
        <aside class="sidebar">
            <div class="sidebar-header">
                <button class="new-chat-btn" id="newChatBtn" onclick="createNewChat()">
                    <span>＋</span> New chat
                </button>
            </div>
            <div class="convo-list" id="convoList">
                <div class="sidebar-empty">Loading conversations…</div>
            </div>
        </aside>

        <!-- CHAT -->
        <div class="chat-area">
            <div class="chat-title-bar" id="chatTitleBar">Select or start a conversation</div>
            <div class="messages-wrap" id="msgsWrap"></div>
            <div class="input-bar">
                <textarea id="msgInput" placeholder="Type a message…" rows="1"></textarea>
                <button id="sendBtn" onclick="sendMessage()">Send</button>
            </div>
        </div>
    </div>

<script>
// ── Config ────────────────────────────────────────────────────────────────────
const BACKEND = `http://${window.location.hostname}:8000`;
const API     = `${BACKEND}/rest/api/v1`;

// ── State ─────────────────────────────────────────────────────────────────────
let activeChatId  = null;
let agentMode     = false;
let isSending     = false;

// ── DOM refs ──────────────────────────────────────────────────────────────────
const msgsWrap    = document.getElementById('msgsWrap');
const msgInput    = document.getElementById('msgInput');
const sendBtn     = document.getElementById('sendBtn');
const convoList   = document.getElementById('convoList');
const chatTitleBar= document.getElementById('chatTitleBar');
const modeToggle  = document.getElementById('modeToggle');
const modeBadge   = document.getElementById('modeBadge');
const newChatBtn  = document.getElementById('newChatBtn');

// ── Mode toggle ───────────────────────────────────────────────────────────────
function toggleMode() {
    agentMode = !agentMode;
    if (agentMode) {
        modeToggle.classList.add('active');
        modeBadge.textContent = '🚀 AGENT MODE';
        modeBadge.className = 'mode-badge mode-agent';
        appendMsg('🚀 Switched to Agent Mode — I can now use tools!', 'assistant');
    } else {
        modeToggle.classList.remove('active');
        modeBadge.textContent = 'SIMPLE MODE';
        modeBadge.className = 'mode-badge mode-simple';
        appendMsg('📝 Switched to Simple Mode — Direct responses only', 'assistant');
    }
    localStorage.setItem('agentMode', agentMode);
}

// Restore saved mode
if (localStorage.getItem('agentMode') === 'true') {
    agentMode = true;
    modeToggle.classList.add('active');
    modeBadge.textContent = '🚀 AGENT MODE';
    modeBadge.className = 'mode-badge mode-agent';
}

// ── Conversation list ─────────────────────────────────────────────────────────
async function loadConversations() {
    try {
        const res  = await fetch(`${API}/chats`);
        if (!res.ok) throw new Error(res.status);
        const data = await res.json();
        const items = data.docs ?? data;
        renderConvoList(Array.isArray(items) ? items : []);
        return items;
    } catch (e) {
        convoList.innerHTML = '<div class="sidebar-empty">Could not load conversations</div>';
        return [];
    }
}

function renderConvoList(items) {
    if (!items.length) {
        convoList.innerHTML = '<div class="sidebar-empty">No conversations yet.<br>Click + New chat to start.</div>';
        return;
    }
    convoList.innerHTML = '';
    items.forEach(c => {
        const el = document.createElement('div');
        el.className = 'convo-item' + (c.chat_id === activeChatId ? ' active' : '');
        el.dataset.id = c.chat_id;
        const date = new Date(c.last_message_at || c.created_at);
        const fmt  = date.toLocaleDateString(undefined, { month:'short', day:'numeric' });
        el.innerHTML = `
            <div style="flex:1;min-width:0;">
                <div class="convo-title">${escHtml(c.title || 'New conversation')}</div>
                <div class="convo-date">${fmt}</div>
            </div>
            <button class="convo-del" title="Delete" onclick="deleteChat(event,'${c.chat_id}')">🗑</button>
        `;
        el.addEventListener('click', () => loadChat(c.chat_id, c.title));
        convoList.appendChild(el);
    });
}

// ── Create / load / delete chat ───────────────────────────────────────────────
async function createNewChat() {
    newChatBtn.disabled = true;
    newChatBtn.textContent = '⏳ Creating…';
    try {
        const res  = await fetch(`${API}/chats?namespace=generic`, { method: 'POST' });
        if (!res.ok) throw new Error(res.status);
        const data = await res.json();
        activeChatId = data.chat_id;
        msgsWrap.innerHTML = '';
        chatTitleBar.textContent = data.title || 'New conversation';
        appendMsg('👋 New conversation started. How can I help?', 'assistant');
        await loadConversations();
    } catch (e) {
        alert('Could not create chat: ' + e.message);
    } finally {
        newChatBtn.disabled = false;
        newChatBtn.innerHTML = '<span>＋</span> New chat';
    }
}

async function loadChat(chatId, title) {
    activeChatId = chatId;
    chatTitleBar.textContent = title || 'Conversation';
    msgsWrap.innerHTML = '';
    // Highlight active in sidebar
    document.querySelectorAll('.convo-item').forEach(el => {
        el.classList.toggle('active', el.dataset.id === chatId);
    });
    try {
        const res  = await fetch(`${API}/chats/${chatId}`);
        if (!res.ok) throw new Error(res.status);
        const data = await res.json();
        // messages is a dict keyed by index or message_id
        const msgs = data.messages;
        const arr  = typeof msgs === 'object' && !Array.isArray(msgs) ? Object.values(msgs) : (msgs || []);
        arr.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
        arr.forEach(m => {
            const role = m.role === 'assistant' ? 'assistant' : 'user';
            // content is dict { 0: {type, text}, 1: ... }
            let text = '';
            if (typeof m.content === 'object' && !Array.isArray(m.content)) {
                text = Object.values(m.content).map(c => c.text ?? '').join('');
            } else if (typeof m.content === 'string') {
                text = m.content;
            }
            if (text) appendMsg(text, role);
        });
    } catch(e) {
        appendMsg('Could not load history: ' + e.message, 'assistant');
    }
}

async function deleteChat(evt, chatId) {
    evt.stopPropagation();
    if (!confirm('Delete this conversation?')) return;
    try {
        const res = await fetch(`${API}/chats/${chatId}`, { method: 'DELETE' });
        if (!res.ok) throw new Error(res.status);
        if (chatId === activeChatId) {
            activeChatId = null;
            msgsWrap.innerHTML = '';
            chatTitleBar.textContent = 'Select or start a conversation';
        }
        await loadConversations();
    } catch(e) {
        alert('Could not delete: ' + e.message);
    }
}

// ── Send message ──────────────────────────────────────────────────────────────
async function sendMessage() {
    const text = msgInput.value.trim();
    if (!text || isSending) return;

    // Auto-create chat if none active
    if (!activeChatId) {
        await createNewChat();
        if (!activeChatId) return;
    }

    isSending = true;
    sendBtn.disabled = true;
    msgInput.value = '';
    msgInput.style.height = 'auto';

    appendMsg(text, 'user');

    // Placeholder for streaming assistant response
    const bubbleEl = appendMsg('', 'assistant');
    const inner    = bubbleEl.querySelector('.msg-bubble');
    inner.innerHTML = '<span class="thinking-indicator">●●●</span>';

    let fullText = '';

    try {
        const body = {
            content: text,
            message_config: {
                agent_mode: agentMode,
                reasoning: false,
            }
        };

        const res = await fetch(`${API}/chats/${activeChatId}/messages`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        if (!res.ok) {
            const errText = await res.text();
            inner.innerHTML = marked.parse(`❌ Error ${res.status}: ${errText}`);
            return;
        }

        const contentType = res.headers.get('content-type') || '';
        if (contentType.includes('text/event-stream') || res.body) {
            // ── SSE / streaming ──
            const reader  = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer    = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });

                // Parse SSE lines
                const lines = buffer.split('\n');
                buffer = lines.pop(); // keep incomplete line

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const raw = line.slice(6).trim();
                        if (raw === '[DONE]') continue;
                        try {
                            const obj = JSON.parse(raw);
                            // Handle both {text} and {content} shapes
                            // Handle Anthropic-style SSE: content_block_delta -> {delta:{type:'text_delta',text:'...'}}
                            const deltaVal = obj.delta;
                            const chunk = (deltaVal && typeof deltaVal === 'object' ? deltaVal.text : null)
                                        ?? (typeof deltaVal === 'string' ? deltaVal : null)
                                        ?? obj.text ?? obj.content ?? obj.token ?? null;
                            if (typeof chunk === 'string') {
                                fullText += chunk;
                            }
                        } catch {
                            // Raw text stream (not JSON)
                            if (raw) fullText += raw;
                        }
                        inner.innerHTML = marked.parse(fullText || '…');
                        msgsWrap.scrollTop = msgsWrap.scrollHeight;
                    }
                }
            }
            // Flush remaining buffer
            if (buffer.startsWith('data: ')) {
                const raw = buffer.slice(6).trim();
                if (raw && raw !== '[DONE]') {
                    try { fullText += JSON.parse(raw).text ?? raw; } catch { fullText += raw; }
                }
            }
        } else {
            // Non-streaming JSON fallback
            const data = await res.json();
            fullText = data.response ?? data.content ?? data.message ?? JSON.stringify(data);
        }

        if (fullText) {
            inner.innerHTML = marked.parse(fullText);
        } else if (!inner.textContent || inner.querySelector('.thinking-indicator')) {
            inner.innerHTML = marked.parse('*(No response)*');
        }
    } catch(e) {
        inner.innerHTML = marked.parse(`❌ Request failed: ${e.message}`);
    } finally {
        isSending = false;
        sendBtn.disabled = false;
        msgInput.focus();
        msgsWrap.scrollTop = msgsWrap.scrollHeight;
        // Refresh sidebar so title/timestamp updates
        loadConversations();
    }
}

// ── UI helpers ────────────────────────────────────────────────────────────────
function appendMsg(text, role) {
    const wrap = document.createElement('div');
    wrap.className = 'message ' + role;
    const av = document.createElement('div');
    av.className = 'msg-avatar';
    av.textContent = role === 'user' ? '👤' : '🤖';
    const bub = document.createElement('div');
    bub.className = 'msg-bubble';
    if (role === 'user') {
        bub.textContent = text;
        wrap.appendChild(bub);
        wrap.appendChild(av);
    } else {
        bub.innerHTML = text ? marked.parse(text) : '';
        wrap.appendChild(av);
        wrap.appendChild(bub);
    }
    msgsWrap.appendChild(wrap);
    msgsWrap.scrollTop = msgsWrap.scrollHeight;
    return wrap;
}

function escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Auto-grow textarea
msgInput.addEventListener('input', () => {
    msgInput.style.height = 'auto';
    msgInput.style.height = Math.min(msgInput.scrollHeight, 140) + 'px';
});
msgInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

// ── Init ──────────────────────────────────────────────────────────────────────
(async () => {
    const convos = await loadConversations();
    // Auto-load the most recent conversation
    if (convos && convos.length) {
        const first = (convos.docs ?? convos)[0];
        if (first) await loadChat(first.chat_id, first.title);
    }
})();
</script>
</body>
</html>"""

@app.route('/')
def index():
    return HTML

@app.route('/health')
def health():
    return {'status': 'healthy', 'service': 'dishchat-frontend', 'version': '2.0'}

if __name__ == '__main__':
    app.run(host=os.environ.get('DISHCHAT_FRONTEND_HOST', '0.0.0.0'), port=int(os.environ.get('DISHCHAT_FRONTEND_PORT', '3000')), debug=False)

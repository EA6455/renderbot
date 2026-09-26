/**
 * GPT-6 Astra Standby Widget - Embeddable
 * Usage: <script src="https://yourdomain.com/widget.js" data-api="https://yourdomain.com/api/chat"></script>
 */
(function() {
  const SCRIPT = document.currentScript;
  const API_URL = SCRIPT?.getAttribute('data-api') || '/api/chat';
  const POSITION = SCRIPT?.getAttribute('data-position') || 'bottom-right';
  const PRIMARY_COLOR = SCRIPT?.getAttribute('data-color') || '#f5c518';
  const TITLE = SCRIPT?.getAttribute('data-title') || 'Astra • Standby';

  if (document.getElementById('astra-widget-root')) return;

  const style = document.createElement('style');
  style.textContent = `
    #astra-widget-root { position: fixed; z-index: 999999; font-family: Inter, system-ui, -apple-system, sans-serif; }
    #astra-widget-root.bottom-right { bottom: 24px; right: 24px; }
    #astra-widget-root.bottom-left { bottom: 24px; left: 24px; }
    #astra-btn {
      width: 64px; height: 64px; border-radius: 50%; background: #0f0f12; border: 2px solid ${PRIMARY_COLOR};
      cursor: pointer; display:flex; align-items:center; justify-content:center; box-shadow: 0 8px 32px rgba(0,0,0,0.4);
      transition: transform 0.2s; position:relative;
    }
    #astra-btn:hover { transform: scale(1.05); }
    #astra-btn .dot {
      position:absolute; top:2px; right:2px; width:12px; height:12px; background:#22c55e; border-radius:50%; border:2px solid #0f0f12;
      animation: pulse 2s infinite;
    }
    @keyframes pulse { 0%{box-shadow:0 0 0 0 rgba(34,197,94,0.7)} 70%{box-shadow:0 0 0 10px rgba(34,197,94,0)} 100%{box-shadow:0 0 0 0 rgba(34,197,94,0)} }
    #astra-panel {
      position:absolute; bottom:80px; right:0; width:380px; max-width: calc(100vw - 32px); height:520px; max-height: calc(100vh - 120px);
      background:#121216; border:1px solid #2a2a30; border-radius:20px; display:none; flex-direction:column; overflow:hidden;
      box-shadow: 0 24px 64px rgba(0,0,0,0.5);
    }
    #astra-panel.open { display:flex; }
    #astra-header { padding:16px 20px; background:#1a1a1f; border-bottom:1px solid #2a2a30; display:flex; align-items:center; justify-content:space-between; }
    #astra-header h3 { margin:0; font-size:15px; font-weight:700; color:#fff; display:flex; align-items:center; gap:8px; }
    #astra-header .status { font-size:11px; color:#22c55e; background:rgba(34,197,94,0.1); padding:4px 8px; border-radius:20px; border:1px solid rgba(34,197,94,0.2); }
    #astra-messages { flex:1; overflow-y:auto; padding:16px; display:flex; flex-direction:column; gap:12px; background:#121216; }
    .astra-msg { max-width:85%; padding:12px 14px; border-radius:16px; font-size:14px; line-height:1.5; word-wrap:break-word; }
    .astra-msg.user { align-self:flex-end; background:${PRIMARY_COLOR}; color:#000; border-bottom-right-radius:4px; font-weight:500; }
    .astra-msg.assistant { align-self:flex-start; background:#1e1e24; color:#e6e6e6; border:1px solid #2a2a30; border-bottom-left-radius:4px; }
    .astra-msg.assistant pre { background:#0f0f12; padding:10px; border-radius:8px; overflow-x:auto; margin:8px 0; font-size:12px; }
    #astra-input-area { padding:12px; background:#1a1a1f; border-top:1px solid #2a2a30; display:flex; gap:8px; }
    #astra-input { flex:1; background:#0f0f12; border:1px solid #2a2a30; border-radius:12px; padding:12px 14px; color:#fff; font-size:14px; outline:none; }
    #astra-input:focus { border-color:${PRIMARY_COLOR}; }
    #astra-send { background:${PRIMARY_COLOR}; border:none; width:44px; height:44px; border-radius:12px; cursor:pointer; display:flex; align-items:center; justify-content:center; }
    #astra-typing { font-size:12px; color:#888; padding:0 16px 8px; display:none; }
    #astra-typing.show { display:block; }
  `;
  document.head.appendChild(style);

  const root = document.createElement('div');
  root.id = 'astra-widget-root';
  root.className = POSITION;
  root.innerHTML = `
    <div id="astra-panel">
      <div id="astra-header">
        <h3><span style="width:28px;height:28px;background:${PRIMARY_COLOR};border-radius:8px;display:inline-flex;align-items:center;justify-content:center;color:#000;font-weight:900">A</span> ${TITLE}</h3>
        <span class="status">● standby</span>
      </div>
      <div id="astra-messages">
        <div class="astra-msg assistant">Hi! I'm <b>GPT-6 Astra</b> — standby on this website. 🛰️<br><br>I'm OpenAI's flagship for coding, research, and computer-use. How can I help you today?</div>
      </div>
      <div id="astra-typing">Astra is thinking...</div>
      <div id="astra-input-area">
        <input id="astra-input" placeholder="Ask Astra anything..." />
        <button id="astra-send"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="black" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg></button>
      </div>
    </div>
    <div id="astra-btn" title="Astra standby">
      <div class="dot"></div>
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none"><path d="M12 2 L13.5 8.5 L20 9 L13.5 10.5 L12 17 L10.5 10.5 L4 9 L10.5 8.5 Z" fill="${PRIMARY_COLOR}"/><circle cx="12" cy="12" r="3" fill="none" stroke="${PRIMARY_COLOR}" stroke-width="1.5" opacity="0.5"/></svg>
    </div>
  `;
  document.body.appendChild(root);

  const btn = document.getElementById('astra-btn');
  const panel = document.getElementById('astra-panel');
  const input = document.getElementById('astra-input');
  const send = document.getElementById('astra-send');
  const messages = document.getElementById('astra-messages');
  const typing = document.getElementById('astra-typing');

  let history = [];
  let isOpen = false;

  function toggle() {
    isOpen = !isOpen;
    panel.classList.toggle('open', isOpen);
    if (isOpen) input.focus();
  }

  function addMsg(role, content) {
    const div = document.createElement('div');
    div.className = 'astra-msg ' + role;
    // simple markdown-ish
    let html = content.replace(/</g,'&lt;').replace(/>/g,'&gt;');
    html = html.replace(/```([\s\S]*?)```/g, '<pre>$1</pre>');
    html = html.replace(/\n/g, '<br>');
    div.innerHTML = html;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  async function sendMessage() {
    const text = input.value.trim();
    if (!text) return;
    addMsg('user', text);
    history.push({role:'user', content:text});
    input.value = '';
    typing.classList.add('show');

    try {
      const res = await fetch(API_URL, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({message: text, history: history})
      });
      const data = await res.json();
      typing.classList.remove('show');
      addMsg('assistant', data.reply || 'No reply');
      history.push({role:'assistant', content:data.reply});
      // keep last 20
      if (history.length > 20) history = history.slice(-20);
    } catch (e) {
      typing.classList.remove('show');
      addMsg('assistant', '⚠️ Connection error. Is the Astra server running? ' + e.message);
    }
  }

  btn.addEventListener('click', toggle);
  send.addEventListener('click', sendMessage);
  input.addEventListener('keydown', (e)=>{ if(e.key==='Enter') sendMessage(); });

  // auto open after 3 sec to show standby
  setTimeout(()=>{ if(!isOpen){ /* optional: toggle(); */ } }, 3000);

  console.log('Astra widget standby. API:', API_URL);
})();

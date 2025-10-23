(function(){
  "use strict";

  // --- utils: csrf cookie ---
  function getCookie(name){
    let cookieValue = null;
    if(document.cookie && document.cookie !== ''){
      const cookies = document.cookie.split(';');
      for(let i=0;i<cookies.length;i++){
        const cookie = cookies[i].trim();
        if(cookie.substring(0, name.length + 1) === (name + '=')){
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }
  const csrftoken = getCookie('csrftoken');

  // --- DOM refs ---
  const chatBox  = document.getElementById('chatBox');
  const form     = document.getElementById('chatForm');
  const input    = document.getElementById('msgInput');
  const botImage = document.getElementById('botImage');
  const ENDPOINT = window.C2S_CHAT_ENDPOINT || ""; // "" = postar na mesma rota

  // --- Bot state (idle/typing) com preload e transição suave ---
  const BOT_IDLE   = botImage?.dataset?.srcIdle   || botImage?.getAttribute('data-src-idle');
  const BOT_TYPING = botImage?.dataset?.srcTyping || botImage?.getAttribute('data-src-typing');

  const preload = (src) => { if(!src) return; const i = new Image(); i.src = src; };
  preload(BOT_IDLE); preload(BOT_TYPING);

  function setBotState(state){
    if(!botImage) return;
    const next = state === 'typing' ? BOT_TYPING : BOT_IDLE;
    if(!next) return;
    if(botImage.src.endsWith(next)) return;

    botImage.style.opacity = "0.2";
    botImage.style.transform = state === 'typing' ? 'scale(1.03)' : 'scale(1)';

    const apply = () => {
      botImage.src = next;
      requestAnimationFrame(() => { botImage.style.opacity = "1"; });
    };

    const tmp = new Image();
    tmp.onload = apply;
    tmp.onerror = () => { botImage.style.opacity = "1"; };
    tmp.src = next;
  }

  // --- mensagens ---
  const history = [];

  function appendMessage(role, htmlText){
    const div = document.createElement('div');
    div.className = 'msg ' + (role === 'user' ? 'user' : 'assistant');
    div.innerHTML = `
      <div class="avatar">${role === 'user' ? 'U' : 'A'}</div>
      <div class="bubble">${htmlText}</div>
    `;
    chatBox.appendChild(div);
    chatBox.scrollTop = chatBox.scrollHeight; // scroll apenas no chat
  }

  function makeTypingBubble(){
    const div = document.createElement('div');
    div.className = 'msg assistant';
    div.innerHTML = `
      <div class="avatar">A</div>
      <div class="bubble">
        <span class="typing"><span class="dot"></span><span class="dot"></span><span class="dot"></span></span>
      </div>`;
    return div;
  }

  // --- submit handler ---
  if(form){
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const text = (input.value || "").trim();
      if(!text) return;

      appendMessage('user', text.replace(/\n/g,'<br>'));
      history.push({role:'user', content:text});
      input.value = '';

      // estado digitando
      const typing = makeTypingBubble();
      chatBox.appendChild(typing);
      chatBox.scrollTop = chatBox.scrollHeight;
      setBotState('typing');

      try{
        const resp = await fetch(ENDPOINT, {
          method: "POST",
          headers: {
            "Content-Type":"application/json",
            "X-CSRFToken": csrftoken
          },
          body: JSON.stringify({ message: text, history })
        });
        if(!resp.ok) throw new Error("Falha ao consultar.");

        const data = await resp.json();

        chatBox.removeChild(typing);
        setBotState('idle');

        const replyHtml = (data.reply || "Ok.").replace(/\n/g,'<br>');
        appendMessage('assistant', replyHtml);
        history.push({role:'assistant', content:data.reply || ""});
      }catch(err){
        if(typing.parentNode) typing.parentNode.removeChild(typing);
        setBotState('idle');
        appendMessage('assistant', "Ops! Tive um problema ao consultar. Tente novamente em instantes.");
      }
    });
  }
})();

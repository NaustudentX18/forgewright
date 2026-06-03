      .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    escaped = escaped.replace(new RegExp(PLACEHOLDER + "(\\d+)" + PLACEHOLDER, "g"), function (_m, n) {
      var f = fences[parseInt(n, 10)];
      var langHtml = f.lang ? '<span class="lang">' + escapeHtml(f.lang) + '</span>' : "";
      return (
        '<pre>' + langHtml +
        '<button class="copy" type="button" aria-label="Copy code" data-copy>Copy</button>' +
        '<code>' + f.html + '</code></pre>'
      );
    });
    return escaped;
  }
  var KW = ("break case catch class const continue debugger default delete do else " +
            "export extends finally for function if import in instanceof let new " +
            "of return static switch this throw try typeof var void while with " +
            "yield async await from as true false null undefined")
    .split(" ");
  var KW_RE = new RegExp("^(?:" + KW.join("|") + ")\\b");
  function highlightCode(src, lang) {
    var lines = String(src || "").split("\n");
    var out = [];
    for (var i = 0; i < lines.length; i++) {
      out.push(highlightLine(lines[i], lang));
    }
    return out.join("\n");
  }
  function highlightLine(line, lang) {
    var isShell = /^(bash|sh|shell|zsh)$/i.test(lang || "");
    var isPy = /^py/i.test(lang || "");
    var commentChar = isShell || isPy ? "#" : "//";
    var re = /(\/\/.*$|#[^\n!]*$|'[^'\n]*'|"[^"\n]*"|`[^`\n]*`|\b\d+(?:\.\d+)?\b|\b[A-Za-z_$][\w$]*\b|\s+|[^\w\s])/g;
    var m, out = "", last = 0;
    while ((m = re.exec(line)) !== null) {
      if (m.index > last) out += escapeHtml(line.slice(last, m.index));
      var tok = m[0];
      if (tok[0] === "/" && tok[1] === "/") {
        out += '<span class="tok-c">' + escapeHtml(tok) + '</span>';
      } else if (tok[0] === "#" && (isShell || isPy)) {
        out += '<span class="tok-c">' + escapeHtml(tok) + '</span>';
      } else if (tok[0] === "'" || tok[0] === '"' || tok[0] === "`") {
        out += '<span class="tok-s">' + escapeHtml(tok) + '</span>';
      } else if (/^\d/.test(tok)) {
        out += '<span class="tok-n">' + escapeHtml(tok) + '</span>';
      } else if (/^[A-Za-z_$]/.test(tok)) {
        if (KW_RE.test(tok)) {
          out += '<span class="tok-k">' + escapeHtml(tok) + '</span>';
        } else if (re.lastIndex < line.length && line[re.lastIndex] === "(") {
          out += '<span class="tok-f">' + escapeHtml(tok) + '</span>';
        } else {
          out += escapeHtml(tok);
        }
      } else {
        out += escapeHtml(tok);
      }
      last = re.lastIndex;
    }
    if (last < line.length) out += escapeHtml(line.slice(last));
    return out;
  }
  function scrollToBottom() {
    requestAnimationFrame(function () { messagesEl.scrollTop = messagesEl.scrollHeight; });
  }
  function isMobile() {
    return window.matchMedia("(max-width: 767px)").matches;
  }
  function showToast(msg) {
    if (!toast || !toastMsg) return;
    toastMsg.textContent = msg;
    toast.removeAttribute("hidden");
    clearTimeout(showToast._t);
    showToast._t = setTimeout(function () { toast.setAttribute("hidden", ""); }, 5000);
  }
  function setConnection(stateName, label) {
    if (!connectionPill) return;
    connectionPill.setAttribute("data-state", stateName);
    if (connectionLabel && label) connectionLabel.textContent = label;
  }
  function openSidebar() {
    sidebar.classList.add("open");
    scrim.removeAttribute("hidden");
  }
  function closeSidebar() {
    sidebar.classList.remove("open");
    scrim.setAttribute("hidden", "");
  }
  openBtn && openBtn.addEventListener("click", openSidebar);
  closeBtn && closeBtn.addEventListener("click", closeSidebar);
  scrim && scrim.addEventListener("click", closeSidebar);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      if (sidebar.classList.contains("open")) { closeSidebar(); return; }
      if (settingsModal && settingsModal.open) { settingsModal.close(); return; }
    }
    if (e.key === "/" && !e.metaKey && !e.ctrlKey && !e.altKey) {
      var t = e.target;
      var inEditable = t && (
        t.tagName === "INPUT" || t.tagName === "TEXTAREA" ||
        (t.getAttribute && t.getAttribute("contenteditable") === "true")
      );
      if (!inEditable) {
        e.preventDefault();
        input && input.focus();
      }
    }
  });
  input && input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      if (e.metaKey || e.ctrlKey) {
        e.preventDefault();
        composer.requestSubmit();
      }
    }
  });
  (function edgeSwipe() {
    var startX = 0, startY = 0, tracking = false;
    document.addEventListener("touchstart", function (e) {
      if (e.touches.length !== 1) return;
      if (!isMobile()) return;
      if (sidebar.classList.contains("open")) return;
      if (e.touches[0].clientX > 28) return;
      tracking = true;
      startX = e.touches[0].clientX;
      startY = e.touches[0].clientY;
    }, { passive: true });
    document.addEventListener("touchmove", function (e) {
      if (!tracking) return;
      var dx = e.touches[0].clientX - startX;
      var dy = e.touches[0].clientY - startY;
      if (Math.abs(dy) > 40) { tracking = false; return; }
      if (dx > 50) { tracking = false; openSidebar(); }
    }, { passive: true });
    document.addEventListener("touchend", function () { tracking = false; }, { passive: true });
  })();
  function openSettings(data) {
    if (!settingsModal) return;
    if (data) {
      if (settingsProvider) settingsProvider.textContent = data.provider || "—";
      if (settingsModel) settingsModel.textContent = data.model || "—";
      if (settingsStatus) settingsStatus.textContent = data.status || "—";
    }
    if (typeof settingsModal.showModal === "function") {
      settingsModal.showModal();
    } else {
      settingsModal.setAttribute("open", "");
    }
  }
  settingsBtn && settingsBtn.addEventListener("click", function () {
    getJson("/api/health").then(function (h) {
      openSettings(Object.assign({ status: "online" }, h || {}));
    }).catch(function () {
      openSettings({ provider: "—", model: "—", status: "offline" });
    });
  });
  if (settingsModal) {
    settingsModal.addEventListener("click", function (e) {
      if (e.target && e.target.hasAttribute("data-close")) {
        settingsModal.close();
      }
    });
  }
  function clearMessages() {
    while (messagesEl.firstChild) messagesEl.removeChild(messagesEl.firstChild);
    state.hasRenderedHistory = false;
  }
  function markHistory() {
    if (state.hasRenderedHistory) return;
    state.hasRenderedHistory = true;
    messagesEl.classList.add("has-history");
  }
  function addMessage(role, content) {
    if (emptyState && emptyState.parentNode) emptyState.parentNode.removeChild(emptyState);
    var wrap = document.createElement("div");
    wrap.className = "msg " + role;
    var bubble = document.createElement("div");
    bubble.className = "bubble";
    if (role === "assistant" && !content) {
      bubble.innerHTML =
        '<span class="typing" aria-label="Assistant is thinking">' +
        '<span class="dot"></span><span class="dot"></span><span class="dot"></span></span>';
    } else if (role === "user") {
      var role_lbl = document.createElement("span");
      role_lbl.className = "role";
      role_lbl.textContent = "you";
      var txt = document.createElement("div");
      txt.className = "user-text";
      txt.textContent = content;
      bubble.appendChild(role_lbl);
      bubble.appendChild(txt);
    } else {
      bubble.innerHTML = renderMd(content);
    }
    wrap.appendChild(bubble);
    messagesEl.appendChild(wrap);
    scrollToBottom();
    return bubble;
  }
  function setAssistantText(bubble, text) {
    bubble.classList.remove("streaming");
    bubble.innerHTML = renderMd(text);
    scrollToBottom();
  }
  function appendAssistantToken(bubble, chunk) {
    if (!bubble) return;
    bubble.classList.add("streaming");
    if (bubble.querySelector(".typing")) {
      bubble.innerHTML = renderMd(chunk);
    } else {
      var current = bubble.textContent || "";
      bubble.innerHTML = renderMd(current + chunk);
    }
    scrollToBottom();
  }
  var statusEl = null;
  function setStatus(text) {
    if (!text) {
      if (statusEl && statusEl.parentNode) statusEl.parentNode.removeChild(statusEl);
      statusEl = null;
      return;
    }
    if (!statusEl) {
      statusEl = document.createElement("div");
      statusEl.className = "status";
      messagesEl.appendChild(statusEl);
    }
    statusEl.textContent = text;
    scrollToBottom();
  }
  function appendToolCard(name, args) {
    var card = document.createElement("div");
    card.className = "tool-card";
    card.setAttribute("data-open", "false");
    var head = document.createElement("button");
    head.type = "button";
    head.className = "tool-card-head";
    head.setAttribute("aria-expanded", "false");
    head.innerHTML =
      '<span class="tool-card-icon" aria-hidden="true">' + toolIcon(name) + '</span>' +
      '<span class="tool-card-label"></span>' +
      '<span class="tool-card-meta"></span>' +
      '<svg class="tool-card-chev" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>';
    head.querySelector(".tool-card-label").textContent = name || "tool";
    var argsStr = args ? safeStringify(args) : "";
    head.querySelector(".tool-card-meta").textContent = argsStr ? truncate(argsStr, 60) : "";
    var body = document.createElement("pre");
    body.className = "tool-card-body";
    body.textContent = argsStr;
    body.style.display = "none";
    head.addEventListener("click", function () {
      var open = card.getAttribute("data-open") === "true";
      card.setAttribute("data-open", open ? "false" : "true");
      head.setAttribute("aria-expanded", open ? "false" : "true");
      body.style.display = open ? "none" : "block";
    });
    card.appendChild(head);
    card.appendChild(body);
    messagesEl.appendChild(card);
    scrollToBottom();
    return card;
  }
  function toolIcon(name) {
    var n = String(name || "").toLowerCase();
    if (n.includes("bash") || n.includes("shell") || n === "sh" || n === "zsh") return "&#x3E;_";
    if (n.includes("editor") || n.includes("str_replace") || n.includes("write")) return "&#x270E;";
    if (n.includes("browser") || n.includes("web")) return "&#x25CB;";
    if (n.includes("terminate") || n.includes("stop")) return "&#x25A0;";
    return "&#x2022;";
  }
  function safeStringify(v) {
    try { return JSON.stringify(v, null, 2); }
    catch (e) { return String(v); }
  }
  function truncate(s, n) {
    s = String(s);
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  }
  function formatRelative(iso) {
    if (!iso) return "";
    var then = new Date(iso).getTime();
    if (isNaN(then)) return "";
    var now = Date.now();
    var diff = Math.max(0, now - then) / 1000;
    if (diff < 60) return "just now";
    if (diff < 3600) return Math.floor(diff / 60) + "m ago";
    if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
    if (diff < 7 * 86400) return "yesterday";
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("button.copy");
    if (!btn) return;
    var pre = btn.parentElement;
    var code = pre && pre.querySelector("code");
    var text = code ? code.textContent : "";
    var done = function (ok) {
      if (ok) {
        btn.setAttribute("data-copied", "true");
        btn.textContent = "Copied";
        setTimeout(function () {
          btn.removeAttribute("data-copied");
          btn.textContent = "Copy";
        }, 1400);
      } else {
        btn.textContent = "Failed";
        setTimeout(function () { btn.textContent = "Copy"; }, 1400);
      }
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); });
    } else {
      try {
        var ta = document.createElement("textarea");
        ta.value = text; ta.setAttribute("readonly", "");
        ta.style.position = "absolute"; ta.style.left = "-9999px";
        document.body.appendChild(ta); ta.select();
        var ok = document.execCommand("copy");
        document.body.removeChild(ta);
        done(ok);
      } catch (e) { done(false); }
    }
  });
  function api(path, opts) {
    opts = opts || {};
    opts.headers = Object.assign(
      { "Content-Type": "application/json" },
      opts.headers || {}
    );
    if (opts.body && typeof opts.body !== "string") {
      opts.body = JSON.stringify(opts.body);
    }
    return fetch(path, opts).then(function (r) {
      if (!r.ok) {
        return r.text().then(function (t) {
          throw new Error(t || ("HTTP " + r.status));
        });
      }
      if (r.status === 204) return null;
      return r.json();
    });
  }
  function getJson(path) { return api(path, { method: "GET" }); }
  function postJson(path, body) { return api(path, { method: "POST", body: body || {} }); }
  function delJson(path) { return api(path, { method: "DELETE" }); }
  function loadSessions() {
    return getJson("/api/sessions").then(function (list) {
      state.sessions = list || [];
      renderSessions();
    }).catch(function () {  });
  }
  function renderSessions() {
    sessionList.innerHTML = "";
    if (!state.sessions.length) {
      var p = document.createElement("p");
      p.className = "session-empty";
      p.textContent = "No chats yet — start one!";
      sessionList.appendChild(p);
      return;
    }
    state.sessions.forEach(function (s) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "session-item" + (s.id === state.sessionId ? " active" : "");
      btn.setAttribute("role", "listitem");
      btn.innerHTML =
        '<span class="title"></span>' +
        '<span class="meta"><span class="ts"></span><span class="count"></span></span>' +
        '<button class="del" type="button" aria-label="Delete chat" title="Delete">×</button>';
      btn.querySelector(".title").textContent = s.title || "(empty)";
      btn.querySelector(".ts").textContent = formatRelative(s.updated_at);
      btn.querySelector(".count").textContent = (s.message_count || 0) + " msgs";
      var delBtn = btn.querySelector(".del");
      delBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        if (window.confirm("Delete this chat?")) {
          delJson("/api/sessions/" + encodeURIComponent(s.id)).then(loadSessions);
        }
      });
      btn.addEventListener("click", function () {
        openSession(s.id);
        if (isMobile()) closeSidebar();
      });
      var pressTimer = null;
      btn.addEventListener("touchstart", function () {
        pressTimer = setTimeout(function () {
          if (window.confirm("Delete this chat?")) {
            delJson("/api/sessions/" + encodeURIComponent(s.id)).then(loadSessions);
          }
        }, 800);
      }, { passive: true });
      btn.addEventListener("touchend", function () { clearTimeout(pressTimer); }, { passive: true });
      btn.addEventListener("touchmove", function () { clearTimeout(pressTimer); }, { passive: true });
      sessionList.appendChild(btn);
    });
  }
  function showEmpty() {
    clearMessages();
    if (emptyState) {
      messagesEl.appendChild(emptyState);
    } else {
      var w = document.createElement("div");
      w.className = "empty-state";
      w.innerHTML = '<div class="wordmark">forgewright</div>' +
        '<p class="tagline">Bring your own keys. Forge agents in your terminal.</p>';
      messagesEl.appendChild(w);
    }
  }
  function openSession(id) {
    state.sessionId = id;
    clearMessages();
    return getJson("/api/sessions/" + encodeURIComponent(id)).then(function (data) {
      var msgs = data.messages || [];
      msgs.forEach(function (m) { addMessage(m.role, m.content); });
      markHistory();
      if (!msgs.length) showEmpty();
      titleEl.textContent = data.title || "Chat";
      loadSessions();
    }).catch(function (err) {
      showEmpty();
      addMessage("system", "Failed to load session: " + err.message);
    });
  }
  function newChat() {
    state.sessionId = null;
    showEmpty();
    titleEl.textContent = "New chat";
    if (isMobile()) closeSidebar();
    input.focus();
  }
  newChatBtn && newChatBtn.addEventListener("click", newChat);
  newChatSidebarBtn && newChatSidebarBtn.addEventListener("click", newChat);
  function autosize() {
    input.style.height = "auto";
    var h = input.scrollHeight;
    if (h > 140) h = 140;
    if (h < 36) h = 36;
    input.style.height = h + "px";
  }
  input.addEventListener("input", function () {
    autosize();
    if (input.value) stopPlaceholderCycle();
  });
  input.addEventListener("blur", function () {
    if (!input.value) startPlaceholderCycle();
  });
  setTimeout(autosize, 0);
  var PLACEHOLDERS = [
    "Type a message…",
    "Ask me to refactor a file…",
    "Run a shell command for me…",
    "Search the web for…",
  ];
  function applyPlaceholder() {
    if (input && !input.value) input.placeholder = PLACEHOLDERS[state.placeholderIdx];
  }
  function startPlaceholderCycle() {
    applyPlaceholder();
    if (state.placeholderTimer) return;
    state.placeholderTimer = setInterval(function () {
      state.placeholderIdx = (state.placeholderIdx + 1) % PLACEHOLDERS.length;
      applyPlaceholder();
    }, 3000);
  }
  function stopPlaceholderCycle() {
    if (state.placeholderTimer) clearInterval(state.placeholderTimer);
    state.placeholderTimer = null;
  }
  startPlaceholderCycle();
  (function bindVisualViewport() {
    if (!window.visualViewport) return;
    var vv = window.visualViewport;
    var apply = function () {
      var kbOpen = vv.height < (window.innerHeight - 100);
      if (kbOpen) {
        document.documentElement.style.setProperty(
          "--safe-bot", (window.innerHeight - vv.height) + "px"
        );
      } else {
        document.documentElement.style.removeProperty("--safe-bot");
      }
    };
    vv.addEventListener("resize", apply);
    vv.addEventListener("scroll", apply);
    apply();
  })();
  composer.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = input.value;
    input.value = "";
    autosize();
    stopPlaceholderCycle();
    send(text);
  });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      composer.requestSubmit();
    }
  });
  function send(text) {
    text = (text || "").trim();
    if (!text || state.sending) return;
    state.sending = true;
    sendBtn.disabled = true;
    sendBtn.classList.add("sent");
    setTimeout(function () { sendBtn.classList.remove("sent"); }, 700);
    addMessage("user", text);
    var placeholder = addMessage("assistant", "");
    sawToken = false;
    function start() {
      return postJson("/api/sessions", {}).then(function (sess) {
        state.sessionId = sess.id;
        titleEl.textContent = (sess.title || "Chat");
        return runStream(
          "/api/sessions/" + encodeURIComponent(state.sessionId) + "/messages",
          { content: text },
          placeholder
        );
      });
    }
    start().catch(function (err) {
      if (err && err.name === "AbortError") return;
      setAssistantText(placeholder, "[error] " + (err.message || String(err)));
      showToast("Send failed: " + (err.message || String(err)));
    }).then(finish);
  }
  var inFlightTool = null;
  var inFlightStarted = 0;
  var sawToken = false;
  function runStream(path, body, placeholder) {
    state.abortCtrl = new AbortController();
    setConnection("online", "Online");
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: state.abortCtrl.signal,
    }).then(function (resp) {
      if (!resp.ok) {
        return resp.text().then(function (t) { throw new Error(t || ("HTTP " + resp.status)); });
      }
      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";
      var finalText = "";
      return new Promise(function (resolve, reject) {
        function pump() {
          reader.read().then(function (r) {
            if (r.done) {
              setStatus(null);
              setConnection("online", "Online");
              resolve();
              return;
            }
            buffer += decoder.decode(r.value, { stream: true });
            var parts = buffer.split("\n\n");
            buffer = parts.pop();
            parts.forEach(function (chunk) {
              var ev = null, dataLine = null;
              chunk.split("\n").forEach(function (line) {
                if (line.indexOf("event: ") === 0) ev = line.slice(7).trim();
                else if (line.indexOf("data: ") === 0) dataLine = line.slice(6);
              });
              if (!ev || !dataLine) return;
              try { handleEvent(ev, JSON.parse(dataLine)); }
              catch (e) {  }
            });
            pump();
          }, reject);
        }
        function handleEvent(ev, p) {
          if (ev === "thinking") {
            setStatus("thinking…");
          } else if (ev === "tool_call") {
            inFlightTool = (p && p.tool) || "tool";
            inFlightStarted = Date.now();
            appendToolCard(inFlightTool, p && p.args);
            setStatus("running " + inFlightTool + "…");
          } else if (ev === "tool_result") {
            var dur = inFlightStarted ? (Date.now() - inFlightStarted) : 0;
            var name = (p && p.tool) || inFlightTool || "tool";
            setStatus("ran " + name + ", took " + dur + "ms");
            inFlightTool = null; inFlightStarted = 0;
          } else if (ev === "token") {
            sawToken = true;
            appendAssistantToken(placeholder, p && p.content || "");
            finalText += (p && p.content) || "";
          } else if (ev === "final") {
            if (placeholder) placeholder.classList.remove("streaming");
            finalText = p.content || "";
            if (!finalText.trim()) finalText = "No response — try again";
            if (!p.content || !state.sawToken) {
              setAssistantText(placeholder, finalText);
            }
            setStatus(null);
            loadSessions();
          } else if (ev === "error") {
            var msg = (p && p.message) || "unknown error";
            finalText += (finalText ? "\n\n" : "") + "[error] " + msg;
            setAssistantText(placeholder, finalText);
            setStatus(null);
            showToast("Agent error: " + msg);
            setConnection("reconnecting", "Reconnecting…");
          }
        }
        pump();
      });
    });
  }
  function finish() {
    state.sending = false;
    sendBtn.disabled = false;
    state.abortCtrl = null;
  }
  document.querySelectorAll(".chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      var prompt = chip.getAttribute("data-prompt") || chip.textContent;
      input.value = prompt;
      autosize();
      stopPlaceholderCycle();
      input.focus();
      if (composer.requestSubmit) composer.requestSubmit();
      else composer.dispatchEvent(new Event("submit", { cancelable: true }));
    });
  });
  loadSessions();
  showEmpty();

  // --- PWA: service worker registration + install prompt ----------------
  // Keeps a home-screen install path alive on Android (beforeinstallprompt)
  // and shows an iOS Share-sheet hint, since iOS does not fire the event.
  // No-op on desktop browsers and when the app is already installed.
  (function pwaInstall() {
    var DISMISS_KEY = "fw-install-dismissed-v1";
    if (localStorage.getItem(DISMISS_KEY)) return;
    function dismiss() {
      try { localStorage.setItem(DISMISS_KEY, "1"); } catch (e) {}
      var n = document.getElementById("installBanner");
      if (n) n.remove();
    }
    function show(text, action) {
      if (document.getElementById("installBanner")) return;
      var n = document.createElement("div");
      n.id = "installBanner";
      n.setAttribute("role", "region");
      n.setAttribute("aria-label", "Install forgewright");
      n.style.cssText = "position:fixed;left:12px;right:12px;bottom:calc(12px + env(safe-area-inset-bottom,0px));z-index:30;background:var(--color-surface);color:var(--color-text);border:1px solid var(--color-border);border-radius:14px;padding:10px 12px;display:flex;align-items:center;gap:10px;box-shadow:0 8px 24px rgba(0,0,0,.4);font:500 14px/1.3 var(--font-sans)";
      var s = document.createElement("span");
      s.style.cssText = "flex:1;color:var(--color-text-dim)";
      s.textContent = text;
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = "Install";
      b.style.cssText = "background:var(--color-cta);color:#020617;border:0;border-radius:8px;padding:8px 14px;font:600 14px/1 inherit;cursor:pointer;min-height:36px";
      b.addEventListener("click", function () { action(); dismiss(); });
      n.appendChild(s); n.appendChild(b);
      document.body.appendChild(n);
    }
    window.addEventListener("beforeinstallprompt", function (e) {
      e.preventDefault();
      show("Install forgewright as an app", function () { e.prompt(); });
    });
    window.addEventListener("appinstalled", dismiss);
    var ua = navigator.userAgent || "";
    var isiOS = /iPhone|iPad|iPod/.test(ua);
    var isStandalone = window.navigator.standalone === true ||
      window.matchMedia("(display-mode: standalone)").matches;
    if (isiOS && !isStandalone) {
      show('Tap Share, then "Add to Home Screen".', function () {});
    }
  })();

  // Service worker — register on the same origin as the app, scope "/".
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker
        .register("/static/sw.js", { scope: "/" })
        .catch(function (err) { console.warn("sw.register.failed", err); });
    });
  }
})();
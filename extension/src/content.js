/* Tondar - "Download this video" panel shown over web players. */
(() => {
  if (window.__tondarLoaded) return;
  window.__tondarLoaded = true;
  const B = globalThis.browser ?? globalThis.chrome;

  const KNOWN = /^https?:\/\/([a-z0-9-]+\.)*(youtube\.com|youtu\.be|youtube-nocookie\.com|vimeo\.com|dailymotion\.com|twitch\.tv|instagram\.com|facebook\.com|fb\.watch|twitter\.com|x\.com|tiktok\.com|soundcloud\.com|aparat\.com|namasha\.com|telewebion\.com|bilibili\.com|reddit\.com|bandcamp\.com|mixcloud\.com|rumble\.com|odysee\.com|ok\.ru|vk\.com|streamable\.com)\//i;
  const YT_MEDIA_PAGE = /youtube\.com\/(watch|shorts\/|embed\/|live\/)|youtu\.be\//i;

  let enabled = false;
  let sniffed = [];
  let target = null;           // current <video>/<audio> element
  const dismissed = new WeakSet();
  let dismissedFloating = false;
  let host, root, panel, menu, menuOpen = false, lastUrl = location.href;

  function send(msg) {
    return new Promise((res) => {
      try {
        B.runtime.sendMessage(msg, (r) => res(r || { error: B.runtime.lastError?.message || "no reply" }));
      } catch (e) {
        res({ error: String(e) });
      }
    });
  }

  function human(n) {
    if (!n || n <= 0) return "";
    const u = ["B", "KB", "MB", "GB"];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return (i ? n.toFixed(1) : n) + " " + u[i];
  }

  function isMediaPage() {
    if (/youtube\.com|youtu\.be/i.test(location.hostname)) return YT_MEDIA_PAGE.test(location.href);
    return KNOWN.test(location.href);
  }

  /* --------------------------------------------------------------- UI */
  function build() {
    host = document.createElement("tondar-panel");
    host.style.cssText = "all:initial;direction:ltr;position:absolute;z-index:2147483647;top:0;left:0;display:none;";
    root = host.attachShadow({ mode: "closed" });
    root.innerHTML = `
      <style>
        :host{all:initial}
        .wrap{direction:ltr;text-align:left;font:13px/1.2 system-ui,-apple-system,"Segoe UI",Ubuntu,sans-serif;color:#fff;user-select:none}
        .btn{display:flex;align-items:center;gap:6px;height:30px;padding:0 4px 0 9px;border-radius:6px;
             background:linear-gradient(#2f86f0,#1458b8);box-shadow:0 2px 8px rgba(0,0,0,.45);
             border:1px solid rgba(255,255,255,.25);cursor:pointer;opacity:.93;transition:opacity .15s}
        .btn:hover{opacity:1;background:linear-gradient(#3a90f7,#1a63c6)}
        .lbl{white-space:nowrap;font-weight:600;letter-spacing:.1px}
        .x{margin-left:4px;width:18px;height:18px;line-height:17px;text-align:center;border-radius:4px;
           color:#d8e6fb;font-size:15px}
        .x:hover{background:rgba(255,255,255,.2);color:#fff}
        .menu{position:absolute;right:0;top:34px;min-width:270px;max-width:380px;max-height:380px;overflow:auto;
              background:#fff;color:#1c2733;border-radius:6px;box-shadow:0 6px 22px rgba(0,0,0,.45);
              border:1px solid #b9c6d3;display:none;padding:4px 0}
        .menu.open{display:block}
        .head{padding:6px 12px 4px;font-size:11px;font-weight:700;color:#5b6b7b;text-transform:uppercase}
        .title{padding:2px 12px 6px;unicode-bidi:plaintext;font-size:12px;color:#334;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .it{display:flex;justify-content:space-between;gap:16px;padding:7px 12px;cursor:pointer;white-space:nowrap}
        .it .nm{overflow:hidden;text-overflow:ellipsis;min-width:0}
        .it .sz{flex:none}
        .it:hover{background:#1f6fd8;color:#fff}
        .it .sz{color:#7a8794}.it:hover .sz{color:#e3edfb}
        .msg{padding:10px 12px;color:#556;white-space:normal}
        .err{color:#b3261e}
        .note{padding:2px 12px 6px;font-size:11px;color:#8a5a00}
        .spin{display:inline-block;width:12px;height:12px;border:2px solid #9fb6d0;border-top-color:#1f6fd8;
              border-radius:50%;animation:s 1s linear infinite;vertical-align:-2px;margin-right:6px}
        @keyframes s{to{transform:rotate(360deg)}}
        .toast{position:absolute;right:0;top:34px;background:#1d2b38;color:#fff;padding:8px 12px;border-radius:6px;
               white-space:nowrap;box-shadow:0 4px 14px rgba(0,0,0,.4)}
      </style>
      <div class="wrap">
        <div class="btn" title="Tondar Download Manager"><svg viewBox="0 0 64 64" width="18" height="18"><path fill="#ffd24a" d="M36 6 16 36h14l-6 22 24-32H34l6-20z"/></svg><span class="lbl">Download this video</span><span class="x" title="Hide">×</span></div>
        <div class="menu"></div>
      </div>`;
    panel = root.querySelector(".btn");
    menu = root.querySelector(".menu");
    panel.addEventListener("click", (e) => {
      e.stopPropagation();
      e.preventDefault();
      if (e.target.classList.contains("x")) {
        if (target) dismissed.add(target); else dismissedFloating = true;
        hide();
        return;
      }
      toggleMenu();
    });
    menu.addEventListener("click", (e) => e.stopPropagation());
    document.addEventListener("click", (e) => {
      if (!e.composedPath().includes(host)) closeMenu();     // clicks inside the panel keep it open
    }, true);
    (document.documentElement || document.body).appendChild(host);
  }

  function hide() {
    if (host) host.style.display = "none";
    closeMenu();
  }

  function label(kind) {
    root.querySelector(".lbl").textContent = kind === "audio" ? "Download this audio" : "Download this video";
  }

  function closeMenu() {
    menuOpen = false;
    menu?.classList.remove("open");
  }

  function toggleMenu() {
    if (menuOpen) return closeMenu();
    menuOpen = true;
    menu.classList.add("open");
    fillMenu();
  }

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function shortName(url) {
    let n = url.split("?")[0].split("#")[0].split("/").pop() || url;
    try { n = decodeURIComponent(n); } catch (e) { /* keep raw */ }
    return n;
  }

  function sizeText(e) {
    const sz = human(e.size);
    return sz ? (e.approx ? "~" + sz : sz) : "size unknown";
  }

  let resolveCache = { key: null, data: null };

  async function fillMenu() {
    menu.textContent = "";
    const pageUrl = location.href;
    const loading = el("div", "msg");
    const spin = el("span", "spin");
    loading.append(spin, "Finding videos on this page...");
    menu.appendChild(loading);

    // what the tab has played so far (with the headers the browser sent) + the current <video> source
    const streams = [], files = [];
    for (const s of sniffed) {
      (s.kind === "stream" ? streams : files).push({ url: s.url, referer: s.referer || "", origin: s.origin || "" });
    }
    for (const m of document.querySelectorAll("video, audio, video source, audio source")) {
      const src = m.currentSrc || m.src;
      if (src && /^https?:/i.test(src)) {
        let cross = true;
        try { cross = new URL(src).origin !== location.origin; } catch (e) { /* ignore */ }
        const ref = { url: src, referer: cross ? location.origin + "/" : location.href, origin: "" };
        (/\.(m3u8|mpd)(\?|$)/i.test(src) ? streams : files).push(ref);
      }
    }
    const uniq = (a) => {
      const seen = new Map();
      for (const x of a) if (!seen.has(x.url)) seen.set(x.url, x);
      return [...seen.values()].slice(-12);
    };
    const req = { type: "resolve", page: pageUrl, title: document.title, streams: uniq(streams).reverse(),
                  files: uniq(files).reverse() };
    const key = JSON.stringify(req);
    let data = resolveCache.key === key ? resolveCache.data : null;
    if (!data) {
      data = await send(req);
      if (!data.error) resolveCache = { key, data };
    }
    if (!menuOpen) return;
    menu.textContent = "";
    if (data.error && !(data.entries || []).length) {
      menu.appendChild(el("div", "msg err", /not running/.test(data.error)
        ? "Tondar Download Manager is not running. Start it and try again."
        : "No downloadable video found on this page." + (data.error ? " (" + data.error.slice(0, 140) + ")" : "")));
      return;
    }
    menu.appendChild(el("div", "head", "Download with Tondar"));
    if (data.page_error) {
      const n = el("div", "msg note", /log ?in|login|cookies|private|rate/i.test(data.page_error)
        ? "This site needs you to be logged in. Showing the files the page loaded instead."
        : "Could not read this page directly; showing the files it loaded.");
      n.title = data.page_error;
      menu.appendChild(n);
    }
    if (data.title) {
      const t = el("div", "title", data.title);
      t.dir = "auto";
      menu.appendChild(t);
    }
    let lastKind = null;
    for (const e of data.entries) {
      if (e.kind === "file" && lastKind !== "file") menu.appendChild(el("div", "head", "Files on this page"));
      lastKind = e.kind;
      const row = el("div", "it");
      const label = el("span", "nm", e.kind === "file" ? shortName(e.label || e.url) : e.label);
      label.title = e.kind === "file" ? e.url : e.label;
      row.append(label, el("span", "sz", sizeText(e)));
      row.addEventListener("click", () => {
        if (e.kind === "file") {
          act({ type: "file-download", url: e.url, referer: e.referer || pageUrl, origin: e.origin || "",
                filename: e.label || "" });
        } else {
          act({ type: "media-download", url: e.url, page: pageUrl, format: e.format, referer: e.referer || "",
                origin: e.origin || "", title: e.url !== pageUrl ? (data.title || document.title) : "" });
        }
      });
      menu.appendChild(row);
    }
    addPlaylistRow();
  }

  function addPlaylistRow() {
    let list = null;
    try { list = new URL(location.href).searchParams.get("list"); } catch (e) { /* ignore */ }
    if (!list || !/(^|\.)youtube\.com$/i.test(location.hostname)) return;
    menu.appendChild(el("div", "head", "Playlist"));
    const row = el("div", "it");
    row.append(el("span", "nm", "Download the whole playlist…"), el("span", "sz", ""));
    row.addEventListener("click", () => act({ type: "links", links: [{ url: location.href, referer: location.href, page: true }] }));
    menu.appendChild(row);
  }

  async function act(msg) {
    closeMenu();
    const r = await send(msg);
    const t = el("div", "toast", r && !r.error ? "Sent to Tondar Download Manager" : (r.error || "Failed"));
    root.querySelector(".wrap").appendChild(t);
    setTimeout(() => t.remove(), 2500);
  }

  /* ------------------------------------------------------- placement */
  function visibleArea(v) {
    const r = v.getBoundingClientRect();
    if (r.width < 200 || r.height < 110) return 0;
    const st = getComputedStyle(v);
    if (st.visibility === "hidden" || st.display === "none" || +st.opacity === 0) return 0;
    const w = Math.min(r.right, innerWidth) - Math.max(r.left, 0);
    const h = Math.min(r.bottom, innerHeight) - Math.max(r.top, 0);
    return w > 0 && h > 0 ? w * h : 0;
  }

  function pickTarget() {
    let best = null, area = 0;
    for (const v of document.querySelectorAll("video")) {
      if (dismissed.has(v)) continue;
      const a = visibleArea(v);
      if (a > area) { area = a; best = v; }
    }
    return best;
  }

  function place() {
    if (!enabled) return hide();
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      sniffed = [];
      resolveCache = { key: null, data: null };
      dismissedFloating = false;
      closeMenu();
    }
    // YouTube home/search pages autoplay hover previews: only show on real video pages
    const ytNonVideo = /(^|\.)youtube\.com$/i.test(location.hostname) && !YT_MEDIA_PAGE.test(location.href);
    target = ytNonVideo ? null : pickTarget();
    const hasAudio = sniffed.some((s) => s.kind === "audio");
    const want = target || ((isMediaPage() || hasAudio) && !dismissedFloating && window.top === window);
    if (!want) return hide();
    if (!host) build();
    if (!host.isConnected) (document.documentElement || document.body).appendChild(host);
    host.style.display = "block";
    const w = panel.offsetWidth || 190;
    if (target) {
      label("video");
      const r = target.getBoundingClientRect();
      const top = Math.max(r.top, 0) + 10;
      host.style.position = "absolute";
      host.style.top = top + scrollY + "px";
      host.style.left = Math.min(r.right, innerWidth) - w - 12 + scrollX + "px";
    } else {
      label(hasAudio && !YT_MEDIA_PAGE.test(location.href) ? "audio" : "video");
      host.style.position = "fixed";
      host.style.top = innerHeight - 52 + "px";
      host.style.left = innerWidth - w - 24 + "px";
    }
  }

  /* --------------------------------------------------------- wiring */
  B.runtime.onMessage.addListener((msg) => {
    if (msg.type === "tondar-media") {
      sniffed = msg.items || [];
      place();
    } else if (msg.type === "tondar-collect-links" && window.top === window) {
      collectLinks(msg.selection);
    }
  });

  function collectLinks(selectionOnly) {
    let anchors = [...document.querySelectorAll("a[href]")];
    const sel = getSelection();
    if (selectionOnly && sel && sel.rangeCount) {
      const range = sel.getRangeAt(0);
      anchors = anchors.filter((a) => range.intersectsNode(a));
    }
    const seen = new Set();
    // the page itself first: if it is a playlist / mix / channel, Tondar lists all of it
    const links = [{ url: location.href, referer: location.href, page: true }];
    for (const a of anchors) {
      const u = a.href;
      if (!/^(https?|ftp):/i.test(u) || seen.has(u)) continue;
      seen.add(u);
      const text = (a.getAttribute("title") || a.textContent || "").replace(/\s+/g, " ").trim().slice(0, 150);
      links.push({ url: u, referer: location.href, text });
    }
    send({ type: "links", links });
  }

  async function init() {
    const st = await send({ type: "status" });
    enabled = !!st.panel;
    const s = await send({ type: "sniffed" });
    sniffed = s.items || [];
    place();
    setInterval(place, 1000);
    addEventListener("scroll", place, { passive: true });
    addEventListener("resize", place, { passive: true });
    document.addEventListener("yt-navigate-finish", () => setTimeout(place, 300));
    document.addEventListener("play", () => place(), true);
  }

  B.storage?.onChanged?.addListener((ch) => {
    if (ch.panel) { enabled = !!ch.panel.newValue; place(); }
  });

  init();
})();

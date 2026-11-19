/* Tondar Download Manager - browser integration (background).
 * - Captures browser downloads and hands them to the desktop app.
 * - Sniffs video/audio requests per tab for the "Download this video" panel.
 * - Talks to the app over http://127.0.0.1:<port> (default 9614).
 */
const B = globalThis.browser ?? globalThis.chrome;

const DEFAULTS = { port: 9614, capture: true, panel: true };
let appInfo = null;          // result of /ping
let lastPing = 0;
const tabMedia = new Map();  // tabId -> Map(url -> {url, type, size, mime})
const recentlyHandled = new Set();

async function cfg() {
  const s = await B.storage.local.get(DEFAULTS);
  return { ...DEFAULTS, ...s };
}

async function api(path, body, timeoutMs = 120000) {
  const { port } = await cfg();
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch(`http://127.0.0.1:${port}${path}`, {
      method: body ? "POST" : "GET",
      headers: { "X-Tondar-Client": "1", "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
      signal: ctl.signal,
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } finally {
    clearTimeout(t);
  }
}

async function ping(force = false) {
  if (!force && Date.now() - lastPing < 15000) return appInfo;
  lastPing = Date.now();
  try {
    appInfo = await api("/ping", null, 2000);
  } catch (e) {
    appInfo = null;
  }
  updateBadge();
  return appInfo;
}

function updateBadge() {
  const action = B.action ?? B.browserAction;
  if (!action) return;
  action.setBadgeText({ text: appInfo ? "" : "off" });
  action.setBadgeBackgroundColor({ color: "#c62828" });
}

// full cookie objects (domain/path/expiry), so yt-dlp can use them on every sub-domain
async function cookieJar(url) {
  try {
    const list = await B.cookies.getAll({ url });
    return list.map((c) => ({ domain: c.domain, path: c.path, secure: c.secure, hostOnly: c.hostOnly,
                              expires: Math.floor(c.expirationDate || 0), name: c.name, value: c.value }));
  } catch (e) {
    return [];
  }
}

async function cookiesFor(url) {
  try {
    const list = await B.cookies.getAll({ url });
    return list.map((c) => `${c.name}=${c.value}`).join("; ");
  } catch (e) {
    return "";
  }
}

function extOf(name) {
  const clean = (name || "").split(/[?#]/)[0];
  const base = clean.substring(clean.lastIndexOf("/") + 1);
  const i = base.lastIndexOf(".");
  return i > 0 ? base.substring(i + 1).toLowerCase() : "";
}

function baseName(p) {
  return (p || "").split(/[\\/]/).pop();
}

async function sendDownload(url, referer, filename, origin, tabUrl) {
  const cookies = await cookiesFor(url);
  return api("/download", { url, referer: referer || "", origin: origin || "", filename: filename || "",
                            cookies, userAgent: navigator.userAgent, tabUrl: tabUrl || "" });
}

/* ---------------------------------------------------------------- downloads */
B.downloads.onCreated.addListener(async (item) => {
  const c = await cfg();
  if (!c.capture) return;
  const url = item.finalUrl || item.url;
  if (!/^(https?|ftp):/i.test(url)) return;         // blob:, data: stay in the browser
  if (recentlyHandled.has(url)) return;
  const info = await ping(true);
  if (!info) return;                                 // app not running: let the browser download
  const name = baseName(item.filename) || "";
  const ext = extOf(name) || extOf(url);
  const minBytes = (info.capture_min_size_kb || 0) * 1024;
  const wanted = info.capture_extensions.includes(ext);
  if (!wanted) return;
  if (minBytes && item.totalBytes > 0 && item.totalBytes < minBytes) return;
  try {
    await B.downloads.cancel(item.id);
    await B.downloads.erase({ id: item.id });
  } catch (e) { /* already finished */ }
  recentlyHandled.add(url);
  setTimeout(() => recentlyHandled.delete(url), 5000);
  try {
    await sendDownload(url, item.referrer, name);
  } catch (e) {
    // app went away between ping and send -> download in the browser after all
    B.downloads.download({ url });
  }
});

/* ------------------------------------------------------------- media sniff */
const MEDIA_MIME = /^(video\/|audio\/|application\/(vnd\.apple\.mpegurl|x-mpegurl|dash\+xml))/i;
const MEDIA_EXT = /\.(mp4|m4v|webm|mkv|mov|flv|m3u8|mpd|mp3|m4a|aac|ogg|oga|opus|flac|wav)(\?|$)/i;
const SKIP_HOST = /(^|\.)(googlevideo\.com|youtube\.com|ytimg\.com|doubleclick\.net|googlesyndication\.com)$/i;
const SEGMENT = /\.(ts|m4s|aac|cmfv|cmfa)(\?|$)|[?&](range|bytestart)=|\/seg-?\d+|\/chunk-?\d+|fragment/i;

function header(headers, name) {
  const h = (headers || []).find((x) => x.name.toLowerCase() === name);
  return h ? h.value : "";
}

/* Remember the Referer / Origin the browser really sent for each request: CDNs such as
 * arvanvod.ir only serve the full video to requests that come from their own player
 * (often an <iframe> on another domain), so downloads must repeat these headers. */
const sentHeaders = new Map();          // requestId -> {referer, origin}
const SNIFF_TYPES = ["media", "xmlhttprequest", "other", "object"];

function originOf(u) {
  try { return new URL(u).origin; } catch (e) { return ""; }
}

function onSend(d) {
  if (d.tabId < 0) return;
  const h = { referer: header(d.requestHeaders, "referer"), origin: header(d.requestHeaders, "origin") };
  if (h.referer || h.origin) {
    sentHeaders.set(d.requestId, h);
    if (sentHeaders.size > 2000) sentHeaders.delete(sentHeaders.keys().next().value);
  }
}
try {   // Chrome needs "extraHeaders" to expose Referer/Origin; Firefox has no such option
  B.webRequest.onSendHeaders.addListener(onSend, { urls: ["<all_urls>"], types: SNIFF_TYPES },
                                         ["requestHeaders", "extraHeaders"]);
} catch (e) {
  B.webRequest.onSendHeaders.addListener(onSend, { urls: ["<all_urls>"], types: SNIFF_TYPES }, ["requestHeaders"]);
}
B.webRequest.onErrorOccurred.addListener((d) => sentHeaders.delete(d.requestId), { urls: ["<all_urls>"] });

B.webRequest.onHeadersReceived.addListener(
  (d) => {
    const sent = sentHeaders.get(d.requestId) || {};
    sentHeaders.delete(d.requestId);
    if (d.tabId < 0 || d.statusCode >= 400) return;
    let host = "";
    try { host = new URL(d.url).hostname; } catch (e) { return; }
    if (SKIP_HOST.test(host)) return;
    const mime = header(d.responseHeaders, "content-type").split(";")[0].trim();
    const isPlaylist = /mpegurl|dash\+xml/i.test(mime) || /\.(m3u8|mpd)(\?|$)/i.test(d.url);
    if (!isPlaylist && SEGMENT.test(d.url)) return;
    if (!(MEDIA_MIME.test(mime) || MEDIA_EXT.test(d.url))) return;
    if (/^(text|image)\//i.test(mime)) return;
    let size = parseInt(header(d.responseHeaders, "content-length") || "0", 10);
    const cr = header(d.responseHeaders, "content-range").match(/\/(\d+)$/);
    if (cr) size = parseInt(cr[1], 10);
    if (!isPlaylist && size && size < 300 * 1024) return;      // ads / previews / thumbnails
    const kind = isPlaylist ? "stream" : (/^audio\//i.test(mime) || /\.(mp3|m4a|aac|ogg|oga|opus|flac|wav)(\?|$)/i.test(d.url)) ? "audio" : "video";
    if (!tabMedia.has(d.tabId)) tabMedia.set(d.tabId, new Map());
    const m = tabMedia.get(d.tabId);
    const key = isPlaylist ? d.url : d.url.split("?")[0];
    if (m.has(key)) return;
    // what the page that made the request looks like to the server
    const docUrl = d.documentUrl || d.originUrl || (d.initiator ? d.initiator + "/" : "");
    const docOrigin = d.initiator || originOf(docUrl);
    const crossOrigin = docOrigin && docOrigin !== originOf(d.url);
    m.set(key, {
      url: d.url, kind, size, mime,
      referer: sent.referer || (crossOrigin ? docOrigin + "/" : docUrl),
      origin: sent.origin || (crossOrigin && d.type === "xmlhttprequest" ? docOrigin : ""),
    });
    B.tabs.sendMessage(d.tabId, { type: "tondar-media", items: [...m.values()] }).catch(() => {});
  },
  { urls: ["<all_urls>"], types: SNIFF_TYPES },
  ["responseHeaders"]
);

B.tabs.onRemoved.addListener((id) => tabMedia.delete(id));
B.tabs.onUpdated.addListener((id, change) => {
  if (change.url) tabMedia.delete(id);     // navigation (also SPA URL changes)
});

/* ---------------------------------------------------- messages from pages */
B.runtime.onMessage.addListener((msg, sender, reply) => {
  (async () => {
    try {
      if (msg.type === "status") {
        const c = await cfg();
        const info = await ping(!!msg.force);
        reply({ ok: !!info, panel: c.panel && (!info || info.media_panel !== false), info });
      } else if (msg.type === "formats") {
        reply(await api("/media/formats", { url: msg.url }, 120000));
      } else if (msg.type === "resolve") {
        const cookies = await cookiesFor(msg.page);
        const cookie_jar = await cookieJar(msg.page);
        // players often live in an <iframe> without a title: use the tab's title then
        reply(await api("/media/resolve", { page: msg.page, title: msg.title || sender.tab?.title || "",
                                            streams: msg.streams, files: msg.files, referer: msg.page,
                                            cookies, cookie_jar }, 180000));
      } else if (msg.type === "media-download") {
        const ref = msg.referer || sender.tab?.url || "";
        const cookies = await cookiesFor(msg.url);
        const cookie_jar = msg.url === msg.page ? await cookieJar(msg.url) : null;
        reply(await api("/media/download", { url: msg.url, format: msg.format, referer: msg.referer || "",
                                             cookie_jar,
                                             origin: msg.origin || "",
                                             title: msg.title || (msg.url !== msg.page ? sender.tab?.title : "") || "",
                                             cookies,
                                             userAgent: navigator.userAgent, pageUrl: ref,
                                             tabUrl: sender.tab?.url || msg.page || "" }));
      } else if (msg.type === "file-download") {
        reply(await sendDownload(msg.url, msg.referer, msg.filename || "", msg.origin || "", sender.tab?.url));
      } else if (msg.type === "sniffed") {
        const m = tabMedia.get(sender.tab?.id);
        reply({ items: m ? [...m.values()] : [] });
      } else if (msg.type === "links") {
        const cookies = msg.links.length ? await cookiesFor(msg.links[0].url) : "";
        reply(await api("/links", { links: msg.links.map((l) => ({ ...l, cookies })) }));
      } else {
        reply({ error: "unknown" });
      }
    } catch (e) {
      reply({ error: "Tondar Download Manager is not running (" + e.message + ")" });
    }
  })();
  return true;
});

/* ------------------------------------------------------------ context menu */
function buildMenus() {
  B.contextMenus.removeAll(() => {
    B.contextMenus.create({ id: "tondar-link", title: "Download with Tondar", contexts: ["link"] });
    B.contextMenus.create({ id: "tondar-media", title: "Download this video/audio with Tondar",
                            contexts: ["video", "audio", "page"] });
    B.contextMenus.create({ id: "tondar-all", title: "Download all links with Tondar",
                            contexts: ["page", "selection"] });
  });
}
B.runtime.onInstalled.addListener(buildMenus);
B.runtime.onStartup?.addListener(buildMenus);

B.contextMenus.onClicked.addListener(async (info, tab) => {
  try {
    if (info.menuItemId === "tondar-link") {
      await sendDownload(info.linkUrl, tab?.url, "", "", tab?.url);
    } else if (info.menuItemId === "tondar-media") {
      const src = info.srcUrl && /^https?:/.test(info.srcUrl) ? info.srcUrl : null;
      // page URL first: yt-dlp knows the site and can offer all qualities
      await api("/media/download", { url: tab.url, format: null, direct: src });
    } else if (info.menuItemId === "tondar-all") {
      B.tabs.sendMessage(tab.id, { type: "tondar-collect-links", selection: !!info.selectionText });
    }
  } catch (e) {
    console.warn("Tondar:", e);
  }
});

ping(true);

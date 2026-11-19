const B = globalThis.browser ?? globalThis.chrome;
const DEFAULTS = { port: 9614, capture: true, panel: true };
const $ = (id) => document.getElementById(id);

async function refresh() {
  const s = { ...DEFAULTS, ...(await B.storage.local.get(DEFAULTS)) };
  $("capture").checked = s.capture;
  $("panel").checked = s.panel;
  $("port").value = s.port;
  B.runtime.sendMessage({ type: "status", force: true }, (r) => {
    const st = $("st");
    if (r && r.ok) {
      st.innerHTML = `<span class="ok">● Connected</span> to Tondar ${r.info.version}`;
    } else {
      st.innerHTML = '<span class="bad">● Not connected</span> — start Tondar Download Manager';
    }
  });
  if (B.permissions && globalThis.browser) {           // Firefox: host access is opt-in
    const has = await B.permissions.contains({ origins: ["<all_urls>"] });
    $("perm").hidden = has;
  }
}

$("capture").onchange = (e) => B.storage.local.set({ capture: e.target.checked });
$("panel").onchange = (e) => B.storage.local.set({ panel: e.target.checked });
$("port").onchange = (e) => B.storage.local.set({ port: parseInt(e.target.value, 10) || 9614 }).then(refresh);
$("perm").onclick = async () => {
  await B.permissions.request({ origins: ["<all_urls>"] });
  refresh();
};
refresh();

/* MemoPet — 零依赖前端 */
"use strict";

const $ = (id) => document.getElementById(id);
let activeId = null;
let busy = false;

function setStatus(ok, text) {
  $("status").className = ok ? "dot-on" : "dot-off";
  if (text) $("status").title = text;
}

async function api(path, opts) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}

function fmtTime(t) {
  const d = new Date(t * 1000);
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/* ---------- 猫窝列表 ---------- */
async function loadSlots() {
  const { pets } = await api("/api/pets");
  const list = $("slot-list");
  list.innerHTML = "";
  for (const p of pets) {
    const item = document.createElement("div");
    item.className = "slot" + (p.pet_id === activeId ? " active" : "");
    const name = document.createElement("div");
    name.className = "slot-name";
    name.textContent = p.name;
    const meta = document.createElement("div");
    meta.className = "slot-meta";
    meta.textContent = `${p.age_days} 天 · ${p.interactions} 次互动`;
    item.append(name, meta);
    item.onclick = () => selectPet(p.pet_id);
    list.appendChild(item);
  }
  if (!pets.length) {
    const tip = document.createElement("div");
    tip.className = "muted tip";
    tip.textContent = "起个名字领养一只吧";
    list.appendChild(tip);
  }
  return pets;
}

/* ---------- 舞台 ---------- */
/* 手绘二次元小猫：chibi 比例、渐变虹膜大眼（带高光）、ω 猫嘴、腮红、
   会摇的呆毛；心情三态（开心眯眼 / 常态 / 难过含泪）；dim=true 灰调版。 */
function catSvg(mood, dim = false) {
  const C = dim
    ? { cream: "#c3c7ce", ginger: "#a9adb5", lash: "#6f737b", nose: "#a9a29b",
        irisA: "#d7dade", irisB: "#b9bdc4", blush: "#dadde2", tear: "#cfe0ee",
        bell: "#c9cdd4", collar: "#9aa0a8", whisker: "#b6bac2" }
    : { cream: "#ffe9c9", ginger: "#f4a259", lash: "#4a3520", nose: "#e88a8a",
        irisA: "#ffd27a", irisB: "#ef8b32", blush: "#ffb3ba", tear: "#a5d8ff",
        bell: "#ffd34d", collar: "#5b74ff", whisker: "#e3b877" };
  const eye = (cx) => `
      <path d="M${cx - 6} 36.5 q6 -5.5 12 0" stroke="${C.lash}" stroke-width="2.4" fill="none" stroke-linecap="round"/>
      <ellipse cx="${cx}" cy="43" rx="5.4" ry="6.8" fill="url(#irisGrad)"/>
      <ellipse cx="${cx}" cy="44.6" rx="2.1" ry="4.2" fill="${C.lash}"/>
      <circle cx="${cx - 2.2}" cy="40.4" r="1.9" fill="#fff"/>
      <circle cx="${cx + 2.4}" cy="46.6" r="0.9" fill="#fff" opacity="0.85"/>`;
  const eyes = mood === "happy"
    ? `<path d="M30 43 q6 -7 12 0" stroke="${C.lash}" stroke-width="3" fill="none" stroke-linecap="round"/>
       <path d="M54 43 q6 -7 12 0" stroke="${C.lash}" stroke-width="3" fill="none" stroke-linecap="round"/>`
    : mood === "sad"
    ? `<path d="M30 45 q6 5 12 0" stroke="${C.lash}" stroke-width="3" fill="none" stroke-linecap="round"/>
       <path d="M54 45 q6 5 12 0" stroke="${C.lash}" stroke-width="3" fill="none" stroke-linecap="round"/>
       <path d="M62.5 50 q2.6 3.6 0 5.2 q-2.6 -1.6 0 -5.2" fill="${C.tear}"/>`
    : `<g class="cat-eyes">${eye(36)}${eye(60)}</g>`;
  const mouth = mood === "happy"
    ? `<path d="M44.2 52.2 q3.8 5 7.6 0 z" fill="${C.lash}"/>
       <ellipse cx="48" cy="54.6" rx="1.9" ry="1.1" fill="#ff9aa2"/>`
    : mood === "sad"
    ? `<path d="M45 55 q3 -2.6 6 0" stroke="${C.lash}" stroke-width="2" fill="none" stroke-linecap="round"/>`
    : `<path d="M44.2 52.6 q1.9 2.6 3.8 0 q1.9 2.6 3.8 0" stroke="${C.lash}" stroke-width="1.8" fill="none" stroke-linecap="round"/>`;
  const ears = mood === "sad"
    ? `<path d="M28 32 Q 19 12 35 17 Q 41 20 45 23 Z" fill="${C.ginger}"/>
       <path d="M68 32 Q 77 12 61 17 Q 55 20 51 23 Z" fill="${C.ginger}"/>`
    : `<path d="M28 30 Q 18 7 35 13 Q 41 16 45 20 Z" fill="${C.ginger}"/>
       <path d="M68 30 Q 78 7 61 13 Q 55 16 51 20 Z" fill="${C.ginger}"/>`;
  return `<svg viewBox="0 0 96 96" width="118" height="118" aria-hidden="true">
    <defs>
      <linearGradient id="irisGrad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="${C.irisA}"/>
        <stop offset="1" stop-color="${C.irisB}"/>
      </linearGradient>
    </defs>
    <path d="M67 73 q 17 4 15 -12 q -1.5 -8.5 -10.5 -8.5" fill="none" stroke="${C.ginger}" stroke-width="8" stroke-linecap="round"/>
    <ellipse cx="48" cy="73" rx="21" ry="14" fill="${C.cream}"/>
    <ellipse cx="40" cy="82.5" rx="5" ry="3.2" fill="${C.cream}"/>
    <ellipse cx="56" cy="82.5" rx="5" ry="3.2" fill="${C.cream}"/>
    ${ears}
    <path d="M31 27 Q 26 16 35 19 Q 39 21 41 23 Z" fill="${C.blush}" opacity="0.9"/>
    <path d="M65 27 Q 70 16 61 19 Q 57 21 55 23 Z" fill="${C.blush}" opacity="0.9"/>
    <path class="ahoge" d="M47 12 q 3.5 -8 9.5 -6.5 q -5.5 2 -4 8" fill="none" stroke="${C.ginger}" stroke-width="2.6" stroke-linecap="round"/>
    <circle cx="48" cy="41" r="26" fill="${C.cream}"/>
    <ellipse cx="30.5" cy="49.5" rx="5" ry="2.8" fill="${C.blush}" opacity="0.65"/>
    <ellipse cx="65.5" cy="49.5" rx="5" ry="2.8" fill="${C.blush}" opacity="0.65"/>
    ${eyes}
    <polygon points="46.3,50 49.7,50 48,52.2" fill="${C.nose}"/>
    ${mouth}
    <g stroke="${C.whisker}" stroke-width="1.3" stroke-linecap="round" opacity="0.9">
      <line x1="26" y1="46" x2="14" y2="43"/><line x1="26" y1="50" x2="14" y2="51"/>
      <line x1="70" y1="46" x2="82" y2="43"/><line x1="70" y1="50" x2="82" y2="51"/>
    </g>
    <path d="M28 62.5 q20 9 40 0 l0 5 q-20 9 -40 0 z" fill="${C.collar}"/>
    <circle cx="48" cy="70" r="3.6" fill="${C.bell}" stroke="${C.whisker}" stroke-width="1"/>
    <line x1="46" y1="69.5" x2="50" y2="70.5" stroke="${C.whisker}" stroke-width="1"/>
  </svg>`;
}

function renderCat(mood) {
  $("pet-emoji").innerHTML = catSvg(mood);
}

function renderEmptyStage() {
  $("pet-emoji").innerHTML = catSvg("normal", true);
  $("pet-name").textContent = "还没有猫";
  $("pet-meta").textContent = "起个名字，领一只回家吧";
  $("bar-hunger").style.width = "0%";
  $("bar-mood").style.width = "0%";
  $("bubble").classList.add("hidden");
  $("growth").classList.add("hidden");
}

function renderPet(p) {
  const mood = p.mood > 0.7 ? "happy" : p.mood < 0.35 ? "sad" : "normal";
  renderCat(mood);
  $("pet-name").textContent = p.name;
  $("pet-meta").textContent = `来到你家 ${p.age_days} 天 · ${p.interactions} 次互动`;
  $("bar-hunger").style.width = `${Math.round(p.hunger * 100)}%`;
  $("bar-mood").style.width = `${Math.round(p.mood * 100)}%`;
}

async function selectPet(id) {
  activeId = id;
  $("growth").classList.add("hidden"); // 成长面板随宠物切换收起
  const pets = await loadSlots();
  const p = pets.find((x) => x.pet_id === id);
  if (p) {
    renderPet(p);
    await loadDiary();
  }
}

/* ---------- 成长档案（当前大脑 vs 出生大脑的逐层余弦） ---------- */
async function toggleGrowth() {
  const box = $("growth");
  if (!activeId) return;
  if (!box.classList.contains("hidden")) { box.classList.add("hidden"); return; }
  try {
    const d = await api(`/api/pets/${activeId}/growth`);
    box.classList.remove("hidden");
    const bars = $("growth-bars");
    bars.innerHTML = "";
    if (!d.layers || !d.layers.length) {
      $("growth-summary").textContent = d.note || "出生大脑未记录";
      return;
    }
    const min = Math.min(...d.layers.map((l) => l.cos));
    const max = Math.max(...d.layers.map((l) => l.cos));
    for (const l of d.layers) {
      const cell = document.createElement("div");
      cell.className = "growth-cell";
      const t = max - min > 1e-6 ? (l.cos - min) / (max - min) : 1;
      cell.style.height = `${10 + Math.round(t * 34)}px`;
      cell.style.background = `rgba(91, 116, 255, ${0.18 + (1 - t) * 0.82})`;
      cell.title = `L${l.i} · cos ${l.cos}`;
      bars.appendChild(cell);
    }
    $("growth-summary").textContent =
      `平均相似 ${d.mean_cos}（1.0 = 完全没变）· 越低说明这一层被经历改变得越多`;
  } catch (e) {
    $("growth-summary").textContent = `⚠ ${e.message}`;
  }
}
$("btn-growth").onclick = toggleGrowth;

/* ---------- 时光倒流：回到最近一次自动存档 ---------- */
$("btn-timetravel").onclick = async () => {
  if (!activeId) return;
  try {
    const { snapshots } = await api(`/api/pets/${activeId}/snapshots`);
    if (!snapshots.length) {
      alert("还没有自动存档——相处满一天后会自动存一份。");
      return;
    }
    const s = snapshots[0];
    if (!confirm(`回到 ${s.when} 的状态？这之后发生的事会被覆盖（日记也会回退）。`)) return;
    const r = await api(`/api/pets/${activeId}/restore`, {
      method: "POST",
      body: JSON.stringify({ ts: s.ts }),
    });
    renderPet(r);
    await loadSlots();
    await loadDiary();
    const bubble = $("bubble");
    bubble.classList.remove("hidden");
    bubble.textContent = `🕰️ 已回到 ${s.when}。`;
  } catch (e) { alert(e.message); }
};

/* ---------- 日记 ---------- */
async function loadDiary() {
  if (!activeId) { $("diary-list").innerHTML = ""; return; }
  const { diary } = await api(`/api/pets/${activeId}/diary`);
  const box = $("diary-list");
  box.innerHTML = "";
  for (const e of [...diary].reverse()) {
    const row = document.createElement("div");
    row.className = "diary-entry";
    const head = document.createElement("div");
    head.className = "diary-head";
    head.textContent = `${fmtTime(e.t)} · ${e.label}`;
    const body = document.createElement("div");
    body.className = "diary-reply";
    body.textContent = e.reply;
    row.append(head, body);
    box.appendChild(row);
  }
}

/* ---------- 交互（SSE 流式） ---------- */
async function interact(action, text = "") {
  if (!activeId || busy) return;
  busy = true;
  document.querySelectorAll("#actions button, #chat-row button").forEach((b) => (b.disabled = true));
  const myPet = activeId; // 生成期间可能切换宠物：回应只属于发起它的猫
  const bubble = $("bubble");
  bubble.classList.remove("hidden");
  bubble.textContent = "…";
  // 生成期间切走了宠物就不再写舞台（只刷新列表），避免 A 猫的话出现在 B 猫的气泡里
  const show = (t) => {
    if (activeId !== myPet) return;
    bubble.textContent = t;
    bubble.scrollTop = bubble.scrollHeight; // 限高后自动跟到最新一行
  };
  let dreamText = null, acc = "";
  const withDream = (t) => (dreamText ? `🌙 它刚睡醒，梦到了：${dreamText}\n\n${t}` : t);
  try {
    const res = await fetch(`/api/pets/${myPet}/interact/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, text }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const events = buf.split("\n\n");
      buf = events.pop(); // 末尾可能是不完整事件，留给下一次 read 拼齐
      for (const chunk of events) {
        const line = chunk.trim();
        if (!line.startsWith("data: ")) continue;
        const p = JSON.parse(line.slice(6));
        if (p.error) throw new Error(p.error);
        if (p.dream) { dreamText = p.dream; show(`🌙 它刚睡醒，梦到了：${p.dream}\n\n`); }
        if (p.delta) { acc += p.delta; show(withDream(acc)); }
        if (p.reply !== undefined) {
          acc = p.reply; // 最终帧（含退化替换文案）以它为准
          show(withDream(acc));
          if (activeId === myPet) {
            renderPet(p);
            await loadDiary();
          }
          await loadSlots();
        }
      }
    }
  } catch (e) {
    show(`⚠ ${e.message}`);
  } finally {
    busy = false;
    document.querySelectorAll("#actions button, #chat-row button").forEach((b) => (b.disabled = false));
  }
}

/* ---------- 创建 / 分身 / 放归 ---------- */
async function loadPersonas() {
  const { personas } = await api("/api/personas");
  const sel = $("new-persona");
  sel.innerHTML = personas
    .map((p) => `<option value="${p.id}">${p.id === "none" ? "白纸（冷启动）" : `🧬 ${p.name}`}</option>`)
    .join("");
}

$("btn-create").onclick = async () => {
  const name = $("new-name").value.trim();
  if (!name || busy) return;
  busy = true;
  try {
    const p = await api("/api/pets", {
      method: "POST",
      body: JSON.stringify({ name, persona_id: $("new-persona").value }),
    });
    $("new-name").value = "";
    await loadSlots();
    await selectPet(p.pet_id);
    await loadDiary();
    const bubble = $("bubble");
    bubble.classList.remove("hidden");
    const { diary } = await api(`/api/pets/${p.pet_id}/diary`);
    bubble.textContent = diary.at(-1)?.reply || "喵？";
  } catch (e) { alert(e.message); } finally { busy = false; }
};

$("btn-fork").onclick = async () => {
  if (!activeId || busy) return;
  const name = prompt("分身的名字：");
  if (!name) return;
  const p = await api(`/api/pets/${activeId}/fork`, { method: "POST", body: JSON.stringify({ name }) });
  await loadSlots();
  await selectPet(p.pet_id);
};

$("btn-delete").onclick = async () => {
  if (!activeId) return;
  if (!confirm("放归这只猫？它的记忆张量将被删除，无法找回。")) return;
  await api(`/api/pets/${activeId}`, { method: "DELETE" });
  activeId = null;
  renderEmptyStage();
  $("diary-list").innerHTML = "";
  await loadSlots();
};

/* ---------- 存档导出 / 导入（把猫送给朋友） ---------- */
$("btn-export").onclick = () => {
  if (activeId) window.open(`/api/pets/${activeId}/save`, "_blank");
};
$("btn-import").onclick = () => $("import-file").click();
$("import-file").onchange = async (ev) => {
  const f = ev.target.files[0];
  if (!f) return;
  try {
    const res = await fetch("/api/pets/import", { method: "POST", body: await f.arrayBuffer() });
    if (!res.ok) throw new Error((await res.json()).detail || "导入失败");
    const p = await res.json();
    ev.target.value = "";
    await loadSlots();
    await selectPet(p.pet_id);
  } catch (e) { alert(e.message); ev.target.value = ""; }
};

/* ---------- 事件绑定 ---------- */
for (const btn of document.querySelectorAll("#actions button")) {
  btn.onclick = () => interact(btn.dataset.act);
}
$("chat-row").onsubmit = (ev) => {
  ev.preventDefault();
  const el = $("chat-input");
  const text = el.value.trim();
  if (!text) return;
  el.value = "";
  interact("chat", text);
};

/* ---------- theme（与 stateswap 同款） ---------- */
function applyThemeIcon() {
  const dark = document.documentElement.dataset.theme === "dark";
  $("btn-theme").textContent = dark ? "☀️" : "🌙";
}
$("btn-theme").onclick = () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("memopet-theme", next);
  applyThemeIcon();
};
applyThemeIcon();

/* ---------- 启动 ---------- */
(async () => {
  for (let i = 0; i < 60; i++) {
    try {
      const h = await fetch("/health").then((r) => r.json());
      if (h.ready) { setStatus(true, "服务正常"); break; }
      setStatus(false, "大脑加载中…");
    } catch { setStatus(false, "连接中…"); }
    await new Promise((r) => setTimeout(r, 1000));
  }
  await loadPersonas();
  const pets = await loadSlots();
  if (pets.length) await selectPet(pets[0].pet_id);
  else renderEmptyStage();
})();

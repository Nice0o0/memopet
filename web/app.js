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
/* 手绘 SVG 小猫：随心情变表情（开心眯眼 / 正常圆眼 / 难过垂眼），
   项圈用品牌蓝紫色，跨亮暗主题通用。 */
function catSvg(mood) {
  const eyes = mood === "happy"
    ? '<path d="M36 40 q4 -5 8 0" stroke="#4a3520" stroke-width="2.6" fill="none" stroke-linecap="round"/>'
      + '<path d="M52 40 q4 -5 8 0" stroke="#4a3520" stroke-width="2.6" fill="none" stroke-linecap="round"/>'
    : mood === "sad"
    ? '<path d="M36 43 q4 4 8 0" stroke="#4a3520" stroke-width="2.6" fill="none" stroke-linecap="round"/>'
      + '<path d="M52 43 q4 4 8 0" stroke="#4a3520" stroke-width="2.6" fill="none" stroke-linecap="round"/>'
    : '<circle cx="40" cy="40" r="3.1" fill="#4a3520"/><circle cx="56" cy="40" r="3.1" fill="#4a3520"/>';
  const mouth = mood === "happy"
    ? '<path d="M42 50 q6 7 12 0" stroke="#4a3520" stroke-width="2.2" fill="none" stroke-linecap="round"/>'
    : mood === "sad"
    ? '<path d="M44 54 q4 -3.5 8 0" stroke="#4a3520" stroke-width="2.2" fill="none" stroke-linecap="round"/>'
    : '<path d="M44 51 q4 3 8 0" stroke="#4a3520" stroke-width="2.2" fill="none" stroke-linecap="round"/>';
  const ears = mood === "sad"
    ? '<polygon points="29,27 20,10 40,19" fill="#f7b955"/><polygon points="67,27 76,10 56,19" fill="#f7b955"/>'
    : '<polygon points="30,26 24,5 43,17" fill="#f7b955"/><polygon points="66,26 72,5 53,17" fill="#f7b955"/>';
  return `<svg viewBox="0 0 96 96" width="112" height="112" aria-hidden="true">
    <path d="M26 76 q -15 2 -13 -15 q 1 -9 9 -9" stroke="#f0a53e" stroke-width="6" fill="none" stroke-linecap="round"/>
    <ellipse cx="48" cy="72" rx="26" ry="17" fill="#f7b955"/>
    ${ears}
    <polygon points="32.5,23.5 28.5,12 39,19" fill="#f2a0a0" opacity="0.9"/>
    <polygon points="63.5,23.5 67.5,12 57,19" fill="#f2a0a0" opacity="0.9"/>
    <circle cx="48" cy="41" r="24" fill="#f7b955"/>
    <ellipse cx="35" cy="48" rx="4" ry="2.4" fill="#f2a0a0" opacity="0.55"/>
    <ellipse cx="61" cy="48" rx="4" ry="2.4" fill="#f2a0a0" opacity="0.55"/>
    ${eyes}
    <polygon points="45.5,46 50.5,46 48,49" fill="#d16c6c"/>
    ${mouth}
    <g stroke="#c8933a" stroke-width="1.4" stroke-linecap="round" opacity="0.8">
      <line x1="28" y1="45" x2="15" y2="42"/><line x1="28" y1="49" x2="15" y2="50"/>
      <line x1="68" y1="45" x2="81" y2="42"/><line x1="68" y1="49" x2="81" y2="50"/>
    </g>
    <path d="M26 63 q22 10 44 0 l 0 5 q -22 10 -44 0 z" fill="#5b74ff"/>
    <circle cx="48" cy="70.5" r="3.4" fill="#ffd34d" stroke="#c8933a" stroke-width="1"/>
    <line x1="46" y1="70" x2="50" y2="71" stroke="#c8933a" stroke-width="1"/>
  </svg>`;
}

function renderCat(mood) {
  $("pet-emoji").innerHTML = catSvg(mood);
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
  const pets = await loadSlots();
  const p = pets.find((x) => x.pet_id === id);
  if (p) {
    renderPet(p);
    await loadDiary();
  }
}

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

/* ---------- 交互 ---------- */
async function interact(action, text = "") {
  if (!activeId || busy) return;
  busy = true;
  document.querySelectorAll("#actions button, #chat-row button").forEach((b) => (b.disabled = true));
  const bubble = $("bubble");
  bubble.classList.remove("hidden");
  bubble.textContent = "…";
  try {
    const r = await api(`/api/pets/${activeId}/interact`, {
      method: "POST",
      body: JSON.stringify({ action, text }),
    });
    bubble.textContent = r.dream ? `🌙 它刚睡醒，梦到了：${r.dream}\n\n${r.reply}` : r.reply;
    renderPet(r);
    await loadSlots();
    await loadDiary();
  } catch (e) {
    bubble.textContent = `⚠ ${e.message}`;
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
  $("pet-name").textContent = "还没有猫";
  $("pet-meta").textContent = "";
  $("bubble").classList.add("hidden");
  $("diary-list").innerHTML = "";
  await loadSlots();
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
})();

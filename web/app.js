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
function renderPet(p) {
  $("pet-emoji").textContent = p.mood > 0.7 ? "😺" : p.mood < 0.35 ? "😿" : "🐱";
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

"""MemoPet: 一只以 RWKV-7 递归状态为大脑的电子宠物。

核心思想：宠物的一切经历都保存在一个恒定大小（1.5B ≈ 12.8MB）的递归状态
张量里——存档 = 保存张量，分身 = 复制张量，读档 = 加载张量。
KV-cache 模型做不了这个玩具：它的"记忆"随对话长度无限膨胀且绑定 token 位置。

复用 stateswap 的底座加载 / 分词器 / 采样器 / 退化护栏；游戏逻辑独立。
纯逻辑（停轮规则/衰减/人格过滤）在 rules.py，可脱离 GPU 单测。
"""

from __future__ import annotations

import codecs
import random
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import torch
from stateswap.engine import Engine, _unique_4gram_ratio
from stateswap.lowrank import lowrank_reconstruct, svd_truncate
from stateswap.s0 import S0, load_base_model, load_s0_payload, make_cache
from stateswap.tokenizer import load_tokenizer

from .rules import (
    ACTION_LABELS,
    AUTO_SNAPSHOT_HOURS,
    DEGEN_MAX_UQ4,
    DEGEN_MIN_CHARS,
    DREAM_OPENERS,
    DREAM_TOKENS,
    MAX_LOADED,
    MAX_NEW_TOKENS,
    MAX_SNAPSHOTS,
    METER_DELTA,
    REPLAY_EVENTS,
    PetMeta,
    apply_stop,
    backfill_meta,
    decay_meters,
    discover_personas,
    dream_prompt,
    meters_hint,
    trim_diary,
)

_STATE_KEYS = ("recurrent_state", "conv_state", "ffn_state")


@dataclass
class MemoPet:
    meta: PetMeta
    cache: object | None  # fla Cache：递归状态就是这只猫的大脑（None = 已卸载到 CPU）
    diary: list = field(default_factory=list)
    parked: dict | None = None  # {layer_idx: (rec, conv, ffn)} on CPU
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class PetHome:
    """管理模型（单例）与所有宠物的持久状态。"""

    def __init__(self, model_dir: str, vocab: str, pets_dir: str | Path,
                 s0_dir: str | Path | None = None, dream_gap_hours: float = 6.0,
                 device: str = "cuda"):
        self.model = load_base_model(model_dir, device=device)
        self.tok = load_tokenizer(vocab)
        self.device = device
        self.pets_dir = Path(pets_dir)
        self.pets_dir.mkdir(parents=True, exist_ok=True)
        self.births_dir = self.pets_dir / "births"
        self.births_dir.mkdir(exist_ok=True)
        self.snapshots_dir = self.pets_dir / "snapshots"
        self.snapshots_dir.mkdir(exist_ok=True)
        self.dream_gap_sec = max(0.0, dream_gap_hours) * 3600
        self.personas = discover_personas(s0_dir)
        self.pets: dict[str, MemoPet] = {}
        self._loaded: list[str] = []  # GPU 常驻 LRU（设备上的顺序）
        self._lock = threading.Lock()
        for f in sorted(self.pets_dir.glob("*.pt")):
            try:
                self._adopt(f)
            except Exception as e:  # noqa: BLE001
                print(f"[memopet] 跳过损坏存档 {f.name}: {e}")

    # ---------- 状态装载 / 卸载（LRU） ----------

    def _blank_cache(self, s0_path: Path | None = None):
        holder = S0(self.model).to(self.device)
        if s0_path is not None:
            holder.load_stacked(load_s0_payload(torch.load(s0_path, map_location="cpu", weights_only=False)))
        return make_cache(self.model, holder, detach_states=True)

    def _ensure_gpu(self, pet: MemoPet) -> None:
        if pet.cache is not None:
            self._touch(pet.meta.pet_id)
            return
        pet.cache = self._blank_cache()
        for i, (rec, conv, ffn) in (pet.parked or {}).items():
            pet.cache.update(
                recurrent_state=rec.to(self.device),
                conv_state=conv.to(self.device),
                ffn_state=ffn.to(self.device),
                layer_idx=int(i), offset=0,
            )
        pet.parked = None
        self._touch(pet.meta.pet_id)

    def _touch(self, pid: str) -> None:
        with self._lock:
            if pid in self._loaded:
                self._loaded.remove(pid)
            self._loaded.append(pid)
            while len(self._loaded) > MAX_LOADED:
                old = self._loaded.pop(0)
                p = self.pets.get(old)
                if p is None or p.cache is None or old == pid:
                    continue
                if p.lock.acquire(blocking=False):  # 正在交互的猫不卸载
                    try:
                        self._park(p)
                    finally:
                        p.lock.release()

    def _park(self, pet: MemoPet) -> None:
        pet.parked = {
            i: tuple(pet.cache[i][k].to("cpu") for k in _STATE_KEYS)
            for i in range(self.model.config.num_hidden_layers)
        }
        pet.cache = None

    # ---------- 存档 I/O ----------

    def _snapshot(self, pet: MemoPet) -> list:
        self._ensure_gpu(pet)
        return [
            tuple(pet.cache[i][k].to("cpu") for k in _STATE_KEYS)
            for i in range(self.model.config.num_hidden_layers)
        ]

    def _restore(self, pet: MemoPet, snap: list) -> None:
        pet.cache = self._blank_cache()
        for i, (rec, conv, ffn) in enumerate(snap):
            pet.cache.update(
                recurrent_state=rec.to(self.device),
                conv_state=conv.to(self.device),
                ffn_state=ffn.to(self.device),
                layer_idx=i, offset=0,
            )
        pet.parked = None
        self._touch(pet.meta.pet_id)

    def _payload(self, pet: MemoPet) -> dict:
        if pet.cache is not None:
            state = {
                i: tuple(pet.cache[i][k].to("cpu") for k in _STATE_KEYS)
                for i in range(self.model.config.num_hidden_layers)
            }
        else:
            state = pet.parked or {}
        return {"meta": asdict(pet.meta), "diary": trim_diary(pet.diary), "state": state}

    def _save(self, pet: MemoPet) -> None:
        if pet.meta.pet_id not in self.pets:
            return  # 已被放归：交互中删除的猫不回写存档（否则重启后僵尸复活）
        tmp = self.pets_dir / f".{pet.meta.pet_id}.pt.tmp"
        torch.save(self._payload(pet), tmp)
        tmp.replace(self.pets_dir / f"{pet.meta.pet_id}.pt")

    def _adopt(self, path: Path) -> MemoPet:
        payload = torch.load(path, map_location="cpu", weights_only=False)
        meta = backfill_meta(payload["meta"])
        pet = MemoPet(meta=meta, cache=None, diary=payload["diary"], parked=payload["state"])
        self.pets[meta.pet_id] = pet
        return pet

    # ---------- 生命周期 ----------

    def create(self, name: str, persona_id: str = "none") -> dict:
        name = name.strip()[:16]
        if not name:
            raise ValueError("宠物需要名字")
        s0_path = self.personas.get(persona_id)
        if persona_id != "none" and s0_path is None:
            raise ValueError(f"unknown persona {persona_id}")
        meta = PetMeta(pet_id=uuid.uuid4().hex[:10], name=name, born_at=time.time(),
                       persona_id=persona_id, last_seen=time.time())
        pet = MemoPet(meta=meta, cache=self._blank_cache(s0_path))
        with self._lock:
            if len(self.pets) >= 30:
                raise ValueError("猫窝满了（最多 30 只）——先放归几只吧")
            self.pets[meta.pet_id] = pet  # 先占位：创世生成需数秒，否则并发领养可越过上限
        # 创世预填：把"它是谁"写进状态——这段经历永远在它脑子里
        origin = "带着一段与生俱来的性格（烘焙好的初始状态）" if s0_path is not None else "作为一张白纸"
        genesis = (
            f"你是一只电子小猫，名字叫「{name}」，{origin}。你的记忆保存在一个递归状态张量里，"
            f"主人做的每一件事都会写进你的脑子，慢慢塑造你的性格。\n"
            f"今天是你们相遇的第一天，主人把你从屏幕里领了出来。\n\n"
            f"User: （你睁开了眼睛，第一次看到了主人）你好呀，小家伙。\n\nAssistant: "
        )
        try:
            ids = self.tok.encode(genesis)
            with torch.no_grad():
                out = self.model(
                    input_ids=torch.tensor([ids], device=self.device),
                    past_key_values=pet.cache, use_cache=True,
                )
            reply = self._generate(pet, out, prompt_ids=ids)
        except Exception:
            with self._lock:
                self.pets.pop(meta.pet_id, None)  # 创世失败：让出名额
            raise
        pet.diary.append({"t": time.time(), "label": "出生：被主人领回家", "reply": reply})
        self._save(pet)
        self._save_birth(pet)  # 出生大脑（rank-4 压缩，~1.6MB）供"成长档案"对比
        return self.describe(pet)

    def _save_birth(self, pet: MemoPet) -> None:
        self._ensure_gpu(pet)
        cur = torch.stack([pet.cache[i]["recurrent_state"][0] for i in range(self.model.config.num_hidden_layers)])
        payload = svd_truncate(cur.float(), 4)
        payload["meta"] = {"pet_id": pet.meta.pet_id, "persona": pet.meta.persona_id}
        torch.save(payload, self.births_dir / f"{pet.meta.pet_id}.rank4.pt")

    def growth(self, pet_id: str) -> dict:
        """成长档案：当前大脑 vs 出生大脑的逐层余弦——"这只猫被你养成了什么样"。"""
        pet = self.get(pet_id)
        birth_path = self.births_dir / f"{pet.meta.pet_id}.rank4.pt"
        if not birth_path.exists():
            return {"layers": [], "mean_cos": None, "note": "出生大脑未记录"}
        birth = lowrank_reconstruct(torch.load(birth_path, map_location="cpu", weights_only=False))
        with pet.lock:
            snap = self._snapshot(pet)
            cur = torch.stack([rec[0].float() for rec, _, _ in snap])
        layers = []
        for i in range(cur.shape[0]):
            x = cur[i].reshape(cur.shape[1], -1)
            y = birth[i].float().reshape(birth.shape[1], -1)
            cos = torch.nn.functional.cosine_similarity(x, y, dim=-1).mean().item()
            layers.append({"i": i, "cos": round(cos, 4)})
        mean_cos = round(sum(layer["cos"] for layer in layers) / len(layers), 4)
        return {"layers": layers, "mean_cos": mean_cos}

    def fork(self, pet_id: str, new_name: str) -> dict:
        src = self.get(pet_id)
        meta = PetMeta(
            pet_id=uuid.uuid4().hex[:10],
            name=(new_name.strip() or src.meta.name + "的分身")[:16],
            born_at=time.time(),
            hunger=src.meta.hunger, mood=src.meta.mood,
            persona_id=src.meta.persona_id, dreams=src.meta.dreams,
            last_seen=time.time(),
        )
        pet = MemoPet(meta=meta, cache=self._blank_cache(), diary=list(src.diary))
        with src.lock:  # 快照必须拿源宠物的锁，防止拷到正在交互中的一半状态
            src_snap = self._snapshot(src)
        self._restore(pet, src_snap)  # 大脑 = 源宠物此刻状态的完整拷贝
        with self._lock:
            self.pets[meta.pet_id] = pet
        self._save(pet)
        self._save_birth(pet)  # 分身的"出生"= 此刻，成长档案从 0 开始
        return self.describe(pet)

    def delete(self, pet_id: str) -> bool:
        with self._lock:
            existed = self.pets.pop(pet_id, None) is not None
            if pet_id in self._loaded:
                self._loaded.remove(pet_id)
        (self.pets_dir / f"{pet_id}.pt").unlink(missing_ok=True)
        (self.births_dir / f"{pet_id}.rank4.pt").unlink(missing_ok=True)
        snap_dir = self.snapshots_dir / pet_id
        if snap_dir.exists():
            for f in snap_dir.glob("*.pt"):
                f.unlink(missing_ok=True)
        return existed

    def get(self, pet_id: str) -> MemoPet:
        pet = self.pets.get(pet_id)
        if pet is None:
            raise KeyError(f"unknown pet {pet_id}")
        return pet

    def describe(self, pet: MemoPet) -> dict:
        m = pet.meta
        return {
            "pet_id": m.pet_id,
            "name": m.name,
            "age_days": int((time.time() - m.born_at) // 86400),
            "interactions": m.interactions,
            "hunger": round(m.hunger, 2),
            "mood": round(m.mood, 2),
            "diary_len": len(pet.diary),
            "persona_id": m.persona_id,
            "dreams": m.dreams,
        }

    def list(self) -> list[dict]:
        with self._lock:  # 并发 create/delete 时无锁迭代会 RuntimeError
            pets = list(self.pets.values())
        return [self.describe(p) for p in pets]

    # ---------- 自动存档 / 时光倒流 ----------

    def _write_snapshot(self, pet: MemoPet) -> None:
        d = self.snapshots_dir / pet.meta.pet_id
        d.mkdir(exist_ok=True)
        ts = int(time.time())
        torch.save(self._payload(pet), d / f"{ts}.pt")
        files = sorted(d.glob("*.pt"))
        for f in files[:-MAX_SNAPSHOTS]:
            f.unlink(missing_ok=True)

    def snapshots(self, pet_id: str) -> list[dict]:
        self.get(pet_id)
        d = self.snapshots_dir / pet_id
        if not d.exists():
            return []
        return [
            {"ts": int(f.stem), "when": time.strftime("%m-%d %H:%M", time.localtime(int(f.stem)))}
            for f in sorted(d.glob("*.pt"), reverse=True)
        ]

    def restore_snapshot(self, pet_id: str, ts: int) -> dict:
        pet = self.get(pet_id)
        path = self.snapshots_dir / pet_id / f"{ts}.pt"
        if not path.exists():
            raise KeyError(f"unknown snapshot {ts}")
        payload = torch.load(path, map_location="cpu", weights_only=False)
        with pet.lock:
            pet.meta = backfill_meta(payload["meta"])
            pet.diary = payload["diary"]
            pet.parked = payload["state"]
            pet.cache = None
            self._save(pet)
        return self.describe(pet)

    # ---------- 交互 ----------

    def _gen_deltas(self, pet: MemoPet, out, prompt_ids: list[int],
                    max_tokens: int = MAX_NEW_TOKENS):
        """逐 token 采样并 yield 增量文本；停轮条件走 rules.apply_stop，
        停止前不再把 token 喂回状态。截断发生在增量产生之后。"""
        inc = codecs.getincrementaldecoder("utf-8")(errors="replace")
        text, recent = "", list(prompt_ids)
        with torch.no_grad():
            for _ in range(max_tokens):
                nxt = Engine._sample(None, out.logits[0, -1], 0.8, 0.8, recent, 1.25, 8)
                recent.append(nxt)
                new_text, stop = apply_stop(text + inc.decode(self.tok.id_to_bytes[nxt]))
                if stop:
                    if len(new_text) > len(text):
                        yield new_text[len(text):]
                    return
                out = self.model(
                    input_ids=torch.tensor([[nxt]], device=self.device),
                    past_key_values=pet.cache, use_cache=True,
                )
                if new_text != text:
                    yield new_text[len(text):]
                    text = new_text

    def _generate(self, pet: MemoPet, out, prompt_ids: list[int],
                  max_tokens: int = MAX_NEW_TOKENS) -> str:
        return "".join(self._gen_deltas(pet, out, prompt_ids, max_tokens))

    def _dream(self, pet: MemoPet, gap_hours: float) -> str | None:
        """睡了一觉回来先做梦：梦里是当前状态生成的碎片，随后成为真实记忆
        （生成过程本身写进状态）。梦的内容随饥饿/心情/离开时长变化。
        退化则回滚跳过——梦可以怪，不能复读。"""
        snap = self._snapshot(pet)
        prompt = dream_prompt(pet.diary, pet.meta, gap_hours, random.choice(DREAM_OPENERS))
        ids = self.tok.encode(prompt)
        with torch.no_grad():
            out = self.model(
                input_ids=torch.tensor([ids], device=self.device),
                past_key_values=pet.cache, use_cache=True,
            )
        dream = self._generate(pet, out, prompt_ids=ids, max_tokens=DREAM_TOKENS)
        if len(dream) >= DEGEN_MIN_CHARS and _unique_4gram_ratio(dream) < DEGEN_MAX_UQ4:
            self._restore(pet, snap)
            return None
        pet.meta.dreams += 1
        pet.diary.append({"t": time.time(), "label": "做了一个梦", "reply": dream})
        self._save(pet)
        return dream

    def interact(self, pet_id: str, action: str, text: str = "") -> dict:
        last = None
        for chunk in self.interact_stream(pet_id, action, text):
            last = chunk
        return last

    def interact_stream(self, pet_id: str, action: str, text: str = ""):
        """流式交互：先 yield {"dream"}（若有），再逐字 yield {"delta"}，
        最终帧带 {"reply", "degenerated", **describe}。退化时已流出的文本
        由最终帧的替换文案覆盖（状态已回滚）。"""
        pet = self.get(pet_id)
        with pet.lock:
            self._ensure_gpu(pet)
            now = time.time()
            prev_seen = pet.meta.last_seen
            gap_hours = max(0.0, now - prev_seen) / 3600 if prev_seen else 0.0
            # 睡了一觉（间隔超过梦阈值）→ 醒来先做梦，梦写进状态与日记
            dream = None
            if (prev_seen > 0 and pet.meta.interactions >= 1
                    and now - prev_seen >= self.dream_gap_sec):
                dream = self._dream(pet, gap_hours)
            pet.meta.last_seen = now
            # 时间流逝的代价：不喂自然会饿、心情回归中位（作用于动作加成之前）
            decay_meters(pet.meta, gap_hours)
            if dream:
                yield {"dream": dream}
            snap = self._snapshot(pet)  # 退化护栏：本轮开始前的大脑快照
            if action == "chat":
                user_text = (text or "").strip()[:200] or "（沉默地看着你）"
                label = f"主人说：{user_text[:40]}"
            elif action in ACTION_LABELS:
                user_text = ACTION_LABELS[action] + "。"
                label = ACTION_LABELS[action]
            else:
                raise ValueError(f"unknown action {action}")
            parts = []
            if pet.diary:
                lines = "".join(f"- {e['label']}\n" for e in pet.diary[-REPLAY_EVENTS:])
                parts.append(f"（最近的相处回忆：\n{lines}）\n")
            parts.append(meters_hint(pet.meta) + "\n")
            parts.append(user_text)
            prompt = "User: " + "".join(parts) + "\n\nAssistant: "
            ids = self.tok.encode(prompt)
            with torch.no_grad():
                out = self.model(
                    input_ids=torch.tensor([ids], device=self.device),
                    past_key_values=pet.cache, use_cache=True,
                )
            reply = ""
            for delta in self._gen_deltas(pet, out, ids):
                reply += delta
                yield {"delta": delta}
            degenerated = (
                len(reply) >= DEGEN_MIN_CHARS
                and _unique_4gram_ratio(reply) < DEGEN_MAX_UQ4
            )
            if degenerated:
                self._restore(pet, snap)  # 毒化内容不进长期记忆
                yield {
                    "reply": "（它好像走神了，咕噜咕噜说了一串听不懂的话…再试试？）",
                    "degenerated": True, "dream": dream, **self.describe(pet),
                }
                return
            for k, dv in METER_DELTA.get(action, {}).items():
                setattr(pet.meta, k, min(1.0, max(0.0, getattr(pet.meta, k) + dv)))
            pet.meta.interactions += 1
            pet.diary.append({"t": time.time(), "label": label, "reply": reply})
            # 自动存档：超过间隔写一份快照，保留最近 MAX_SNAPSHOTS 份
            if now - pet.meta.last_snapshot >= AUTO_SNAPSHOT_HOURS * 3600:
                pet.meta.last_snapshot = now
                self._save(pet)
                self._write_snapshot(pet)
            else:
                self._save(pet)
            yield {"reply": reply, "degenerated": False, "dream": dream, **self.describe(pet)}

    def import_save(self, content: bytes) -> dict:
        """导入存档（把朋友送的猫接回家）。注意 torch.load(weights_only=False)
        有反序列化风险——只导入可信来源的存档（本地玩具项目，README 已注明）。"""
        import io

        payload = torch.load(io.BytesIO(content), map_location="cpu", weights_only=False)
        meta = backfill_meta(payload["meta"])  # 缺字段即格式不符，抛异常
        if meta.pet_id in self.pets:  # 与在住猫撞号：换新 id 入住，不覆盖原猫
            meta.pet_id = uuid.uuid4().hex[:10]
            payload["meta"]["pet_id"] = meta.pet_id
        path = self.pets_dir / f"{meta.pet_id}.pt"
        torch.save(payload, path)
        try:
            return self.describe(self._adopt(path))
        except Exception:
            path.unlink(missing_ok=True)  # 坏存档不留孤儿文件（否则每次启动都报一次跳过）
            raise

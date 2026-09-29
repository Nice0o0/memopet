"""MemoPet: 一只以 RWKV-7 递归状态为大脑的电子宠物。

核心思想：宠物的一切经历都保存在一个恒定大小（1.5B ≈ 12.8MB）的递归状态
张量里——存档 = 保存张量，分身 = 复制张量，读档 = 加载张量。
KV-cache 模型做不了这个玩具：它的"记忆"随对话长度无限膨胀且绑定 token 位置。

复用 stateswap 的底座加载 / 分词器 / 采样器 / 退化护栏；游戏逻辑独立。
"""

from __future__ import annotations

import codecs
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import torch
from stateswap.engine import Engine, _unique_4gram_ratio
from stateswap.s0 import S0, load_base_model, make_cache
from stateswap.tokenizer import load_tokenizer

MAX_NEW_TOKENS = 96
REPLAY_EVENTS = 3  # 近事以可见文本重放（1.5B 状态事实保持弱，stateswap 工程结论）
DEGEN_MIN_CHARS = 120
DEGEN_MAX_UQ4 = 0.72

ACTION_LABELS = {
    "feed": "主人往你碗里倒了一把小鱼干",
    "play": "主人拿出逗猫棒，在空中晃来晃去逗你",
    "pet": "主人轻轻摸了摸你的头和下巴",
    "scold": "主人板着脸，皱着眉责骂了你",
}
METER_DELTA = {
    "feed": {"hunger": +0.25, "mood": +0.05},
    "play": {"hunger": -0.05, "mood": +0.20},
    "pet": {"mood": +0.15},
    "scold": {"mood": -0.25},
    "chat": {"mood": +0.03},
}


@dataclass
class PetMeta:
    pet_id: str
    name: str
    born_at: float
    interactions: int = 0
    hunger: float = 0.55  # 0~1，越高越饱
    mood: float = 0.55


@dataclass
class MemoPet:
    meta: PetMeta
    cache: object  # fla Cache：递归状态就是这只猫的大脑
    diary: list = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


def _meters_hint(meta: PetMeta) -> str:
    def word(v: float, low: str, high: str) -> str:
        return low if v < 0.35 else (high if v > 0.7 else "还行")

    return f"（你现在的身体感受：肚子{word(meta.hunger, '很饿', '很饱')}，心情{word(meta.mood, '低落', '很好')}）"


class PetHome:
    """管理模型（单例）与所有宠物的持久状态。"""

    def __init__(self, model_dir: str, vocab: str, pets_dir: str | Path, device: str = "cuda"):
        self.model = load_base_model(model_dir, device=device)
        self.tok = load_tokenizer(vocab)
        self.device = device
        self.pets_dir = Path(pets_dir)
        self.pets_dir.mkdir(parents=True, exist_ok=True)
        self.pets: dict[str, MemoPet] = {}
        self._lock = threading.Lock()
        for f in sorted(self.pets_dir.glob("*.pt")):
            try:
                self._adopt(f)
            except Exception as e:  # noqa: BLE001
                print(f"[memopet] 跳过损坏存档 {f.name}: {e}")

    # ---------- 存档 I/O ----------

    def _blank_cache(self):
        holder = S0(self.model).to(self.device)  # 全零 S0 = 冷启动
        return make_cache(self.model, holder, detach_states=True)

    def _snapshot(self, pet: MemoPet) -> list:
        keys = ("recurrent_state", "conv_state", "ffn_state")
        return [
            tuple(pet.cache[i][k].to("cpu") for k in keys)
            for i in range(self.model.config.num_hidden_layers)
        ]

    def _restore(self, pet: MemoPet, snap: list) -> None:
        for i, (rec, conv, ffn) in enumerate(snap):
            pet.cache.update(
                recurrent_state=rec.to(self.device),
                conv_state=conv.to(self.device),
                ffn_state=ffn.to(self.device),
                layer_idx=i, offset=0,
            )

    def _save(self, pet: MemoPet) -> None:
        keys = ("recurrent_state", "conv_state", "ffn_state")
        state = {
            i: tuple(pet.cache[i][k].to("cpu") for k in keys)
            for i in range(self.model.config.num_hidden_layers)
        }
        payload = {"meta": asdict(pet.meta), "diary": pet.diary, "state": state}
        tmp = self.pets_dir / f".{pet.meta.pet_id}.pt.tmp"
        torch.save(payload, tmp)
        tmp.replace(self.pets_dir / f"{pet.meta.pet_id}.pt")

    def _adopt(self, path: Path) -> MemoPet:
        payload = torch.load(path, map_location="cpu", weights_only=False)
        meta = PetMeta(**payload["meta"])
        pet = MemoPet(meta=meta, cache=self._blank_cache(), diary=payload["diary"])
        for i, (rec, conv, ffn) in payload["state"].items():
            pet.cache.update(
                recurrent_state=rec.to(self.device),
                conv_state=conv.to(self.device),
                ffn_state=ffn.to(self.device),
                layer_idx=int(i), offset=0,
            )
        self.pets[meta.pet_id] = pet
        return pet

    # ---------- 生命周期 ----------

    def create(self, name: str) -> dict:
        name = name.strip()[:16]
        if not name:
            raise ValueError("宠物需要名字")
        meta = PetMeta(pet_id=uuid.uuid4().hex[:10], name=name, born_at=time.time())
        pet = MemoPet(meta=meta, cache=self._blank_cache())
        # 创世预填：把"它是谁"写进状态——这段经历永远在它脑子里
        genesis = (
            f"你是一只电子小猫，名字叫「{name}」。你的记忆保存在一个递归状态张量里，"
            f"主人做的每一件事都会写进你的脑子，慢慢塑造你的性格。\n"
            f"今天是你们相遇的第一天，主人把你从屏幕里领了出来。\n\n"
            f"User: （你睁开了眼睛，第一次看到了主人）你好呀，小家伙。\n\nAssistant: "
        )
        ids = self.tok.encode(genesis)
        with torch.no_grad():
            out = self.model(
                input_ids=torch.tensor([ids], device=self.device),
                past_key_values=pet.cache, use_cache=True,
            )
        reply, _ = self._generate(pet, out, prompt_ids=ids)
        pet.diary.append({"t": time.time(), "label": "出生：被主人领回家", "reply": reply})
        with self._lock:
            self.pets[meta.pet_id] = pet
        self._save(pet)
        return self.describe(pet)

    def fork(self, pet_id: str, new_name: str) -> dict:
        src = self.get(pet_id)
        meta = PetMeta(
            pet_id=uuid.uuid4().hex[:10],
            name=(new_name.strip() or src.meta.name + "的分身")[:16],
            born_at=time.time(),
            hunger=src.meta.hunger, mood=src.meta.mood,
        )
        pet = MemoPet(meta=meta, cache=self._blank_cache(), diary=list(src.diary))
        self._restore(pet, self._snapshot(src))  # 大脑 = 源宠物此刻状态的完整拷贝
        with self._lock:
            self.pets[meta.pet_id] = pet
        self._save(pet)
        return self.describe(pet)

    def delete(self, pet_id: str) -> bool:
        with self._lock:
            existed = self.pets.pop(pet_id, None) is not None
        (self.pets_dir / f"{pet_id}.pt").unlink(missing_ok=True)
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
        }

    def list(self) -> list[dict]:
        return [self.describe(p) for p in self.pets.values()]

    # ---------- 交互 ----------

    def _generate(self, pet: MemoPet, out, prompt_ids: list[int]) -> tuple[str, bool]:
        """逐 token 采样（复用 stateswap 采样器），停轮条件与 stateswap 对齐：
        \\n\\n 或幻觉出的下一轮 "User:"；停止前不再把 token 喂回状态。"""
        inc = codecs.getincrementaldecoder("utf-8")(errors="replace")
        text, recent = "", list(prompt_ids)
        with torch.no_grad():
            for _ in range(MAX_NEW_TOKENS):
                nxt = Engine._sample(None, out.logits[0, -1], 0.8, 0.8, recent, 1.25, 8)
                recent.append(nxt)
                delta = inc.decode(self.tok.id_to_bytes[nxt])
                text += delta
                stop = False
                if "\n\n" in text:
                    text = text.split("\n\n")[0]
                    stop = True
                elif "User:" in text:
                    # 模型没按格式另起一行就开始幻觉"下一轮"：就地截断
                    text = text.split("User:")[0]
                    stop = True
                elif text.endswith("User"):
                    # 停止符的前缀 token：不再喂回状态
                    text = text[: -len("User")]
                    stop = True
                if stop:
                    return text, False
                out = self.model(
                    input_ids=torch.tensor([[nxt]], device=self.device),
                    past_key_values=pet.cache, use_cache=True,
                )
        return text, False

    def interact(self, pet_id: str, action: str, text: str = "") -> dict:
        pet = self.get(pet_id)
        with pet.lock:
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
            parts.append(_meters_hint(pet.meta) + "\n")
            parts.append(user_text)
            prompt = "User: " + "".join(parts) + "\n\nAssistant: "
            ids = self.tok.encode(prompt)
            with torch.no_grad():
                out = self.model(
                    input_ids=torch.tensor([ids], device=self.device),
                    past_key_values=pet.cache, use_cache=True,
                )
            reply, _ = self._generate(pet, out, prompt_ids=ids)
            degenerated = (
                len(reply) >= DEGEN_MIN_CHARS
                and _unique_4gram_ratio(reply) < DEGEN_MAX_UQ4
            )
            if degenerated:
                self._restore(pet, snap)  # 毒化内容不进长期记忆
                return {
                    "reply": "（它好像走神了，咕噜咕噜说了一串听不懂的话…再试试？）",
                    "degenerated": True, **self.describe(pet),
                }
            for k, dv in METER_DELTA.get(action, {}).items():
                setattr(pet.meta, k, min(1.0, max(0.0, getattr(pet.meta, k) + dv)))
            pet.meta.interactions += 1
            pet.diary.append({"t": time.time(), "label": label, "reply": reply})
            self._save(pet)
            return {"reply": reply, "degenerated": False, **self.describe(pet)}

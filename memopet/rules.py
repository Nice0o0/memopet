"""纯逻辑：不依赖 torch / stateswap，可脱离 GPU 单测（CI 只装 ruff+pytest）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MAX_NEW_TOKENS = 96
DREAM_TOKENS = 64
REPLAY_EVENTS = 3  # 近事以可见文本重放（1.5B 状态事实保持弱，stateswap 工程结论）
DEGEN_MIN_CHARS = 120
DEGEN_MAX_UQ4 = 0.72
DIARY_MAX = 500  # 日记上限：存档与 /diary 端点都随此封顶
DECAY_HUNGER_PER_HOUR = 0.02  # 时间流逝的代价：不喂自然会饿
DECAY_MOOD_DRIFT_PER_HOUR = 0.02  # 心情每小时向中位回归 2%
MAX_LOADED = 8  # GPU 上同时驻留的状态上限，超出按 LRU 卸载到 CPU
AUTO_SNAPSHOT_HOURS = 24  # 自动存档间隔
MAX_SNAPSHOTS = 3  # 每只猫保留的自动存档数

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

DREAM_OPENERS = (
    "（你睡着了。梦里有一些模模糊糊的碎片……）",
    "（你做了一个长长的梦，梦里有些熟悉的气味……）",
    "（你在梦里翻了个身，梦见了……）",
    "（睡梦中，一些画面慢慢浮了上来……）",
)


@dataclass
class PetMeta:
    pet_id: str
    name: str
    born_at: float
    interactions: int = 0
    hunger: float = 0.55  # 0~1，越高越饱
    mood: float = 0.55
    persona_id: str = "none"  # 出生大脑来自哪个 S0（none = 冷启动白纸）
    last_seen: float = 0.0  # 上次互动时间；间隔超过梦阈值则先"做梦"
    dreams: int = 0
    last_snapshot: float = 0.0


def backfill_meta(raw: dict) -> PetMeta:
    """旧存档缺新字段时补默认值；last_seen 缺失回填出生时间（否则永不做梦）。"""
    meta = PetMeta(**raw)
    if meta.last_seen == 0:
        meta.last_seen = meta.born_at
    return meta


def apply_stop(text: str) -> tuple[str, bool]:
    """停轮规则（与 stateswap 对齐）：返回 (截断后文本, 是否停止)。
    \\n\\n 或幻觉出的下一轮 "User:"；结尾部分 "User" 是停止符前缀，剥掉。"""
    if "\n\n" in text:
        return text.split("\n\n")[0], True
    if "User:" in text:
        return text.split("User:")[0], True
    if text.endswith("User"):
        return text[: -len("User")], True
    return text, False


def decay_meters(meta: PetMeta, gap_hours: float) -> None:
    """时间流逝的代价：饿意随小时累积，心情缓慢回归中位——
    不回来玩它，它是真的会饿坏的。"""
    if gap_hours <= 0:
        return
    meta.hunger = max(0.0, meta.hunger - gap_hours * DECAY_HUNGER_PER_HOUR)
    meta.mood += (0.5 - meta.mood) * min(1.0, gap_hours * DECAY_MOOD_DRIFT_PER_HOUR)


def meters_hint(meta: PetMeta) -> str:
    def word(v: float, low: str, high: str) -> str:
        return low if v < 0.35 else (high if v > 0.7 else "还行")

    return f"（你现在的身体感受：肚子{word(meta.hunger, '很饿', '很饱')}，心情{word(meta.mood, '低落', '很好')}）"


def trim_diary(diary: list) -> list:
    return diary[-DIARY_MAX:] if len(diary) > DIARY_MAX else diary


def dream_prompt(diary: list, meta: PetMeta, gap_hours: float, opener: str) -> str:
    """梦的提示词：只取真实相处（不引用上一次的梦，避免梦里套梦），
    并把离开时长/身体状态写进去——梦的内容会随饥饿、心情、离开多久而变化。"""
    real = [e for e in diary if e["label"] != "做了一个梦"]
    lines = "".join(f"- {e['label']}\n" for e in real[-2:])
    days = int(gap_hours // 24)
    slept = f"你睡了大约 {days} 天" if days >= 1 else "你睡了一觉"
    return (
        f"（最近的相处回忆：\n{lines}）\n\n"
        f"User: {opener}\n（{slept}，{meters_hint(meta)[1:-1]}）\n\nAssistant: "
    )


_PERSONA_SKIP = re.compile(r"^(zh2en|mem-|mix-|scaling-)")


def discover_personas(s0_dir: str | Path | None) -> dict[str, Path | None]:
    """可选出生人格：{id: s0 文件路径}，创建宠物时注入初始状态。
    过滤任务/实验人格（zh2en 会把一切翻译成英文；mem-/mix-/scaling- 是研究产物）。"""
    personas: dict[str, Path | None] = {"none": None}
    if s0_dir and Path(s0_dir).exists():
        for f in sorted(Path(s0_dir).glob("*/s0.pt")):
            pid = f.parent.name
            if _PERSONA_SKIP.match(pid):
                continue
            personas[pid] = f
    return personas

"""MemoPet 纯逻辑测试（不依赖 torch / GPU / 模型权重，CI 可跑）。

覆盖：停轮截断规则、时间衰减数学、出生人格过滤、日记封顶、旧存档回填、
梦提示词的内容约束。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memopet.rules import (  # noqa: E402
    DIARY_MAX,
    PetMeta,
    apply_stop,
    backfill_meta,
    decay_meters,
    discover_personas,
    dream_prompt,
    meters_hint,
    trim_diary,
)

# ---------- 停轮截断 ----------

def test_apply_stop_turn_boundary():
    assert apply_stop("喵~好开心\n\nUser: 下一轮") == ("喵~好开心", True)
    assert apply_stop("正常的一句回复") == ("正常的一句回复", False)


def test_apply_stop_hallucinated_user_turn():
    # 模型没换行就幻觉下一轮：就地截断（真实 smoke 测试里抓到的 bug）
    assert apply_stop("就是这样喵User: （主人摸摸头）") == ("就是这样喵", True)


def test_apply_stop_partial_stop_token():
    # 停止符前缀 "User"：剥掉并停止，不喂回状态
    assert apply_stop("说完了User") == ("说完了", True)
    assert apply_stop("说完了User:") == ("说完了", True)


# ---------- 时间衰减 ----------

def test_decay_meters_one_day():
    m = PetMeta(pet_id="t", name="t", born_at=0.0, hunger=1.0, mood=0.0)
    decay_meters(m, 24.0)
    assert abs(m.hunger - 0.52) < 0.01
    assert abs(m.mood - 0.24) < 0.01  # 向中位走完 48% 的路程


def test_decay_meters_clamps_and_noop():
    m = PetMeta(pet_id="t", name="t", born_at=0.0, hunger=1.0, mood=0.0)
    decay_meters(m, 100.0)
    assert m.hunger == 0.0
    before = (m.hunger, m.mood)
    decay_meters(m, 0.0)  # 无间隔不衰减
    assert (m.hunger, m.mood) == before


def test_meters_hint_qualifies_state():
    hungry = PetMeta(pet_id="t", name="t", born_at=0.0, hunger=0.1, mood=0.1)
    happy = PetMeta(pet_id="t", name="t", born_at=0.0, hunger=0.9, mood=0.9)
    assert "很饿" in meters_hint(hungry) and "低落" in meters_hint(hungry)
    assert "很饱" in meters_hint(happy) and "很好" in meters_hint(happy)


# ---------- 出生人格过滤 ----------

def test_discover_personas_filters_task_and_experiment(tmp_path):
    for pid in ("neko-1.5b", "zh2en-1.5b", "mem-100", "mix-a", "scaling-neko-50", "chat-buddy"):
        d = tmp_path / pid
        d.mkdir()
        (d / "s0.pt").write_bytes(b"stub")
    got = set(discover_personas(tmp_path))
    assert got == {"none", "neko-1.5b", "chat-buddy"}
    assert discover_personas(None) == {"none": None}


# ---------- 日记与旧存档 ----------

def test_trim_diary_caps():
    diary = [{"t": i} for i in range(DIARY_MAX + 100)]
    trimmed = trim_diary(diary)
    assert len(trimmed) == DIARY_MAX
    assert trimmed[-1]["t"] == DIARY_MAX + 99


def test_backfill_meta_old_save():
    # 旧存档没有 last_seen/persona_id/dreams：默认值补齐，last_seen 回填出生时间
    raw = {"pet_id": "abc", "name": "年糕", "born_at": 123.0}
    m = backfill_meta(raw)
    assert m.persona_id == "none" and m.dreams == 0
    assert m.last_seen == 123.0


# ---------- 梦提示词 ----------

def test_dream_prompt_excludes_previous_dreams_and_mentions_state():
    meta = PetMeta(pet_id="t", name="t", born_at=0.0, hunger=0.1, mood=0.2)
    diary = [
        {"t": 1, "label": "主人喂了小鱼干", "reply": "喵"},
        {"t": 2, "label": "做了一个梦", "reply": "梦到鱼干山"},
        {"t": 3, "label": "主人摸了摸头", "reply": "呼噜"},
    ]
    prompt = dream_prompt(diary, meta, 50.0, "（你睡着了……）")
    assert "喂了小鱼干" in prompt and "摸了摸头" in prompt
    assert "梦到鱼干山" not in prompt  # 梦里不套梦
    assert "睡了大约 2 天" in prompt
    assert "很饿" in prompt

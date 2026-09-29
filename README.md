# MemoPet 🐱

**一只以 RWKV-7 递归状态为大脑的电子宠物：它的记忆是一个 12.8MB 的张量。**

喂它、陪它玩、骂它——每一段经历都真实地写进它的递归状态里，慢慢塑造它的性格。
存档 = 保存张量，**分身 = 复制张量**（同一只猫的两个平行宇宙从此独立成长），
读档 = 加载张量。KV-cache 模型做不了这个玩具：它的记忆随对话长度无限膨胀且
绑定 token 位置；RWKV 的记忆是恒定大小的，随便存、随便切、随便带走。

## 运行

依赖现成的 RWKV-7 World 权重与 stateswap 库（同一块 GPU 上与 stateswap 服务
共存毫无压力，推理仅需 ~3.5GB 显存）：

```bash
# 复用 stateswap 的 venv（stateswap 需已 editable 安装：pip install -e G:/rwkv）
G:/rwkv/.venv312/Scripts/python.exe -m memopet.server --port 8001
# 打开 http://127.0.0.1:8001 —— 起个名字领养
```

默认权重路径指向 `../rwkv/models/rwkv7-1.5b-world-hf`，可用 `--model/--vocab` 覆盖。

## 它怎么"记事"

- **大脑**：每只猫一个 fla Cache（24 层递归状态），随交互逐字演化，**跨重启持久**
- **创世**：领养时把"它是谁"预填进状态，这段经历永远在
- **近事回放**：最近 3 件事以可见文本拼进 prompt（1.5B 的状态事实保持弱——
  这是 stateswap 项目的实测结论，工程上用有界回放弥补）
- **退化护栏**：每轮交互前快照大脑，回复复读/乱码即回滚，毒化内容不进长期记忆
- **数值面板**：饱食度/心情是游戏层计数器，同时以"身体感受"提示喂给模型

## 架构

```
memopet/pet.py     PetHome：持久状态引擎（创世/交互/存读档/分身/护栏）
memopet/server.py  FastAPI：REST API + 托管零依赖 WebUI
web/               单页前端（猫窝 / 舞台 / 日记本）
pets/<id>.pt       存档 = meta + 日记 + 24 层状态张量（~13MB/只）
```

API：`GET /api/pets` · `POST /api/pets` · `POST /api/pets/{id}/interact`
(feed/play/pet/scold/chat) · `POST /api/pets/{id}/fork` · `DELETE /api/pets/{id}`

## Roadmap

- [ ] 用 stateswap persona factory 烧一只专属性格的 S₀ 宠物（现在靠创世文本 + 经历养成）
- [ ] 梦机制：隔天回来时"它梦到了…"，把时间流逝写进状态
- [ ] 存档导出/导入（把分身送给朋友）
- [ ] 0.4B 档位（手机/核显也能养）

## 致谢

基于 [stateswap](https://github.com/Nice0o0/stateswap)（RWKV-7 S₀ 状态调优与服务栈）、
[flash-linear-attention](https://github.com/fla-org/flash-linear-attention)、
[BlinkDL/RWKV-LM](https://github.com/BlinkDL/RWKV-LM)。

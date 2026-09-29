"""MemoPet 服务：REST API + 零依赖 WebUI。

启动（在仓库根目录）：
    ../rwkv/.venv312/Scripts/python.exe -m memopet.server --port 8001
"""

from __future__ import annotations

import argparse
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]


class InteractRequest(BaseModel):
    action: str  # feed / play / pet / scold / chat
    text: str = ""


class NameRequest(BaseModel):
    name: str


def create_app(model_dir: str, vocab: str, pets_dir: str) -> FastAPI:
    app = FastAPI(title="memopet", version="0.1.0")
    state = {"home": None}

    @app.on_event("startup")
    def _startup():
        from .pet import PetHome

        state["home"] = PetHome(model_dir, vocab, pets_dir)

    @app.get("/health")
    def health():
        return {"ok": True, "ready": state["home"] is not None}

    def _home():
        if state["home"] is None:
            raise HTTPException(503, "engine is still loading")
        return state["home"]

    @app.get("/api/pets")
    def list_pets():
        return {"pets": _home().list()}

    @app.post("/api/pets")
    def create_pet(req: NameRequest = Body(...)):
        try:
            return _home().create(req.name)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/pets/{pet_id}/interact")
    def interact(pet_id: str, req: InteractRequest = Body(...)):
        try:
            return _home().interact(pet_id, req.action, req.text)
        except KeyError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/pets/{pet_id}/diary")
    def diary(pet_id: str):
        pet = _home().get(pet_id)
        return {"diary": pet.diary}

    @app.post("/api/pets/{pet_id}/fork")
    def fork(pet_id: str, req: NameRequest = Body(...)):
        try:
            return _home().fork(pet_id, req.name)
        except KeyError as e:
            raise HTTPException(404, str(e))

    @app.delete("/api/pets/{pet_id}")
    def delete_pet(pet_id: str):
        if not _home().delete(pet_id):
            raise HTTPException(404, f"unknown pet {pet_id}")
        return {"ok": True}

    web_dir = ROOT / "web"
    if web_dir.exists():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    return app


def main():
    ap = argparse.ArgumentParser(description="MemoPet: a pet whose brain is an RWKV state")
    ap.add_argument("--model", default=str(ROOT.parent / "rwkv" / "models" / "rwkv7-1.5b-world-hf"))
    ap.add_argument("--vocab", default=str(ROOT.parent / "rwkv" / "vendor" / "rwkv_vocab_v20230424.txt"))
    ap.add_argument("--pets-dir", default=str(ROOT / "pets"))
    ap.add_argument("--port", type=int, default=8001)
    args = ap.parse_args()

    import uvicorn

    uvicorn.run(create_app(args.model, args.vocab, args.pets_dir),
                host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()

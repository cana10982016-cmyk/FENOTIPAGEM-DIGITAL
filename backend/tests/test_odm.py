"""Montagem pelas fotos: o sistema conversa com um NodeODM de mentira que devolve o ortomosaico e o DSM do exemplo."""
import importlib.util
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="fenotipagem-odm-"))
os.environ.setdefault("ADMIN_EMAIL", "admin@teste.com")
os.environ.setdefault("ADMIN_PASSWORD", "senha-teste")

from fastapi.testclient import TestClient  # noqa: E402

from app import config, odm  # noqa: E402
from app.main import _prepare, app  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("gerar", ROOT / "exemplos" / "gerar_ortomosaico.py")
gerar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gerar)
EX = Path(tempfile.mkdtemp(prefix="odm-exemplo-"))
gerar.gerar(EX)

fake = FastAPI()
TASKS: dict = {}


@fake.get("/info")
def f_info():
    return {"version": "teste", "taskQueueCount": len(TASKS), "maxImages": None}


@fake.post("/task/new/init")
def f_init(name: str = Form(""), options: str = Form("[]")):
    uid = f"t{len(TASKS) + 1}"
    TASKS[uid] = {"name": name, "options": options, "imgs": [], "polls": 0, "committed": False}
    return {"uuid": uid}


@fake.post("/task/new/upload/{uid}")
async def f_upload(uid: str, images: list[UploadFile] = File(...)):
    TASKS[uid]["imgs"] += [i.filename for i in images]
    return {"success": True}


@fake.post("/task/new/commit/{uid}")
def f_commit(uid: str):
    TASKS[uid]["committed"] = True
    return {"uuid": uid}


@fake.get("/task/{uid}/info")
def f_tinfo(uid: str):
    t = TASKS.get(uid)
    if not t:
        return JSONResponse({"error": "not found"}, 404)
    t["polls"] += 1
    done = t["polls"] >= 3
    return {"uuid": uid, "status": {"code": 40 if done else 20}, "progress": 100 if done else 30 * t["polls"], "imagesCount": len(t["imgs"])}


@fake.get("/task/{uid}/download/{asset}")
def f_down(uid: str, asset: str):
    m = {"orthophoto.tif": EX / "ortomosaico_exemplo_cana.tif", "dsm.tif": EX / "dsm_exemplo_cana.tif"}
    return FileResponse(m[asset]) if asset in m else JSONResponse({"error": "no asset"}, 404)


@fake.post("/task/remove")
@fake.post("/task/cancel")
async def f_remove(request: Request):
    return {"success": True}


def _free_port():
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        return so.getsockname()[1]


@pytest.fixture(scope="module")
def client():
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(fake, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(50):
        if srv.started:
            break
        time.sleep(0.1)
    old = config.ODM_URL
    config.ODM_URL = f"http://127.0.0.1:{port}"
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"email": os.environ["ADMIN_EMAIL"], "senha": os.environ["ADMIN_PASSWORD"]})
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c
    config.ODM_URL = old
    srv.should_exit = True


def test_montagem_pelas_fotos(client):
    import app.main as M
    M._ODM_CACHE["t"] = 0
    assert client.get("/api/saude").json()["odm"] is True
    tid = client.post("/api/ensaios", json={"nome": "ODM"}).json()["id"]
    f = client.post(f"/api/ensaios/{tid}/fotos", json={"rotulo": "60 DAP", "data_voo": "2026-10-01", "qualidade": "completo"}).json()
    assert f["status"] == "fotos"
    assert client.post(f"/api/voos/{f['id']}/montar").status_code == 409  # sem fotos ainda
    fotos = [("fotos", (f"DJI_{i:04d}.JPG", b"\xff\xd8 foto falsa", "image/jpeg")) for i in range(26)]
    fotos.append(("fotos", ("leia-me.txt", b"x", "text/plain")))  # ignorado
    for i in range(0, len(fotos), 10):
        r = client.post(f"/api/voos/{f['id']}/fotos", files=fotos[i:i + 10])
        assert r.status_code == 200, r.text
    assert r.json()["odm_fotos"] == 26
    assert client.post(f"/api/voos/{f['id']}/montar").json()["status"] == "montando"
    for _ in range(8):
        odm.step(_prepare)
        v = client.get(f"/api/voos/{f['id']}").json()
        if v["status"] not in ("montando",):
            break
    t = next(iter(TASKS.values()))
    assert t["committed"] and len(t["imgs"]) == 26 and '"dsm"' in t["options"]
    assert v["status"] == "pronto", v["erro"]
    assert v["georref"] and v["dsm_arquivo"] and v["previa_w"] > 0
    assert not odm.fotos_dir(f["id"]).exists()  # fotos apagadas depois de montar


def test_odm_fora_do_ar(client):
    tid = client.post("/api/ensaios", json={"nome": "ODM 2"}).json()["id"]
    f = client.post(f"/api/ensaios/{tid}/fotos", json={"qualidade": "rapido"}).json()
    client.post(f"/api/voos/{f['id']}/fotos", files=[("fotos", (f"a{i}.jpg", b"x", "image/jpeg")) for i in range(6)])
    client.post(f"/api/voos/{f['id']}/montar")
    old = config.ODM_URL
    config.ODM_URL = "http://127.0.0.1:9"  # nada escutando
    try:
        odm.step(_prepare)
    finally:
        config.ODM_URL = old
    v = client.get(f"/api/voos/{f['id']}").json()
    assert v["status"] == "montando" and "não está acessível" in v["erro"]
    assert client.delete(f"/api/voos/{f['id']}").status_code == 200

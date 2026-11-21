"""Fluxo completo: login, ensaio, upload de GeoTIFF sintético, croqui, processamento e estatística."""
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform as warp_transform

TMP = Path(tempfile.mkdtemp(prefix="fenotipagem-teste-"))
os.environ["DATA_DIR"] = str(TMP / "dados")
os.environ["ADMIN_EMAIL"] = "admin@teste.com"
os.environ["ADMIN_PASSWORD"] = "senha-teste"
os.environ["SECRET_KEY"] = "chave-de-teste-com-mais-de-32-caracteres"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

GSD = 0.05
X0, Y0 = 243000.0, 7531000.0  # UTM 22S
ROWS, COLS, PW, PH = 2, 3, 100, 120  # parcelas de 5 m × 6 m (em pixels de 5 cm)
# cobertura verde por parcela (fração) — linha a linha
COVER = [[0.2, 0.5, 0.8], [0.3, 0.6, 0.9]]


def make_tif(path: Path, cover=COVER):
    W, H = COLS * PW + 100, ROWS * PH + 100
    rng = np.random.default_rng(1)
    img = np.zeros((3, H, W), dtype="uint8")
    img[0], img[1], img[2] = 150, 110, 80  # solo
    for r in range(ROWS):
        for c in range(COLS):
            y0, x0 = 50 + r * PH, 50 + c * PW
            block = rng.random((PH, PW)) < cover[r][c]
            for b, v in enumerate((60, 160, 50)):  # planta
                sub = img[b, y0:y0 + PH, x0:x0 + PW]
                sub[block] = v
    with rasterio.open(path, "w", driver="GTiff", width=W, height=H, count=3, dtype="uint8", crs="EPSG:32722",
                       transform=from_origin(X0, Y0, GSD, GSD)) as dst:
        dst.write(img)
    return W, H


def corners_lonlat():
    xs = [X0 + 50 * GSD, X0 + (50 + COLS * PW) * GSD, X0 + (50 + COLS * PW) * GSD, X0 + 50 * GSD]
    ys = [Y0 - 50 * GSD, Y0 - 50 * GSD, Y0 - (50 + ROWS * PH) * GSD, Y0 - (50 + ROWS * PH) * GSD]
    lon, lat = warp_transform("EPSG:32722", "EPSG:4326", xs, ys)
    return [[a, b] for a, b in zip(lon, lat)]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"email": "admin@teste.com", "senha": "senha-teste"})
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c


def test_login_errado():
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"email": "admin@teste.com", "senha": "x"}).status_code == 401
        assert c.get("/api/ensaios").status_code == 401


def test_fluxo_completo(client):
    tif = TMP / "voo1.tif"
    make_tif(tif)
    trts = [{"code": "1", "sigla": "C", "nome": "Controle", "ctrl": True}, {"code": "2", "sigla": "S", "nome": "Suiker"},
            {"code": "3", "sigla": "M", "nome": "Moddus"}]
    r = client.post("/api/ensaios", json={"nome": "Teste", "tratamentos": trts})
    assert r.status_code == 201
    tid = r.json()["id"]

    with tif.open("rb") as fh:
        r = client.post(f"/api/ensaios/{tid}/voos", files={"arquivo": ("voo1.tif", fh, "image/tiff")}, data={"rotulo": "45 DAP"})
    assert r.status_code == 201, r.text
    fid = r.json()["id"]
    f = client.get(f"/api/voos/{fid}").json()
    assert f["status"] == "pronto", f
    assert f["georref"] and abs(f["gsd_m"] - GSD) < 1e-6
    assert client.get(f"/api/voos/{fid}/previa.png").status_code == 200

    croqui = {"kind": "lonlat", "corners": corners_lonlat(), "rows": ROWS, "cols": COLS, "margin": 0, "gx": 2, "gy": 2,
              "cells": [["1A", "2A", "3A"], ["1B", "2B", "3B"]]}
    assert client.put(f"/api/ensaios/{tid}", json={"croqui": croqui}).status_code == 200

    r = client.post(f"/api/ensaios/{tid}/processar")
    assert r.status_code == 200, r.text
    f = client.get(f"/api/voos/{fid}").json()
    assert f["status"] == "processado", f
    res = f["resultados"]
    assert set(res) == {"1A", "2A", "3A", "1B", "2B", "3B"}
    expected = {"1A": 20, "2A": 50, "3A": 80, "1B": 30, "2B": 60, "3B": 90}
    for pid, cc in expected.items():
        assert abs(res[pid]["CC"] - cc) < 3, (pid, res[pid]["CC"])
        assert len(res[pid]["cells"]) == 4
        assert abs(res[pid]["area"] - PW * PH * GSD * GSD) < 1.5  # ~30 m²

    st = client.get(f"/api/ensaios/{tid}/estatistica", params={"voo": fid, "indice": "CC", "alpha": 0.05}).json()
    assert st["delineamento"] == "DBC"
    means = {g["sigla"]: g["media"] for g in st["grupos"]}
    assert means["M"] > means["S"] > means["C"]
    assert st["P"] < 0.05
    ganho = next(g for g in st["grupos"] if g["sigla"] == "M")["ganho"]
    assert abs(ganho - 60) < 4

    assert client.get(f"/api/ensaios/{tid}/parcelas.csv").status_code == 200
    assert client.get(f"/api/ensaios/{tid}/exportar.xlsx").status_code == 200
    gj = client.get(f"/api/ensaios/{tid}/parcelas.geojson").json()
    assert len(gj["features"]) == 6


def test_imagem_sem_georref(client):
    from PIL import Image
    p = TMP / "foto.png"
    arr = np.zeros((200, 300, 3), dtype="uint8")
    arr[:] = (150, 110, 80)
    arr[:, 150:] = (60, 160, 50)
    Image.fromarray(arr).save(p)
    tid = client.post("/api/ensaios", json={"nome": "Foto", "tratamentos": [{"code": "1", "nome": "A", "ctrl": True}, {"code": "2", "nome": "B"}]}).json()["id"]
    with p.open("rb") as fh:
        fid = client.post(f"/api/ensaios/{tid}/voos", files={"arquivo": ("foto.png", fh, "image/png")}).json()["id"]
    croqui = {"kind": "frac", "corners": [[0, 0], [1, 0], [1, 1], [0, 1]], "rows": 1, "cols": 2, "margin": 0, "gx": 1, "gy": 1,
              "cells": [["1A", "2A"]]}
    client.put(f"/api/ensaios/{tid}", json={"croqui": croqui})
    assert client.post(f"/api/ensaios/{tid}/processar").status_code == 200
    res = client.get(f"/api/voos/{fid}").json()["resultados"]
    assert res["1A"]["CC"] < 2 and res["2A"]["CC"] > 98


def test_processar_sem_croqui(client):
    tid = client.post("/api/ensaios", json={"nome": "Vazio"}).json()["id"]
    r = client.post(f"/api/ensaios/{tid}/processar")
    assert r.status_code == 400

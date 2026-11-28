"""Avaliações de campo: TCH/ATR por parcela, TAH calculado, análise e exportação."""
import io
import os
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="fenotipagem-campo-"))
os.environ.setdefault("ADMIN_EMAIL", "admin@teste.com")
os.environ.setdefault("ADMIN_PASSWORD", "senha-teste")

from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from app.main import app  # noqa: E402


def test_avaliacao_de_campo():
    with TestClient(app) as c:
        tok = c.post("/api/auth/login", json={"email": os.environ["ADMIN_EMAIL"], "senha": os.environ["ADMIN_PASSWORD"]}).json()["token"]
        c.headers["Authorization"] = f"Bearer {tok}"
        tid = c.post("/api/ensaios", json={"nome": "Campo"}).json()["id"]
        trts = [{"code": str(i), "sigla": f"T{i}", "nome": "", "ctrl": i == 1} for i in range(1, 5)]
        cells = [[f"{t}{b}" for t in (1, 2, 3, 4)] for b in "ABCD"]
        tch = {1: 90, 2: 100, 3: 104, 4: 96}
        valores = {f"{t}{b}": {"TCH": str(tch[t] + d).replace(".", ","), "ATR": 130 + t}
                   for t in (1, 2, 3, 4) for b, d in zip("ABCD", (-1.5, 0.5, 1.2, -0.4))}
        campo = [{"id": "a1", "rotulo": "Colheita", "data": "2026-06-24", "vars": ["TCH", "ATR"], "valores": valores}]
        r = c.put(f"/api/ensaios/{tid}", json={"tratamentos": trts, "campo": campo,
                                              "croqui": {"kind": "frac", "corners": [[0, 0], [1, 0], [1, 1], [0, 1]], "rows": 4, "cols": 4,
                                                         "margin": 5, "gx": 1, "gy": 1, "cells": cells}})
        assert r.status_code == 200 and r.json()["campo"][0]["rotulo"] == "Colheita"
        A = c.get(f"/api/ensaios/{tid}/estatistica", params={"aval": "a1", "indice": "TCH", "teste": "scottknott"}).json()
        assert A["delineamento"] == "DBC" and A["P"] < 0.01
        m = {g["code"]: g for g in A["grupos"]}
        assert abs(m["3"]["media"] - 103.95) < 1e-9 and abs(m["2"]["ganho"] - 10) < 1e-9
        T = c.get(f"/api/ensaios/{tid}/estatistica", params={"aval": "a1", "indice": "TAH"}).json()
        assert abs({g["code"]: g for g in T["grupos"]}["1"]["media"] - 89.95 * 131 / 1000) < 1e-9
        x = c.get(f"/api/ensaios/{tid}/exportar.xlsx")
        wb = load_workbook(io.BytesIO(x.content))
        assert "Campo (parcelas)" in wb.sheetnames and wb["Campo (parcelas)"].max_row == 17
        assert c.get(f"/api/ensaios/{tid}/estatistica", params={"aval": "zz", "indice": "TCH"}).status_code == 404


def test_correlacao_drone_campo():
    """Correlação entre um voo processado e uma avaliação de campo, por parcela e por tratamento."""
    from types import SimpleNamespace

    from app import main as M

    with TestClient(app) as c:
        tok = c.post("/api/auth/login", json={"email": os.environ["ADMIN_EMAIL"], "senha": os.environ["ADMIN_PASSWORD"]}).json()["token"]
        c.headers["Authorization"] = f"Bearer {tok}"
        trts = [{"code": str(i), "sigla": f"T{i}", "nome": "", "ctrl": i == 1} for i in range(1, 5)]
        cells = [[f"{t}{b}" for t in (1, 2, 3, 4)] for b in "ABCD"]
        tid = c.post("/api/ensaios", json={"nome": "Corr", "tratamentos": trts,
                                           "croqui": {"rows": 4, "cols": 4, "cells": cells, "corners": [[0, 0], [1, 0], [1, 1], [0, 1]]}}).json()["id"]
        cc = {f"{t}{b}": 30 + 5 * t + i for i, (t, b) in enumerate((t, b) for t in (1, 2, 3, 4) for b in "ABCD")}
        with M.SessionLocal() as s:
            f = M.Flight(ensaio_id=tid, rotulo="60 DAP", status="processado",
                         resultados={k: {"CC": v, "ExG": 0.1, "cells": []} for k, v in cc.items()})
            s.add(f)
            s.commit()
            fid = f.id
        campo = [{"id": "h", "rotulo": "Colheita", "vars": ["TCH"], "valores": {k: {"TCH": 2 * v + 10} for k, v in cc.items()}}]
        c.put(f"/api/ensaios/{tid}", json={"campo": campo})
        R = c.get(f"/api/ensaios/{tid}/correlacao", params={"fx": f"v{fid}", "fy": "ch", "vx": "CC", "vy": "TCH"}).json()
        d = R["detalhe"]
        assert d["n"] == 16 and abs(d["r"] - 1) < 1e-9 and abs(d["b"] - 2) < 1e-9
        T = c.get(f"/api/ensaios/{tid}/correlacao", params={"fx": f"v{fid}", "fy": "ch", "nivel": "tratamento"}).json()
        m = {(x["x"], x["y"]): x for x in T["matriz"]}
        assert m[("CC", "TCH")]["n"] == 4 and m[("ExG", "TCH")]["r"] is None  # ExG constante
        _ = SimpleNamespace

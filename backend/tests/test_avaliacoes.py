"""Falhas de plantio, altura pelo DSM, Tukey e bandas multiespectrais com o exemplo sintético de cana."""
import importlib.util
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform as warp_transform

from app import raster, stats
from app.geometry import plots_of

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("gerar", ROOT / "exemplos" / "gerar_ortomosaico.py")
gerar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gerar)

TMP = Path(tempfile.mkdtemp(prefix="fenotipagem-aval-"))
INFO = gerar.gerar(TMP)
TRTS = [{"code": str(i), "sigla": f"T{i}", "nome": "", "ctrl": i == 1} for i in range(1, 7)]


def _croqui():
    xs, ys = zip(*INFO["cantos_utm"])
    lon, lat = warp_transform(INFO["crs"], "EPSG:4326", list(xs), list(ys))
    return {"kind": "lonlat", "corners": [[a, b] for a, b in zip(lon, lat)], "rows": 4, "cols": 6, "margin": 15,
            "gx": 2, "gy": 3, "cells": INFO["layout"]}


def _run(**kw):
    cro = _croqui()
    plots = plots_of(cro, TRTS)
    res = raster.compute_flight(TMP / "ortomosaico_exemplo_cana.tif", cro, plots, 0.05, dsm_path=TMP / "dsm_exemplo_cana.tif",
                                ajustes={"espac_m": 1.5, "falha_min_m": 0.5}, **kw)
    return plots, res


def test_falhas_e_altura():
    plots, res = _run()
    assert len(res) == 24
    for pid, v in res.items():
        t = INFO["verdade"][pid]
        assert abs(v["FALHA"] - t["falha_pct"]) < 3, (pid, v["FALHA"], t["falha_pct"])
        assert abs(v["ALT"] - t["altura_m"]) < 0.2, (pid, v["ALT"], t["altura_m"])
        assert v["n_linhas"] == 4
    a = stats.analyze(plots, res, TRTS, "ALT", 0.05, "tukey")
    assert a["significativo"] and a["HSD"] > a["DMS"]
    best = max(a["grupos"], key=lambda g: g["media"])
    assert best["code"] == "6" and best["letras"].startswith("a")


def test_multiespectral(tmp_path):
    # 5 bandas (azul, verde, vermelho, RedEdge, NIR); planta com NIR alto
    H = W = 200
    img = np.zeros((5, H, W), "uint16")
    img[:] = np.array([800, 900, 1000, 1500, 1600])[:, None, None]
    img[:, :, :100] = np.array([300, 900, 400, 2500, 5000])[:, None, None]
    p = tmp_path / "ms.tif"
    with rasterio.open(p, "w", driver="GTiff", width=W, height=H, count=5, dtype="uint16", crs="EPSG:31983",
                       transform=from_origin(285000, 7480000, 0.05, 0.05)) as d:
        d.write(img)
    cro = {"kind": "frac", "corners": [[0, 0], [1, 0], [1, 1], [0, 1]], "rows": 1, "cols": 2, "margin": 0, "gx": 1, "gy": 1,
           "cells": [["1A", "2A"]]}
    plots = plots_of(cro, TRTS)
    res = raster.compute_flight(p, cro, plots, 0.05, bandas={"b": 1, "g": 2, "r": 3, "re": 4, "nir": 5})
    ndvi_planta = (5000 - 400) / (5000 + 400)
    assert abs(res["1A"]["NDVI"] - ndvi_planta) < 1e-3
    assert abs(res["1A"]["NDRE"] - (5000 - 2500) / 7500) < 1e-3
    assert res["2A"]["NDVI"] < 0.3
    # sem banda azul: cobertura pelo NDVI
    res2 = raster.compute_flight(p, cro, plots, 0.05, bandas={"b": 0, "g": 2, "r": 3, "re": 4, "nir": 5})
    assert res2["1A"]["CC"] > 95 and res2["2A"]["CC"] < 5

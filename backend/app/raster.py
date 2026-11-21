"""Leitura do ortomosaico, pré-visualização e cálculo dos índices RGB.

Os índices são calculados na resolução total do ortomosaico, lendo só a janela de
cada parcela, então arquivos de vários GB não precisam caber na memória.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import Affine
from rasterio.warp import calculate_default_transform, reproject, transform_geom
from rasterio.windows import Window

from .geometry import plot_quad

WGS84 = "EPSG:4326"
DARK = 60  # soma R+G+B (escala 8 bits) abaixo disso é sombra: não conta como planta
OTSU_MIN, OTSU_MAX = 0.02, 0.20

INDICES = {
    "CC": {"nome": "Cobertura vegetal", "unidade": "%", "casas": 1},
    "ExG": {"nome": "Excesso de verde", "unidade": "", "casas": 3},
    "ExGR": {"nome": "ExG − ExR", "unidade": "", "casas": 3},
    "VARI": {"nome": "VARI", "unidade": "", "casas": 3},
    "GLI": {"nome": "GLI", "unidade": "", "casas": 3},
    "NGRDI": {"nome": "NGRDI", "unidade": "", "casas": 3},
    "MGRVI": {"nome": "MGRVI", "unidade": "", "casas": 3},
    "RGBVI": {"nome": "RGBVI", "unidade": "", "casas": 3},
    "ExGveg": {"nome": "ExG da planta", "unidade": "", "casas": 3},
}


class RasterError(Exception):
    pass


# ---------------------------------------------------------------- leitura

def _scale_8bit(src) -> float:
    """Fator para levar a imagem à escala 0-255 (imagens de 16 bits ou float)."""
    if src.dtypes[0] == "uint8":
        return 1.0
    f = max(1, int(max(src.width, src.height) / 1500))
    arr = src.read([1, 2, 3], out_shape=(3, max(1, src.height // f), max(1, src.width // f)), masked=True)
    vals = arr.compressed() if np.ma.isMaskedArray(arr) else arr.ravel()
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return 1.0
    hi = float(np.percentile(vals, 99.5))
    return 255.0 / hi if hi > 0 else 1.0


def inspect(path: str | Path) -> dict:
    with rasterio.open(path) as src:
        if src.count < 3:
            raise RasterError("A imagem precisa ter ao menos 3 bandas (vermelho, verde e azul).")
        geo = src.crs is not None and not src.transform.is_identity
        gsd = None
        if geo:
            rx = abs(src.transform.a)
            if src.crs.is_geographic:
                lat = (src.bounds.top + src.bounds.bottom) / 2
                gsd = rx * 111320 * math.cos(math.radians(lat))
            else:
                gsd = rx * (src.crs.linear_units_factor[1] if src.crs.linear_units_factor else 1.0)
        return {"width": src.width, "height": src.height, "crs": src.crs.to_string() if src.crs else "", "georref": geo, "gsd_m": gsd}


def _rgba_preview_array(src, max_px: int, scale: float):
    """Lê a imagem reduzida (usa as overviews do arquivo, quando houver)."""
    f = max(1.0, max(src.width, src.height) / max_px)
    w, h = max(1, int(src.width / f)), max(1, int(src.height / f))
    rgb = src.read([1, 2, 3], out_shape=(3, h, w), resampling=Resampling.average).astype("float32")
    mask = src.dataset_mask(out_shape=(h, w), resampling=Resampling.nearest)
    rgb = np.clip(np.nan_to_num(rgb * scale), 0, 255).astype("uint8")
    black = rgb.sum(axis=0) == 0
    alpha = np.where((mask > 0) & ~black, 255, 0).astype("uint8")
    transform = src.transform * Affine.scale(src.width / w, src.height / h)
    return np.concatenate([rgb, alpha[None]], axis=0), transform


def make_preview(path: str | Path, out_png: str | Path, max_px: int = 4096) -> dict:
    """Gera um PNG para o mapa. Georreferenciada: reprojetada para lon/lat (EPSG:4326)."""
    with rasterio.open(path) as src:
        scale = _scale_8bit(src)
        arr, tr = _rgba_preview_array(src, max_px, scale)
        geo = src.crs is not None and not src.transform.is_identity
        bounds = None
        if geo:
            h, w = arr.shape[1:]
            dtr, dw, dh = calculate_default_transform(src.crs, WGS84, w, h, *rasterio.transform.array_bounds(h, w, tr))
            out = np.zeros((4, dh, dw), dtype="uint8")
            for b in range(4):
                reproject(arr[b], out[b], src_transform=tr, src_crs=src.crs, dst_transform=dtr, dst_crs=WGS84,
                          resampling=Resampling.nearest if b == 3 else Resampling.bilinear)
            arr = out
            west, north = dtr * (0, 0)
            east, south = dtr * (dw, dh)
            bounds = [west, south, east, north]
        otsu = otsu_exg(arr)
    Image.fromarray(np.moveaxis(arr, 0, -1), "RGBA").save(out_png, optimize=True)
    return {"previa_w": int(arr.shape[2]), "previa_h": int(arr.shape[1]), "limites": bounds, "otsu": otsu}


# ---------------------------------------------------------------- índices

def otsu_exg(rgba: np.ndarray) -> float:
    """Limiar de Otsu sobre o ExG da imagem, limitado a [0,02; 0,20]."""
    r, g, b = (rgba[i].astype("float32") for i in range(3))
    s = r + g + b
    ok = (rgba[3] > 0) & (s >= DARK)
    if ok.sum() < 100:
        return 0.05
    exg = (2 * g[ok] - r[ok] - b[ok]) / s[ok]
    hist, edges = np.histogram(exg, bins=300, range=(-1, 2))
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * centers)
    mt = m0[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        var = w0 * w1 * ((m0 / w0) - (mt - m0) / w1) ** 2
    var = np.nan_to_num(var)
    th = float(centers[int(np.argmax(var))])
    return float(min(OTSU_MAX, max(OTSU_MIN, th)))


def pixel_indices(R: np.ndarray, G: np.ndarray, B: np.ndarray, thr: float) -> dict:
    """Índices médios para um conjunto de pixels válidos (arrays float, escala 0-255)."""
    n = int(R.size)
    if n == 0:
        return {"n": 0}
    s = R + G + B
    with np.errstate(divide="ignore", invalid="ignore"):
        r, g, b = R / s, G / s, B / s
        exg = np.where(s >= DARK, 2 * g - r - b, 0.0)
        exg = np.nan_to_num(exg)
        exr = np.nan_to_num(1.4 * r - g)
        dv = G + R - B
        vari = np.where(dv != 0, np.clip((G - R) / dv, -1, 1), np.nan)
        gli = np.nan_to_num((2 * G - R - B) / (2 * G + R + B))
        ngrdi = np.nan_to_num((G - R) / (G + R))
        mgrvi = np.nan_to_num((G * G - R * R) / (G * G + R * R))
        rgbvi = np.nan_to_num((G * G - B * R) / (G * G + B * R))
    veg = exg > thr
    nveg = int(veg.sum())
    vv = vari[np.isfinite(vari)]
    return {
        "n": n,
        "CC": nveg / n * 100,
        "ExG": float(exg.mean()),
        "ExGR": float((exg - exr).mean()),
        "VARI": float(vv.mean()) if vv.size else None,
        "GLI": float(gli.mean()),
        "NGRDI": float(ngrdi.mean()),
        "MGRVI": float(mgrvi.mean()),
        "RGBVI": float(rgbvi.mean()),
        "ExGveg": float(exg[veg].mean()) if nveg else None,
    }


def _merge(parts: list[dict]) -> dict:
    """Média ponderada pelo nº de pixels (equivale a calcular sobre todos os pixels)."""
    parts = [p for p in parts if p and p.get("n")]
    if not parts:
        return {"n": 0}
    n = sum(p["n"] for p in parts)
    out = {"n": n}
    for k in INDICES:
        if k == "ExGveg":
            w = [(p[k], p["n"] * p["CC"] / 100) for p in parts if p.get(k) is not None]
            tw = sum(x[1] for x in w)
            out[k] = sum(v * wt for v, wt in w) / tw if tw else None
            continue
        w = [(p[k], p["n"]) for p in parts if p.get(k) is not None]
        tw = sum(x[1] for x in w)
        out[k] = sum(v * wt for v, wt in w) / tw if tw else None
    return out


def _to_src_geom(quad, croqui_kind: str, src):
    ring = [list(p) for p in quad] + [list(quad[0])]
    if croqui_kind == "lonlat":
        if src.crs is None:
            raise RasterError("O croqui está em coordenadas, mas esta imagem não é georreferenciada.")
        geom = {"type": "Polygon", "coordinates": [ring]}
        return transform_geom(WGS84, src.crs, geom)
    # fração da imagem -> pixel -> coordenadas do arquivo
    pts = [src.transform * (x * src.width, y * src.height) for x, y in ring]
    return {"type": "Polygon", "coordinates": [[list(p) for p in pts]]}


def compute_flight(path: str | Path, croqui: dict, plots: list, thr: float) -> dict:
    """Calcula os índices de cada parcela e de cada célula da grade."""
    gx, gy = int(croqui.get("gx", 1) or 1), int(croqui.get("gy", 1) or 1)
    kind = croqui.get("kind", "lonlat")
    results: dict = {}
    with rasterio.open(path) as src:
        scale = _scale_8bit(src)
        px_area = None
        if src.crs is not None and not src.crs.is_geographic:
            f = src.crs.linear_units_factor[1] if src.crs.linear_units_factor else 1.0
            px_area = abs(src.transform.a * src.transform.e) * f * f
        for p in plots:
            pgeom = _to_src_geom(plot_quad(croqui, p.r, p.c), kind, src)
            inv = ~src.transform
            pix = [inv * tuple(pt[:2]) for pt in pgeom["coordinates"][0]]
            c0, r0 = math.floor(min(x for x, _ in pix)), math.floor(min(y for _, y in pix))
            c1, r1 = math.ceil(max(x for x, _ in pix)), math.ceil(max(y for _, y in pix))
            c0, r0, c1, r1 = max(0, c0), max(0, r0), min(src.width, c1), min(src.height, r1)
            if c1 <= c0 or r1 <= r0:  # parcela fora da imagem
                continue
            win = Window(c0, r0, c1 - c0, r1 - r0)
            if win.width < 1 or win.height < 1:
                continue
            rgb = src.read([1, 2, 3], window=win).astype("float32") * scale
            valid = src.read_masks(1, window=win) > 0
            valid &= rgb.sum(axis=0) > 0
            wtr = src.window_transform(win)
            cells = []
            for j in range(gy):
                for i in range(gx):
                    cq = plot_quad(croqui, p.r, p.c, i / gx, (i + 1) / gx, j / gy, (j + 1) / gy)
                    cg = _to_src_geom(cq, kind, src)
                    inside = geometry_mask([cg], out_shape=valid.shape, transform=wtr, invert=True, all_touched=False)
                    sel = inside & valid
                    cells.append(pixel_indices(rgb[0][sel], rgb[1][sel], rgb[2][sel], thr))
            tot = _merge(cells)
            if not tot.get("n"):
                continue
            if px_area:
                tot["area"] = tot["n"] * px_area
            tot["cells"] = [c if c.get("n") else None for c in cells]
            results[p.id] = tot
    return results

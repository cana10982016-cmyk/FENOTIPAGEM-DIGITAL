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

from .indices import BANDAS_PADRAO, INDICES, PIXEL_INDICES, RasterError  # noqa: E402,F401

NDVI_VEG = 0.4  # sem banda azul: planta = NDVI acima disso


# ---------------------------------------------------------------- leitura

def _bands(bandas: dict | None) -> dict:
    b = dict(BANDAS_PADRAO)
    b.update({k: int(v or 0) for k, v in (bandas or {}).items() if k in b})
    return b


def _check_bands(src, b: dict) -> None:
    for k in ("r", "g"):
        if not b[k]:
            raise RasterError("Informe as bandas do vermelho e do verde.")
    for k, v in b.items():
        if v and v > src.count:
            raise RasterError(f"A imagem tem {src.count} bandas; a banda {v} indicada não existe.")


def _rgb_ids(b: dict) -> list[int]:
    """Bandas usadas na pré-visualização (sem azul, repete o verde)."""
    return [b["r"], b["g"], b["b"] or b["g"]]


def _scale_8bit(src, ids=(1, 2, 3)) -> float:
    """Fator para levar a imagem à escala 0-255 (imagens de 16 bits ou float). O mesmo fator vale para todas as bandas."""
    if src.dtypes[0] == "uint8":
        return 1.0
    f = max(1, int(max(src.width, src.height) / 1500))
    arr = src.read(list(ids), out_shape=(3, max(1, src.height // f), max(1, src.width // f)), masked=True)
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


def _rgba_preview_array(src, max_px: int, scale: float, ids=(1, 2, 3)):
    """Lê a imagem reduzida (usa as overviews do arquivo, quando houver)."""
    f = max(1.0, max(src.width, src.height) / max_px)
    w, h = max(1, int(src.width / f)), max(1, int(src.height / f))
    rgb = src.read(list(ids), out_shape=(3, h, w), resampling=Resampling.average).astype("float32")
    mask = src.dataset_mask(out_shape=(h, w), resampling=Resampling.nearest)
    rgb = np.clip(np.nan_to_num(rgb * scale), 0, 255).astype("uint8")
    black = rgb.sum(axis=0) == 0
    alpha = np.where((mask > 0) & ~black, 255, 0).astype("uint8")
    transform = src.transform * Affine.scale(src.width / w, src.height / h)
    return np.concatenate([rgb, alpha[None]], axis=0), transform


def make_preview(path: str | Path, out_png: str | Path, max_px: int = 4096, bandas: dict | None = None) -> dict:
    """Gera um PNG para o mapa. Georreferenciada: reprojetada para lon/lat (EPSG:4326)."""
    b = _bands(bandas)
    with rasterio.open(path) as src:
        _check_bands(src, b)
        ids = _rgb_ids(b)
        scale = _scale_8bit(src, ids)
        arr, tr = _rgba_preview_array(src, max_px, scale, ids)
        geo = src.crs is not None and not src.transform.is_identity
        bounds = None
        if geo:
            h, w = arr.shape[1:]
            dtr, dw, dh = calculate_default_transform(src.crs, WGS84, w, h, *rasterio.transform.array_bounds(h, w, tr))
            out = np.zeros((4, dh, dw), dtype="uint8")
            for k in range(4):
                reproject(arr[k], out[k], src_transform=tr, src_crs=src.crs, dst_transform=dtr, dst_crs=WGS84,
                          resampling=Resampling.nearest if k == 3 else Resampling.bilinear)
            arr = out
            west, north = dtr * (0, 0)
            east, south = dtr * (dw, dh)
            bounds = [west, south, east, north]
        otsu = otsu_exg(arr) if b["b"] else None
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


def _nd(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.clip(np.nan_to_num((a - b) / (a + b)), -1, 1)


def veg_mask(R, G, B, thr: float, NIR=None) -> np.ndarray:
    """Pixels de planta: ExG acima do limiar; sem banda azul, NDVI acima de 0,4."""
    if B is None:
        return _nd(NIR, R) > NDVI_VEG if NIR is not None else np.zeros(R.shape, bool)
    s = R + G + B
    with np.errstate(divide="ignore", invalid="ignore"):
        exg = np.nan_to_num((2 * G - R - B) / s)
    return (s >= DARK) & (exg > thr)


def pixel_indices(R: np.ndarray, G: np.ndarray, B, thr: float, RE=None, NIR=None) -> dict:
    """Índices médios para um conjunto de pixels válidos (arrays float, escala 0-255)."""
    n = int(R.size)
    if n == 0:
        return {"n": 0}
    ms = {}
    if NIR is not None:
        ms["NDVI"] = float(_nd(NIR, R).mean())
        ms["GNDVI"] = float(_nd(NIR, G).mean())
        if RE is not None:
            ms["NDRE"] = float(_nd(NIR, RE).mean())
    if B is None:  # câmera sem azul: só índices multiespectrais e cobertura pelo NDVI
        veg = veg_mask(R, G, None, thr, NIR)
        return {"n": n, "CC": float(veg.sum()) / n * 100, **ms}
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
        **ms,
    }


def _merge(parts: list[dict]) -> dict:
    """Média ponderada pelo nº de pixels (equivale a calcular sobre todos os pixels)."""
    parts = [p for p in parts if p and p.get("n")]
    if not parts:
        return {"n": 0}
    n = sum(p["n"] for p in parts)
    out = {"n": n}
    for k in PIXEL_INDICES:
        if k == "ExGveg":
            w = [(p[k], p["n"] * p["CC"] / 100) for p in parts if p.get(k) is not None]
            tw = sum(x[1] for x in w)
            out[k] = sum(v * wt for v, wt in w) / tw if tw else None
            continue
        w = [(p[k], p["n"]) for p in parts if p.get(k) is not None]
        tw = sum(x[1] for x in w)
        if tw:
            out[k] = sum(v * wt for v, wt in w) / tw
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


# ---------------------------------------------------------------- falhas de plantio

def _local_uv(quad_src, X, Y):
    """Coordenadas locais (0 a 1) de cada pixel dentro da parcela, tratando-a como paralelogramo."""
    p0, p1, p3 = np.array(quad_src[0][:2]), np.array(quad_src[1][:2]), np.array(quad_src[3][:2])
    e1, e2 = p1 - p0, p3 - p0
    M = np.array([[e1[0], e2[0]], [e1[1], e2[1]]])
    inv = np.linalg.inv(M)
    dx, dy = X - p0[0], Y - p0[1]
    return inv[0, 0] * dx + inv[0, 1] * dy, inv[1, 0] * dx + inv[1, 1] * dy, float(np.hypot(*e1)), float(np.hypot(*e2))


def gaps(veg: np.ndarray, inside: np.ndarray, u: np.ndarray, v: np.ndarray, width_m: float, length_m: float,
         espac_m: float = 1.5, falha_min_m: float = 0.5, passo_m: float = 0.1) -> dict | None:
    """Falhas na linha de plantio (critério de Stolf: trecho sem planta maior que falha_min_m).

    Acha o sentido das linhas e a posição de cada linha pelo perfil de vegetação, depois
    percorre cada linha em passos de 10 cm e soma os trechos vazios maiores que o mínimo."""
    if inside.sum() < 50 or width_m <= 0 or length_m <= 0:
        return None
    vg, uu, vv = veg[inside].astype("float32"), u[inside], v[inside]
    best = None
    for across, along, A, L in ((uu, vv, width_m, length_m), (vv, uu, length_m, width_m)):
        a_m, l_m = across * A, along * L
        nb = max(4, int(A / 0.05))
        tot = np.bincount(np.clip((a_m / A * nb).astype(int), 0, nb - 1), minlength=nb)
        hit = np.bincount(np.clip((a_m / A * nb).astype(int), 0, nb - 1), weights=vg, minlength=nb)
        prof = np.where(tot > 0, hit / np.maximum(tot, 1), 0)
        var = float(prof.var())
        if best is None or var > best[0]:
            best = (var, a_m, l_m, A, L, prof)
    _, a_m, l_m, A, L, prof = best
    nrows = int(round(A / espac_m))
    if nrows < 1:
        return None
    # fase que coloca as linhas sobre o máximo de vegetação
    bw = A / prof.size
    fases = np.arange(0, espac_m, 0.05)
    score = []
    for ph in fases:
        pos = ph + espac_m * np.arange(nrows + 1)
        pos = pos[pos < A]
        score.append(prof[np.clip((pos / bw).astype(int), 0, prof.size - 1)].sum())
    ph = fases[int(np.argmax(score))]
    centers = ph + espac_m * np.arange(nrows + 1)
    centers = centers[(centers >= 0) & (centers < A)]
    half = min(0.25, espac_m * 0.2)
    nbins = max(1, int(np.ceil(L / passo_m)))
    rows = []
    for c in centers:
        sel = np.abs(a_m - c) < half
        if sel.sum() < 10:
            continue
        idx = np.clip((l_m[sel] / passo_m).astype(int), 0, nbins - 1)
        tot = np.bincount(idx, minlength=nbins)
        hit = np.bincount(idx, weights=vg[sel], minlength=nbins)
        rows.append((float(vg[sel].mean()), tot > 0, (hit / np.maximum(tot, 1)) >= 0.1))
    if not rows:
        return None
    # posições sem cana (carreador ou bordadura dentro do retângulo) não são linhas
    top = max(r[0] for r in rows)
    rows = [r for r in rows if r[0] >= 0.25 * top]
    # o comprimento útil vai da primeira à última planta (descarta carreador nas pontas)
    anyocc = np.any([r[2] for r in rows], axis=0)
    occ_idx = np.flatnonzero(anyocc)
    if occ_idx.size == 0:
        return None
    k0, k1 = int(occ_idx[0]), int(occ_idx[-1]) + 1
    falha, linha = 0.0, 0.0
    for _, has, occ in rows:
        has, occ = has[k0:k1], occ[k0:k1]
        linha += has.sum() * passo_m
        run = 0
        for k in range(has.size):
            if has[k] and not occ[k]:
                run += 1
            else:
                if run * passo_m >= falha_min_m:
                    falha += run * passo_m
                run = 0
        if run * passo_m >= falha_min_m:
            falha += run * passo_m
    centers = rows
    if linha <= 0:
        return None
    return {"FALHA": falha / linha * 100, "falha_m": round(falha, 2), "linha_m": round(linha, 2), "n_linhas": int(len(centers))}


# ---------------------------------------------------------------- altura (modelo digital de superfície)

def plot_height(dsm, geom_wgs_or_src, src_crs) -> dict | None:
    """Altura = percentil 95 menos percentil 5 do DSM dentro da parcela (o solo entre as linhas é a base)."""
    g = geom_wgs_or_src
    if src_crs is not None and dsm.crs is not None and src_crs != dsm.crs:
        g = transform_geom(src_crs, dsm.crs, g)
    inv = ~dsm.transform
    pix = [inv * tuple(pt[:2]) for pt in g["coordinates"][0]]
    c0, r0 = max(0, math.floor(min(x for x, _ in pix))), max(0, math.floor(min(y for _, y in pix)))
    c1, r1 = min(dsm.width, math.ceil(max(x for x, _ in pix))), min(dsm.height, math.ceil(max(y for _, y in pix)))
    if c1 <= c0 or r1 <= r0:
        return None
    win = Window(c0, r0, c1 - c0, r1 - r0)
    z = dsm.read(1, window=win, masked=True).astype("float64")
    inside = geometry_mask([g], out_shape=z.shape, transform=dsm.window_transform(win), invert=True)
    vals = z.filled(np.nan)[inside]
    vals = vals[np.isfinite(vals)]
    if dsm.nodata is not None:
        vals = vals[vals != dsm.nodata]
    if vals.size < 20:
        return None
    p5, p95, p99 = np.percentile(vals, [5, 95, 99])
    return {"ALT": float(p95 - p5), "alt_max": float(p99 - p5)}


# ---------------------------------------------------------------- cálculo do voo

def compute_flight(path: str | Path, croqui: dict, plots: list, thr: float, bandas: dict | None = None,
                   dsm_path: str | Path | None = None, ajustes: dict | None = None) -> dict:
    """Calcula os índices de cada parcela e de cada célula da grade, as falhas e a altura."""
    gx, gy = int(croqui.get("gx", 1) or 1), int(croqui.get("gy", 1) or 1)
    kind = croqui.get("kind", "lonlat")
    aj = ajustes or {}
    espac = float(aj.get("espac_m") or 1.5)
    fmin = float(aj.get("falha_min_m") or 0.5)
    b = _bands(bandas)
    results: dict = {}
    dsm = rasterio.open(dsm_path) if dsm_path and Path(dsm_path).exists() else None
    try:
        with rasterio.open(path) as src:
            _check_bands(src, b)
            ids = [b["r"], b["g"]] + ([b["b"]] if b["b"] else []) + ([b["re"]] if b["re"] else []) + ([b["nir"]] if b["nir"] else [])
            scale = _scale_8bit(src, _rgb_ids(b))
            metric = src.crs is not None and not src.crs.is_geographic
            uf = (src.crs.linear_units_factor[1] if src.crs and src.crs.linear_units_factor else 1.0) if metric else 1.0
            px_area = abs(src.transform.a * src.transform.e) * uf * uf if metric else None
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
                data = src.read(ids, window=win).astype("float32") * scale
                bandmap = dict(zip([k for k in ("r", "g", "b", "re", "nir") if b[k]], data))
                R, G = bandmap["r"], bandmap["g"]
                B, RE, NIR = bandmap.get("b"), bandmap.get("re"), bandmap.get("nir")
                valid = src.read_masks(b["r"], window=win) > 0
                valid &= data.sum(axis=0) > 0
                wtr = src.window_transform(win)
                pick = lambda a, m: None if a is None else a[m]  # noqa: E731
                cells = []
                for j in range(gy):
                    for i in range(gx):
                        cq = plot_quad(croqui, p.r, p.c, i / gx, (i + 1) / gx, j / gy, (j + 1) / gy)
                        cg = _to_src_geom(cq, kind, src)
                        inside = geometry_mask([cg], out_shape=valid.shape, transform=wtr, invert=True, all_touched=False)
                        sel = inside & valid
                        cells.append(pixel_indices(R[sel], G[sel], pick(B, sel), thr, pick(RE, sel), pick(NIR, sel)))
                tot = _merge(cells)
                if not tot.get("n"):
                    continue
                if px_area:
                    tot["area"] = tot["n"] * px_area
                if metric:
                    inside = geometry_mask([pgeom], out_shape=valid.shape, transform=wtr, invert=True) & valid
                    rr, cc = np.mgrid[0:valid.shape[0], 0:valid.shape[1]]
                    X = wtr.a * (cc + .5) + wtr.b * (rr + .5) + wtr.c
                    Y = wtr.d * (cc + .5) + wtr.e * (rr + .5) + wtr.f
                    u, v, wl, ll = _local_uv(pgeom["coordinates"][0], X, Y)
                    gres = gaps(veg_mask(R, G, B, thr, NIR), inside, u, v, wl * uf, ll * uf, espac, fmin)
                    if gres:
                        tot.update(gres)
                if dsm is not None:
                    h = plot_height(dsm, pgeom, src.crs)
                    if h:
                        tot.update(h)
                tot["cells"] = [c if c.get("n") else None for c in cells]
                results[p.id] = tot
    finally:
        if dsm is not None:
            dsm.close()
    return results


def inspect_dsm(path: str | Path) -> dict:
    with rasterio.open(path) as src:
        if src.crs is None or src.transform.is_identity:
            raise RasterError("O modelo de altura (DSM) precisa ser um GeoTIFF georreferenciado.")
        return {"width": src.width, "height": src.height, "crs": src.crs.to_string()}

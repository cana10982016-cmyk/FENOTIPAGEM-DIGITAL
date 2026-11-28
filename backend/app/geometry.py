"""Geometria do croqui: a área das parcelas é um quadrilátero de 4 cantos,
dividido em linhas × colunas. Cada parcela pode ser dividida numa grade.

Os cantos ficam em longitude/latitude (kind="lonlat") quando a imagem é
georreferenciada, ou em fração da imagem (kind="frac", 0 a 1) quando não é.
Ordem dos cantos: superior esquerdo, superior direito, inferior direito, inferior esquerdo.
"""
import re
from dataclasses import dataclass


def bilinear(q, u, v):
    return (
        (1 - u) * (1 - v) * q[0][0] + u * (1 - v) * q[1][0] + u * v * q[2][0] + (1 - u) * v * q[3][0],
        (1 - u) * (1 - v) * q[0][1] + u * (1 - v) * q[1][1] + u * v * q[2][1] + (1 - u) * v * q[3][1],
    )


def plot_quad(croqui: dict, r: int, c: int, u0=0.0, u1=1.0, v0=0.0, v1=1.0):
    q = croqui["corners"]
    rows, cols = croqui["rows"], croqui["cols"]
    m = float(croqui.get("margin", 0)) / 100 / 2
    a0, a1 = (c + m) / cols, (c + 1 - m) / cols
    b0, b1 = (r + m) / rows, (r + 1 - m) / rows
    U = lambda t: a0 + (a1 - a0) * t  # noqa: E731
    V = lambda t: b0 + (b1 - b0) * t  # noqa: E731
    return [bilinear(q, U(u0), V(v0)), bilinear(q, U(u1), V(v0)), bilinear(q, U(u1), V(v1)), bilinear(q, U(u0), V(v1))]


@dataclass
class Plot:
    id: str
    r: int
    c: int
    trt: dict | None
    bloco: str | None


def _find_trt(trts, code):
    code = code.lower()
    for t in trts:
        if str(t.get("code", "")).lower() == code or (t.get("sigla") and str(t["sigla"]).lower() == code):
            return t
    return None


def parse_cell(value: str, r: int, trts: list):
    """'4A' -> tratamento 4, bloco A. '4' -> tratamento 4, bloco = letra da linha."""
    m = re.match(r"^(.+?)[-_ ]?([A-Za-z])$", value)
    if m and _find_trt(trts, m.group(1)):
        return _find_trt(trts, m.group(1)), m.group(2).upper()
    t = _find_trt(trts, value)
    if t:
        return t, chr(65 + r)
    return None, None


def plots_of(trial_croqui: dict, trts: list) -> list[Plot]:
    out = []
    cells = trial_croqui.get("cells") or []
    seen: dict[str, int] = {}
    pos = []
    for r in range(int(trial_croqui.get("rows", 0))):
        for c in range(int(trial_croqui.get("cols", 0))):
            v = (cells[r][c] if r < len(cells) and c < len(cells[r]) else "") or ""
            v = str(v).strip()
            if v:
                seen[v] = seen.get(v, 0) + 1
                pos.append((v, r, c))
    for v, r, c in pos:
        t, b = parse_cell(v, r, trts)
        # o mesmo código em várias células (ex.: só a sigla T1): cada parcela ganha um código pela posição
        pid = v if seen[v] == 1 else f"{v}-L{r + 1}C{c + 1}"
        out.append(Plot(pid, r, c, t, b))
    return out


def croqui_ready(croqui: dict) -> bool:
    return bool(croqui and croqui.get("corners") and len(croqui["corners"]) == 4 and croqui.get("rows") and croqui.get("cols"))


def plots_geojson(croqui: dict, trts: list) -> dict:
    feats = []
    if croqui.get("kind") != "lonlat" or not croqui_ready(croqui):
        return {"type": "FeatureCollection", "features": feats}
    for p in plots_of(croqui, trts):
        q = plot_quad(croqui, p.r, p.c)
        ring = [list(x) for x in q] + [list(q[0])]
        feats.append({
            "type": "Feature",
            "properties": {"parcela": p.id, "tratamento": (p.trt or {}).get("code"), "sigla": (p.trt or {}).get("sigla"),
                           "bloco": p.bloco, "linha": p.r + 1, "coluna": p.c + 1},
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        })
    return {"type": "FeatureCollection", "features": feats}

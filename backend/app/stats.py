"""Análise de variância (DBC ou DIC) e teste de médias (DMS/t ou Tukey) por tratamento."""
from __future__ import annotations

import math
from functools import lru_cache

from scipy import stats as st


@lru_cache(maxsize=256)
def _q(alpha: float, k: int, df: int) -> float:
    """Valor crítico da amplitude estudentizada (Tukey)."""
    return float(st.studentized_range.ppf(1 - alpha, k, df))


def analyze(plots, results: dict, trts: list, index: str, alpha: float = 0.1, teste: str = "tukey") -> dict:
    pp = [p for p in plots if p.trt and p.id in results and results[p.id].get(index) is not None]
    groups = []
    for t in trts:
        mine = [p for p in pp if p.trt is t or p.trt.get("code") == t.get("code")]
        if not mine:
            continue
        vals = [float(results[p.id][index]) for p in mine]
        n = len(vals)
        mean = sum(vals) / n
        sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1)) if n > 1 else None
        groups.append({"code": t.get("code"), "sigla": t.get("sigla"), "nome": t.get("nome"), "ctrl": bool(t.get("ctrl")),
                       "n": n, "media": mean, "desvio": sd, "valores": vals, "blocos": [p.bloco for p in mine]})
    out: dict = {"indice": index, "alpha": alpha, "teste": teste, "grupos": groups, "delineamento": None}
    if len(groups) < 2:
        return out
    allv = [v for g in groups for v in g["valores"]]
    N = len(allv)
    gm = sum(allv) / N
    sqt = sum(g["n"] * (g["media"] - gm) ** 2 for g in groups)
    sqtot = sum((v - gm) ** 2 for v in allv)
    blocks = sorted({p.bloco for p in pp if p.bloco})
    balanced = len(blocks) > 1 and all(g["n"] == len(blocks) and len(set(g["blocos"])) == len(blocks) for g in groups)
    sqb, dfb, design = 0.0, 0, "DIC"
    if balanced:
        design, dfb = "DBC", len(blocks) - 1
        for b in blocks:
            v = [float(results[p.id][index]) for p in pp if p.bloco == b]
            sqb += len(v) * (sum(v) / len(v) - gm) ** 2
    dft = len(groups) - 1
    dfr = N - 1 - dft - dfb
    out["delineamento"] = design
    if dfr < 1:
        return out
    sqr = max(0.0, sqtot - sqt - sqb)
    qmr = sqr / dfr
    F = (sqt / dft) / qmr if qmr > 0 else float("inf")
    P = float(st.f.sf(F, dft, dfr)) if math.isfinite(F) else 0.0
    cv = math.sqrt(qmr) / abs(gm) * 100 if gm else None
    rh = len(groups) / sum(1 / g["n"] for g in groups)
    dms = float(st.t.ppf(1 - alpha / 2, dfr)) * math.sqrt(2 * qmr / rh)
    hsd = _q(alpha, len(groups), dfr) * math.sqrt(qmr / rh)
    crit = hsd if teste == "tukey" else dms
    order = sorted(groups, key=lambda g: -g["media"])
    for g in order:
        g["letras"] = ""
    if P < alpha:
        L, last_end = 0, -1
        for i in range(len(order)):
            j = i
            while j + 1 < len(order) and order[i]["media"] - order[j + 1]["media"] < crit:
                j += 1
            if j > last_end:
                ch = chr(97 + L)
                L += 1
                for x in range(i, j + 1):
                    order[x]["letras"] += ch
                last_end = j
    else:
        for g in order:
            g["letras"] = "a"
    ctrl = next((g for g in groups if g["ctrl"]), None)
    for g in groups:
        g["ganho"] = g["media"] - ctrl["media"] if ctrl else None
        g["ganho_pct"] = (g["ganho"] / abs(ctrl["media"]) * 100) if ctrl and ctrl["media"] else None
        del g["blocos"]
    out.update({"F": F, "P": P, "CV": cv, "DMS": dms, "HSD": hsd, "dif_minima": crit, "QMres": qmr, "gl_res": dfr, "media_geral": gm,
                "blocos": len(blocks), "significativo": P < alpha})
    return out

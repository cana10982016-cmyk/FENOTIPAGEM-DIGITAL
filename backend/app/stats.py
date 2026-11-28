"""Análise de variância (DBC ou DIC), pressupostos e testes de médias por tratamento.

Testes: Tukey, DMS (t), Bonferroni, Duncan, SNK, Scott-Knott e Dunnett (cada tratamento contra o controle).
Conferido com o R (agricolae, ScottKnott, multcomp) em backend/tests/test_testes_medias.py.
"""
from __future__ import annotations

import math
from functools import lru_cache

from scipy import stats as st


@lru_cache(maxsize=256)
def _q(alpha: float, k: int, df: int) -> float:
    """Valor crítico da amplitude estudentizada (Tukey)."""
    return float(st.studentized_range.ppf(1 - alpha, k, df))


TESTES = {"tukey": "Tukey", "dms": "DMS (t)", "bonferroni": "Bonferroni", "duncan": "Duncan", "snk": "SNK",
          "scottknott": "Scott-Knott", "dunnett": "Dunnett"}


def _letters_ranges(order: list, nonsig) -> None:
    """Letras para médias em ordem decrescente: nonsig(i, j) diz se as médias i..j não diferem."""
    k = len(order)
    L, last_end = 0, -1
    for i in range(k):
        j = max([j for j in range(i, k) if nonsig(i, j)] or [i])
        if j > last_end:
            ch = chr(97 + L) if L < 26 else "?"
            L += 1
            for x in range(i, j + 1):
                order[x]["letras"] += ch
            last_end = j


def _scott_knott(means: list[float], s2m: float, dfr: int, alpha: float) -> list[int]:
    """Agrupamento de Scott & Knott (1974). means em ordem decrescente; devolve o nº do grupo de cada média."""
    grupo = [0] * len(means)
    nxt = [1]

    def rec(lo: int, hi: int, gid: int) -> None:
        y = means[lo:hi]
        k = len(y)
        if k < 2:
            return
        m = sum(y) / k
        best, cut = -1.0, None
        for c in range(1, k):
            a, b = y[:c], y[c:]
            b0 = len(a) * (sum(a) / len(a) - m) ** 2 + len(b) * (sum(b) / len(b) - m) ** 2
            if b0 > best:
                best, cut = b0, c
        s0 = (sum((v - m) ** 2 for v in y) + dfr * s2m) / (k + dfr)
        lam = math.pi / (2 * (math.pi - 2)) * best / s0 if s0 > 0 else float("inf")
        if st.chi2.sf(lam, k / (math.pi - 2)) < alpha:
            g2 = nxt[0]
            nxt[0] += 1
            for i in range(lo + cut, hi):
                grupo[i] = g2
            rec(lo, lo + cut, gid)
            rec(lo + cut, hi, g2)

    rec(0, len(means), 0)
    return grupo


@lru_cache(maxsize=256)
def _dunnett_crit(alpha: float, m: int, df: int) -> float:
    """Valor crítico bilateral de Dunnett (m comparações com o controle, correlação 0,5)."""
    from scipy.optimize import brentq
    import numpy as np

    if m == 1:
        return float(st.t.ppf(1 - alpha / 2, df))
    corr = np.full((m, m), 0.5) + 0.5 * np.eye(m)
    mvt = st.multivariate_t(loc=np.zeros(m), shape=corr, df=df)

    def f(c):
        return float(mvt.cdf(np.full(m, c), lower_limit=np.full(m, -c), random_state=1, maxpts=200000)) - (1 - alpha)

    return float(brentq(f, 1.0, 8.0, xtol=1e-4))


def _pressupostos(groups: list, resid: list[float]) -> dict:
    out: dict = {}
    try:
        if 3 <= len(resid) <= 5000 and max(resid) - min(resid) > 1e-12:
            out["shapiro_W"], out["shapiro_P"] = (float(x) for x in st.shapiro(resid))
        amostras = [g["valores"] for g in groups if len(g["valores"]) > 1]
        if len(amostras) >= 2 and all(max(a) - min(a) > 1e-12 for a in amostras):
            out["bartlett"], out["bartlett_P"] = (float(x) for x in st.bartlett(*amostras))
        if len(amostras) >= 2:
            out["levene"], out["levene_P"] = (float(x) for x in st.levene(*amostras, center="mean"))
    except Exception:  # noqa: BLE001 — pressupostos são informativos
        pass
    return out


def _clean(x):
    """NaN/infinito viram None (o JSON não aceita), em qualquer nível."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    return x


def analyze(plots, results: dict, trts: list, index: str, alpha: float = 0.1, teste: str = "tukey") -> dict:
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return _clean(_analyze(plots, results, trts, index, alpha, teste))


def _analyze(plots, results: dict, trts: list, index: str, alpha: float = 0.1, teste: str = "tukey") -> dict:
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
    # resíduos do modelo (para a normalidade)
    tm = {g["code"]: g["media"] for g in groups}
    bm = {}
    if balanced:
        for b in blocks:
            v = [float(results[p.id][index]) for p in pp if p.bloco == b]
            bm[b] = sum(v) / len(v)
    resid = [float(results[p.id][index]) - tm[p.trt.get("code")] - ((bm[p.bloco] - gm) if balanced else 0.0) for p in pp
             if p.trt.get("code") in tm]
    k = len(groups)
    se = math.sqrt(qmr / rh)
    dms = float(st.t.ppf(1 - alpha / 2, dfr)) * math.sqrt(2 * qmr / rh)
    hsd = _q(alpha, k, dfr) * se
    teste = teste if teste in TESTES else "tukey"
    order = sorted(groups, key=lambda g: -g["media"])
    for g in order:
        g["letras"] = ""
    ctrl = next((g for g in groups if g["ctrl"]), None)
    crit, crit_p = hsd, None
    if teste == "dms":
        crit = dms
    elif teste == "bonferroni":
        crit = float(st.t.ppf(1 - alpha / (k * (k - 1)), dfr)) * math.sqrt(2 * qmr / rh)
    elif teste in ("duncan", "snk"):
        crit_p = {p: _q(1 - (1 - alpha) ** (p - 1) if teste == "duncan" else alpha, p, dfr) * se for p in range(2, k + 1)}
        crit = None
    elif teste == "dunnett":
        crit = _dunnett_crit(alpha, k - 1, dfr) * math.sqrt(2 * qmr / rh) if ctrl else None
    sig_any = P < alpha
    if teste == "dunnett":
        # sem letras: cada tratamento é comparado só com o controle
        for g in groups:
            if ctrl is None or g is ctrl:
                g["letras"] = ""
            else:
                g["letras"] = "*" if crit is not None and abs(g["media"] - ctrl["media"]) >= crit else "ns"
    elif not sig_any:
        for g in order:
            g["letras"] = "a"
    elif teste == "scottknott":
        gid = _scott_knott([g["media"] for g in order], qmr / rh, dfr, alpha)
        ids = []
        for x in gid:
            if x not in ids:
                ids.append(x)
        for g, x in zip(order, gid):
            g["letras"] = chr(97 + ids.index(x))
    else:
        if crit_p:
            # Duncan/SNK: amplitude de p médias comparada com o valor crítico de p médias; uma faixa
            # dentro de outra não significativa também não é significativa
            ns = {}
            for size in range(k, 0, -1):
                for i in range(0, k - size + 1):
                    j = i + size - 1
                    if size == 1:
                        ns[i, j] = True
                        continue
                    outer = (i > 0 and ns.get((i - 1, j))) or (j < k - 1 and ns.get((i, j + 1)))
                    ns[i, j] = bool(outer) or order[i]["media"] - order[j]["media"] < crit_p[size]
            _letters_ranges(order, lambda i, j: ns[i, j])
        else:
            _letters_ranges(order, lambda i, j: order[i]["media"] - order[j]["media"] < crit)
    for g in groups:
        g["ganho"] = g["media"] - ctrl["media"] if ctrl else None
        g["ganho_pct"] = (g["ganho"] / abs(ctrl["media"]) * 100) if ctrl and ctrl["media"] else None
        del g["blocos"]
    out.update({"teste": teste, "teste_nome": TESTES[teste], "dif_minima_p": {str(p): v for p, v in crit_p.items()} if crit_p else None,
                "pressupostos": _pressupostos(groups, resid),
                "F": F, "P": P, "CV": cv, "DMS": dms, "HSD": hsd, "dif_minima": crit, "QMres": qmr, "gl_res": dfr, "media_geral": gm,
                "blocos": len(blocks), "significativo": P < alpha})
    return out

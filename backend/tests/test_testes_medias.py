"""Confere os testes de médias e os pressupostos com o R (multcomp, car, base) nos dados do exemplo de cana.

Referência gerada por tests/dados/testes_medias_referencia.R (Scott-Knott escrito em R a partir do artigo original).
"""
import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import stats

D = Path(__file__).parent / "dados"
ROWS = list(csv.DictReader(open(D / "testes_medias_dados.csv", encoding="utf-8")))
REF = json.load(open(D / "testes_medias_R.json", encoding="utf-8"))
TRTS = [{"code": str(i), "sigla": f"T{i}", "nome": "", "ctrl": i == 1} for i in range(1, 7)]
PLOTS = [SimpleNamespace(id=f"{r['trt']}{r['bloco']}", bloco=r["bloco"], trt=TRTS[int(r["trt"]) - 1]) for r in ROWS]
CASOS = [(v, a) for v in ("FALHA", "ALT", "CC", "CCr") for a in (0.05, 0.1)]


def _an(v, a, teste):
    res = {f"{r['trt']}{r['bloco']}": {v: float(r[v])} for r in ROWS}
    return stats.analyze(PLOTS, res, TRTS, v, a, teste)


def _letras(A):
    return {g["code"]: g["letras"] for g in A["grupos"]}


@pytest.mark.parametrize("v,a", CASOS)
def test_anova_e_criticos(v, a):
    R = REF[f"{v}_{a}"]
    A = _an(v, a, "tukey")
    assert A["delineamento"] == "DBC" and A["gl_res"] == R["gl"]
    for k, kr in (("QMres", "QMres"), ("F", "F"), ("CV", "CV"), ("DMS", "dms"), ("HSD", "hsd")):
        assert A[k] == pytest.approx(R[kr], rel=1e-6), k
    assert A["P"] == pytest.approx(R["P"], rel=1e-4)
    assert _an(v, a, "bonferroni")["dif_minima"] == pytest.approx(R["bonf"], rel=1e-6)
    assert _an(v, a, "dunnett")["dif_minima"] == pytest.approx(R["dunnett"], rel=2e-3)
    for t in ("duncan", "snk"):
        dp = _an(v, a, t)["dif_minima_p"]
        assert [dp[str(p)] for p in range(2, 7)] == pytest.approx(R[t], rel=1e-5), t


@pytest.mark.parametrize("v,a", CASOS)
def test_letras_tukey_scottknott_dunnett(v, a):
    R = REF[f"{v}_{a}"]
    T = _an(v, a, "tukey")
    L = _letras(T)
    if T["P"] < a:  # mesma letra <=> TukeyHSD do R não acha diferença
        for par, p in R["tukey_par"].items():
            i, j = par.split("-")
            assert bool(set(L[i]) & set(L[j])) == (p >= a), par
    assert _letras(_an(v, a, "scottknott")) == (R["scottknott"] if T["P"] < a else {c: "a" for c in R["scottknott"]})
    dn = _letras(_an(v, a, "dunnett"))
    for par, p in R["dunnett_p"].items():
        i = par.split(" - ")[0]
        if abs(p - a) > 0.01:
            assert dn[i] == ("*" if p < a else "ns"), par


@pytest.mark.parametrize("v", ["FALHA", "ALT", "CC", "CCr"])
def test_pressupostos(v):
    R = REF[f"{v}_0.05"]
    P = _an(v, 0.05, "tukey")["pressupostos"]
    assert P["shapiro_P"] == pytest.approx(R["shapiro"], rel=1e-3, abs=1e-6)
    assert P["bartlett_P"] == pytest.approx(R["bartlett"], rel=1e-6)
    assert P["levene_P"] == pytest.approx(R["levene"], rel=1e-6)


def test_croqui_com_sigla_repetida_e_sem_variancia():
    """Croqui só com a sigla (T1 em várias células): cada parcela ganha um código; valores iguais não derrubam a resposta."""
    import json as _json

    from app.geometry import plots_of
    trts = [{"code": str(i), "sigla": f"T{i}", "nome": "", "ctrl": i == 1} for i in range(1, 6)]
    cro = {"rows": 3, "cols": 6, "cells": [["T1", "T2", "T3", "T4", "T5", "T1"], ["T3", "T4", "T5", "T1", "T2", "T3"],
                                           ["T5", "T1", "T2", "T3", "T4", "T5"]]}
    pl = plots_of(cro, trts)
    assert len({p.id for p in pl}) == 18 and all(p.trt for p in pl)
    res = {p.id: {"CC": 10.0 * int(p.trt["code"])} for p in pl}  # sem variação dentro do tratamento
    for t in ("tukey", "scottknott", "duncan", "dunnett"):
        A = stats.analyze(pl, res, trts, "CC", 0.1, t)
        _json.dumps(A, allow_nan=False)

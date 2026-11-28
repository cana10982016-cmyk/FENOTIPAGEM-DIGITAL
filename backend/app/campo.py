"""Avaliações de campo (produção e qualidade) digitadas ou coladas por parcela."""
from __future__ import annotations

# chave: (nome, unidade, casas decimais)
VARS = {
    "TCH": ("Toneladas de cana por hectare", "t/ha", 1),
    "ATR": ("Açúcar total recuperável", "kg/t", 1),
    "TAH": ("Toneladas de açúcar por hectare", "t/ha", 2),
    "POL": ("Pol da cana", "%", 2),
    "BRIX": ("Brix", "%", 2),
    "FIBRA": ("Fibra", "%", 2),
    "AR": ("Açúcares redutores", "%", 2),
    "PUREZA": ("Pureza", "%", 1),
    "BAGACO": ("Bagaço", "t/ha", 1),
    "PALHA": ("Palha", "t/ha", 1),
    "ENERGIA": ("Energia (cogeração)", "MWh/ha", 1),
    "COMPR": ("Comprimento do colmo", "cm", 1),
    "DIAM": ("Diâmetro do colmo", "cm", 2),
    "PERF": ("Número de perfilhos", "nº", 1),
    "ALT_CAMPO": ("Altura medida no campo", "cm", 1),
}
DERIVADAS = {"TAH": ("TCH", "ATR")}


def valores(aval: dict) -> dict:
    """{parcela: {var: valor}} da avaliação, com TAH = TCH × ATR / 1000 quando não foi digitado."""
    out = {}
    for pid, vs in (aval.get("valores") or {}).items():
        row = {}
        for k, v in (vs or {}).items():
            try:
                if v is not None and str(v).strip() != "":
                    row[k] = float(str(v).replace(",", "."))
            except ValueError:
                pass
        if "TAH" not in row and "TCH" in row and "ATR" in row:
            row["TAH"] = row["TCH"] * row["ATR"] / 1000
        out[pid] = row
    return out


def variaveis(aval: dict) -> list[str]:
    vs = list(aval.get("vars") or [])
    if "TCH" in vs and "ATR" in vs and "TAH" not in vs:
        vs.append("TAH")
    return vs

"""Gera um ortomosaico RGB e um modelo de altura (DSM) de exemplo para testar o sistema.

Simula um ensaio de cana em DBC: 6 tratamentos x 4 blocos (24 parcelas), linhas de plantio
a 1,5 m, solo exposto, cobertura, falhas na linha e altura diferentes por tratamento.
Também grava o croqui em texto.

Uso:  python gerar_ortomosaico.py  [pasta de saída]
"""
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

GSD = 0.03                      # 3 cm por pixel
PLOT_W, PLOT_H = 6.0, 10.0      # parcela de 6 m x 10 m (4 linhas de cana a 1,5 m)
ESPAC = 1.5
COLS, ROWS = 6, 4               # 6 parcelas por bloco, 4 blocos (A-D)
GAP, BORDER = 1.0, 4.0          # carreador entre parcelas e borda da imagem (m)
X0, Y0 = 285000.0, 7480000.0    # UTM 23S (SIRGAS 2000), interior de SP
COVER = {1: 0.45, 2: 0.52, 3: 0.60, 4: 0.68, 5: 0.56, 6: 0.74}   # cobertura média
FALHA = {1: 14.0, 2: 10.0, 3: 6.0, 4: 8.0, 5: 4.0, 6: 3.0}       # % de falhas na linha
ALTURA = {1: 1.10, 2: 1.25, 3: 1.45, 4: 1.60, 5: 1.35, 6: 1.80}  # altura das plantas (m)
SOLO_Z = 612.0                  # altitude do solo (m)


def gerar(out_dir: Path, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    layout = []
    for letra in "ABCD":
        trts = rng.permutation(6) + 1
        layout.append([f"{t}{letra}" for t in trts])

    px = lambda m: int(round(m / GSD))  # noqa: E731
    W = px(2 * BORDER + COLS * PLOT_W + (COLS - 1) * GAP)
    H = px(2 * BORDER + ROWS * PLOT_H + (ROWS - 1) * GAP)

    noise = rng.normal(0, 1, (H, W)).astype("float32")
    img = np.empty((3, H, W), dtype="float32")
    img[0], img[1], img[2] = 150 + 12 * noise, 105 + 10 * noise, 75 + 8 * noise
    yy, xx = np.mgrid[0:H, 0:W]
    # solo com leve declive
    dsm = (SOLO_Z + 0.004 * xx * GSD + 0.002 * yy * GSD + rng.normal(0, 0.02, (H, W))).astype("float32")
    verdade = {}
    for r in range(ROWS):
        for c in range(COLS):
            code = layout[r][c]
            trt = int(code[:-1])
            x0, y0 = px(BORDER + c * (PLOT_W + GAP)), px(BORDER + r * (PLOT_H + GAP))
            x1, y1 = x0 + px(PLOT_W), y0 + px(PLOT_H)
            cover = float(np.clip(COVER[trt] + rng.normal(0, 0.04), 0.2, 0.95))
            sub_x = (xx[y0:y1, x0:x1] - x0) * GSD
            sub_y = (yy[y0:y1, x0:x1] - y0) * GSD
            dist = np.abs((sub_x % ESPAC) - ESPAC / 2)  # linhas no centro de cada faixa de 1,5 m
            planta = dist < 0.75 * cover * (1 + 0.25 * rng.normal(0, 1, dist.shape))
            # falhas: trechos de 0,6 a 1,5 m sem planta em cada linha
            linha_id = np.floor(sub_x / ESPAC).astype(int)
            alvo = FALHA[trt] / 100 * PLOT_H
            for k in range(int(PLOT_W / ESPAC)):
                feito = 0.0
                while feito < alvo:
                    comp = float(rng.uniform(0.6, 1.5))
                    ini = float(rng.uniform(0, PLOT_H - comp))
                    planta[(linha_id == k) & (sub_y >= ini) & (sub_y < ini + comp)] = False
                    feito += comp
            g = rng.normal(0, 1, dist.shape)
            for b, (base, amp) in enumerate(((55, 10), (125, 18), (45, 8))):
                band = img[b, y0:y1, x0:x1]
                band[planta] = base + amp * g[planta]
            alt = ALTURA[trt] + rng.normal(0, 0.05)
            zs = dsm[y0:y1, x0:x1]
            zs[planta] += (alt * (0.85 + 0.15 * rng.random(planta.sum()))).astype("float32")
            # falha real: trechos de 0,5 m ou mais sem planta no centro de cada linha
            vazio_m = 0.0
            for k in range(int(PLOT_W / ESPAC)):
                col = int(round((ESPAC / 2 + k * ESPAC) / GSD))
                vazio = ~planta[:, max(0, col - 3):col + 3].any(axis=1)
                run = 0
                for e in list(vazio) + [False]:
                    if e:
                        run += 1
                    else:
                        if run * GSD >= 0.5:
                            vazio_m += run * GSD
                        run = 0
            falha_real = vazio_m / (PLOT_H * int(PLOT_W / ESPAC)) * 100
            verdade[code] = {"tratamento": trt, "falha_pct": round(falha_real, 1), "altura_m": round(alt, 2)}

    img = np.clip(img, 0, 255).astype("uint8")
    out_dir.mkdir(parents=True, exist_ok=True)
    tif = out_dir / "ortomosaico_exemplo_cana.tif"
    prof = dict(driver="GTiff", width=W, height=H, crs="EPSG:31983", transform=from_origin(X0, Y0, GSD, GSD), compress="deflate")
    with rasterio.open(tif, "w", count=3, dtype="uint8", photometric="RGB", **prof) as dst:
        dst.write(img)
    with rasterio.open(out_dir / "dsm_exemplo_cana.tif", "w", count=1, dtype="float32", nodata=-9999, **prof) as dst:
        dst.write(dsm, 1)
    (out_dir / "croqui_exemplo.txt").write_text(
        "Croqui do ortomosaico de exemplo (6 tratamentos x 4 blocos, DBC).\n"
        "Linhas = blocos A a D, de cima para baixo. Cole no sistema em Croqui > Colar do Excel:\n\n"
        + "\n".join("\t".join(l) for l in layout) + "\n\n"
        "Linhas: 4   Colunas: 6   Tratamento 1 = controle.   Espaçamento das linhas de cana: 1,5 m.\n"
        "Para a altura, envie o dsm_exemplo_cana.tif no mesmo voo (botão Altura / DSM).\n", encoding="utf-8")
    corners = [(X0 + BORDER, Y0 - BORDER), (X0 + W * GSD - BORDER, Y0 - BORDER),
               (X0 + W * GSD - BORDER, Y0 - H * GSD + BORDER), (X0 + BORDER, Y0 - H * GSD + BORDER)]
    info = {"layout": layout, "cantos_utm": corners, "crs": "EPSG:31983", "verdade": verdade}
    (out_dir / "gabarito_exemplo.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    return info


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    gerar(out)
    print("Gerado em", out)

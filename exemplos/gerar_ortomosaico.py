"""Gera um ortomosaico RGB de exemplo (GeoTIFF) para testar o sistema.

Simula um ensaio de cana em DBC: 6 tratamentos x 4 blocos (24 parcelas), linhas de plantio,
solo exposto e cobertura vegetal diferente por tratamento. Também grava o croqui em texto.

Uso:  python gerar_ortomosaico.py  [pasta de saída]
"""
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

GSD = 0.03                      # 3 cm por pixel
PLOT_W, PLOT_H = 6.0, 10.0      # parcela de 6 m x 10 m (4 linhas de cana a 1,5 m)
COLS, ROWS = 6, 4               # 6 parcelas por bloco, 4 blocos (A-D)
GAP, BORDER = 1.0, 4.0          # carreador entre parcelas e borda da imagem (m)
X0, Y0 = 285000.0, 7480000.0    # UTM 23S, interior de SP
COVER = {1: 0.45, 2: 0.52, 3: 0.60, 4: 0.68, 5: 0.56, 6: 0.74}  # cobertura média por tratamento

rng = np.random.default_rng(42)
# croqui sorteado (DBC): cada linha é um bloco
layout = []
for b, letra in enumerate("ABCD"):
    trts = rng.permutation(6) + 1
    layout.append([f"{t}{letra}" for t in trts])

px = lambda m: int(round(m / GSD))
W = px(2 * BORDER + COLS * PLOT_W + (COLS - 1) * GAP)
H = px(2 * BORDER + ROWS * PLOT_H + (ROWS - 1) * GAP)

# solo: marrom avermelhado com textura
noise = rng.normal(0, 1, (H, W)).astype("float32")
img = np.empty((3, H, W), dtype="float32")
img[0] = 150 + 12 * noise
img[1] = 105 + 10 * noise
img[2] = 75 + 8 * noise

yy, xx = np.mgrid[0:H, 0:W]
for r in range(ROWS):
    for c in range(COLS):
        code = layout[r][c]
        trt = int(code[:-1])
        x0 = px(BORDER + c * (PLOT_W + GAP)); y0 = px(BORDER + r * (PLOT_H + GAP))
        x1 = x0 + px(PLOT_W); y1 = y0 + px(PLOT_H)
        cover = np.clip(COVER[trt] + rng.normal(0, 0.04), 0.2, 0.95)
        sub_x = (xx[y0:y1, x0:x1] - x0) * GSD
        # 4 linhas de cana no sentido do comprimento; largura da faixa verde depende da cobertura
        dist = np.abs(((sub_x - 0.75) % 1.5) - 0.75)
        half = 0.75 * cover
        planta = dist < half * (1 + 0.25 * rng.normal(0, 1, dist.shape))
        g = rng.normal(0, 1, dist.shape)
        for b, (base, amp) in enumerate(((55, 10), (125, 18), (45, 8))):
            band = img[b, y0:y1, x0:x1]
            band[planta] = base + amp * g[planta]

img = np.clip(img, 0, 255).astype("uint8")
out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
out_dir.mkdir(parents=True, exist_ok=True)
tif = out_dir / "ortomosaico_exemplo_cana.tif"
with rasterio.open(tif, "w", driver="GTiff", width=W, height=H, count=3, dtype="uint8", crs="EPSG:31983",
                   transform=from_origin(X0, Y0, GSD, GSD), compress="deflate", photometric="RGB") as dst:
    dst.write(img)
(out_dir / "croqui_exemplo.txt").write_text(
    "Croqui do ortomosaico de exemplo (6 tratamentos x 4 blocos, DBC).\n"
    "Linhas = blocos A a D, de cima para baixo. Cole no sistema em Croqui > Colar do Excel:\n\n"
    + "\n".join("\t".join(l) for l in layout) + "\n\n"
    "Linhas: 4   Colunas: 6   Tratamento 1 = controle.\n", encoding="utf-8")
print(tif, f"{W}x{H} px", f"{tif.stat().st_size/1e6:.1f} MB")

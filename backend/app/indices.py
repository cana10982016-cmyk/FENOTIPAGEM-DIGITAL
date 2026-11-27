"""Lista de índices e erro de imagem (sem depender do rasterio, para o site de consulta)."""

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
    # por parcela (não entram na grade)
    "FALHA": {"nome": "Falhas de plantio", "unidade": "%", "casas": 1, "parcela": True},
    "ALT": {"nome": "Altura de plantas", "unidade": "m", "casas": 2, "parcela": True},
    # multiespectrais (só quando o ortomosaico tem as bandas)
    "NDVI": {"nome": "NDVI", "unidade": "", "casas": 3},
    "NDRE": {"nome": "NDRE", "unidade": "", "casas": 3},
    "GNDVI": {"nome": "GNDVI", "unidade": "", "casas": 3},
}

# índices calculados pixel a pixel (média na parcela e na grade)
PIXEL_INDICES = [k for k, v in INDICES.items() if not v.get("parcela")]

# bandas padrão: vermelho, verde, azul nas bandas 1, 2 e 3; sem RedEdge e NIR
BANDAS_PADRAO = {"r": 1, "g": 2, "b": 3, "re": 0, "nir": 0}


class RasterError(Exception):
    pass

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
}


class RasterError(Exception):
    pass

"""Configuração lida das variáveis de ambiente."""
import os
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


DATA_DIR = Path(_env("DATA_DIR", str(Path(__file__).resolve().parents[2] / "dados")))
UPLOAD_DIR = DATA_DIR / "voos"
PREVIEW_DIR = DATA_DIR / "previas"

# SQLite por padrão; em produção use o Postgres do Supabase:
# postgresql+psycopg://postgres:SENHA@db.xxxx.supabase.co:5432/postgres
DATABASE_URL = _env("DATABASE_URL", f"sqlite:///{DATA_DIR / 'fenotipagem.db'}")

SECRET_KEY = _env("SECRET_KEY", "troque-esta-chave-em-producao")
TOKEN_HOURS = int(_env("TOKEN_HOURS", "72"))

ADMIN_EMAIL = _env("ADMIN_EMAIL", "admin@fenotipagem.local")
ADMIN_PASSWORD = _env("ADMIN_PASSWORD", "")
ADMIN_NAME = _env("ADMIN_NAME", "Administrador")

# Lado maior da imagem de pré-visualização mostrada no mapa (px)
PREVIEW_MAX_PX = int(_env("PREVIEW_MAX_PX", "4096"))

FRONTEND_DIR = Path(_env("FRONTEND_DIR", str(Path(__file__).resolve().parents[2] / "frontend")))


def ensure_dirs() -> None:
    for d in (DATA_DIR, UPLOAD_DIR, PREVIEW_DIR):
        d.mkdir(parents=True, exist_ok=True)

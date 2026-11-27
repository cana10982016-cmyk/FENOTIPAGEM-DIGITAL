"""Configuração lida das variáveis de ambiente."""
import os
import re
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


DATA_DIR = Path(_env("DATA_DIR", str(Path(__file__).resolve().parents[2] / "dados")))
UPLOAD_DIR = DATA_DIR / "voos"
PREVIEW_DIR = DATA_DIR / "previas"

# SQLite por padrão; em produção use o Postgres do Supabase:
# postgresql+psycopg://postgres:SENHA@db.xxxx.supabase.co:5432/postgres
DATABASE_URL = _env("DATABASE_URL", f"sqlite:///{DATA_DIR / 'fenotipagem.db'}")


def _fix_db_url(url: str) -> str:
    """Aceita a URI copiada do Supabase como está: troca postgres:// e postgresql:// pelo driver
    psycopg e tira os colchetes de [SENHA]."""
    url = url.strip().strip('"').strip("'")
    for old in ("postgres://", "postgresql://"):
        if url.startswith(old):
            url = "postgresql+psycopg://" + url[len(old):]
    return re.sub(r"^(postgresql\+psycopg://[^:/@]+):\[([^\]@]*)\]@", r"\1:\2@", url)


DATABASE_URL = _fix_db_url(DATABASE_URL)
# Schema do Postgres onde ficam as tabelas (permite dividir um projeto Supabase com outro sistema)
DB_SCHEMA = _env("DB_SCHEMA", "")

SECRET_KEY = _env("SECRET_KEY", "troque-esta-chave-em-producao")
TOKEN_HOURS = int(_env("TOKEN_HOURS", "72"))

ADMIN_EMAIL = _env("ADMIN_EMAIL", "admin@fenotipagem.local")
ADMIN_PASSWORD = _env("ADMIN_PASSWORD", "")
ADMIN_NAME = _env("ADMIN_NAME", "Administrador")

# Lado maior da imagem de pré-visualização mostrada no mapa (px)
PREVIEW_MAX_PX = int(_env("PREVIEW_MAX_PX", "4096"))

# false na nuvem: lá não há os ortomosaicos originais, então não recebe arquivos nem processa
PERMITIR_ENVIO = _env("PERMITIR_ENVIO", "true").lower() not in ("0", "false", "nao", "não", "no")

FRONTEND_DIR = Path(_env("FRONTEND_DIR", str(Path(__file__).resolve().parents[2] / "frontend")))


def ensure_dirs() -> None:
    for d in (DATA_DIR, UPLOAD_DIR, PREVIEW_DIR):
        d.mkdir(parents=True, exist_ok=True)

#!/usr/bin/env bash
# Inicia a Fenotipagem Digital neste computador (macOS ou Linux), sem Docker.
# Uso: ./iniciar.sh   (na primeira vez cria o ambiente Python e instala tudo)
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -f .env ]; then
  cp .env.example .env
  python3 - <<'PY'
import re, secrets
p = ".env"; t = open(p).read()
t = re.sub(r"^SECRET_KEY=.*$", "SECRET_KEY=" + secrets.token_urlsafe(48), t, flags=re.M)
t = re.sub(r"^DB_SCHEMA=.*$", "DB_SCHEMA=fenotipagem", t, flags=re.M)
open(p, "w").write(t)
PY
  echo "Criei o arquivo .env. Preencha ADMIN_EMAIL, ADMIN_PASSWORD e DATABASE_URL e rode ./iniciar.sh de novo."
  exit 0
fi
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
fi
.venv/bin/pip install -q -r backend/requirements.txt
export DATA_DIR="${DATA_DIR:-$PWD/dados}"
cd backend
echo "Fenotipagem Digital em http://localhost:${PORT:-8000}  (Ctrl+C para parar)"
exec ../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --env-file ../.env

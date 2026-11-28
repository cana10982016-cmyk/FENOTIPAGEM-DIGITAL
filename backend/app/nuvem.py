"""Servidor de montagem sob demanda na Hetzner Cloud.

Com HCLOUD_TOKEN no .env, o sistema cria um servidor com o OpenDroneMap (NodeODM) quando há fotos
para montar e apaga o servidor quando termina. A Hetzner cobra por hora enquanto o servidor existe.
O servidor é marcado com a etiqueta app=fenotipagem-odm, então o sistema o reencontra depois de reiniciar.
"""
from __future__ import annotations

import logging
import secrets
import time
from datetime import datetime, timezone

import requests

from . import config

log = logging.getLogger("fenotipagem.nuvem")
API = "https://api.hetzner.cloud/v1"
ETIQUETA = "app=fenotipagem-odm"
MAX_HORAS = 8  # segurança: um servidor nunca fica ligado mais que isso
PORTA = 3000


class NuvemError(Exception):
    pass


def ativo() -> bool:
    return bool(config.HCLOUD_TOKEN)


def _h() -> dict:
    return {"Authorization": f"Bearer {config.HCLOUD_TOKEN}"}


def _req(method: str, path: str, **kw) -> dict:
    r = requests.request(method, API + path, headers=_h(), timeout=60, **kw)
    if r.status_code in (401, 403):
        raise NuvemError("O token da Hetzner (HCLOUD_TOKEN) foi recusado. Gere um token com permissão Read & Write.")
    d = r.json() if r.content else {}
    if r.status_code >= 400:
        e = d.get("error") or {}
        raise NuvemError(f"{e.get('code', r.status_code)}: {e.get('message', '')}")
    return d


def servidores() -> list[dict]:
    return _req("GET", "/servers", params={"label_selector": ETIQUETA}).get("servers", [])


def _user_data(token: str) -> str:
    return f"""#cloud-config
runcmd:
  - command -v docker || (curl -fsSL https://get.docker.com | sh)
  - docker run -d --restart unless-stopped -p 3000:3000 opendronemap/nodeodm:latest --token {token}
"""


def _criar() -> dict:
    token = secrets.token_hex(16)
    erros = []
    for tipo in config.HCLOUD_TIPOS:
        for local in config.HCLOUD_LOCAIS:
            body = {"name": f"fenotipagem-odm-{int(time.time())}", "server_type": tipo, "image": "ubuntu-24.04",
                    "location": local, "user_data": _user_data(token), "start_after_create": True,
                    "labels": {"app": "fenotipagem-odm", "odm-token": token}}
            try:
                s = _req("POST", "/servers", json=body)["server"]
                log.info("servidor de montagem criado: %s %s em %s", s["id"], tipo, local)
                return s
            except NuvemError as e:
                if "token da Hetzner" in str(e):
                    raise
                erros.append(f"{tipo}/{local}: {e}")
    raise NuvemError("A Hetzner não liberou nenhum servidor agora (" + "; ".join(erros[:3]) + ").")


def _idade_h(s: dict) -> float:
    c = datetime.fromisoformat(s["created"].replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - c).total_seconds() / 3600


def garantir() -> dict:
    """Garante um servidor de montagem. Devolve {url, token, pronto}."""
    ss = servidores()
    s = ss[0] if ss else _criar()
    ip = ((s.get("public_net") or {}).get("ipv4") or {}).get("ip")
    token = (s.get("labels") or {}).get("odm-token", "")
    url = f"http://{ip}:{PORTA}" if ip else ""
    pronto = False
    if url and s.get("status") == "running":
        try:
            r = requests.get(f"{url}/info", params={"token": token}, timeout=5)
            pronto = r.ok and "version" in r.json()
        except Exception:  # noqa: BLE001
            pronto = False
    return {"id": s["id"], "url": url, "token": token, "pronto": pronto, "idade_h": _idade_h(s) if s.get("created") else 0}


def desligar_todos(motivo: str = "") -> int:
    n = 0
    for s in servidores():
        try:
            _req("DELETE", f"/servers/{s['id']}")
            n += 1
            log.info("servidor de montagem %s apagado %s", s["id"], motivo)
        except NuvemError:
            log.exception("não consegui apagar o servidor %s", s["id"])
    return n

"""Montagem do ortomosaico e do DSM a partir das fotos do drone, pelo OpenDroneMap (API do NodeODM).

Funciona com qualquer nó NodeODM: o OpenDroneMap instalado em outro computador da rede, num Mac,
ou a nuvem do WebODM Lightning (ODM_URL + ODM_TOKEN no .env).

Fluxo de um voo: fotos (recebendo as fotos) -> montando (enviado ao ODM) -> preparando -> pronto.
Uma linha de execução em segundo plano envia as fotos, acompanha o progresso e baixa o resultado.
"""
from __future__ import annotations

import json
import logging
import shutil
import threading
import time
import zipfile
from pathlib import Path

import requests
from sqlalchemy import select

from . import config
from .db import Flight, SessionLocal

log = logging.getLogger("fenotipagem.odm")

FOTO_EXT = {".jpg", ".jpeg", ".tif", ".tiff", ".png", ".dng"}
QUALIDADES = {
    # rápido: só ortomosaico (sem altura), bem mais leve
    "rapido": [{"name": "fast-orthophoto", "value": True}, {"name": "orthophoto-resolution", "value": 2},
               {"name": "auto-boundary", "value": True}],
    # completo: ortomosaico + modelo de superfície (DSM) para a altura de plantas
    "completo": [{"name": "dsm", "value": True}, {"name": "orthophoto-resolution", "value": 2},
                 {"name": "dem-resolution", "value": 4}, {"name": "pc-quality", "value": "medium"},
                 {"name": "feature-quality", "value": "high"}, {"name": "auto-boundary", "value": True},
                 # economiza memória: o modelo 3D texturizado completo não é usado na fenotipagem
                 {"name": "skip-3dmodel", "value": True}, {"name": "texturing-skip-global-seam-leveling", "value": True}],
}
# códigos de status do NodeODM
QUEUED, RUNNING, FAILED, COMPLETED, CANCELED = 10, 20, 30, 40, 50
LOTE = 20  # fotos por envio ao ODM
_lock = threading.Lock()
_started = False


class OdmError(Exception):
    pass


def _url(path: str) -> str:
    u = config.ODM_URL + path
    if config.ODM_TOKEN:
        u += ("&" if "?" in u else "?") + "token=" + config.ODM_TOKEN
    return u


def _check(r: requests.Response) -> dict:
    try:
        d = r.json()
    except ValueError:
        d = {}
    if r.status_code >= 400 or (isinstance(d, dict) and d.get("error")):
        raise OdmError(str(d.get("error") if isinstance(d, dict) and d.get("error") else f"HTTP {r.status_code}"))
    return d


def info(timeout: float = 3) -> dict | None:
    """Informações do nó ODM, ou None se não estiver acessível."""
    try:
        return _check(requests.get(_url("/info"), timeout=timeout))
    except Exception:  # noqa: BLE001
        return None


def fotos_dir(fid: int) -> Path:
    return config.FOTOS_DIR / str(fid)


def _submit(f: Flight) -> str:
    fotos = sorted(p for p in fotos_dir(f.id).iterdir() if p.suffix.lower() in FOTO_EXT)
    if len(fotos) < 5:
        raise OdmError("Envie pelo menos 5 fotos com sobreposição para montar o ortomosaico.")
    opts = QUALIDADES.get(f.odm_qualidade or "completo", QUALIDADES["completo"])
    # o NodeODM só lê os campos em multipart/form-data (com urlencoded ignora as opções)
    form = {"name": (None, f"voo-{f.id} {f.rotulo}"[:100]), "options": (None, json.dumps(opts))}
    d = _check(requests.post(_url("/task/new/init"), files=form, timeout=60))
    uid = d["uuid"]
    for i in range(0, len(fotos), LOTE):
        files = []
        try:
            files = [("images", (p.name, p.open("rb"), "image/jpeg")) for p in fotos[i:i + LOTE]]
            _check(requests.post(_url(f"/task/new/upload/{uid}"), files=files, timeout=600))
        finally:
            for _, (_, fh, _) in files:
                fh.close()
        _set(f.id, odm_progresso=round(-(i + LOTE) / len(fotos) * 100, 1))  # negativo = enviando fotos
    _check(requests.post(_url(f"/task/new/commit/{uid}"), timeout=120))
    return uid


def _download(uid: str, asset: str, dest: Path) -> bool:
    with requests.get(_url(f"/task/{uid}/download/{asset}"), stream=True, timeout=600) as r:
        # asset inexistente volta 200 com {"error": ...}
        if r.status_code >= 400 or "json" in r.headers.get("content-type", ""):
            return False
        with dest.open("wb") as out:
            for chunk in r.iter_content(8 * 1024 * 1024):
                out.write(chunk)
    return dest.stat().st_size > 0


def _fetch_results(f: Flight) -> tuple[Path, Path | None]:
    base = config.UPLOAD_DIR / f"{f.ensaio_id}_odm{f.id}"
    orto, dsm = Path(f"{base}.tif"), Path(f"{base}_dsm.tif")
    ok_o = _download(f.odm_uuid, "orthophoto.tif", orto)
    ok_d = (f.odm_qualidade != "rapido") and _download(f.odm_uuid, "dsm.tif", dsm)
    if not ok_o:
        # nós antigos só entregam o pacote completo
        z = Path(f"{base}_all.zip")
        if not _download(f.odm_uuid, "all.zip", z):
            raise OdmError("O OpenDroneMap terminou mas não entregou o ortomosaico.")
        with zipfile.ZipFile(z) as zz:
            names = zz.namelist()
            for want, out in (("odm_orthophoto/odm_orthophoto.tif", orto), ("odm_dem/dsm.tif", dsm)):
                if want in names:
                    with zz.open(want) as src, out.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
        z.unlink(missing_ok=True)
        ok_o, ok_d = orto.exists(), dsm.exists()
        if not ok_o:
            raise OdmError("O pacote do OpenDroneMap não tem o ortomosaico.")
    if not ok_d:
        dsm.unlink(missing_ok=True)
    return orto, (dsm if ok_d else None)


def _set(fid: int, **kw) -> None:
    with SessionLocal() as s:
        f = s.get(Flight, fid)
        if f:
            for k, v in kw.items():
                setattr(f, k, v)
            s.commit()


def remove_task(uid: str) -> None:
    for p in ("/task/cancel", "/task/remove"):
        try:
            requests.post(_url(p), data={"uuid": uid}, timeout=10)  # aqui o NodeODM só lê urlencoded
        except Exception:  # noqa: BLE001
            pass


_step_lock = threading.Lock()


def step(prepare) -> None:
    """Uma rodada: envia voos novos ao ODM, atualiza o progresso e recebe os que terminaram."""
    if not _step_lock.acquire(blocking=False):
        return
    try:
        _step(prepare)
    finally:
        _step_lock.release()


def _step(prepare) -> None:
    with SessionLocal() as s:
        ids = list(s.scalars(select(Flight.id).where(Flight.status == "montando")))
    for fid in ids:
        with SessionLocal() as s:
            f = s.get(Flight, fid)
            if not f or f.status != "montando":
                continue
            try:
                if not f.odm_uuid:
                    if info() is None:
                        f.erro = f"O OpenDroneMap não está acessível em {config.ODM_URL}. Vou tentar de novo."
                        s.commit()
                        continue
                    f.erro = ""
                    s.commit()
                    uid = _submit(f)
                    _set(fid, odm_uuid=uid, odm_progresso=0.0)
                    continue
                r = requests.get(_url(f"/task/{f.odm_uuid}/info"), timeout=30)
                if r.status_code == 404:
                    raise OdmError("A tarefa sumiu do OpenDroneMap (o programa foi reiniciado?). Envie as fotos de novo.")
                d = _check(r)
                code = (d.get("status") or {}).get("code")
                if code in (QUEUED, RUNNING):
                    f.odm_progresso, f.erro = float(d.get("progress") or 0), ""
                    s.commit()
                elif code == COMPLETED:
                    orto, dsm = _fetch_results(f)
                    f.caminho, f.arquivo, f.tamanho = str(orto), f"Ortomosaico ODM ({f.odm_fotos} fotos)", orto.stat().st_size
                    if dsm:
                        f.dsm_caminho, f.dsm_arquivo = str(dsm), "DSM do OpenDroneMap"
                    f.status, f.odm_progresso, f.erro = "preparando", 100.0, ""
                    s.commit()
                    remove_task(f.odm_uuid)
                    shutil.rmtree(fotos_dir(fid), ignore_errors=True)
                    prepare(fid)
                else:
                    msg = (d.get("status") or {}).get("errorMessage") or ("cancelada" if code == CANCELED else "falhou")
                    raise OdmError(f"O OpenDroneMap não conseguiu montar: {msg}. Confira a sobreposição das fotos.")
            except OdmError as e:
                f.status, f.erro = "erro", str(e)
                s.commit()
            except requests.RequestException as e:
                f.erro = f"Sem contato com o OpenDroneMap ({type(e).__name__}). Vou tentar de novo."
                s.commit()
            except Exception as e:  # noqa: BLE001
                log.exception("falha na montagem do voo %s", fid)
                f.status, f.erro = "erro", f"Falha na montagem: {e}"
                s.commit()


def start_worker(prepare, intervalo: float = 15) -> None:
    global _started
    with _lock:
        if _started:
            return
        _started = True

    def loop():
        while True:
            try:
                step(prepare)
            except Exception:  # noqa: BLE001
                log.exception("falha no acompanhamento do OpenDroneMap")
            time.sleep(intervalo)

    threading.Thread(target=loop, name="odm", daemon=True).start()

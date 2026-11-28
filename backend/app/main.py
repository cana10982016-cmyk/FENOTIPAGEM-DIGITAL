"""API do INOVAAGRO Fenotipagem."""
from __future__ import annotations

import csv
import io
import logging
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import config, stats
from .indices import INDICES, RasterError
from .auth import admin_user, bootstrap_admin, check_password, current_user, hash_password, make_token
from .db import Flight, PreviewImage, SessionLocal, Trial, User, get_session, init_db
from .geometry import croqui_ready, plots_geojson, plots_of

log = logging.getLogger("fenotipagem")
DB_ERRO = ""


def _data_ok(d: str | None) -> str:
    """AAAA-MM-DD válida, ou vazio."""
    try:
        return datetime.strptime((d or "").strip(), "%Y-%m-%d").strftime("%Y-%m-%d") if d else ""
    except ValueError:
        return ""


def _fix_bad_dates(s: Session) -> None:
    """Voos gravados com data inválida (ex.: tirada errado do nome do arquivo) ficam sem data."""
    for f in s.scalars(select(Flight).where(Flight.data_voo != "")):
        if not _data_ok(f.data_voo):
            bad = "/".join(reversed(f.data_voo.split("-")))
            if f.rotulo in (bad, f.data_voo):
                f.rotulo = Path(f.arquivo or "voo").stem[:100]
            f.data_voo = ""
    s.commit()


def _sem_senha(msg: str) -> str:
    return re.sub(r"(://[^:/@\s]+:)[^@\s]+@", r"\1***@", msg)[:500]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global DB_ERRO
    try:
        init_db()
    except Exception as e:  # o site sobe mesmo assim e mostra o erro em /api/saude
        DB_ERRO = _sem_senha(str(e))
        log.error("não consegui conectar ao banco: %s", DB_ERRO)
        yield
        return
    with SessionLocal() as s:
        bootstrap_admin(s)
        _fix_bad_dates(s)
        if config.PERMITIR_ENVIO:
            # voos que estavam no meio do processamento quando o servidor parou
            for f in s.scalars(select(Flight).where(Flight.status.in_(["preparando", "calculando"]))):
                f.status, f.erro = "erro", "O servidor reiniciou durante o processamento. Processe de novo."
            s.commit()
            _store_missing_previews(s)
    if config.PERMITIR_ENVIO:
        from . import odm
        odm.start_worker(_prepare)
    yield


def _preview_bytes(png_path: str | Path) -> bytes:
    """Converte a pré-visualização em WebP (bem menor que o PNG) para guardar no banco."""
    buf = io.BytesIO()
    with Image.open(png_path) as im:
        im.save(buf, "WEBP", quality=85, method=4)
    return buf.getvalue()


def _store_preview(s: Session, f: Flight) -> None:
    if not f.previa or not Path(f.previa).exists():
        return
    row = s.get(PreviewImage, f.id) or PreviewImage(voo_id=f.id)
    row.tipo, row.dados = "image/webp", _preview_bytes(f.previa)
    s.add(row)


def _store_missing_previews(s: Session) -> None:
    """Voos preparados antes desta versão: copia a pré-visualização para o banco."""
    have = set(s.scalars(select(PreviewImage.voo_id)))
    for f in s.scalars(select(Flight).where(Flight.previa != "")):
        if f.id not in have:
            try:
                _store_preview(s, f)
                s.commit()
            except Exception:
                s.rollback()
                log.exception("falha ao guardar a pré-visualização do voo %s", f.id)


app = FastAPI(title="INOVAAGRO Fenotipagem", version="0.1.0", lifespan=lifespan)


# ------------------------------------------------------------------ esquemas

class LoginIn(BaseModel):
    email: str
    senha: str


class PasswordIn(BaseModel):
    atual: str
    nova: str = Field(min_length=8)


class UserIn(BaseModel):
    email: str
    nome: str = ""
    senha: str = Field(min_length=6)
    admin: bool = False


class TrialIn(BaseModel):
    nome: str | None = None
    cliente: str | None = None
    local: str | None = None
    cultura: str | None = None
    variedade: str | None = None
    observacoes: str | None = None
    tratamentos: list | None = None
    croqui: dict | None = None
    ajustes: dict | None = None


class FlightIn(BaseModel):
    rotulo: str | None = None
    data_voo: str | None = None
    bandas: dict | None = None


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "nome": u.nome, "admin": u.admin, "ativo": u.ativo}


def flight_out(f: Flight, with_results: bool = False) -> dict:
    d = {k: getattr(f, k) for k in ("id", "ensaio_id", "rotulo", "data_voo", "arquivo", "tamanho", "status", "erro", "crs", "georref",
                                     "largura", "altura", "gsd_m", "previa_w", "previa_h", "limites", "otsu", "limiar_usado",
                                     "bandas", "dsm_arquivo", "odm_fotos", "odm_qualidade", "odm_progresso")}
    d["processado_em"] = f.processado_em.isoformat() if f.processado_em else None
    d["tem_resultados"] = bool(f.resultados)
    if with_results:
        d["resultados"] = f.resultados or {}
    return d


def trial_out(t: Trial, with_results: bool = False) -> dict:
    return {"id": t.id, "nome": t.nome, "cliente": t.cliente, "local": t.local, "cultura": t.cultura, "variedade": t.variedade,
            "observacoes": t.observacoes, "tratamentos": t.tratamentos or [], "croqui": t.croqui or {}, "ajustes": t.ajustes or {},
            "criado_em": t.criado_em.isoformat() if t.criado_em else None,
            "atualizado_em": t.atualizado_em.isoformat() if t.atualizado_em else None,
            "voos": [flight_out(f, with_results) for f in t.voos]}


def get_trial(s: Session, tid: int) -> Trial:
    t = s.get(Trial, tid)
    if not t:
        raise HTTPException(404, "Ensaio não encontrado.")
    return t


def get_flight(s: Session, fid: int) -> Flight:
    f = s.get(Flight, fid)
    if not f:
        raise HTTPException(404, "Voo não encontrado.")
    return f


# ------------------------------------------------------------------ login e usuários

_ODM_CACHE = {"t": 0.0, "v": None}


def _odm_info():
    import time
    if not config.PERMITIR_ENVIO:
        return None
    if time.time() - _ODM_CACHE["t"] > 30:
        from . import odm
        _ODM_CACHE["v"], _ODM_CACHE["t"] = odm.info(), time.time()
    return _ODM_CACHE["v"]


@app.get("/api/saude")
def health():
    if DB_ERRO:
        return {"ok": False, "erro_banco": DB_ERRO}
    i = _odm_info()
    return {"ok": True, "envio": config.PERMITIR_ENVIO, "odm": bool(i),
            "odm_info": {k: i.get(k) for k in ("version", "engineVersion", "taskQueueCount", "maxImages")} if i else None}


@app.post("/api/auth/login")
def login(body: LoginIn, s: Session = Depends(get_session)):
    u = s.scalar(select(User).where(User.email == body.email.strip().lower()))
    if not u or not u.ativo or not check_password(body.senha, u.senha_hash):
        raise HTTPException(401, "E-mail ou senha incorretos.")
    return {"token": make_token(u), "usuario": user_out(u)}


@app.get("/api/auth/eu")
def me(u: User = Depends(current_user)):
    return user_out(u)


@app.put("/api/auth/senha")
def change_password(body: PasswordIn, u: User = Depends(current_user), s: Session = Depends(get_session)):
    if not check_password(body.atual, u.senha_hash):
        raise HTTPException(400, "A senha atual está errada.")
    u = s.get(User, u.id)
    u.senha_hash = hash_password(body.nova)
    s.commit()
    return {"ok": True}


@app.get("/api/usuarios")
def list_users(_: User = Depends(admin_user), s: Session = Depends(get_session)):
    return [user_out(u) for u in s.scalars(select(User).order_by(User.nome))]


@app.post("/api/usuarios", status_code=201)
def create_user(body: UserIn, _: User = Depends(admin_user), s: Session = Depends(get_session)):
    email = body.email.strip().lower()
    if s.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Já existe um usuário com esse e-mail.")
    u = User(email=email, nome=body.nome, senha_hash=hash_password(body.senha), admin=body.admin)
    s.add(u)
    s.commit()
    return user_out(u)


@app.delete("/api/usuarios/{uid}")
def deactivate_user(uid: int, me_: User = Depends(admin_user), s: Session = Depends(get_session)):
    u = s.get(User, uid)
    if not u:
        raise HTTPException(404, "Usuário não encontrado.")
    if u.id == me_.id:
        raise HTTPException(400, "Você não pode desativar a própria conta.")
    u.ativo = False
    s.commit()
    return {"ok": True}


# ------------------------------------------------------------------ ensaios

@app.get("/api/indices")
def list_indices():
    return INDICES


@app.get("/api/ensaios")
def list_trials(_: User = Depends(current_user), s: Session = Depends(get_session)):
    rows = s.execute(select(Trial, func.count(Flight.id)).outerjoin(Flight).group_by(Trial.id).order_by(Trial.atualizado_em.desc())).all()
    return [{"id": t.id, "nome": t.nome, "cliente": t.cliente, "local": t.local, "cultura": t.cultura,
             "tratamentos": len(t.tratamentos or []), "voos": n,
             "atualizado_em": t.atualizado_em.isoformat() if t.atualizado_em else None} for t, n in rows]


@app.post("/api/ensaios", status_code=201)
def create_trial(body: TrialIn, u: User = Depends(current_user), s: Session = Depends(get_session)):
    data = body.model_dump(exclude_none=True)
    data.setdefault("nome", "Novo ensaio")
    data.setdefault("croqui", {"kind": None, "corners": None, "rows": 4, "cols": 6, "margin": 8, "gx": 3, "gy": 2, "cells": []})
    data.setdefault("ajustes", {"thr_mode": "otsu", "thr_value": 0.05})
    t = Trial(criado_por=u.id, **data)
    s.add(t)
    s.commit()
    return trial_out(t)


@app.get("/api/ensaios/{tid}")
def read_trial(tid: int, _: User = Depends(current_user), s: Session = Depends(get_session)):
    return trial_out(get_trial(s, tid), with_results=True)


@app.put("/api/ensaios/{tid}")
def update_trial(tid: int, body: TrialIn, _: User = Depends(current_user), s: Session = Depends(get_session)):
    t = get_trial(s, tid)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(t, k, v)
    t.atualizado_em = datetime.now(timezone.utc)
    s.commit()
    return trial_out(t)


@app.delete("/api/ensaios/{tid}")
def delete_trial(tid: int, u: User = Depends(current_user), s: Session = Depends(get_session)):
    t = get_trial(s, tid)
    if not (u.admin or t.criado_por == u.id):
        raise HTTPException(403, "Só quem criou o ensaio ou o administrador pode excluí-lo.")
    paths = [p for f in t.voos for p in (f.caminho, f.previa, f.dsm_caminho) if p]
    fids = [f.id for f in t.voos]
    if fids:
        s.execute(delete(PreviewImage).where(PreviewImage.voo_id.in_(fids)))
    s.delete(t)
    s.commit()
    for p in paths:
        Path(p).unlink(missing_ok=True)
    return {"ok": True}


# ------------------------------------------------------------------ voos (ortomosaicos)

ALLOWED = re.compile(r"\.(tif|tiff|jpg|jpeg|png)$", re.I)


def _prepare(fid: int) -> None:
    from . import raster  # só no computador do servidor (o site de consulta não processa)
    with SessionLocal() as s:
        f = s.get(Flight, fid)
        if not f:
            return
        try:
            info = raster.inspect(f.caminho)
            f.largura, f.altura, f.crs, f.georref, f.gsd_m = info["width"], info["height"], info["crs"], info["georref"], info["gsd_m"]
            out = config.PREVIEW_DIR / f"{Path(f.caminho).stem}.png"
            pv = raster.make_preview(f.caminho, out, config.PREVIEW_MAX_PX, f.bandas)
            f.previa, f.previa_w, f.previa_h, f.limites, f.otsu = str(out), pv["previa_w"], pv["previa_h"], pv["limites"], pv["otsu"]
            _store_preview(s, f)
            f.status, f.erro = "pronto", ""
        except RasterError as e:
            f.status, f.erro = "erro", str(e)
        except Exception as e:  # arquivo corrompido ou formato não suportado
            log.exception("falha ao preparar voo %s", fid)
            f.status, f.erro = "erro", f"Não consegui ler a imagem: {e}"
        s.commit()


@app.post("/api/ensaios/{tid}/voos", status_code=201)
def upload_flight(tid: int, bg: BackgroundTasks, arquivo: UploadFile = File(...), rotulo: str = Form(""), data_voo: str = Form(""),
                  _: User = Depends(current_user), s: Session = Depends(get_session)):
    if not config.PERMITIR_ENVIO:
        raise HTTPException(409, "Este endereço é só para consulta. Envie os ortomosaicos e processe pelo computador do servidor.")
    t = get_trial(s, tid)
    name = Path(arquivo.filename or "imagem.tif").name
    if not ALLOWED.search(name):
        raise HTTPException(400, "Envie um GeoTIFF (.tif) ou uma imagem JPG/PNG.")
    dest = config.UPLOAD_DIR / f"{tid}_{uuid.uuid4().hex[:10]}{Path(name).suffix.lower()}"
    with dest.open("wb") as out:
        shutil.copyfileobj(arquivo.file, out, length=8 * 1024 * 1024)
    data_voo = _data_ok(data_voo)
    f = Flight(ensaio_id=t.id, rotulo=rotulo or data_voo or name, data_voo=data_voo, arquivo=name, caminho=str(dest),
               tamanho=dest.stat().st_size, status="preparando")
    s.add(f)
    s.commit()
    bg.add_task(_prepare, f.id)
    return flight_out(f)


class FotosIn(BaseModel):
    rotulo: str = ""
    data_voo: str = ""
    qualidade: str = "completo"


def _need_envio():
    if not config.PERMITIR_ENVIO:
        raise HTTPException(409, "Este endereço é só para consulta. Envie as fotos pelo computador do servidor.")


@app.post("/api/ensaios/{tid}/fotos", status_code=201)
def start_photos(tid: int, body: FotosIn, _: User = Depends(current_user), s: Session = Depends(get_session)):
    """Cria um voo que será montado pelo OpenDroneMap a partir das fotos (enviadas em lotes depois)."""
    _need_envio()
    t = get_trial(s, tid)
    q = body.qualidade if body.qualidade in ("rapido", "completo") else "completo"
    f = Flight(ensaio_id=t.id, rotulo=body.rotulo or body.data_voo or "Fotos do drone", data_voo=_data_ok(body.data_voo),
               arquivo="Fotos do drone", status="fotos", odm_qualidade=q, odm_fotos=0, tamanho=0)
    s.add(f)
    s.commit()
    from . import odm
    odm.fotos_dir(f.id).mkdir(parents=True, exist_ok=True)
    return flight_out(f)


@app.post("/api/voos/{fid}/fotos")
def upload_photos(fid: int, fotos: list[UploadFile] = File(...), _: User = Depends(current_user), s: Session = Depends(get_session)):
    _need_envio()
    from . import odm
    f = get_flight(s, fid)
    if f.status != "fotos":
        raise HTTPException(409, "Este voo já foi enviado para a montagem.")
    d = odm.fotos_dir(f.id)
    d.mkdir(parents=True, exist_ok=True)
    n, tam = 0, 0
    for up in fotos:
        name = Path(up.filename or "").name
        if Path(name).suffix.lower() not in odm.FOTO_EXT:
            continue
        dest = d / name
        with dest.open("wb") as out:
            shutil.copyfileobj(up.file, out, length=4 * 1024 * 1024)
        n, tam = n + 1, tam + dest.stat().st_size
    f.odm_fotos = sum(1 for p in d.iterdir() if p.suffix.lower() in odm.FOTO_EXT)
    f.tamanho = sum(p.stat().st_size for p in d.iterdir())
    f.arquivo = f"{f.odm_fotos} fotos do drone"
    s.commit()
    return flight_out(f)


@app.post("/api/voos/{fid}/montar")
def assemble(fid: int, _: User = Depends(current_user), s: Session = Depends(get_session)):
    _need_envio()
    f = get_flight(s, fid)
    if f.status not in ("fotos", "erro") or not f.odm_fotos:
        raise HTTPException(409, "Envie as fotos antes de montar.")
    if f.odm_fotos < 5:
        raise HTTPException(400, "Envie pelo menos 5 fotos com sobreposição.")
    if f.odm_uuid:
        from . import odm
        odm.remove_task(f.odm_uuid)
    f.status, f.erro, f.odm_uuid, f.odm_progresso = "montando", "", "", None
    s.commit()
    return flight_out(f)


@app.put("/api/voos/{fid}")
def update_flight(fid: int, body: FlightIn, bg: BackgroundTasks, _: User = Depends(current_user), s: Session = Depends(get_session)):
    f = get_flight(s, fid)
    data = body.model_dump(exclude_none=True)
    if "data_voo" in data:
        data["data_voo"] = _data_ok(data["data_voo"])
    bandas = data.pop("bandas", None)
    for k, v in data.items():
        setattr(f, k, v)
    if bandas is not None and bandas != (f.bandas or {}):
        if not config.PERMITIR_ENVIO:
            raise HTTPException(409, "Troque as bandas pelo computador do servidor.")
        f.bandas = {k: int(bandas.get(k) or 0) for k in ("r", "g", "b", "re", "nir")}
        f.status, f.erro, f.resultados = "preparando", "", None
        s.commit()
        bg.add_task(_prepare, f.id)
        return flight_out(f)
    s.commit()
    return flight_out(f)


@app.delete("/api/voos/{fid}")
def delete_flight(fid: int, _: User = Depends(current_user), s: Session = Depends(get_session)):
    f = get_flight(s, fid)
    for p in (f.caminho, f.previa, f.dsm_caminho):
        if p:
            Path(p).unlink(missing_ok=True)
    if f.odm_uuid or f.odm_fotos:
        from . import odm
        if f.odm_uuid and f.status == "montando":
            odm.remove_task(f.odm_uuid)
        shutil.rmtree(odm.fotos_dir(f.id), ignore_errors=True)
    s.execute(delete(PreviewImage).where(PreviewImage.voo_id == f.id))
    s.delete(f)
    s.commit()
    return {"ok": True}


@app.get("/api/voos/{fid}")
def read_flight(fid: int, _: User = Depends(current_user), s: Session = Depends(get_session)):
    return flight_out(get_flight(s, fid), with_results=True)


@app.post("/api/voos/{fid}/dsm")
def upload_dsm(fid: int, arquivo: UploadFile = File(...), _: User = Depends(current_user), s: Session = Depends(get_session)):
    """Modelo digital de superfície (DSM) do mesmo voo, para a altura de plantas."""
    if not config.PERMITIR_ENVIO:
        raise HTTPException(409, "Este endereço é só para consulta. Envie os arquivos pelo computador do servidor.")
    f = get_flight(s, fid)
    name = Path(arquivo.filename or "dsm.tif").name
    if not re.search(r"\.(tif|tiff)$", name, re.I):
        raise HTTPException(400, "Envie o DSM em GeoTIFF (.tif).")
    dest = config.UPLOAD_DIR / f"{f.ensaio_id}_{uuid.uuid4().hex[:10]}_dsm.tif"
    with dest.open("wb") as out:
        shutil.copyfileobj(arquivo.file, out, length=8 * 1024 * 1024)
    from . import raster
    try:
        raster.inspect_dsm(dest)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, str(e) if isinstance(e, RasterError) else f"Não consegui ler o DSM: {e}")
    if f.dsm_caminho:
        Path(f.dsm_caminho).unlink(missing_ok=True)
    f.dsm_arquivo, f.dsm_caminho = name, str(dest)
    s.commit()
    return flight_out(f)


@app.delete("/api/voos/{fid}/dsm")
def delete_dsm(fid: int, _: User = Depends(current_user), s: Session = Depends(get_session)):
    f = get_flight(s, fid)
    if f.dsm_caminho:
        Path(f.dsm_caminho).unlink(missing_ok=True)
    f.dsm_arquivo, f.dsm_caminho = "", ""
    s.commit()
    return flight_out(f)


@app.get("/api/voos/{fid}/previa.png")
def flight_preview(fid: int, _: User = Depends(current_user), s: Session = Depends(get_session)):
    f = get_flight(s, fid)
    row = s.get(PreviewImage, f.id)
    if row:
        return Response(row.dados, media_type=row.tipo, headers={"Cache-Control": "private, max-age=86400"})
    if not f.previa or not Path(f.previa).exists():
        raise HTTPException(404, "A pré-visualização ainda não está pronta.")
    return FileResponse(f.previa, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


# ------------------------------------------------------------------ processamento

def _threshold(t: Trial, f: Flight) -> float:
    aj = t.ajustes or {}
    if aj.get("thr_mode") == "fixed":
        return float(aj.get("thr_value", 0.05))
    return float(f.otsu if f.otsu is not None else 0.05)


def _process(tid: int, fids: list[int]) -> None:
    from . import raster
    with SessionLocal() as s:
        t = s.get(Trial, tid)
        if not t:
            return
        plots = plots_of(t.croqui, t.tratamentos or [])
        for fid in fids:
            f = s.get(Flight, fid)
            if not f:
                continue
            try:
                thr = _threshold(t, f)
                f.resultados = raster.compute_flight(f.caminho, t.croqui, plots, thr, f.bandas, f.dsm_caminho or None, t.ajustes)
                f.limiar_usado = thr
                f.processado_em = datetime.now(timezone.utc)
                f.status, f.erro = "processado", ""
                if not f.resultados:
                    f.erro = "Nenhuma parcela caiu dentro desta imagem. Confira os cantos do croqui."
            except RasterError as e:
                f.status, f.erro = "erro", str(e)
            except Exception as e:
                log.exception("falha ao processar voo %s", fid)
                f.status, f.erro = "erro", f"Falha no cálculo: {e}"
            s.commit()


@app.post("/api/ensaios/{tid}/processar")
def process_trial(tid: int, bg: BackgroundTasks, voo: int | None = None, _: User = Depends(current_user), s: Session = Depends(get_session)):
    if not config.PERMITIR_ENVIO:
        raise HTTPException(409, "Este endereço é só para consulta. Envie os ortomosaicos e processe pelo computador do servidor.")
    t = get_trial(s, tid)
    if not croqui_ready(t.croqui or {}):
        raise HTTPException(400, "Marque os 4 cantos e defina linhas e colunas do croqui.")
    plots = plots_of(t.croqui, t.tratamentos or [])
    if not plots:
        raise HTTPException(400, "Preencha a identificação das parcelas no croqui.")
    bad = [p.id for p in plots if not p.trt]
    if bad:
        raise HTTPException(400, f"Parcelas com tratamento não cadastrado: {', '.join(bad[:8])}.")
    flights = [f for f in t.voos if f.status in ("pronto", "processado", "erro") and f.previa and (voo is None or f.id == voo)]
    if not flights:
        raise HTTPException(400, "Nenhum voo pronto para processar.")
    for f in flights:
        f.status, f.erro = "calculando", ""
    s.commit()
    bg.add_task(_process, t.id, [f.id for f in flights])
    return {"voos": [f.id for f in flights]}


# ------------------------------------------------------------------ resultados

@app.get("/api/ensaios/{tid}/estatistica")
def trial_stats(tid: int, voo: int, indice: str = "CC", alpha: float = Query(0.1, gt=0, lt=1), teste: str = "tukey",
                _: User = Depends(current_user), s: Session = Depends(get_session)):
    t = get_trial(s, tid)
    f = get_flight(s, voo)
    if f.ensaio_id != t.id:
        raise HTTPException(404, "Voo não pertence a este ensaio.")
    if indice not in INDICES:
        raise HTTPException(400, "Índice desconhecido.")
    return stats.analyze(plots_of(t.croqui, t.tratamentos or []), f.resultados or {}, t.tratamentos or [], indice, alpha, teste)


@app.get("/api/ensaios/{tid}/parcelas.geojson")
def trial_geojson(tid: int, _: User = Depends(current_user), s: Session = Depends(get_session)):
    t = get_trial(s, tid)
    return JSONResponse(plots_geojson(t.croqui or {}, t.tratamentos or []), media_type="application/geo+json")


def _plot_rows(t: Trial):
    plots = plots_of(t.croqui or {}, t.tratamentos or [])
    keys = list(INDICES)
    extra = ["falha_m", "linha_m", "n_linhas", "alt_max"]
    head = ["voo", "data", "parcela", "tratamento", "sigla", "produto", "bloco", "linha", "coluna", "pixels", "area_m2", *keys, *extra]
    rows = []
    for f in t.voos:
        res = f.resultados or {}
        for p in plots:
            v = res.get(p.id)
            if not v:
                continue
            trt = p.trt or {}
            rows.append([f.rotulo, f.data_voo, p.id, trt.get("code"), trt.get("sigla"), trt.get("nome"), p.bloco, p.r + 1, p.c + 1,
                         v.get("n"), v.get("area"), *[v.get(k) for k in keys], *[v.get(k) for k in extra]])
    return head, rows


@app.get("/api/ensaios/{tid}/parcelas.csv")
def export_csv(tid: int, _: User = Depends(current_user), s: Session = Depends(get_session)):
    t = get_trial(s, tid)
    head, rows = _plot_rows(t)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(head)
    for r in rows:
        w.writerow(["" if x is None else (f"{x:.6f}".replace(".", ",") if isinstance(x, float) else x) for x in r])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="ensaio-{t.id}-parcelas.csv"'})


@app.get("/api/ensaios/{tid}/exportar.xlsx")
def export_xlsx(tid: int, alpha: float = 0.1, teste: str = "tukey", _: User = Depends(current_user), s: Session = Depends(get_session)):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    t = get_trial(s, tid)
    wb = Workbook()
    ws = wb.active
    ws.title = "Ensaio"
    for k, v in [("Ensaio", t.nome), ("Cliente", t.cliente), ("Local", t.local), ("Cultura", t.cultura), ("Variedade", t.variedade),
                 ("Observações", t.observacoes)]:
        ws.append([k, v])
    ws.append([])
    ws.append(["Nº", "Sigla", "Produto / dose", "Controle"])
    for tr in t.tratamentos or []:
        ws.append([tr.get("code"), tr.get("sigla"), tr.get("nome"), "sim" if tr.get("ctrl") else ""])
    bold = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="1D8A3A")

    ws2 = wb.create_sheet("Parcelas")
    head, rows = _plot_rows(t)
    ws2.append(head)
    for r in rows:
        ws2.append(r)
    for c in ws2[1]:
        c.font, c.fill = bold, fill

    ws3 = wb.create_sheet("Tratamentos")
    ws3.append(["voo", "índice", "tratamento", "sigla", "n", "média", "grupo", "desvio", "ganho", "ganho %", "delineamento", "F", "P", "CV %", "teste", "dif. mínima",
                "Shapiro-Wilk P", "Bartlett P", "Levene P"])
    for c in ws3[1]:
        c.font, c.fill = bold, fill
    plots = plots_of(t.croqui or {}, t.tratamentos or [])
    for f in t.voos:
        if not f.resultados:
            continue
        for k in INDICES:
            a = stats.analyze(plots, f.resultados, t.tratamentos or [], k, alpha, teste)
            if not a["grupos"]:
                continue
            for g in a["grupos"]:
                ws3.append([f.rotulo, k, g["code"], g["sigla"], g["n"], g["media"], g.get("letras", ""), g["desvio"], g.get("ganho"),
                            g.get("ganho_pct"), a.get("delineamento"), a.get("F"), a.get("P"), a.get("CV"), a.get("teste_nome"),
                            a.get("dif_minima"), *((a.get("pressupostos") or {}).get(x) for x in ("shapiro_P", "bartlett_P", "levene_P"))])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="ensaio-{t.id}.xlsx"'})


# ------------------------------------------------------------------ site

class _Site(StaticFiles):
    """Arquivos do site sempre conferidos com o servidor, para uma atualização aparecer sem Ctrl+F5."""
    async def get_response(self, path, scope):
        r = await super().get_response(path, scope)
        if not path.startswith("img/"):
            r.headers["Cache-Control"] = "no-cache"
        return r


if config.FRONTEND_DIR.exists():
    app.mount("/", _Site(directory=str(config.FRONTEND_DIR), html=True), name="site")

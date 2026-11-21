"""Modelos do banco (SQLAlchemy). Funciona com SQLite e Postgres (Supabase)."""
from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from . import config


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "usuarios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(200), default="")
    senha_hash: Mapped[str] = mapped_column(String(200))
    admin: Mapped[bool] = mapped_column(Boolean, default=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Trial(Base):
    """Ensaio: dados do experimento, tratamentos e croqui."""
    __tablename__ = "ensaios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nome: Mapped[str] = mapped_column(String(300))
    cliente: Mapped[str] = mapped_column(String(300), default="")
    local: Mapped[str] = mapped_column(String(300), default="")
    cultura: Mapped[str] = mapped_column(String(200), default="")
    variedade: Mapped[str] = mapped_column(String(200), default="")
    observacoes: Mapped[str] = mapped_column(Text, default="")
    # [{code, sigla, nome, ctrl}]
    tratamentos: Mapped[list] = mapped_column(JSON, default=list)
    # {kind: "lonlat"|"frac", corners: [[x,y]*4], rows, cols, margin, gx, gy, cells: [[str]]}
    croqui: Mapped[dict] = mapped_column(JSON, default=dict)
    # {thr_mode: "otsu"|"fixed", thr_value: float}
    ajustes: Mapped[dict] = mapped_column(JSON, default=dict)
    criado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    voos: Mapped[list["Flight"]] = relationship(back_populates="ensaio", cascade="all, delete-orphan", order_by="Flight.id")


class Flight(Base):
    """Voo de drone (um ortomosaico por data)."""
    __tablename__ = "voos"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ensaio_id: Mapped[int] = mapped_column(ForeignKey("ensaios.id", ondelete="CASCADE"), index=True)
    rotulo: Mapped[str] = mapped_column(String(100), default="")
    data_voo: Mapped[str] = mapped_column(String(20), default="")  # AAAA-MM-DD
    arquivo: Mapped[str] = mapped_column(String(300), default="")
    caminho: Mapped[str] = mapped_column(String(500), default="")
    tamanho: Mapped[int] = mapped_column(BigInteger, default=0)
    # recebido -> preparando -> pronto -> calculando -> processado | erro
    status: Mapped[str] = mapped_column(String(20), default="recebido")
    erro: Mapped[str] = mapped_column(Text, default="")
    crs: Mapped[str] = mapped_column(String(200), default="")
    georref: Mapped[bool] = mapped_column(Boolean, default=False)
    largura: Mapped[int] = mapped_column(Integer, default=0)
    altura: Mapped[int] = mapped_column(Integer, default=0)
    gsd_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    # pré-visualização: em EPSG:4326 quando georreferenciada, senão em pixels
    previa: Mapped[str] = mapped_column(String(500), default="")
    previa_w: Mapped[int] = mapped_column(Integer, default=0)
    previa_h: Mapped[int] = mapped_column(Integer, default=0)
    limites: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [oeste, sul, leste, norte]
    otsu: Mapped[float | None] = mapped_column(Float, nullable=True)
    limiar_usado: Mapped[float | None] = mapped_column(Float, nullable=True)
    # {plot_id: {n, area, CC, ExG, ..., cells: [{...}]}}
    resultados: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    processado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ensaio: Mapped[Trial] = relationship(back_populates="voos")


_sqlite = config.DATABASE_URL.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _sqlite else {}
if config.DB_SCHEMA and not _sqlite:
    _connect_args["options"] = f"-csearch_path={config.DB_SCHEMA}"
engine = create_engine(config.DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    config.ensure_dirs()
    if config.DB_SCHEMA and not _sqlite:
        with engine.begin() as c:
            c.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{config.DB_SCHEMA}"'))
    Base.metadata.create_all(engine)


def get_session():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()

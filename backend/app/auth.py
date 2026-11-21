"""Login com e-mail e senha; o servidor devolve um token (JWT)."""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .db import User, get_session

_bearer = HTTPBearer(auto_error=False)


def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def check_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except ValueError:
        return False


def make_token(user: User) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=config.TOKEN_HOURS)
    return jwt.encode({"sub": str(user.id), "exp": exp}, config.SECRET_KEY, algorithm="HS256")


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer), s: Session = Depends(get_session)) -> User:
    if not cred:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Faça login para continuar.")
    try:
        data = jwt.decode(cred.credentials, config.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão expirada. Entre de novo.")
    user = s.get(User, int(data["sub"]))
    if not user or not user.ativo:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuário inativo.")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Só o administrador pode fazer isso.")
    return user


def bootstrap_admin(s: Session) -> None:
    """Cria o primeiro administrador a partir de ADMIN_EMAIL / ADMIN_PASSWORD."""
    if not config.ADMIN_PASSWORD:
        return
    if s.scalar(select(User).where(User.email == config.ADMIN_EMAIL.lower())):
        return
    s.add(User(email=config.ADMIN_EMAIL.lower(), nome=config.ADMIN_NAME, senha_hash=hash_password(config.ADMIN_PASSWORD), admin=True))
    s.commit()

"""Access with DNI and password (RF-63), logout and first-login consent (RF-66)."""

import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from auth import sessions
from auth.deps import csrf_valido, usuario_actual, usuario_opcional
from auth.passwords import verify_password
from config import settings
from db.models import Usuario
from db.session import get_db
from rules.calendar import ahora
from web.views import page, volver

router = APIRouter()
_FALLOS: dict[str, deque] = defaultdict(deque)
_LOCK = threading.Lock()
MAX_FALLOS, VENTANA = 5, 15 * 60


def _bloqueado(clave: str) -> bool:
    with _LOCK:
        cola = _FALLOS[clave]
        while cola and time.monotonic() - cola[0] > VENTANA:
            cola.popleft()
        return len(cola) >= MAX_FALLOS


def _fallo(clave: str) -> None:
    with _LOCK:
        _FALLOS[clave].append(time.monotonic())


def _cookie(request: Request, response, token: str | None):
    segura = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    ruta = settings.BASE_PATH or "/"
    if token is None:
        response.delete_cookie(sessions.COOKIE, path=ruta)
    else:
        response.set_cookie(sessions.COOKIE, token, max_age=settings.SESSION_HOURS * 3600, httponly=True,
                            samesite="lax", secure=segura, path=ruta)
    return response


@router.get("/ingresar", name="login")
def login_form(request: Request, usuario=Depends(usuario_opcional)):
    if usuario is not None:
        return RedirectResponse(request.url_for("home"), status_code=303)
    return page(request, "auth/login.html", {"page_title": "Ingresar"})


@router.post("/ingresar", name="login_post")
def login(request: Request, dni: str = Form(""), password: str = Form(""), db=Depends(get_db)):
    origin = request.headers.get("origin")
    if origin and origin != "null" and urlsplit(origin).netloc != (
            request.headers.get("x-forwarded-host") or request.headers.get("host", "")):
        raise HTTPException(status_code=403, detail="Origen no permitido.")
    dni = dni.strip()
    clave = f"{dni}|{request.client.host if request.client else ''}"
    error = None
    if _bloqueado(clave):
        error = "Demasiados intentos. Espera unos minutos antes de volver a intentarlo."
    else:
        usuario = db.scalar(select(Usuario).where(Usuario.dni == dni, Usuario.activo.is_(True)))
        if usuario is None or not verify_password(password, usuario.password_hash):
            _fallo(clave)
            error = "DNI o contraseña incorrectos."
    if error:
        return page(request, "auth/login.html", {"page_title": "Ingresar", "error": error, "dni": dni},
                    status_code=400)
    token = sessions.crear(db, usuario)
    db.commit()
    destino = "consent" if usuario.rol == "alumno" and usuario.consentimiento_en is None else "home"
    return _cookie(request, RedirectResponse(request.url_for(destino), status_code=303), token)


@router.post("/salir", name="logout", dependencies=[Depends(csrf_valido)])
def logout(request: Request, db=Depends(get_db), usuario=Depends(usuario_actual)):
    sessions.cerrar(db, request.cookies.get(sessions.COOKIE))
    db.commit()
    return _cookie(request, RedirectResponse(request.url_for("login"), status_code=303), None)


@router.get("/consentimiento", name="consent")
def consent_form(request: Request, usuario=Depends(usuario_actual)):
    if usuario.rol != "alumno":
        return RedirectResponse(request.url_for("home"), status_code=303)
    return page(request, "auth/consent.html", {"page_title": "Antes de empezar"})


@router.post("/consentimiento", name="consent_post", dependencies=[Depends(csrf_valido)])
def consent(request: Request, acepto: str = Form(""), db=Depends(get_db), usuario=Depends(usuario_actual)):
    if usuario.rol != "alumno":
        return RedirectResponse(request.url_for("home"), status_code=303)
    if acepto != "si":
        return page(request, "auth/consent.html", {
            "page_title": "Antes de empezar", "error": "Para continuar necesitas aceptar el aviso."}, status_code=400)
    usuario.consentimiento_en = usuario.consentimiento_en or ahora()
    db.commit()
    return volver(request, "student_home", ok="consentimiento")

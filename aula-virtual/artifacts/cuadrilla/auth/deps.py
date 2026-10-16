"""Request dependencies: current user, roles, consent, CSRF and per-course permissions."""

import hmac
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from auth import sessions
from db.models import Curso, Inscripcion, Usuario
from db.session import get_db


@dataclass(frozen=True)
class VistaUsuario:
    """What templates need about the signed-in user, independent of the database session."""
    id: int
    nombre: str
    apellido: str
    rol: str

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombre} {self.apellido}".strip()


class Redirect(Exception):
    """Raised by dependencies; main.py turns it into a 303 redirect."""

    def __init__(self, url: str):
        self.url = url


def usuario_opcional(request: Request, db=Depends(get_db)) -> Usuario | None:
    encontrado = sessions.buscar(db, request.cookies.get(sessions.COOKIE))
    if encontrado is None:
        request.state.usuario = None
        request.state.csrf = None
        return None
    sesion, usuario = encontrado
    request.state.usuario = VistaUsuario(usuario.id, usuario.nombre, usuario.apellido, usuario.rol)
    request.state.csrf = sesion.csrf
    return usuario


def usuario_actual(request: Request, usuario=Depends(usuario_opcional)) -> Usuario:
    if usuario is None:
        raise Redirect(str(request.url_for("login")))
    return usuario


def alumno_actual(request: Request, usuario=Depends(usuario_actual)) -> Usuario:
    if usuario.rol != "alumno":
        raise HTTPException(status_code=403, detail="Esta sección es solo para alumnos.")
    if usuario.consentimiento_en is None:
        raise Redirect(str(request.url_for("consent")))
    return usuario


def docente_actual(usuario=Depends(usuario_actual)) -> Usuario:
    if usuario.rol not in ("docente", "admin"):
        raise HTTPException(status_code=403, detail="Esta sección es solo para docentes.")
    return usuario


def admin_actual(usuario=Depends(usuario_actual)) -> Usuario:
    if usuario.rol != "admin":
        raise HTTPException(status_code=403, detail="Esta sección es solo para administradores.")
    return usuario


async def csrf_valido(request: Request, _usuario=Depends(usuario_opcional)):
    """Every POST carries the session's token; a foreign Origin is rejected as well."""
    origin = request.headers.get("origin")
    if origin and origin != "null":
        host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
        if urlsplit(origin).netloc != host:
            raise HTTPException(status_code=403, detail="Origen no permitido.")
    form = await request.form()
    enviado = form.get("_csrf")
    esperado = getattr(request.state, "csrf", None)
    if not esperado or not isinstance(enviado, str) or not hmac.compare_digest(enviado, esperado):
        raise HTTPException(status_code=403, detail="El formulario venció. Recarga la página e inténtalo de nuevo.")


def curso_de_alumno(db, alumno: Usuario, curso_id: int) -> Curso:
    curso = db.scalar(select(Curso).join(Inscripcion, Inscripcion.curso_id == Curso.id).where(
        Curso.id == curso_id, Inscripcion.usuario_id == alumno.id, Inscripcion.rol_en_curso == "alumno",
    ).with_for_update(read=True, key_share=True, of=Curso))
    if curso is None:
        raise HTTPException(status_code=404, detail="No encontramos ese curso.")
    return curso


def curso_de_docente(db, usuario: Usuario, curso_id: int) -> Curso:
    """Teachers see only their courses; administrators see all of them."""
    consulta = select(Curso).where(Curso.id == curso_id)
    if usuario.rol != "admin":
        consulta = consulta.join(Inscripcion, Inscripcion.curso_id == Curso.id).where(
            Inscripcion.usuario_id == usuario.id, Inscripcion.rol_en_curso == "docente",
        )
    curso = db.scalar(consulta.with_for_update(read=True, key_share=True, of=Curso))
    if curso is None:
        raise HTTPException(status_code=404, detail="No encontramos ese curso.")
    return curso


def cursos_de(db, usuario: Usuario) -> list[Curso]:
    if usuario.rol == "admin":
        return list(db.scalars(select(Curso).order_by(Curso.estado, Curso.nombre)))
    rol = "docente" if usuario.rol == "docente" else "alumno"
    return list(db.scalars(select(Curso).join(Inscripcion, Inscripcion.curso_id == Curso.id).where(
        Inscripcion.usuario_id == usuario.id, Inscripcion.rol_en_curso == rol,
    ).order_by(Curso.estado, Curso.nombre)))

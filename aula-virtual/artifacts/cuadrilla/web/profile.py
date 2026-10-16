"""Own profile editing; authorized staff can inspect declared educational background."""

from fastapi import APIRouter, Depends, Request

from auth.deps import Redirect, csrf_valido, usuario_actual
from db.session import get_db
from rules.calendar import ahora
from services import profiles
from web.views import page, volver

router = APIRouter()


def _acceso(request, usuario):
    if usuario.rol == "alumno" and usuario.consentimiento_en is None:
        raise Redirect(str(request.url_for("consent")))


def mostrar(request, db, persona, *, editar=False, curso=None, origen=None, error=None, enviado=None, status=200):
    contexto = profiles.detalle(db, persona)
    propio = request.state.usuario.id == persona.id
    contexto.update(page_title="Mi perfil" if propio else f"Perfil de {persona.nombre_completo}",
        active_nav="alumnos" if curso else "perfil" if propio else "usuarios", persona=persona,
        curso=curso, origen=origen, propio=propio, editar=editar and propio, error=error,
        form=enviado if enviado is not None else contexto["datos"], hoy=ahora().date().isoformat())
    respuesta = page(request, "profile/detail.html", contexto, status_code=status)
    db.commit()
    return respuesta


@router.get("/perfil", name="user_profile")
def detail(request: Request, db=Depends(get_db), usuario=Depends(usuario_actual)):
    _acceso(request, usuario)
    return mostrar(request, db, usuario)


@router.get("/perfil/editar", name="user_profile_edit")
def edit(request: Request, db=Depends(get_db), usuario=Depends(usuario_actual)):
    _acceso(request, usuario)
    return mostrar(request, db, usuario, editar=True)


@router.post("/perfil", name="user_profile_save", dependencies=[Depends(csrf_valido)])
async def save(request: Request, db=Depends(get_db), usuario=Depends(usuario_actual)):
    _acceso(request, usuario)
    form = await request.form()
    datos = {k: form.get(k, "") for k in profiles.CLAVES}
    try:
        profiles.guardar(db, usuario.id, datos, version=form.get("version", ""), confirmo=form.get("confirmo", ""))
        db.commit()
    except profiles.PerfilInvalido as error:
        db.rollback()
        return mostrar(request, db, usuario, editar=True, enviado=datos, error=str(error),
                       status=409 if isinstance(error, profiles.PerfilDesactualizado) else 400)
    return volver(request, "user_profile", ok="perfil_guardado")

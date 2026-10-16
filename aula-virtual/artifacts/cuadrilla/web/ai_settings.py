"""Administrator-only provider controls; no credential fields or raw provider errors."""
from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select

from ai import runtime
from ai.llm import IAError
from auth.deps import admin_actual, csrf_valido
from db.models import ConfiguracionIA, Usuario
from db.session import get_db
from services import ai_settings
from web.views import page, volver

router = APIRouter(prefix="/admin")


def _pagina(request, db, *, form=None, error=None, aviso=None, status=200):
    actual = runtime.actual()
    respuesta = page(request, "admin/ai_settings.html", {"page_title": "Inteligencia artificial", "active_nav": "ia",
        "form": form or {**actual.opciones, "proveedor": actual.proveedor, "version": actual.version},
        "error": error, **({"aviso": aviso} if aviso is not None else {}),
        "historial": db.execute(select(ConfiguracionIA, Usuario).outerjoin(Usuario,
            Usuario.id == ConfiguracionIA.cambiado_por).order_by(ConfiguracionIA.id.desc()).limit(10)).all(),
    }, status_code=status)
    respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


@router.get("/ia", name="admin_ai")
def vista(request: Request, db=Depends(get_db), usuario=Depends(admin_actual)):
    return _pagina(request, db)


@router.post("/ia", name="admin_ai_save", dependencies=[Depends(csrf_valido)])
def guardar(request: Request, proveedor: str = Form(""), modelo_openai: str = Form(""),
            audio_openai: str = Form(""), modelo_vertex: str = Form(""), version: str = Form(""),
            accion: str = Form("probar"), db=Depends(get_db), usuario=Depends(admin_actual)):
    form = {"proveedor": proveedor, "modelo_openai": modelo_openai, "audio_openai": audio_openai,
            "modelo_vertex": modelo_vertex, "version": version}
    try:
        if accion not in ("probar", "activar"):
            raise ai_settings.ConfiguracionInvalida("Acción no disponible.")
        if version != str(runtime.actual().version):
            raise ai_settings.ConfiguracionInvalida("La configuración cambió. Recarga la página antes de continuar.")
        config = ai_settings.candidata(form, runtime.actual())
        ai_settings.probar(config)
        if accion == "probar":
            return _pagina(request, db, form=form, aviso="La conexión de texto y transcripción funciona. Puedes activar este proveedor.")
        ai_settings.activar(db, config, usuario.id, version)
        db.commit()
    except (ai_settings.ConfiguracionInvalida, IAError) as error:
        db.rollback()
        return _pagina(request, db, form=form, error=str(error),
                       status=400 if isinstance(error, ai_settings.ConfiguracionInvalida) else 503)
    return volver(request, "admin_ai", ok="ia_configurada")

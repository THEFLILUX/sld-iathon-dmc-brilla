"""Server-rendered pages (Jinja2) and small helpers shared by the routers."""

from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from config import APP_DIR, settings
from rules import calendar, levels, mastery

templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
templates.env.globals.update(settings=settings, NIVEL=levels.ETIQUETA, BLOOM=levels.BLOOM, VERSION=levels.VERSION,
                             NIVELES=levels.NIVELES, ESTADO_TEMA=mastery.ETIQUETA_ESTADO)
templates.env.filters["fecha"] = calendar.fecha_lima
templates.env.filters["fecha_hora"] = calendar.fecha_hora_lima
templates.env.filters["miles"] = lambda n: f"{int(n or 0):,}".replace(",", " ")


def _sigla(nombre: str) -> str:
    from services.cursos_alumno import sigla
    return sigla(nombre)


def _color(curso) -> str:
    from services.cursos_alumno import COLORES
    return COLORES[curso.id % len(COLORES)]


templates.env.filters["sigla"] = _sigla
templates.env.filters["color_curso"] = _color

AVISOS = {
    "ia_configurada": "Proveedor de IA activado. Las nuevas solicitudes usarán esta configuración.",
    "perfil_guardado": "Tu perfil se guardó correctamente.",
    "resumen_encolado": "Brilla está preparando el resumen de la clase.",
    "reporte": "Gracias. Avisamos a tu docente sobre este reto.",
    "reclamo": "Tu docente revisará esta calificación. Tu puntaje no cambia mientras tanto.",
    "tarea": "Tarea marcada como lista.",
    "canje": "Canje registrado. Tus Coins restantes siguen acumulándose.",
    "guardado": "Cambios guardados.",
    "publicada": "La clase está publicada y tus alumnos ya ven el quiz.",
    "rechazado": "Reto rechazado. Estamos generando otro en su lugar.",
    "aprobado": "Reto aprobado.",
    "subida": "Clase recibida. Te avisaremos aquí cuando el quiz esté listo para validar.",
    "contactado": "Alerta marcada como contactada.",
    "resuelta": "Revisión resuelta.",
    "malla": "Malla guardada.",
    "demo": "Contenido inicial cargado.",
    "demo_existente": "El contenido inicial ya estaba cargado.",
    "usuario": "Usuario guardado.",
    "coins": "Coins registradas.",
    "exp": "Ajuste de EXP registrado.",
    "cerrado": "Curso cerrado y podio final pagado.",
    "curso_eliminado": "Curso y datos asociados eliminados definitivamente.",
    "clase_eliminada": "Clase y datos asociados eliminados definitivamente de la plataforma.",
    "propuesta": "Pedimos a la IA la propuesta de niveles y rúbricas. Se actualizará en unos minutos.",
    "parametros": "Parámetros actualizados. Se aplican desde ahora.",
    "reintento": "Reintentando el procesamiento.",
    "consentimiento": "¡Bienvenido! Ya puedes practicar.",
}


def page(request, template: str, context: dict | None = None, status_code: int = 200):
    from ai import runtime
    usuario = getattr(request.state, "usuario", None)
    contexto = {
        "usuario": usuario, "csrf": getattr(request.state, "csrf", None),
        "aviso": AVISOS.get(request.query_params.get("ok", "")), "active_nav": "",
        "config_ia": runtime.actual(),
        **(context or {}),
    }
    return templates.TemplateResponse(request=request, name=template, context=contexto, status_code=status_code)


def volver(request, nombre: str, *, ok: str | None = None, ancla: str | None = None, **params):
    url = str(request.url_for(nombre, **params))
    if ok:
        url += f"?ok={ok}"
    if ancla:
        url += f"#{ancla}"
    return RedirectResponse(url, status_code=303)

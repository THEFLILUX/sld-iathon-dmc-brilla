"""Teacher assistant: authenticated, CSRF-protected, course-scoped, read-only requests."""

from datetime import datetime
from secrets import token_hex

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from ai import jobs
from ai.llm import IAError
from auth.deps import csrf_valido, curso_de_docente, cursos_de, docente_actual
from db.session import get_db
from services import assistant, reports
from rules.calendar import fecha_hora_lima
from web.views import page, templates

router = APIRouter(prefix="/docente")


def _dato_visible(valor, aliases):
    if isinstance(valor, str):
        if "T" in valor:
            try:
                return fecha_hora_lima(datetime.fromisoformat(valor))
            except ValueError:
                pass
        return assistant.mostrar_aliases(valor, aliases)
    if isinstance(valor, dict):
        return {k.replace("_utc", "").replace("_", " ").capitalize(): _dato_visible(v, aliases)
                for k, v in valor.items()}
    if isinstance(valor, list):
        return [_dato_visible(v, aliases) for v in valor]
    return round(valor, 2) if isinstance(valor, float) else valor


def _pagina(request, db, curso, *, alumno_id=0, periodo=30, pregunta="", resultado=None, error=None, status=200):
    if resultado:
        resultado["fuentes_visibles"] = [{**f, "datos": _dato_visible(f["datos"], resultado["aliases"])}
                                         for f in resultado["fuentes"]]
    if request.headers.get("x-brilla-chat") == "1":
        respuesta = templates.TemplateResponse(request=request, name="teacher/_assistant_result.html", context={
            "resultado": resultado, "error": error, "periodos": assistant.PERIODOS, "periodo": periodo,
            "fuente_prefijo": "turn-" + token_hex(6) + "-",
        }, status_code=status)
        respuesta.headers["Cache-Control"] = "no-store"
        return respuesta
    respuesta = page(request, "teacher/assistant.html", {
        "page_title": "Asistente Brilla", "active_nav": "asistente", "curso": curso,
        "alumnos": reports.alumnos_del_curso(db, curso.id), "alumno_id": alumno_id,
        "periodos": assistant.PERIODOS, "periodo": periodo, "pregunta": pregunta,
        "resultado": resultado, "error": error,
    }, status_code=status)
    respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


@router.get("/asistente", name="teacher_assistant_panel")
def panel(request: Request, curso_id: int = 0, alumno_id: int = 0,
          db=Depends(get_db), usuario=Depends(docente_actual)):
    cursos = cursos_de(db, usuario)
    curso = curso_de_docente(db, usuario, curso_id) if curso_id else (cursos[0] if cursos else None)
    alumnos = reports.alumnos_del_curso(db, curso.id) if curso else []
    if alumno_id and alumno_id not in {a.id for a in alumnos}:
        raise HTTPException(status_code=404, detail="No encontramos ese alumno en el curso.")
    return page(request, "teacher/assistant_panel.html", {
        "page_title": "Asistente Brilla", "curso": curso, "cursos": cursos, "alumnos": alumnos,
        "alumno_id": alumno_id, "periodos": assistant.PERIODOS,
    })


@router.get("/cursos/{curso_id}/asistente", name="teacher_assistant")
def vista(curso_id: int, request: Request, alumno_id: int = 0, db=Depends(get_db), usuario=Depends(docente_actual)):
    curso = curso_de_docente(db, usuario, curso_id)
    if alumno_id and alumno_id not in {a.id for a in reports.alumnos_del_curso(db, curso.id)}:
        raise HTTPException(status_code=404, detail="No encontramos ese alumno en el curso.")
    return _pagina(request, db, curso, alumno_id=alumno_id)


@router.post("/cursos/{curso_id}/asistente", name="teacher_assistant_ask", dependencies=[Depends(csrf_valido)])
def preguntar(curso_id: int, request: Request, pregunta: str = Form(""), alumno_id: int = Form(0),
              periodo: int = Form(30), db=Depends(get_db), usuario=Depends(docente_actual)):
    curso = curso_de_docente(db, usuario, curso_id)
    try:
        # Existing deletion coordination also protects this in-flight read; nothing is indexed or cached.
        with jobs.usando_curso(curso.id):
            curso = curso_de_docente(db, usuario, curso_id)
            resultado = assistant.consultar(db, curso, usuario.id, pregunta, alumno_id, periodo)
            return _pagina(request, db, curso, alumno_id=alumno_id, periodo=periodo,
                           pregunta=pregunta, resultado=resultado)
    except (assistant.ConsultaInvalida, IAError) as error:
        return _pagina(request, db, curso, alumno_id=alumno_id, periodo=periodo,
                       pregunta=pregunta[:1200], error=str(error), status=400 if isinstance(error, assistant.ConsultaInvalida) else 503)

"""'Mis cursos': one summary card per course the student is enrolled in.

EXP, podium and mastery are per course (they restart in each course); Coins belong to the
student's account and accumulate across courses.
"""

import unicodedata

from sqlalchemy import func, select

from auth.deps import curso_de_alumno, cursos_de
from db.models import AgendaRepaso, Inscripcion, Intento, Tema, Usuario
from rules.calendar import ahora
from services import ledger, progress, weekly
from services import quiz as quiz_service

COLORES = ("azul", "marino", "verde", "violeta")
GENERICAS = {"curso", "especializacion", "programa", "diplomado", "taller", "para", "de", "del", "en", "la", "el",
             "los", "las", "y", "con"}


def sigla(nombre: str) -> str:
    """Two-letter badge: 'Especialización en Big Data' → 'BD', 'Python para Análisis de Datos' → 'PA'."""
    palabras = [p for p in nombre.split() if
                unicodedata.normalize("NFKD", p).encode("ascii", "ignore").decode().lower() not in GENERICAS]
    letras = "".join(p[0] for p in (palabras or nombre.split()))
    return letras[:2].upper()


def _siguiente(curso, quizzes, estado_semanal, repasos) -> dict:
    en_curso = next((f for f in quizzes if f["estado"] == "en_curso"), None)
    if en_curso:
        return {"texto": f"Continuar quiz clase {en_curso['clase'].numero}", "destino": "quiz",
                "clase_id": en_curso["clase"].id}
    nuevo = next((f for f in quizzes if f["estado"] == "nuevo"), None)
    if nuevo and curso.estado == "activo":
        return {"texto": f"Hacer el quiz de la clase {nuevo['clase'].numero}", "destino": "curso"}
    if estado_semanal == "disponible":
        return {"texto": "Hacer el reto semanal", "destino": "semanal"}
    return {"texto": "Ver resumen" if curso.estado == "cerrado" else "Entrar al curso", "destino": "curso"}


def resumen(db, alumno: Usuario) -> dict:
    momento = ahora()
    tarjetas = []
    for curso in cursos_de(db, alumno):
        curso = curso_de_alumno(db, alumno, curso.id)
        quizzes = quiz_service.lista_para_alumno(db, alumno.id, curso.id)
        podio = ledger.podio(db, curso.id)
        mio = next((f for f in podio if f["alumno_id"] == alumno.id), None)
        avance = progress.progreso_alumno(db, alumno.id, curso.id)
        repasos = db.scalar(select(func.count()).select_from(AgendaRepaso).join(Tema, Tema.id == AgendaRepaso.tema_id)
                            .where(AgendaRepaso.alumno_id == alumno.id, Tema.curso_id == curso.id,
                                   AgendaRepaso.proxima_fecha <= momento))
        semanal = weekly.actual(db, curso)
        estado_semanal = weekly.estado_para(db, alumno.id, semanal)
        docentes = db.scalars(select(Usuario).join(Inscripcion, Inscripcion.usuario_id == Usuario.id).where(
            Inscripcion.curso_id == curso.id, Inscripcion.rol_en_curso == "docente").order_by(Usuario.apellido)).all()
        ultima = db.scalar(select(func.max(Intento.creado_en)).where(
            Intento.alumno_id == alumno.id, Intento.curso_id == curso.id))
        completados = sum(1 for f in quizzes if f["estado"] == "completado")
        nuevos = sum(1 for f in quizzes if f["estado"] == "nuevo")
        en_curso = sum(1 for f in quizzes if f["estado"] == "en_curso")
        tarjetas.append({
            "curso": curso, "sigla": sigla(curso.nombre), "color": COLORES[curso.id % len(COLORES)],
            "docentes": [d.nombre_completo for d in docentes], "exp": mio["exp"] if mio else 0,
            "puesto": mio["puesto"] if mio and mio["exp"] else None, "inscritos": len(podio),
            "dominados": avance["conteo"].get("dominado", 0), "en_progreso": avance["conteo"].get("en_progreso", 0),
            "temas": len(avance["temas"]), "quizzes": len(quizzes), "completados": completados,
            "nuevos": nuevos if curso.estado == "activo" else 0, "en_curso": en_curso,
            "repasos": repasos if curso.estado == "activo" else 0, "semanal": estado_semanal, "ultima": ultima,
            "siguiente": _siguiente(curso, quizzes, estado_semanal, repasos),
        })
    activos = [t for t in tarjetas if t["curso"].estado == "activo"]
    return {
        "activos": activos, "finalizados": [t for t in tarjetas if t["curso"].estado != "activo"],
        "coins": ledger.saldo_coins(db, alumno.id),
        "pendientes": sum(t["nuevos"] + t["en_curso"] + t["repasos"] + (t["semanal"] == "disponible") for t in activos),
    }

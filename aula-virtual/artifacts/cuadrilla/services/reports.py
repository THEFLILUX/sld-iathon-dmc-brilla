"""Teacher reports (PRD M8, spec D3/D4): per class and topic, and per student over the whole malla."""

from collections import Counter, defaultdict

from sqlalchemy import func, select

from db.models import (
    Clase, ClaseTema, DominioTema, Inscripcion, Intento, Quiz, QuizItem, Reto, RetoVersion, Tema, Usuario,
)
from rules.mastery import ESTADOS
from services import ledger, progress


def alumnos_del_curso(db, curso_id: int) -> list[Usuario]:
    return list(db.scalars(select(Usuario).join(Inscripcion, Inscripcion.usuario_id == Usuario.id).where(
        Inscripcion.curso_id == curso_id, Inscripcion.rol_en_curso == "alumno", Usuario.activo.is_(True),
    ).order_by(Usuario.apellido, Usuario.nombre)))


def temas_no_cubiertos(db, curso_id: int) -> list[Tema]:
    """Topics of the malla without any class mapped (RF-08)."""
    cubiertos = select(ClaseTema.tema_id).join(Clase, Clase.id == ClaseTema.clase_id).where(
        Clase.curso_id == curso_id, Clase.estado.in_(("por_validar", "publicada")))
    return list(db.scalars(select(Tema).where(Tema.curso_id == curso_id, Tema.id.not_in(cubiertos))
                           .order_by(Tema.orden)))


def reporte_clase(db, clase: Clase, params) -> dict:
    alumnos = alumnos_del_curso(db, clase.curso_id)
    ids = [a.id for a in alumnos]
    temas = [t for t, _ in db.execute(select(Tema, ClaseTema).join(ClaseTema, ClaseTema.tema_id == Tema.id)
                                      .where(ClaseTema.clase_id == clase.id).order_by(Tema.orden)).all()]
    dominios = defaultdict(dict)
    for fila in db.scalars(select(DominioTema).where(
            DominioTema.alumno_id.in_(ids or [0]), DominioTema.tema_id.in_([t.id for t in temas] or [0]))):
        dominios[fila.tema_id][fila.alumno_id] = fila
    practicaron = db.scalar(select(func.count(func.distinct(Quiz.alumno_id)))
                            .join(QuizItem, QuizItem.quiz_id == Quiz.id)
                            .join(Intento, Intento.quiz_item_id == QuizItem.id)
                            .where(Quiz.clase_id == clase.id, Quiz.alumno_id.in_(ids or [0])))
    errores = Counter()
    for tag, reto_id in db.execute(select(Intento.error_tag, Intento.reto_id).join(Reto, Reto.id == Intento.reto_id)
                                   .where(Reto.clase_id == clase.id, Intento.resultado.in_(("incorrecto", "parcial")),
                                          Intento.error_tag != "")):
        errores[tag] += 1
    filas = []
    for tema in temas:
        conteo = Counter()
        debiles, valores = [], []
        for alumno in alumnos:
            fila = dominios[tema.id].get(alumno.id)
            estado = fila.estado if fila and fila.dominio is not None else "sin_datos"
            conteo[estado] += 1
            if fila and fila.dominio is not None:
                valores.append(fila.dominio)
            if estado == "debil":
                debiles.append(alumno)
        con_datos = len(valores)
        promedio = round(sum(valores) / con_datos, 1) if con_datos else None
        total = len(alumnos) or 1
        filas.append({
            "tema": tema, "con_datos": con_datos, "promedio": promedio, "debiles": debiles,
            "porcentajes": {e: round(100 * conteo[e] / total) for e in ESTADOS},
            # Never "dominated by the class" with few students, nor when most of them do not dominate it.
            "dominado_por_clase": con_datos >= params.participacion_minima and conteo["dominado"] * 2 >= con_datos,
            "pocos_datos": con_datos < params.participacion_minima,
        })
    ranking = sorted(filas, key=lambda f: (-f["porcentajes"]["debil"], f["promedio"] if f["promedio"] is not None else 101))
    return {"temas": filas, "ranking": [f for f in ranking if f["porcentajes"]["debil"] > 0],
            "participacion": practicaron or 0, "inscritos": len(alumnos),
            "errores": errores.most_common(6), "no_cubiertos": temas_no_cubiertos(db, clase.curso_id)}


def reporte_alumno(db, curso_id: int, alumno: Usuario) -> dict:
    datos = progress.progreso_alumno(db, alumno.id, curso_id)
    for fila in datos["temas"]:
        if not fila["visto"] and fila["estado"] == "sin_datos":
            fila["estado"] = "no_visto"
    historial = db.execute(select(Intento, Tema, RetoVersion).join(Tema, Tema.id == Intento.tema_id)
                           .join(RetoVersion, RetoVersion.id == Intento.reto_version_id)
                           .where(Intento.alumno_id == alumno.id, Intento.curso_id == curso_id)
                           .order_by(Intento.creado_en.desc()).limit(40)).all()
    errores = Counter(i.error_tag for i, _, _ in historial if i.error_tag and i.resultado != "correcto")
    return {**datos, "historial": historial, "errores": errores.most_common(5),
            "exp": ledger.exp_curso(db, alumno.id, curso_id), "coins": ledger.saldo_coins(db, alumno.id)}


def lista_alumnos(db, curso_id: int) -> list[dict]:
    alumnos = alumnos_del_curso(db, curso_id)
    ids = [a.id for a in alumnos]
    ultima = dict(db.execute(select(Intento.alumno_id, func.max(Intento.creado_en)).where(
        Intento.curso_id == curso_id, Intento.alumno_id.in_(ids or [0])).group_by(Intento.alumno_id)).all())
    promedio = dict(db.execute(select(DominioTema.alumno_id, func.avg(DominioTema.dominio))
                               .join(Tema, Tema.id == DominioTema.tema_id).where(
        Tema.curso_id == curso_id, DominioTema.alumno_id.in_(ids or [0]), DominioTema.dominio.is_not(None),
    ).group_by(DominioTema.alumno_id)).all())
    exp = {f["alumno_id"]: f for f in ledger.podio(db, curso_id)}
    return [{"alumno": a, "ultima": ultima.get(a.id), "dominio": round(float(promedio[a.id]), 1) if a.id in promedio else None,
             "exp": exp.get(a.id, {}).get("exp", 0), "puesto": exp.get(a.id, {}).get("puesto")} for a in alumnos]

"""Read-only SQL + lexical retrieval for the teacher assistant. No conversation cache or index."""

import re
import threading
import unicodedata
from collections import Counter
from datetime import timedelta

from sqlalchemy import case, func, select

from ai import assistant as generacion, privacy
from ai.anonymize import anonimizar
from ai.context import chunks_for, tokens
from db.models import (AgendaRepaso, Clase, DominioTema, Inscripcion, Intento, PerfilUsuario,
                       Quiz, TareaHecha, Tema, Usuario)
from rules.calendar import ahora
from rules import risk
from services import progress, reports
from services.params import cargar

MAX_DETALLE = 12
PERIODOS = {7: "Últimos 7 días", 30: "Últimos 30 días", 90: "Últimos 90 días", 0: "Todo el historial"}
_CUPOS = threading.BoundedSemaphore(2)
_MUTEX = threading.Lock()
_ACTIVOS = set()


class ConsultaInvalida(ValueError):
    pass


def _normal(texto):
    return "".join(c for c in unicodedata.normalize("NFKD", texto.casefold()) if not unicodedata.combining(c))


def _menciones(pregunta, alumnos):
    texto = _normal(pregunta)
    nombres = Counter(_normal(a.nombre.split()[0]) for a in alumnos)
    encontrados = []
    for alumno in alumnos:
        variantes = [alumno.nombre_completo]
        primero = alumno.nombre.split()[0]
        if nombres[_normal(primero)] == 1:
            variantes.append(primero)
        if any(re.search(r"(?<!\w)" + re.escape(_normal(n)) + r"(?!\w)", texto) for n in variantes):
            encontrados.append(alumno.id)
    return encontrados


def _fecha(valor):
    return valor.isoformat() if valor else None


def recuperar(db, curso, pregunta, alumno_id=0, periodo=30):
    """Caller MUST have authorized the course. All evidence queries are constrained to it."""
    pregunta = pregunta.strip()
    if not 8 <= len(pregunta) <= 1200:
        raise ConsultaInvalida("Escribe una consulta de entre 8 y 1.200 caracteres.")
    if periodo not in PERIODOS:
        raise ConsultaInvalida("Selecciona un periodo disponible.")
    alumnos = reports.alumnos_del_curso(db, curso.id)
    ids = [a.id for a in alumnos]
    if alumno_id and alumno_id not in ids:
        raise ConsultaInvalida("Selecciona un alumno de este curso.")
    menciones = _menciones(pregunta, alumnos)
    if alumno_id and any(i != alumno_id for i in menciones):
        raise ConsultaInvalida("La pregunta menciona otro alumno. Elige «Todo el curso» para compararlos.")
    momento, params = ahora(), cargar(db)
    desde = momento - timedelta(days=periodo) if periodo else None
    filtro = [Intento.curso_id == curso.id, Intento.alumno_id.in_(ids)]
    if desde:
        filtro.append(Intento.creado_en >= desde)
    metricas = {r.alumno_id: r for r in db.execute(select(
        Intento.alumno_id, func.count().label("total"),
        func.count().filter(Intento.estado == "completado").label("completados"),
        func.avg(case((Intento.estado == "completado", Intento.puntaje))).label("promedio"),
        func.sum(case((Intento.pistas_usadas > 0, 1), else_=0)).label("con_pistas"),
    ).where(*filtro).group_by(Intento.alumno_id))}
    ultima = dict(db.execute(select(Intento.alumno_id, func.max(Intento.creado_en)).where(
        Intento.curso_id == curso.id, Intento.alumno_id.in_(ids)).group_by(Intento.alumno_id)).all())
    dominios = {}
    for d, t in db.execute(select(DominioTema, Tema).join(Tema, Tema.id == DominioTema.tema_id).where(
            Tema.curso_id == curso.id, DominioTema.alumno_id.in_(ids)).order_by(Tema.orden)):
        dominios.setdefault(d.alumno_id, []).append((d, t))
    seleccion = [alumno_id] if alumno_id else menciones
    if len(seleccion) > MAX_DETALLE:
        raise ConsultaInvalida("Compara hasta doce alumnos por consulta o selecciona uno.")
    if not seleccion:
        # Prioritize weak topics, then students without any practice. Never label this a risk ranking.
        seleccion = [a.id for a in sorted(alumnos, key=lambda a: (
            -sum(d.estado == "debil" for d, _ in dominios.get(a.id, [])),
            a.id in ultima, ultima.get(a.id) or momento, a.id))[:MAX_DETALLE]]
    conocidos = privacy.conocidos(forzar=True)
    fuentes = []

    def agregar(titulo, datos, ruta, **params_url):
        # Sanitize all strings, including JSON profile fields and teacher-authored material.
        def limpiar(valor):
            if isinstance(valor, str):
                return anonimizar(valor, conocidos)
            if isinstance(valor, dict):
                return {k: limpiar(v) for k, v in valor.items()}
            if isinstance(valor, list):
                return [limpiar(v) for v in valor]
            return valor
        limpios = limpiar(datos)
        fuente = {"id": f"F{len(fuentes) + 1}", "titulo": titulo, "datos": limpios,
                  "ruta": ruta, "params": params_url}
        fuentes.append(fuente)

    total = sum(r.total for r in metricas.values())
    completados = sum(r.completados for r in metricas.values())
    puntuados = db.execute(select(func.count(Intento.puntaje), func.avg(Intento.puntaje)).where(
        *filtro, Intento.estado == "completado")).one()
    publicadas = list(db.scalars(select(Clase).where(Clase.curso_id == curso.id, Clase.estado == "publicada")
                                .order_by(Clase.numero)))
    agregar("Panorama del curso", {
        "curso": curso.nombre, "fecha_consulta_utc": momento.isoformat(), "periodo": PERIODOS[periodo],
        "alumnos_activos_inscritos": len(alumnos), "clases_publicadas": len(publicadas),
        "alumnos_con_intentos_en_periodo": len(metricas), "intentos_en_periodo": total,
        "intentos_completados_en_periodo": completados, "intentos_sin_calificacion_final": total - completados,
        "promedio_puntajes_0_a_100": round(float(puntuados[1]), 1) if puntuados[1] is not None else None,
        "respuestas_con_puntaje": puntuados[0], "alumnos_con_detalle_en_contexto": len(seleccion),
        "detalle_parcial_del_grupo": len(seleccion) < len(alumnos),
    }, "teacher_students", curso_id=curso.id)
    elegidos = [a for a in alumnos if a.id in seleccion]
    perfiles = {p.usuario_id: p for p in db.scalars(select(PerfilUsuario).where(PerfilUsuario.usuario_id.in_(seleccion)))}
    inscripciones = dict(db.execute(select(Inscripcion.usuario_id, Inscripcion.creado_en).where(
        Inscripcion.curso_id == curso.id, Inscripcion.usuario_id.in_(seleccion))).all())
    primera = min((c.publicada_en for c in publicadas if c.publicada_en), default=None)
    for alumno in elegidos:
        fila = metricas.get(alumno.id)
        medio = progress.dominio_promedio_en(db, alumno.id, curso.id, momento, params)
        anterior = progress.dominio_promedio_en(db, alumno.id, curso.id,
                                               momento - timedelta(days=params.riesgo_caida_dias), params)
        senales = risk.senales(ultima.get(alumno.id), max(primera, inscripciones[alumno.id]), medio, anterior,
                               momento, params) if primera else []
        quiz_filtro = [Quiz.curso_id == curso.id, Quiz.alumno_id == alumno.id]
        if desde:
            quiz_filtro.append(Quiz.creado_en >= desde)
        quizzes = dict(db.execute(select(Quiz.estado, func.count()).where(*quiz_filtro).group_by(Quiz.estado)).all())
        recientes = db.execute(select(Intento, Tema).join(Tema, Tema.id == Intento.tema_id).where(
            *filtro, Intento.alumno_id == alumno.id, Tema.curso_id == curso.id)
            .order_by(Intento.creado_en.desc(), Intento.id.desc()).limit(8)).all()
        agregar(f"Rendimiento · {alumno.nombre_completo}", {
            "alumno": alumno.alias, "periodo": PERIODOS[periodo],
            "intentos": fila.total if fila else 0, "completados": fila.completados if fila else 0,
            "promedio_puntajes_0_a_100": round(float(fila.promedio), 1) if fila and fila.promedio is not None else None,
            "intentos_con_pistas": fila.con_pistas if fila else 0,
            "quizzes_iniciados_en_periodo_por_estado": quizzes, "ultima_respuesta_utc": _fecha(ultima.get(alumno.id)),
            "senales_actuales_para_revision_docente": [s["detalle"] for s in senales],
            "umbrales_senal": {"inactividad_dias": params.riesgo_inactividad_dias,
                               "caida_dominio_puntos": params.riesgo_caida_puntos, "ventana_dias": params.riesgo_caida_dias},
            "ultimos_intentos_del_periodo": [{"fecha_utc": _fecha(i.creado_en), "tema": t.etiqueta,
                "nivel": i.nivel, "estado": i.estado, "resultado": i.resultado, "puntaje": i.puntaje,
                "pistas": i.pistas_usadas, "error_registrado": i.error_tag[:300]} for i, t in recientes],
        }, "teacher_student", curso_id=curso.id, alumno_id=alumno.id)
        temas = dominios.get(alumno.id, [])
        agregar(f"Dominio y repasos · {alumno.nombre_completo}", {
            "alumno": alumno.alias, "alcance": "Dominio vigente calculado con historial, independiente del filtro de fechas",
            "temas_con_medicion": len([d for d, _ in temas if d.dominio is not None]),
            "temas": [{"tema": t.etiqueta, "dominio_0_a_100": d.dominio, "estado": d.estado,
                       "nivel": d.nivel_actual, "actualizado_utc": _fecha(d.actualizado_en)} for d, t in temas[:40]],
            "detalle_temas_limitado": len(temas) > 40,
            "repasos_vencidos": db.scalar(select(func.count()).select_from(AgendaRepaso).join(
                Tema, Tema.id == AgendaRepaso.tema_id).where(Tema.curso_id == curso.id,
                    AgendaRepaso.alumno_id == alumno.id, AgendaRepaso.proxima_fecha <= momento)),
        }, "teacher_student", curso_id=curso.id, alumno_id=alumno.id)
        tareas = [c for c in publicadas if c.tarea]
        marcadas = dict(db.execute(select(TareaHecha.clase_id, TareaHecha.hecha_en).where(
            TareaHecha.alumno_id == alumno.id, TareaHecha.clase_id.in_([c.id for c in tareas]))).all())
        agregar(f"Tareas · {alumno.nombre_completo}", {
            "alumno": alumno.alias, "alcance": "Todas las tareas de clases publicadas, sin filtro temporal",
            "tareas_disponibles": len(tareas), "marcadas_listas": len(marcadas),
            "sin_marca_lista": len(tareas) - len(marcadas),
            "limite": "Solo declaración del alumno. No se registran entregas verificadas ni notas de tarea.",
            "ultimas_tareas": [{"clase": c.nombre, "marcada_lista_utc": _fecha(marcadas.get(c.id))} for c in tareas[-8:]],
        }, "teacher_student", curso_id=curso.id, alumno_id=alumno.id)
        perfil = perfiles.get(alumno.id)
        agregar(f"Perfil y experiencia · {alumno.nombre_completo}", {
            "alumno": alumno.alias, "perfil": {k: v for k, v in (perfil.datos if perfil else {}).items()
                if k in ("situacion", "carrera", "estado_estudios", "ocupacion", "sector", "experiencia_anios",
                         "ingreso_dmc", "cursos_previos", "herramientas", "objetivo", "horas_semana")},
            "revisado_por_titular": bool(perfil and perfil.confirmado_en),
            "actualizado_utc": _fecha(perfil.actualizado_en) if perfil else None,
            "limite": "Contexto declarado; no equivale a competencias, matrículas o certificados acreditados.",
        }, "teacher_student_profile", curso_id=curso.id, alumno_id=alumno.id)
    # Retrieve relevant portions across every published class, not just the beginning of one file.
    consulta = pregunta + " " + " ".join(t.etiqueta for i in seleccion for d, t in dominios.get(i, []) if d.estado == "debil")
    terminos = tokens(_normal(consulta))
    malla = list(db.scalars(select(Tema).where(Tema.curso_id == curso.id).order_by(Tema.orden)))
    relevantes = sorted(malla, key=lambda t: (-len(terminos & tokens(_normal(t.etiqueta + " " + t.objetivo))), t.orden))[:12]
    if relevantes:
        agregar("Malla y objetivos del curso", {"temas_totales": len(malla), "detalle_parcial": len(malla) > 12,
            "temas_relevantes": [{"tema": t.etiqueta, "objetivo": t.objetivo[:1000], "nivel_maximo": t.nivel_maximo,
                "fundamental": t.es_fundamental, "rubrica": t.rubrica if t.nivel_maximo == "maestria" else []} for t in relevantes],
            "limite": "Objetivos de formación; no acreditan dominio del estudiante."},
            "teacher_curriculum", curso_id=curso.id)
    fragmentos = []
    for clase in publicadas:
        for indice, fragmento in enumerate(chunks_for(clase.transcript_anon or clase.transcript or "", size=1800)):
            puntaje = len(terminos & tokens(_normal(fragmento)))
            if puntaje:
                fragmentos.append((puntaje, clase.numero, indice, clase, fragmento))
    for _, _, indice, clase, fragmento in sorted(fragmentos, key=lambda f: (-f[0], -f[1], f[2]))[:4]:
        agregar(f"{clase.nombre} · fragmento {indice + 1}", {"clase": clase.nombre, "fecha": _fecha(clase.fecha),
            "fragmento": indice + 1, "texto": fragmento, "limite": "Contenido enseñado, no evidencia de rendimiento."},
            "teacher_class", clase_id=clase.id)
    # Replace authorized identities with existing AI aliases before applying the global privacy guard.
    for alumno in sorted(alumnos, key=lambda a: -len(a.nombre_completo)):
        variantes = [alumno.nombre_completo]
        if sum(_normal(a.nombre.split()[0]) == _normal(alumno.nombre.split()[0]) for a in alumnos) == 1:
            variantes.append(alumno.nombre.split()[0])
        for variante in variantes:
            # Accent-insensitive offsets remain stable for Spanish characters.
            patrones = list(re.finditer(r"(?<!\w)" + re.escape(_normal(variante)) + r"(?!\w)", _normal(pregunta)))
            for m in reversed(patrones):
                pregunta = pregunta[:m.start()] + alumno.alias + pregunta[m.end():]
    pregunta = anonimizar(pregunta, conocidos)
    alcance = {"fecha_consulta_utc": momento.isoformat(), "periodo_puntajes": PERIODOS[periodo],
               "alumnos_inscritos": len(alumnos), "alumnos_con_detalle": [a.alias for a in elegidos],
               "seleccion": "solicitados" if alumno_id or menciones else "hasta doce, priorizando temas débiles y falta de práctica",
               "sin_notas_oficiales_ni_entregas_verificadas": True}
    return {"fuentes": fuentes, "alcance": alcance, "pregunta_anon": pregunta, "momento": momento,
            "alumnos": alumnos, "aliases": {a.alias: a.nombre_completo for a in elegidos},
            "alumno_id": alumno_id, "periodo": periodo}


def consultar(db, curso, docente_id, pregunta, alumno_id=0, periodo=30):
    with _MUTEX:
        if docente_id in _ACTIVOS:
            raise ConsultaInvalida("Ya hay una consulta tuya en proceso. Espera a que termine.")
        if not _CUPOS.acquire(blocking=False):
            raise ConsultaInvalida("Brilla está atendiendo otras consultas. Inténtalo en unos momentos.")
        _ACTIVOS.add(docente_id)
    try:
        contexto = recuperar(db, curso, pregunta, alumno_id, periodo)
        respuesta = generacion.responder(contexto["pregunta_anon"], contexto["fuentes"], contexto["alcance"],
                                         referencia=f"curso:{curso.id}:asistente")
        # Re-identify only aliases from the authorized retrieved set; Jinja escapes every result.
        for lista in (respuesta["hallazgos"], respuesta["recomendaciones"]):
            for item in lista:
                item["texto"] = mostrar_aliases(item["texto"], contexto["aliases"])
        respuesta["limites"] = [mostrar_aliases(t, contexto["aliases"]) for t in respuesta["limites"]]
        return {**contexto, "respuesta": respuesta}
    finally:
        with _MUTEX:
            _ACTIVOS.discard(docente_id)
            _CUPOS.release()


def mostrar_aliases(texto, aliases):
    for alias in sorted(aliases, key=len, reverse=True):
        texto = re.sub(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", lambda _: aliases[alias], texto)
    return texto

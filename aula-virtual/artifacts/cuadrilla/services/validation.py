"""Teacher validation of the quiz (PRD M2, spec D2): approve, edit, replace, reject; one hour; always 4."""

from datetime import timedelta

from sqlalchemy import func, select

from ai import jobs
from db.models import AuditoriaReto, Clase, Curso, Intento, Reto, RetoReporte, RetoVersion, Tema
from rules.calendar import ahora
from rules.levels import NIVELES
from services import messages
from services.classes import VALIDACION_MINUTOS, ClaseInvalida, guardar_versiones, tema_dict

USABLES = ("aprobado", "editado")


def auditar(db, reto_id: int, accion: str, usuario_id: int | None, detalle: str = "") -> None:
    db.add(AuditoriaReto(reto_id=reto_id, accion=accion, usuario_id=usuario_id, detalle=detalle[:500]))


def versiones_vigentes(db, reto: Reto) -> dict[str, RetoVersion]:
    filas = db.scalars(select(RetoVersion).where(
        RetoVersion.reto_id == reto.id, RetoVersion.revision == reto.revision,
    ))
    return {v.nivel: v for v in sorted(filas, key=lambda v: NIVELES.index(v.nivel))}


def retos_de_clase(db, clase_id: int, *, incluir_rechazados: bool = False) -> list[Reto]:
    consulta = select(Reto).where(Reto.clase_id == clase_id)
    if not incluir_rechazados:
        consulta = consulta.where(Reto.estado != "rechazado")
    return list(db.scalars(consulta.order_by(Reto.uso.desc(), Reto.posicion.nulls_last(), Reto.id)))


def _bloquear_clase(db, clase_id: int) -> Clase:
    clase = db.scalar(select(Clase).where(Clase.id == clase_id).with_for_update()
                      .execution_options(populate_existing=True))
    if clase is None:
        raise ClaseInvalida("No encontramos la clase.")
    return clase


def aprobar(db, reto: Reto, usuario_id: int) -> None:
    if reto.estado not in ("propuesto",):
        raise ClaseInvalida("Este reto ya tiene una decisión.")
    reto.estado = "aprobado"
    auditar(db, reto.id, "aprobo", usuario_id)


def _texto_lista(valor: str) -> list[str]:
    return [linea.strip() for linea in (valor or "").splitlines() if linea.strip()]


def validar_edicion(tipo: str, datos: dict) -> dict:
    """Checks a teacher-written or edited version with the same rules as the generator."""
    enunciado = (datos.get("enunciado") or "").strip()
    if len(enunciado) < 10:
        raise ClaseInvalida("El enunciado necesita al menos 10 caracteres.")
    pistas = [(datos.get(f"pista_{i}") or "").strip() for i in (1, 2, 3)]
    limpio = {"tipo": tipo, "enunciado": enunciado[:4000], "explicacion": (datos.get("explicacion") or "").strip()[:3000],
              "pistas": [p[:1000] for p in pistas], "opciones": [], "respuesta_correcta": "",
              "respuestas_aceptadas": [], "puntos_clave": [], "casos_de_prueba": []}
    if not limpio["explicacion"]:
        raise ClaseInvalida("Escribe una explicación breve de la respuesta.")
    if tipo == "alternativas":
        opciones = _texto_lista(datos.get("opciones", ""))
        correcta = (datos.get("respuesta_correcta") or "").strip()
        if not 3 <= len(opciones) <= 6 or len({o.casefold() for o in opciones}) != len(opciones):
            raise ClaseInvalida("Escribe de 3 a 6 alternativas distintas, una por línea.")
        if correcta not in opciones:
            raise ClaseInvalida("La respuesta correcta debe ser exactamente una de las alternativas.")
        limpio.update(opciones=opciones, respuesta_correcta=correcta)
    elif tipo == "completar":
        aceptadas = list(dict.fromkeys(
            [(datos.get("respuesta_correcta") or "").strip(), *_texto_lista(datos.get("respuestas_aceptadas", ""))]))
        aceptadas = [a for a in aceptadas if a]
        if not aceptadas:
            raise ClaseInvalida("Indica la respuesta correcta del espacio en blanco.")
        limpio.update(respuesta_correcta=aceptadas[0], respuestas_aceptadas=aceptadas)
    elif tipo in ("definir", "caso"):
        puntos = _texto_lista(datos.get("puntos_clave", ""))
        if not 2 <= len(puntos) <= 4:
            raise ClaseInvalida("Una respuesta abierta necesita de 2 a 4 puntos clave, uno por línea.")
        limpio.update(puntos_clave=puntos, respuesta_correcta=(datos.get("respuesta_correcta") or "").strip()[:3000])
    else:
        raise ClaseInvalida("Tipo de reto no disponible en esta versión.")
    return limpio


def editar(db, reto: Reto, usuario_id: int, nivel: str, datos: dict, error_comun: str | None = None) -> None:
    """Before publication edits in place; afterwards a new revision keeps past attempts on the original."""
    vigentes = versiones_vigentes(db, reto)
    tipo = datos.get("tipo") or (vigentes[nivel].tipo if nivel in vigentes else "alternativas")
    nueva = validar_edicion(tipo, datos)
    clase = db.get(Clase, reto.clase_id) if reto.clase_id else None
    usada = db.scalar(select(func.count()).select_from(Intento).where(Intento.reto_id == reto.id))
    if (clase is not None and clase.estado == "publicada") or usada:
        revision = reto.revision + 1
        copia = {n: {c: getattr(v, c) for c in ("tipo", "enunciado", "opciones", "respuesta_correcta",
                                                 "respuestas_aceptadas", "puntos_clave", "casos_de_prueba",
                                                 "explicacion", "pistas")}
                 for n, v in vigentes.items()}
        copia[nivel] = nueva
        reto.revision = revision
        guardar_versiones(db, reto, copia, revision)
    elif nivel in vigentes:
        for campo, valor in nueva.items():
            setattr(vigentes[nivel], campo, valor)
    else:
        guardar_versiones(db, reto, {nivel: nueva})
    if error_comun is not None:
        reto.error_comun = error_comun.strip()[:600]
    if reto.estado in ("propuesto", "aprobado", "retirado"):
        reto.estado = "editado"
    auditar(db, reto.id, "edito", usuario_id, f"Versión {nivel}")


def _placeholder(db, reto: Reto, usuario_id: int | None, accion: str) -> Reto:
    nuevo = Reto(curso_id=reto.curso_id, clase_id=reto.clase_id, tema_id=reto.tema_id, uso=reto.uso,
                 posicion=reto.posicion, estado="generando", reemplaza_a=reto.id, origen="ia")
    db.add(nuevo)
    db.flush()
    auditar(db, nuevo.id, "genero", usuario_id, f"Reemplazo del reto {reto.id} ({accion})")
    jobs.al_confirmar(db, generar_reemplazo, nuevo.id, curso_id=nuevo.curso_id)
    return nuevo


def rechazar(db, reto: Reto, usuario_id: int | None) -> Reto | None:
    """Discard and generate another in the same position. The position never stays empty."""
    if reto.estado in ("rechazado", "generando"):
        raise ClaseInvalida("Este reto ya fue rechazado o se está generando.")
    reto.estado = "rechazado"
    auditar(db, reto.id, "rechazo", usuario_id)
    db.flush()
    if reto.uso == "clase" and reto.posicion is not None:
        return _placeholder(db, reto, usuario_id, "rechazo")
    return None


def reintentar_generacion(db, reto: Reto, usuario_id: int) -> Reto:
    if reto.estado != "error":
        raise ClaseInvalida("Solo se reintenta un reto con error.")
    reto.estado = "rechazado"
    db.flush()
    return _placeholder(db, reto, usuario_id, "reintento")


def crear_propio(db, clase: Clase, usuario_id: int, *, tema_id: int, nivel: str, tipo: str, datos: dict,
                 error_comun: str, reemplaza: Reto | None = None) -> Reto:
    """Teacher's own challenge: takes the replaced position or stays in reserve; the AI fills other levels."""
    tema = db.get(Tema, tema_id)
    if tema is None or tema.curso_id != clase.curso_id:
        raise ClaseInvalida("Elige un tema de la malla del curso.")
    if nivel not in NIVELES or NIVELES.index(nivel) > NIVELES.index(tema.nivel_maximo):
        raise ClaseInvalida("El nivel supera el nivel máximo del tema.")
    version = validar_edicion(tipo, datos)
    posicion = None
    if reemplaza is not None:
        if reemplaza.estado in ("rechazado", "generando"):
            raise ClaseInvalida("Ese reto ya no ocupa la posición.")
        posicion = reemplaza.posicion
        reemplaza.estado = "rechazado"
        auditar(db, reemplaza.id, "reemplazo", usuario_id, "Reemplazado por un reto del docente")
        db.flush()
    reto = Reto(curso_id=clase.curso_id, clase_id=clase.id, tema_id=tema_id, uso="clase", posicion=posicion,
                origen="docente", estado="aprobado", error_comun=error_comun.strip()[:600], fuente_tipo="docente",
                fuente_ref="Reto escrito por el docente", reemplaza_a=reemplaza.id if reemplaza else None)
    db.add(reto)
    db.flush()
    guardar_versiones(db, reto, {nivel: version})
    auditar(db, reto.id, "agrego", usuario_id, "Posición " + str(posicion) if posicion else "Reserva")
    jobs.al_confirmar(db, completar_versiones, reto.id, nivel, curso_id=reto.curso_id)
    return reto


def publicar(db, clase_id: int, usuario_id: int | None) -> bool:
    """Publish now, or by default when the hour ends. Undecided challenges are approved by default."""
    curso_id = db.scalar(select(Clase.curso_id).where(Clase.id == clase_id))
    if curso_id is None:
        return False
    db.scalar(select(Curso.id).where(Curso.id == curso_id).with_for_update(read=True, key_share=True))
    clase = _bloquear_clase(db, clase_id)
    if clase is None or clase.estado != "por_validar":
        return False
    curso = db.get(Curso, clase.curso_id)
    for reto in db.scalars(select(Reto).where(Reto.clase_id == clase.id, Reto.estado == "propuesto")):
        reto.estado = "aprobado"
        auditar(db, reto.id, "aprobado_por_defecto", usuario_id,
                "Publicación del docente" if usuario_id else "Venció la hora de validación")
    clase.estado, clase.publicada_en = "publicada", ahora()
    if curso.estado == "activo":
        messages.encolar_clase_nueva(db, clase)
    return True


def publicar_vencidas(db) -> int:
    momento = ahora()
    filas = db.execute(select(Clase.id, Clase.curso_id).where(
        Clase.estado == "por_validar", Clase.vence_validacion_en <= momento,
    )).all()
    publicadas = 0
    for clase_id, curso_id in filas:
        disponible = db.scalar(select(Curso.id).where(Curso.id == curso_id)
                               .with_for_update(read=True, key_share=True, skip_locked=True))
        if disponible is None:
            continue
        clase = db.scalar(select(Clase).where(Clase.id == clase_id).with_for_update(skip_locked=True))
        if clase is not None:
            publicadas += int(publicar(db, clase_id, None))
    # Replacements created after publication follow the same one-hour default.
    filas_retos = db.execute(select(Reto.id, Reto.curso_id).where(
        Reto.estado == "propuesto", Reto.vence_validacion_en.is_not(None), Reto.vence_validacion_en <= momento,
    )).all()
    for reto_id, curso_id in filas_retos:
        disponible = db.scalar(select(Curso.id).where(Curso.id == curso_id)
                               .with_for_update(read=True, key_share=True, skip_locked=True))
        if disponible is None:
            continue
        reto = db.scalar(select(Reto).where(Reto.id == reto_id).with_for_update(skip_locked=True)
                         .execution_options(populate_existing=True))
        if reto is None or reto.estado != "propuesto":
            continue
        reto.estado = "aprobado"
        auditar(db, reto.id, "aprobado_por_defecto", None, "Venció la hora de validación")
    return publicadas


def reactivar(db, reto: Reto, usuario_id: int) -> None:
    if reto.estado != "retirado":
        raise ClaseInvalida("El reto no está retirado.")
    reto.estado = "aprobado"
    db.execute(RetoReporte.__table__.delete().where(RetoReporte.reto_id == reto.id))
    auditar(db, reto.id, "reactivo", usuario_id)


def _evitar(db, clase_id) -> list[str]:
    return list(db.scalars(select(RetoVersion.enunciado).join(Reto, Reto.id == RetoVersion.reto_id).where(
        Reto.clase_id == clase_id, RetoVersion.nivel == "intermedio")))


def generar_reemplazo(reto_id: int) -> None:
    from ai.components import generar_reemplazo as generar
    from ai.llm import mensaje_seguro
    from db.session import SessionLocal

    with SessionLocal() as db:
        reto = db.get(Reto, reto_id)
        if reto is None or reto.estado != "generando":
            return
        clase = db.get(Clase, reto.clase_id)
        tema = tema_dict(db.get(Tema, reto.tema_id))
        transcript, material = clase.transcript_anon or "", clase.recursos_texto or ""
        evitar, posicion = _evitar(db, clase.id), reto.posicion
    try:
        generado = generar(tema, transcript, material, posicion, evitar, referencia=f"reto:{reto_id}")
    except Exception as error:
        with SessionLocal.begin() as db:
            reto = db.get(Reto, reto_id)
            if reto.estado == "generando":
                reto.estado, reto.error_mensaje = "error", mensaje_seguro(error)
        return
    with SessionLocal.begin() as db:
        reto = db.scalar(select(Reto).where(Reto.id == reto_id).with_for_update())
        if reto.estado != "generando":
            return
        clase = db.get(Clase, reto.clase_id)
        reto.error_comun, reto.fuente_tipo = generado.error_comun, generado.fuente_tipo
        reto.fuente_ref, reto.avisos = generado.fuente_ref, generado.avisos
        reto.estado = "propuesto"
        if clase.estado == "publicada":
            reto.vence_validacion_en = ahora() + timedelta(minutes=VALIDACION_MINUTOS)
        guardar_versiones(db, reto, generado.versiones)


def completar_versiones(reto_id: int, nivel_docente: str) -> None:
    from ai.components import completar_niveles
    from config import settings
    from db.session import SessionLocal

    if not settings.ai_enabled:
        return
    with SessionLocal() as db:
        reto = db.get(Reto, reto_id)
        if reto is None:
            return
        clase = db.get(Clase, reto.clase_id)
        tema = tema_dict(db.get(Tema, reto.tema_id))
        version = versiones_vigentes(db, reto).get(nivel_docente)
        if version is None:
            return
        datos = {c: getattr(version, c) for c in ("tipo", "enunciado", "opciones", "respuesta_correcta",
                                                   "respuestas_aceptadas", "puntos_clave", "explicacion", "pistas")}
        revision, transcript, posicion = reto.revision, clase.transcript_anon or "", reto.posicion
    try:
        nuevas = completar_niveles(tema, datos, nivel_docente, transcript, posicion, referencia=f"reto:{reto_id}")
    except Exception:
        nuevas = {}
    with SessionLocal.begin() as db:
        reto = db.scalar(select(Reto).where(Reto.id == reto_id).with_for_update())
        if reto is None or reto.revision != revision:
            return
        existentes = set(versiones_vigentes(db, reto))
        faltan = {n: v for n, v in nuevas.items() if n not in existentes}
        guardar_versiones(db, reto, faltan)
        if not faltan:
            reto.avisos = (reto.avisos or []) + ["Solo existe la versión escrita por el docente."]


def auditoria(db, reto_id: int):
    return db.scalars(select(AuditoriaReto).where(AuditoriaReto.reto_id == reto_id).order_by(AuditoriaReto.fecha)).all()


def resumen_validacion(db, clase: Clase) -> dict:
    retos = retos_de_clase(db, clase.id)
    return {
        "base": [r for r in retos if r.uso == "clase" and r.posicion is not None],
        "reserva": [r for r in retos if r.uso == "clase" and r.posicion is None],
        "previo": [r for r in retos if r.uso == "previo"],
    }


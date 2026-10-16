"""Class quiz (PRD M3-M5, spec §7.2): 3 class challenges and 1 REPASO, one at a time, adaptive by topic.

The quiz is fixed when the student presses "Generar"; the level (and so the version)
of each challenge is decided when it is shown, from the stored level and the results
of earlier challenges of the same topic in this quiz.
"""

from datetime import timedelta

from sqlalchemy import func, select

from db.models import (
    VERIFICABLES, AgendaRepaso, Clase, ClaseTema, Intento, Movimiento, Quiz, QuizItem, Reto, RetoVersion, Tema,
    Usuario,
)
from rules import levels, scoring
from rules.calendar import ahora
from rules.selection import elegir_retos_clase
from services import attempts, ledger, messages, progress, review
from services.validation import USABLES, versiones_vigentes

RETOS_DE_CLASE = 3


class QuizError(ValueError):
    pass


def clases_publicadas(db, curso_id: int) -> list[Clase]:
    return list(db.scalars(select(Clase).where(Clase.curso_id == curso_id, Clase.estado == "publicada")
                           .order_by(Clase.numero.desc())))


def lista_para_alumno(db, alumno_id: int, curso_id: int) -> list[dict]:
    """A1: one row per published class, newest first: Nuevo, En curso n/4 or Completado."""
    clases = clases_publicadas(db, curso_id)
    quizzes = {q.clase_id: q for q in db.scalars(select(Quiz).where(
        Quiz.alumno_id == alumno_id, Quiz.curso_id == curso_id))}
    respondidos = dict(db.execute(select(QuizItem.quiz_id, func.count(Intento.id))
                                  .join(Intento, Intento.quiz_item_id == QuizItem.id)
                                  .where(QuizItem.quiz_id.in_([q.id for q in quizzes.values()] or [0]))
                                  .group_by(QuizItem.quiz_id)).all())
    totales = dict(db.execute(select(QuizItem.quiz_id, func.count()).where(
        QuizItem.quiz_id.in_([q.id for q in quizzes.values()] or [0])).group_by(QuizItem.quiz_id)).all())
    filas = []
    for clase in clases:
        quiz = quizzes.get(clase.id)
        estado = "nuevo" if quiz is None else quiz.estado
        filas.append({"clase": clase, "quiz": quiz, "estado": estado,
                      "respondidos": respondidos.get(quiz.id, 0) if quiz else 0,
                      "total": totales.get(quiz.id, 4) if quiz else 4})
    return filas


def usables(db, clase_id: int, uso: str = "clase") -> list[Reto]:
    return list(db.scalars(select(Reto).where(Reto.clase_id == clase_id, Reto.uso == uso,
                                              Reto.estado.in_(USABLES)).order_by(Reto.posicion.nulls_last(), Reto.id)))


def _dominios(db, alumno_id: int, tema_ids) -> dict:
    from db.models import DominioTema
    return {f.tema_id: f.dominio for f in db.scalars(select(DominioTema).where(
        DominioTema.alumno_id == alumno_id, DominioTema.tema_id.in_(list(tema_ids) or [0])))}


def _repaso(db, alumno_id: int, clase: Clase, params) -> tuple[Reto, bool] | None:
    """Class 1: the prior-knowledge challenge. From class 2: the most overdue review of the agenda."""
    if clase.numero == 1:
        previos = usables(db, clase.id, "previo")
        return (previos[0], True) if previos else None
    momento = ahora()
    vencidos = db.scalars(select(AgendaRepaso).join(Tema, Tema.id == AgendaRepaso.tema_id).where(
        AgendaRepaso.alumno_id == alumno_id, Tema.curso_id == clase.curso_id, AgendaRepaso.proxima_fecha <= momento,
    ).order_by(AgendaRepaso.proxima_fecha)).all()
    for fila in vencidos:
        candidatos = list(db.scalars(select(Reto).join(Clase, Clase.id == Reto.clase_id).where(
            Reto.tema_id == fila.tema_id, Reto.uso == "clase", Reto.estado.in_(USABLES),
            Clase.estado == "publicada", Clase.curso_id == clase.curso_id, Clase.numero < clase.numero,
        ).order_by(Reto.id)))
        if not candidatos:
            continue
        vistos = dict(db.execute(select(Intento.reto_id, func.max(Intento.creado_en)).where(
            Intento.alumno_id == alumno_id, Intento.reto_id.in_([r.id for r in candidatos]),
        ).group_by(Intento.reto_id)).all())
        limite = momento - timedelta(days=params.banco_repetir_dias)
        frescos = [r for r in candidatos if r.id not in vistos or vistos[r.id] < limite]
        elegido = frescos[0] if frescos else min(candidatos, key=lambda r: vistos[r.id])
        return elegido, False
    return None


def generar(db, alumno: Usuario, clase: Clase, params) -> Quiz:
    existente = db.scalar(select(Quiz).where(Quiz.alumno_id == alumno.id, Quiz.clase_id == clase.id))
    if existente:
        return existente
    db.scalar(select(Usuario.id).where(Usuario.id == alumno.id).with_for_update())
    existente = db.scalar(select(Quiz).where(Quiz.alumno_id == alumno.id, Quiz.clase_id == clase.id))
    if existente:
        return existente
    retos = usables(db, clase.id)
    por_id = {r.id: r for r in retos}
    base = [{"id": r.id, "posicion": r.posicion, "tema_id": r.tema_id} for r in retos if r.posicion is not None]
    reservas = [{"id": r.id, "posicion": None, "tema_id": r.tema_id} for r in retos if r.posicion is None]
    elegidos, sobrantes = elegir_retos_clase(base, _dominios(db, alumno.id, {r.tema_id for r in retos}),
                                             RETOS_DE_CLASE)
    extra = sobrantes + reservas
    while len(elegidos) < RETOS_DE_CLASE and extra:
        elegidos.append(extra.pop(0))
    filas = [(por_id[r["id"]], "clase", False) for r in elegidos]
    repaso = _repaso(db, alumno.id, clase, params)
    if repaso:
        filas.append((repaso[0], "repaso", repaso[1]))
    elif extra:
        filas.append((por_id[extra.pop(0)["id"]], "clase", False))
    if not filas:
        raise QuizError("Esta clase todavía no tiene retos disponibles. Vuelve más tarde.")
    principal = db.scalar(select(ClaseTema.tema_id).where(ClaseTema.clase_id == clase.id)
                          .order_by(ClaseTema.confianza.desc(), ClaseTema.tema_id).limit(1))
    tema_principal = db.get(Tema, principal) if principal else db.get(Tema, filas[0][0].tema_id)
    quiz = Quiz(alumno_id=alumno.id, curso_id=clase.curso_id, clase_id=clase.id, tiene_repaso=repaso is not None,
                tema_principal_id=tema_principal.id,
                nivel_coins=progress.nivel_guardado(db, alumno.id, tema_principal),
                puesto_inicial=ledger.puesto(db, clase.curso_id, alumno.id))
    db.add(quiz)
    db.flush()
    for orden, (reto, etiqueta, es_previo) in enumerate(filas, start=1):
        db.add(QuizItem(quiz_id=quiz.id, orden=orden, reto_id=reto.id, etiqueta=etiqueta, es_previo=es_previo))
    db.flush()
    return quiz


def items(db, quiz: Quiz) -> list[QuizItem]:
    return list(db.scalars(select(QuizItem).where(QuizItem.quiz_id == quiz.id).order_by(QuizItem.orden)))


def intento_de(db, item: QuizItem) -> Intento | None:
    return db.scalar(select(Intento).where(Intento.quiz_item_id == item.id))


def item_actual(db, quiz: Quiz) -> QuizItem | None:
    lista = items(db, quiz)
    return lista[quiz.indice_actual] if quiz.indice_actual < len(lista) else None


def etiqueta(quiz: Quiz, item: QuizItem, total: int, numero_clase: int) -> dict:
    """Corner label and counter: CLASE n with 1/3..3/3 then REPASO; without review 1/4..4/4."""
    if item.etiqueta == "repaso":
        return {"esquina": "REPASO", "contador": None}
    de = total - 1 if quiz.tiene_repaso else total
    return {"esquina": f"CLASE {numero_clase}", "contador": f"{item.orden}/{de}"}


def _reemplazo_si_retirado(db, quiz: Quiz, item: QuizItem) -> None:
    reto = db.get(Reto, item.reto_id)
    if reto.estado in USABLES or item.reto_version_id is not None:
        return
    en_quiz = {i.reto_id for i in items(db, quiz)}
    candidatos = [r for r in usables(db, quiz.clase_id) if r.id not in en_quiz]
    if candidatos:
        item.reto_id, item.pistas_usadas = candidatos[0].id, 0


def preparar(db, alumno: Usuario, quiz: Quiz, item: QuizItem) -> tuple[RetoVersion, Reto, Tema]:
    """Decide the level and version when the challenge is shown. Stable afterwards (resume)."""
    if item.reto_version_id is None:
        _reemplazo_si_retirado(db, quiz, item)
        reto = db.get(Reto, item.reto_id)
        tema = db.get(Tema, reto.tema_id)
        versiones = versiones_vigentes(db, reto)
        if not versiones:
            raise QuizError("Este reto no tiene contenido disponible. Avísale a tu docente con «Reportar error».")
        guardado = progress.nivel_guardado(db, alumno.id, tema)
        if item.es_previo:
            objetivo = "basico"
        elif item.etiqueta == "repaso":
            objetivo = guardado
        else:
            previos = []
            for anterior in items(db, quiz):
                if anterior.orden >= item.orden or anterior.nivel is None:
                    continue
                if db.get(Reto, anterior.reto_id).tema_id != tema.id:
                    continue
                intento = intento_de(db, anterior)
                if intento is not None:
                    previos.append((anterior.nivel, intento.resultado, intento.pistas_usadas))
            objetivo = levels.siguiente_en_quiz(guardado, tema.nivel_maximo, previos)
        nivel = levels.mas_cercano(objetivo, versiones.keys())
        item.nivel, item.reto_version_id, item.presentado_en = nivel, versiones[nivel].id, ahora()
        db.flush()
    reto = db.get(Reto, item.reto_id)
    return db.get(RetoVersion, item.reto_version_id), reto, db.get(Tema, reto.tema_id)


def _bloquear(db, quiz_id: int) -> Quiz:
    return db.scalar(select(Quiz).where(Quiz.id == quiz_id).with_for_update()
                     .execution_options(populate_existing=True))


def _actual_bloqueado(db, quiz: Quiz, item_id: int) -> QuizItem:
    quiz = _bloquear(db, quiz.id)
    if quiz.estado == "completado":
        raise QuizError("Este quiz ya está completado.")
    item = item_actual(db, quiz)
    if item is None or item.id != item_id:
        raise QuizError("Ese reto ya no es el actual. Recarga la página.")
    return item


def pedir_pista(db, quiz: Quiz, item_id: int) -> QuizItem:
    item = _actual_bloqueado(db, quiz, item_id)
    if intento_de(db, item) is None and item.pistas_usadas < 3:
        item.pistas_usadas += 1
    return item


def ver_solucion(db, quiz: Quiz, item_id: int) -> QuizItem:
    """The full solution only after the third hint, or after having answered."""
    item = _actual_bloqueado(db, quiz, item_id)
    if item.pistas_usadas < 3 and intento_de(db, item) is None:
        raise QuizError("La solución se muestra después de la tercera pista o de intentarlo.")
    item.solucion_vista = True
    return item


def responder(db, alumno: Usuario, quiz: Quiz, item_id: int, respuesta: str, envio_id: str, params) -> tuple[Intento, bool]:
    """Returns (attempt, needs_ai). Verifiable answers are graded and recorded here."""
    item = _actual_bloqueado(db, quiz, item_id)
    existente = intento_de(db, item)
    if existente is not None:
        return existente, False
    version, reto, _ = preparar(db, alumno, quiz, item)
    respuesta = attempts.validar_respuesta(version, respuesta, params)
    es_repaso = item.etiqueta == "repaso"
    intento = attempts.crear_intento(
        db, alumno=alumno, curso_id=quiz.curso_id, reto=reto, version=version,
        origen="repaso" if es_repaso and not item.es_previo else "quiz", es_repaso=es_repaso,
        cuenta_para_dominio=not item.es_previo, respuesta=respuesta, pistas=item.pistas_usadas,
        presentado_en=item.presentado_en, envio_id=envio_id, quiz_item_id=item.id,
    )
    if version.tipo in VERIFICABLES:
        resultado = attempts.calificar_verificable(version, respuesta)
        attempts.finalizar(db, intento, resultado,
                           attempts.feedback_verificable(version, reto, resultado, item.pistas_usadas), params)
        return intento, False
    return intento, True


def seguir(db, quiz: Quiz, params) -> bool:
    """'Seguir': next challenge, or close the quiz after the last one. Returns True when completed."""
    quiz = _bloquear(db, quiz.id)
    if quiz.estado == "completado":
        return True
    item = item_actual(db, quiz)
    intento = intento_de(db, item) if item else None
    if intento is None:
        raise QuizError("Responde el reto antes de seguir.")
    if intento.estado == "evaluando":
        raise QuizError("Todavía estamos revisando tu respuesta. Espera unos segundos.")
    quiz.indice_actual += 1
    if quiz.indice_actual >= len(items(db, quiz)):
        cerrar(db, quiz, params)
        return True
    return False


def cerrar(db, quiz: Quiz, params) -> None:
    """Bonuses, quiz Coins, agenda, podium message and anomalies. Safe to call again after a late grading."""
    lista = items(db, quiz)
    intentos = [intento_de(db, item) for item in lista]
    if any(i is None for i in intentos):
        return
    alumno = db.get(Usuario, quiz.alumno_id)
    resultados = [(i.resultado, i.pistas_usadas) for i in intentos]
    bonos = scoring.bonos_quiz(resultados, len(lista), params)
    ledger.registrar(db, alumno_id=alumno.id, curso_id=quiz.curso_id, tipo="EXP", origen="quiz",
                     referencia=f"quiz:{quiz.id}:completado", cantidad=bonos["completado"])
    ledger.registrar(db, alumno_id=alumno.id, curso_id=quiz.curso_id, tipo="EXP", origen="quiz",
                     referencia=f"quiz:{quiz.id}:perfecto", cantidad=bonos["perfecto"])
    verificables = [(i.resultado, i.pistas_usadas) for i in intentos if i.tipo in VERIFICABLES and i.resultado]
    quiz.puntaje_verificable = scoring.puntaje_quiz(verificables)
    coins = scoring.coins_quiz(quiz.puntaje_verificable, quiz.nivel_coins, params)
    if coins and not alumno.coins_pausadas:
        ledger.registrar(db, alumno_id=alumno.id, curso_id=quiz.curso_id, tipo="COINS", origen="quiz",
                         referencia=f"quiz:{quiz.id}", cantidad=coins)
    db.flush()
    quiz.exp_obtenido = int(db.scalar(select(func.coalesce(func.sum(Movimiento.cantidad), 0)).where(
        Movimiento.alumno_id == alumno.id, Movimiento.tipo == "EXP",
        Movimiento.referencia.in_([f"quiz_item:{i.id}" for i in lista] +
                                  [f"quiz:{quiz.id}:completado", f"quiz:{quiz.id}:perfecto"]))))
    quiz.coins_obtenidas = int(db.scalar(select(func.coalesce(func.sum(Movimiento.cantidad), 0)).where(
        Movimiento.alumno_id == alumno.id, Movimiento.tipo == "COINS", Movimiento.referencia == f"quiz:{quiz.id}")))
    if quiz.estado == "completado":
        return
    quiz.estado, quiz.completado_en = "completado", ahora()
    for item in lista:
        if item.etiqueta == "clase" and not item.es_previo:
            progress.agendar_si_falta(db, alumno.id, db.get(Reto, item.reto_id).tema_id)
    nuevo = ledger.puesto(db, quiz.curso_id, alumno.id)
    if quiz.puesto_inicial and nuevo and nuevo < quiz.puesto_inicial:
        messages.encolar(db, alumno.id, quiz.curso_id, "podio", f"quiz:{quiz.id}")
    _anomalias(db, quiz, intentos, bonos, params)


def _anomalias(db, quiz: Quiz, intentos: list[Intento], bonos: dict, params) -> None:
    """Very fast answers or a sudden perfect quiz go to the teacher. Never an automatic penalty."""
    tiempos = [i.tiempo_respuesta_ms for i in intentos if i.tiempo_respuesta_ms is not None]
    if len(tiempos) >= 3 and sum(tiempos) / len(tiempos) < params.anomalia_segundos * 1000 \
            and sum(i.resultado == "correcto" for i in intentos) >= 3:
        review.crear(db, curso_id=quiz.curso_id, tipo="anomalia", referencia=f"quiz:{quiz.id}:rapido",
                     alumno_id=quiz.alumno_id, motivo=f"Quiz resuelto con un promedio de "
                     f"{sum(tiempos) / len(tiempos) / 1000:.1f} s por reto y casi todo correcto.")
    if bonos["perfecto"]:
        previos = db.scalars(select(Quiz.puntaje_verificable).where(
            Quiz.alumno_id == quiz.alumno_id, Quiz.curso_id == quiz.curso_id, Quiz.estado == "completado",
            Quiz.id != quiz.id, Quiz.puntaje_verificable.is_not(None))).all()
        if len(previos) >= 2 and sum(previos) / len(previos) < 50:
            review.crear(db, curso_id=quiz.curso_id, tipo="anomalia", referencia=f"quiz:{quiz.id}:salto",
                         alumno_id=quiz.alumno_id, motivo="Quiz perfecto tras un promedio previo menor a 50.")


def resumen_final(db, quiz: Quiz) -> dict:
    """A4: total EXP of the quiz, breakdown, Coins and the updated podium."""
    lista = items(db, quiz)
    intentos = [intento_de(db, item) for item in lista]
    bonos = {m.referencia.rsplit(":", 1)[-1]: m.cantidad for m in db.scalars(select(Movimiento).where(
        Movimiento.alumno_id == quiz.alumno_id, Movimiento.tipo == "EXP",
        Movimiento.referencia.in_([f"quiz:{quiz.id}:completado", f"quiz:{quiz.id}:perfecto"])))}
    podio = ledger.podio(db, quiz.curso_id)
    mio = next((f for f in podio if f["alumno_id"] == quiz.alumno_id), None)
    return {
        "aciertos": sum(1 for i in intentos if i and i.resultado == "correcto"), "total": len(lista),
        "exp_retos": sum(i.exp for i in intentos if i), "bono_completado": bonos.get("completado", 0),
        "bono_perfecto": bonos.get("perfecto", 0), "exp_total": quiz.exp_obtenido, "coins": quiz.coins_obtenidas,
        "pendientes": sum(1 for i in intentos if i and i.estado != "completado"),
        "podio": podio[:5], "mio": mio,
        "cambio": (quiz.puesto_inicial - mio["puesto"]) if mio and quiz.puesto_inicial else 0,
    }

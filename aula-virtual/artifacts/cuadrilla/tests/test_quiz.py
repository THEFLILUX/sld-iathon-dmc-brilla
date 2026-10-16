"""Class quiz end to end through HTTP (spec §7.2, A2-A4): order, labels, hints, EXP, Coins, podium, review."""

import apoyo  # noqa: F401  (must be first)

import re
from datetime import timedelta

from sqlalchemy import func, select, update

from db.models import (
    AgendaRepaso, Clase, Intento, Movimiento, Quiz, QuizItem, Reto, RetoVersion, Revision, Tema, Usuario,
)
from db.session import SessionLocal
from falso_llm import FalsoModelo
from rules.calendar import ahora
from services import validation

ALUMNO, DOCENTE = "70000001", "20000001"


class QuizTest(apoyo.Caso):
    def setUp(self):
        super().setUp()
        self.curso = self.demo(actividad=True)
        with SessionLocal() as db:
            self.clase_1 = db.scalar(select(Clase).where(Clase.curso_id == self.curso.id, Clase.numero == 1))
            self.clase_2 = db.scalar(select(Clase).where(Clase.curso_id == self.curso.id, Clase.numero == 2))
            self.lucia = db.scalar(select(Usuario).where(Usuario.dni == ALUMNO))
        self.web = self.cliente(ALUMNO)
        self.aceptar_consentimiento(self.web, ALUMNO)
        self.token = self.csrf(ALUMNO)

    # -- helpers ---------------------------------------------------------------------------------
    def url(self, clase, sufijo=""):
        return f"/alumno/cursos/{self.curso.id}/clases/{clase.id}/quiz{sufijo}"

    def generar(self, clase):
        r = self.web.post(f"/alumno/cursos/{self.curso.id}/clases/{clase.id}/generar", data={"_csrf": self.token})
        self.assertEqual(r.status_code, 303, r.text[:800])

    def actual(self, clase):
        with SessionLocal() as db:
            quiz = db.scalar(select(Quiz).where(Quiz.alumno_id == self.lucia.id, Quiz.clase_id == clase.id))
            items = db.scalars(select(QuizItem).where(QuizItem.quiz_id == quiz.id).order_by(QuizItem.orden)).all()
            item = items[quiz.indice_actual] if quiz.indice_actual < len(items) else None
            version = db.get(RetoVersion, item.reto_version_id) if item and item.reto_version_id else None
            return quiz, item, version

    def responder(self, clase, acierta=True, pistas=0):
        pagina = self.web.get(self.url(clase))
        self.assertEqual(pagina.status_code, 200, pagina.text[:800])
        _, item, version = self.actual(clase)
        for _ in range(pistas):
            self.web.post(self.url(clase, "/pista"), data={"_csrf": self.token, "item_id": item.id})
        if version.tipo == "alternativas":
            respuesta = version.respuesta_correcta if acierta else next(o for o in version.opciones if o != version.respuesta_correcta)
        elif version.tipo == "completar":
            respuesta = version.respuesta_correcta.upper() if acierta else "otra cosa"
        else:
            respuesta = "Respuesta abierta de prueba que desarrolla la idea con suficiente detalle."
        r = self.web.post(self.url(clase, "/responder"), data={"_csrf": self.token, "item_id": item.id,
                                                                "respuesta": respuesta, "envio_id": f"e-{item.id}"})
        self.assertEqual(r.status_code, 303, r.text[:800])
        return item, version, respuesta

    def seguir(self, clase):
        return self.web.post(self.url(clase, "/seguir"), data={"_csrf": self.token})

    def movimientos(self, tipo):
        with SessionLocal() as db:
            # Lucía also practiced in Big Data: only this course's movements matter here.
            return int(db.scalar(select(func.coalesce(func.sum(Movimiento.cantidad), 0)).where(
                Movimiento.alumno_id == self.lucia.id, Movimiento.tipo == tipo,
                (Movimiento.curso_id == self.curso.id) | (Movimiento.curso_id.is_(None)))))

    # -- tests -------------------------------------------------------------------------------------
    def test_retos_no_se_ven_antes_de_generar(self):
        r = self.web.get(self.url(self.clase_1))
        self.assertEqual(r.status_code, 303)

    def test_quiz_perfecto_en_basico_da_475_xp_y_5_coins(self):
        self.generar(self.clase_1)
        pagina = apoyo.texto_visible(self.web.get(self.url(self.clase_1)).text)
        self.assertIn("CLASE 1", pagina)
        self.assertIn("1/3", pagina)
        self.assertNotRegex(pagina, r"\d+:\d\d")    # no visible timer
        etiquetas = []
        for _ in range(4):
            item, _, _ = self.responder(self.clase_1)
            etiquetas.append(item.etiqueta)
            feedback = self.web.get(self.url(self.clase_1)).text
            self.assertIn("¡Correcto!", feedback)
            self.assertIn('data-celebrate', feedback)
            self.assertEqual(self.seguir(self.clase_1).status_code, 303)
        self.assertEqual(etiquetas, ["clase", "clase", "clase", "repaso"])
        final = self.web.get(self.url(self.clase_1, "/final"))
        texto = apoyo.texto_visible(final.text)
        self.assertIn("¡FELICIDADES! HAS GANADO 475 XP!", texto)
        self.assertIn("SIGUE ASÍ!", texto)
        self.assertIn("Ganaste 5 Coins", texto)
        self.assertIn("PODIO ACTUALIZADO", texto)
        self.assertEqual(self.movimientos("EXP"), 475)
        self.assertEqual(self.movimientos("COINS"), 5)
        # Lucía tied Diego at 475 but reached it later: second place.
        self.assertIn("Tu puesto: #2", texto)

    def test_reenvio_y_recarga_no_duplican_exp(self):
        self.generar(self.clase_1)
        self.generar(self.clase_1)
        item, version, respuesta = self.responder(self.clase_1)
        repetido = self.web.post(self.url(self.clase_1, "/responder"), data={
            "_csrf": self.token, "item_id": item.id, "respuesta": respuesta, "envio_id": f"e-{item.id}"})
        self.assertEqual(repetido.status_code, 303)
        self.web.get(self.url(self.clase_1))
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Quiz).where(
                Quiz.alumno_id == self.lucia.id, Quiz.curso_id == self.curso.id)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Intento).where(
                Intento.alumno_id == self.lucia.id, Intento.curso_id == self.curso.id)), 1)
        self.assertEqual(self.movimientos("EXP"), 50)

    def test_formulario_reenviado_en_otro_reto_no_crea_intento(self):
        self.generar(self.clase_1)
        item, _, _ = self.responder(self.clase_1)
        self.seguir(self.clase_1)
        self.web.get(self.url(self.clase_1))
        _, siguiente, version = self.actual(self.clase_1)
        respuesta = version.respuesta_correcta or "x"
        r = self.web.post(self.url(self.clase_1, "/responder"), data={
            "_csrf": self.token, "item_id": siguiente.id, "respuesta": respuesta, "envio_id": f"e-{item.id}"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("ya se envió", r.text)

    def test_pistas_reducen_exp_y_se_conservan_al_volver(self):
        self.generar(self.clase_1)
        _, item, _ = self.actual(self.clase_1)
        self.web.get(self.url(self.clase_1))
        self.web.post(self.url(self.clase_1, "/pista"), data={"_csrf": self.token, "item_id": item.id})
        self.assertEqual(self.web.post(self.url(self.clase_1, "/solucion"), data={
            "_csrf": self.token, "item_id": item.id}).status_code, 400)
        # Leaves and comes back: same challenge with the hint already used.
        self.web.get(f"/alumno/cursos/{self.curso.id}")
        pagina = apoyo.texto_visible(self.web.get(self.url(self.clase_1)).text)
        self.assertIn("Pista 1.", pagina)
        self.assertIn("Pedir pista (1/3)", pagina)
        with SessionLocal() as db:
            reto_id = db.get(QuizItem, item.id).reto_id
        self.responder(self.clase_1, pistas=0)
        with SessionLocal() as db:
            intento = db.scalar(select(Intento).where(Intento.quiz_item_id == item.id))
            self.assertEqual((intento.pistas_usadas, intento.exp, intento.reto_id), (1, 25, reto_id))

    def test_solucion_tras_tercera_pista(self):
        self.generar(self.clase_1)
        self.web.get(self.url(self.clase_1))
        _, item, _ = self.actual(self.clase_1)
        for _ in range(4):
            self.web.post(self.url(self.clase_1, "/pista"), data={"_csrf": self.token, "item_id": item.id})
        with SessionLocal() as db:
            self.assertEqual(db.get(QuizItem, item.id).pistas_usadas, 3)
        self.assertEqual(self.web.post(self.url(self.clase_1, "/solucion"), data={
            "_csrf": self.token, "item_id": item.id}).status_code, 303)
        self.assertIn("Solución:", self.web.get(self.url(self.clase_1)).text)

    def test_fallos_dan_bono_de_completado_pero_no_perfecto_ni_coins(self):
        self.generar(self.clase_1)
        for _ in range(4):
            self.responder(self.clase_1, acierta=False)
            self.assertIn("Lo que faltó", self.web.get(self.url(self.clase_1)).text)
            self.seguir(self.clase_1)
        self.assertEqual(self.movimientos("EXP"), 100)
        self.assertEqual(self.movimientos("COINS"), 0)

    def test_respuesta_vacia_no_se_envia(self):
        self.generar(self.clase_1)
        self.web.get(self.url(self.clase_1))
        _, item, _ = self.actual(self.clase_1)
        r = self.web.post(self.url(self.clase_1, "/responder"), data={"_csrf": self.token, "item_id": item.id,
                                                                       "respuesta": "  ", "envio_id": "x"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Escribe o elige una respuesta", r.text)
        self.assertEqual(self.seguir(self.clase_1).status_code, 303)
        _, mismo, _ = self.actual(self.clase_1)
        self.assertEqual(mismo.id, item.id)

    def test_repaso_viene_de_la_agenda_y_avanza_el_intervalo(self):
        self.generar(self.clase_1)
        for _ in range(4):
            self.responder(self.clase_1)
            self.seguir(self.clase_1)
        with SessionLocal.begin() as db:
            temas = db.scalars(select(AgendaRepaso.tema_id).join(Tema, Tema.id == AgendaRepaso.tema_id).where(
                AgendaRepaso.alumno_id == self.lucia.id, Tema.curso_id == self.curso.id)).all()
            self.assertEqual(len(temas), 3)    # the 3 class topics; the prior-knowledge one is not scheduled
            db.execute(update(AgendaRepaso).where(AgendaRepaso.alumno_id == self.lucia.id)
                       .values(proxima_fecha=ahora() - timedelta(days=1)))
            validation.publicar(db, self.clase_2.id, None)
        self.generar(self.clase_2)
        quiz, _, _ = self.actual(self.clase_2)
        with SessionLocal() as db:
            items = db.scalars(select(QuizItem).where(QuizItem.quiz_id == quiz.id).order_by(QuizItem.orden)).all()
            self.assertEqual([i.etiqueta for i in items], ["clase", "clase", "clase", "repaso"])
            repaso = db.get(Reto, items[3].reto_id)
            self.assertEqual(db.get(Clase, repaso.clase_id).numero, 1)
            tema_repaso = repaso.tema_id
        for i in range(4):
            if i == 3:
                pagina = apoyo.texto_visible(self.web.get(self.url(self.clase_2)).text)
                self.assertIn("REPASO", pagina)
            self.responder(self.clase_2)
            self.seguir(self.clase_2)
        with SessionLocal() as db:
            fila = db.get(AgendaRepaso, (self.lucia.id, tema_repaso))
            self.assertEqual(fila.intervalo_actual, 3)
            intento = db.scalar(select(Intento).where(Intento.quiz_item_id == items[3].id))
            self.assertEqual((intento.origen, intento.intervalo_repaso), ("repaso", 1))

    def test_sin_repaso_el_contador_es_de_4(self):
        with SessionLocal.begin() as db:
            validation.publicar(db, self.clase_2.id, None)
        self.generar(self.clase_2)
        quiz, _, _ = self.actual(self.clase_2)
        self.assertFalse(quiz.tiene_repaso)
        pagina = apoyo.texto_visible(self.web.get(self.url(self.clase_2)).text)
        self.assertIn("1/4", pagina)

    def test_adaptacion_de_nivel_dentro_del_quiz(self):
        """Two challenges of the same topic: a clean success raises the next one a level."""
        with SessionLocal.begin() as db:
            tema_id = db.scalar(select(Reto.tema_id).where(Reto.clase_id == self.clase_2.id, Reto.posicion == 1))
            db.execute(update(Reto).where(Reto.clase_id == self.clase_2.id, Reto.posicion.in_((1, 2, 3, 4)))
                       .values(tema_id=tema_id))
            validation.publicar(db, self.clase_2.id, None)
        self.generar(self.clase_2)
        niveles = []
        for acierta in (True, True, False, False):
            item, version, _ = self.responder(self.clase_2, acierta=acierta)
            niveles.append(version.nivel)
            self.seguir(self.clase_2)
        self.assertEqual(niveles[:3], ["basico", "intermedio", "avanzado"])

    def test_tres_reportes_retiran_el_reto(self):
        self.generar(self.clase_1)
        self.web.get(self.url(self.clase_1))
        _, item, _ = self.actual(self.clase_1)
        # Diego and Valeria (demo) already have the same first challenge in their quizzes.
        for dni in (ALUMNO, "70000002", "70000002", "70000003"):
            web = self.web if dni == ALUMNO else self.cliente(dni)
            r = web.post(self.url(self.clase_1, "/reportar"), data={"_csrf": self.csrf(dni), "reto_id": item.reto_id,
                                                                    "motivo": "La respuesta parece errada"})
            self.assertEqual(r.status_code, 303, r.text[:500])
        with SessionLocal() as db:
            self.assertEqual(db.get(Reto, item.reto_id).estado, "retirado")
            self.assertEqual(db.scalar(select(func.count()).select_from(Revision).where(
                Revision.tipo == "error_reportado")), 1)
        # A student without that challenge in a quiz cannot report it.
        mateo = self.cliente("70000006")
        with SessionLocal.begin() as db:
            db.execute(update(Usuario).where(Usuario.dni == "70000006").values(consentimiento_en=ahora()))
        mateo.post(f"/alumno/cursos/{self.curso.id}/clases/{self.clase_1.id}/generar", data={"_csrf": self.csrf("70000006")})
        r = mateo.post(self.url(self.clase_1, "/reportar"), data={"_csrf": self.csrf("70000006"), "reto_id": item.reto_id})
        self.assertEqual(r.status_code, 404)
        # The teacher reactivates it from the inbox; reports start again from zero.
        docente = self.cliente(DOCENTE)
        with SessionLocal() as db:
            revision = db.scalar(select(Revision).where(Revision.tipo == "error_reportado"))
        docente.post(f"/docente/revisiones/{revision.id}", data={"_csrf": self.csrf(DOCENTE), "accion": "reactivar"})
        with SessionLocal() as db:
            self.assertEqual(db.get(Reto, item.reto_id).estado, "aprobado")

    def test_respuesta_abierta_con_ia_y_reclamo(self):
        falso = FalsoModelo(calificacion={"cubiertos": [True, False], "confianza": "alta", "revisar": False})
        apoyo.activar_ia(self, falso)
        with SessionLocal.begin() as db:
            # Put an open "definir" challenge first in class 1.
            db.execute(update(Reto).where(Reto.clase_id == self.clase_1.id, Reto.posicion == 4).values(posicion=None))
            db.execute(update(Reto).where(Reto.clase_id == self.clase_1.id, Reto.posicion == 1).values(posicion=4))
            reto_abierto = db.scalar(select(Reto).join(RetoVersion, RetoVersion.reto_id == Reto.id).where(
                Reto.clase_id == self.clase_1.id, RetoVersion.tipo == "definir"))
            reto_abierto.posicion = 1
        self.generar(self.clase_1)
        quiz, item, _ = self.actual(self.clase_1)
        with SessionLocal() as db:
            self.assertEqual(db.get(QuizItem, item.id).reto_id, reto_abierto.id)
        _, version, _ = self.responder(self.clase_1)
        self.assertEqual(version.tipo, "definir")
        pagina = self.web.get(self.url(self.clase_1)).text
        self.assertIn("Parcial", pagina)
        self.assertIn("No estoy de acuerdo", pagina)
        self.assertIn("calificador", falso.componentes)
        with SessionLocal() as db:
            intento = db.scalar(select(Intento).where(Intento.quiz_item_id == item.id))
            self.assertEqual((intento.resultado, intento.exp), ("parcial", 25))
        self.web.post(self.url(self.clase_1, "/desacuerdo"), data={"_csrf": self.token, "intento_id": intento.id,
                                                                   "motivo": "Cubrí ambas ideas"})
        docente = self.cliente(DOCENTE)
        with SessionLocal() as db:
            revision = db.scalar(select(Revision).where(Revision.tipo == "reclamo"))
        r = docente.post(f"/docente/revisiones/{revision.id}", data={
            "_csrf": self.csrf(DOCENTE), "accion": "corregir", "resultado": "correcto", "nota": "Tiene razón"})
        self.assertEqual(r.status_code, 303)
        with SessionLocal() as db:
            self.assertEqual(db.get(Intento, intento.id).exp, 50)
            ajuste = db.scalar(select(Movimiento).where(Movimiento.origen == "ajuste_reclamo"))
            self.assertEqual(ajuste.cantidad, 25)
        self.assertEqual(self.movimientos("COINS"), 0)

    def test_fallo_de_la_ia_deja_pendiente_sin_penalizar(self):
        falso = FalsoModelo(fallar={"calificador"})
        apoyo.activar_ia(self, falso)
        with SessionLocal.begin() as db:
            reto_abierto = db.scalar(select(Reto).join(RetoVersion, RetoVersion.reto_id == Reto.id).where(
                Reto.clase_id == self.clase_1.id, RetoVersion.tipo == "definir"))
            db.execute(update(Reto).where(Reto.clase_id == self.clase_1.id, Reto.posicion == 1).values(posicion=None))
            reto_abierto.posicion = 1
        self.generar(self.clase_1)
        _, item, _ = self.actual(self.clase_1)
        self.responder(self.clase_1)
        self.assertIn("pendiente", self.web.get(self.url(self.clase_1)).text)
        self.assertEqual(self.seguir(self.clase_1).status_code, 303)
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(Intento.estado).where(Intento.quiz_item_id == item.id)), "pendiente")
        # The periodic retry grades it later.
        falso.fallar.clear()
        from services import attempts
        from services.params import cargar
        with SessionLocal() as db:
            params = cargar(db)
        self.assertEqual(attempts.reintentar_pendientes(params), 1)
        with SessionLocal() as db:
            intento = db.scalar(select(Intento).where(Intento.quiz_item_id == item.id))
            self.assertEqual((intento.estado, intento.resultado), ("completado", "correcto"))
        self.assertEqual(self.movimientos("EXP"), 50)

    def test_quiz_disponible_aunque_no_haya_asistido_y_sin_mencion_de_asistencia(self):
        self.generar(self.clase_1)
        pagina = self.web.get(self.url(self.clase_1)).text.lower()
        self.assertNotIn("asist", pagina)
        self.assertIsNone(re.search(r"falt(aste|ó a clase)", pagina))

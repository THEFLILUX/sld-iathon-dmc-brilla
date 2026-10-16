"""Weekly challenge (PRD M6, spec §7.3): same for everyone, one level above, one attempt."""

import apoyo  # noqa: F401  (must be first)

from sqlalchemy import func, select

from db.models import DominioTema, Intento, Movimiento, RetoSemanal, RetoSemanalAlumno, RetoVersion, Tema, Usuario
from db.session import SessionLocal
from falso_llm import FalsoModelo
from rules import levels
from services import weekly

ALUMNO = "70000001"


class SemanalTest(apoyo.Caso):
    def setUp(self):
        super().setUp()
        self.curso = self.demo(actividad=True)
        self.web = self.cliente(ALUMNO)
        self.aceptar_consentimiento(self.web, ALUMNO)
        self.lucia = self.usuario(ALUMNO)

    def test_uno_por_semana_igual_para_todos_y_un_solo_intento(self):
        self.web.get(f"/alumno/cursos/{self.curso.id}")
        self.cliente("70000002").get(f"/alumno/cursos/{self.curso.id}")
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(RetoSemanal).where(
                RetoSemanal.curso_id == self.curso.id)), 1)
            fila = db.scalar(select(RetoSemanal).where(RetoSemanal.curso_id == self.curso.id))
            self.assertEqual(fila.estado, "listo")
        pagina = self.web.get(f"/alumno/cursos/{self.curso.id}/semanal")
        self.assertEqual(pagina.status_code, 200)
        self.assertIn("Un solo intento", pagina.text)
        with SessionLocal() as db:
            progreso = db.get(RetoSemanalAlumno, (self.lucia.id, fila.id))
            version = db.get(RetoVersion, progreso.reto_version_id)
            self.assertIn(version.tipo, ("alternativas", "completar"))
            # Lucía has no data: Básico → the weekly challenge is one level above (Intermedio).
            self.assertEqual(progreso.nivel, "intermedio")
        token = self.csrf(ALUMNO)
        for intento in range(2):
            r = self.web.post(f"/alumno/cursos/{self.curso.id}/semanal/responder",
                              data={"_csrf": token, "respuesta": version.respuesta_correcta, "envio_id": f"s{intento}"})
            self.assertEqual(r.status_code, 303)
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Intento).where(
                Intento.alumno_id == self.lucia.id, Intento.semanal_id == fila.id)), 1)
            exp = db.scalar(select(Movimiento.cantidad).where(Movimiento.origen == "reto_semanal",
                                                             Movimiento.tipo == "EXP", Movimiento.alumno_id == self.lucia.id))
            coins = db.scalar(select(Movimiento.cantidad).where(Movimiento.origen == "reto_semanal",
                                                               Movimiento.tipo == "COINS", Movimiento.alumno_id == self.lucia.id))
        self.assertEqual((exp, coins), (500, 5))
        self.assertIn("Completado esta semana", self.web.get(f"/alumno/cursos/{self.curso.id}").text)

    def test_con_pistas_250_y_sin_coins(self):
        self.web.get(f"/alumno/cursos/{self.curso.id}/semanal")
        token = self.csrf(ALUMNO)
        self.web.post(f"/alumno/cursos/{self.curso.id}/semanal/pista", data={"_csrf": token})
        with SessionLocal() as db:
            fila = db.scalar(select(RetoSemanal).where(RetoSemanal.curso_id == self.curso.id))
            version = db.get(RetoVersion, db.get(RetoSemanalAlumno, (self.lucia.id, fila.id)).reto_version_id)
        self.web.post(f"/alumno/cursos/{self.curso.id}/semanal/responder",
                      data={"_csrf": token, "respuesta": version.respuesta_correcta, "envio_id": "s"})
        with SessionLocal() as db:
            movimientos = dict(db.execute(select(Movimiento.tipo, Movimiento.cantidad).where(
                Movimiento.origen == "reto_semanal", Movimiento.alumno_id == self.lucia.id)).all())
        self.assertEqual(movimientos, {"EXP": 250})

    def test_un_nivel_por_encima_del_alumno(self):
        with SessionLocal.begin() as db:
            fila = weekly.actual(db, db.get(type(self.curso), self.curso.id))
            tema = db.get(Tema, fila.tema_id)
            db.add(DominioTema(alumno_id=self.lucia.id, tema_id=tema.id, nivel_actual="intermedio"))
        with SessionLocal.begin() as db:
            progreso, _, _, tema = weekly.preparar(db, db.get(Usuario, self.lucia.id), db.get(RetoSemanal, fila.id))
            verificables = [v.nivel for v in db.scalars(select(RetoVersion).where(RetoVersion.reto_id == fila.reto_id))
                            if v.tipo in ("alternativas", "completar")]
            objetivo = levels.subir("intermedio", tema.nivel_maximo)
            self.assertEqual(progreso.nivel, levels.mas_cercano(objetivo, verificables))

    def test_con_ia_genera_un_reto_verificable_sin_basico(self):
        apoyo.activar_ia(self, FalsoModelo())
        with SessionLocal.begin() as db:
            fila = weekly.actual(db, db.get(type(self.curso), self.curso.id))
        with SessionLocal() as db:
            fila = db.get(RetoSemanal, fila.id)
            self.assertEqual(fila.estado, "listo")
            versiones = db.scalars(select(RetoVersion).where(RetoVersion.reto_id == fila.reto_id)).all()
            self.assertTrue(versiones)
            self.assertTrue(all(v.tipo in ("alternativas", "completar") for v in versiones))
            if db.get(Tema, fila.tema_id).nivel_maximo != "basico":
                self.assertNotIn("basico", [v.nivel for v in versiones])

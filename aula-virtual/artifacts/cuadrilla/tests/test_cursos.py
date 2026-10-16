"""A student with several courses: 'Mis cursos', per-course EXP and podium, account-wide Coins."""

import apoyo  # noqa: F401  (must be first)

from sqlalchemy import select

from db import demo
from db.session import SessionLocal
from services import ledger
from services.cursos_alumno import sigla

LUCIA, VALERIA, CAMILA, ADMIN = "70000001", "70000003", "70000005", "10000001"


class MisCursosTest(apoyo.Caso):
    def setUp(self):
        super().setUp()
        self.python = self.demo(actividad=True)
        with SessionLocal() as db:
            self.big_data = demo.curso_big_data(db)
        self.web = self.cliente(LUCIA)

    def test_mis_cursos_muestra_los_dos_cursos_con_sus_pendientes(self):
        pagina = self.web.get("/alumno")
        self.assertEqual(pagina.status_code, 200, pagina.text[:800])
        texto = apoyo.texto_visible(pagina.text)
        self.assertIn("MIS CURSOS", texto.upper())
        self.assertIn("Python para Análisis de Datos", texto)
        self.assertIn("Especialización en Big Data", texto)
        self.assertIn("2 Cursos en curso", texto)
        self.assertIn("1 quiz nuevo", texto)            # Python: class 1 not taken yet
        self.assertIn("por repasar", texto)             # Big Data: reviews due from her first quiz
        self.assertIn("Fernanda Ríos", texto)
        self.assertIn("Ricardo Paredes", texto)
        self.assertNotIn(">Mi curso<", pagina.text)

    def test_exp_y_podio_por_curso_y_coins_de_la_cuenta(self):
        lucia = self.usuario(LUCIA)
        with SessionLocal() as db:
            self.assertEqual(ledger.exp_curso(db, lucia.id, self.python.id), 0)
            exp_bd = ledger.exp_curso(db, lucia.id, self.big_data.id)
            self.assertGreater(exp_bd, 0)
            self.assertIsNotNone(ledger.puesto(db, self.big_data.id, lucia.id))
        texto = apoyo.texto_visible(self.web.get(f"/alumno/cursos/{self.big_data.id}").text)
        self.assertIn(f"{exp_bd} EXP del curso", texto)
        texto = apoyo.texto_visible(self.web.get(f"/alumno/cursos/{self.python.id}").text)
        self.assertIn("0 EXP del curso", texto)
        # Valeria's Coins came from the Big Data quiz; the history names the course.
        valeria = self.cliente(VALERIA)
        historial = apoyo.texto_visible(valeria.get("/alumno/coins").text)
        self.assertIn("Especialización en Big Data", historial)

    def test_selector_de_curso_y_navegacion(self):
        pagina = self.web.get(f"/alumno/cursos/{self.python.id}").text
        self.assertIn(f'href="http://testserver/alumno/cursos/{self.big_data.id}"', pagina)
        self.assertIn('aria-current="page"><span class="dot', pagina)
        self.assertIn("Mis cursos</a> ›", pagina)
        self.assertIn(">Clases<", pagina)
        self.assertNotIn(">Mi curso<", pagina)

    def test_solo_ve_sus_cursos(self):
        camila = self.cliente(CAMILA)
        texto = apoyo.texto_visible(camila.get("/alumno").text)
        self.assertIn("Python para Análisis de Datos", texto)
        self.assertNotIn("Especialización en Big Data", texto)
        self.assertEqual(camila.get(f"/alumno/cursos/{self.big_data.id}").status_code, 404)
        fernanda, ricardo = self.cliente("20000001"), self.cliente("20000002")
        self.assertEqual(fernanda.get(f"/docente/cursos/{self.big_data.id}").status_code, 404)
        self.assertEqual(ricardo.get(f"/docente/cursos/{self.big_data.id}").status_code, 200)
        self.assertEqual(ricardo.get(f"/docente/cursos/{self.python.id}").status_code, 404)

    def test_curso_cerrado_pasa_a_finalizados(self):
        admin = self.cliente(ADMIN)
        admin.post(f"/admin/cursos/{self.big_data.id}/cerrar", data={"_csrf": self.csrf(ADMIN), "confirmo": "si"})
        texto = apoyo.texto_visible(self.web.get("/alumno").text)
        self.assertIn("Finalizados", texto)
        self.assertIn("1 Curso en curso", texto)
        self.assertIn("Ver resumen", texto)

    def test_siglas(self):
        self.assertEqual(sigla("Python para Análisis de Datos"), "PA")
        self.assertEqual(sigla("Especialización en Big Data"), "BD")

    def test_demo_es_idempotente(self):
        with SessionLocal.begin() as db:
            self.assertFalse(demo.actividad(db))
        with SessionLocal() as db:
            from db.models import Clase
            self.assertEqual(len(db.scalars(select(Clase).where(Clase.curso_id == self.big_data.id)).all()), 1)

"""Movements, redemption, manual Coins, course closing and concurrency (EXP y Coins §3-7, spec A7 and §6)."""

import apoyo  # noqa: F401  (must be first)

import threading

from sqlalchemy import func, select

from db.models import Canje, Curso, Movimiento, Usuario
from db.session import SessionLocal
from rules.params import DEFAULT_PARAMS
from services import admin, ledger
from services.redemption import CanjeInvalido, canjear

ALUMNO, ADMIN = "70000001", "10000001"


class CoinsTest(apoyo.Caso):
    def setUp(self):
        super().setUp()
        self.curso = self.demo(actividad=True)
        self.lucia = self.usuario(ALUMNO)
        self.admin = self.usuario(ADMIN)

    def sumar(self, cantidad, motivo="Taller presencial"):
        with SessionLocal.begin() as db:
            admin.sumar_coins(db, self.admin.id, db.get(Usuario, self.lucia.id), cantidad, motivo)

    def saldo(self):
        with SessionLocal() as db:
            return ledger.saldo_coins(db, self.lucia.id)

    def test_movimiento_unico_por_alumno_origen_y_referencia(self):
        with SessionLocal.begin() as db:
            self.assertTrue(ledger.registrar(db, alumno_id=self.lucia.id, curso_id=self.curso.id, tipo="EXP",
                                             origen="reto", referencia="quiz_item:999", cantidad=100))
            self.assertFalse(ledger.registrar(db, alumno_id=self.lucia.id, curso_id=self.curso.id, tipo="EXP",
                                              origen="reto", referencia="quiz_item:999", cantidad=100))
        with SessionLocal() as db:
            self.assertEqual(ledger.exp_curso(db, self.lucia.id, self.curso.id), 100)

    def test_movimientos_no_se_editan(self):
        with SessionLocal() as db:
            movimiento = db.scalars(select(Movimiento)).first()
            movimiento.cantidad = 1_000_000
            with self.assertRaises(ValueError):
                db.flush()

    def test_canje_desde_la_pantalla(self):
        web = self.cliente(ALUMNO)
        self.aceptar_consentimiento(web, ALUMNO)
        pagina = apoyo.texto_visible(web.get("/alumno/coins").text)
        self.assertIn("Te faltan 600 Coins para el 30 %", pagina)
        self.sumar(890)
        confirmar = apoyo.texto_visible(web.get("/alumno/coins?porcentaje=40").text)
        self.assertIn("Saldo que quedará 90", confirmar)
        # A percentage the balance does not reach cannot be confirmed.
        self.assertNotIn("Confirmar canje", apoyo.texto_visible(web.get("/alumno/coins?porcentaje=45").text))
        r = web.post("/alumno/coins/canjear", data={"_csrf": self.csrf(ALUMNO), "porcentaje": "40", "confirmo": "si"})
        self.assertEqual(r.status_code, 303)
        self.assertEqual(self.saldo(), 90)
        r = web.post("/alumno/coins/canjear", data={"_csrf": self.csrf(ALUMNO), "porcentaje": "30", "confirmo": "si"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Te faltan 510 Coins", r.text)
        self.assertEqual(self.saldo(), 90)

    def test_dos_canjes_simultaneos_no_dejan_saldo_negativo(self):
        self.sumar(700)
        resultados, barrera = [], threading.Barrier(2)

        def intentar():
            barrera.wait()
            try:
                with SessionLocal.begin() as db:
                    canjear(db, db.get(Usuario, self.lucia.id), 30, DEFAULT_PARAMS)
                resultados.append("ok")
            except CanjeInvalido:
                resultados.append("rechazado")
        hilos = [threading.Thread(target=intentar) for _ in range(2)]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(timeout=20)
        self.assertEqual(sorted(resultados), ["ok", "rechazado"])
        self.assertEqual(self.saldo(), 100)

    def test_admin_corrige_un_canje_devolviendo_coins(self):
        self.sumar(600)
        with SessionLocal.begin() as db:
            canje = canjear(db, db.get(Usuario, self.lucia.id), 30, DEFAULT_PARAMS)
        web = self.cliente(ADMIN)
        sin_motivo = web.post(f"/admin/canjes/{canje.id}/corregir", data={"_csrf": self.csrf(ADMIN), "motivo": " "})
        self.assertEqual(sin_motivo.status_code, 400)
        r = web.post(f"/admin/canjes/{canje.id}/corregir", data={"_csrf": self.csrf(ADMIN), "motivo": "Canje duplicado"})
        self.assertEqual(r.status_code, 303)
        self.assertEqual(self.saldo(), 600)
        otra = web.post(f"/admin/canjes/{canje.id}/corregir", data={"_csrf": self.csrf(ADMIN), "motivo": "Otra vez"})
        self.assertEqual(otra.status_code, 400)
        self.assertEqual(self.saldo(), 600)

    def test_coins_manuales_exigen_motivo_y_quedan_registradas(self):
        web = self.cliente(ADMIN)
        r = web.post("/admin/coins", data={"_csrf": self.csrf(ADMIN), "dni": ALUMNO, "cantidad": "50", "motivo": ""})
        self.assertEqual(r.status_code, 400)
        r = web.post("/admin/coins", data={"_csrf": self.csrf(ADMIN), "dni": ALUMNO, "cantidad": "50",
                                           "motivo": "Taller presencial"})
        self.assertEqual(r.status_code, 303)
        with SessionLocal() as db:
            movimiento = db.scalar(select(Movimiento).where(Movimiento.origen == "ajuste_admin"))
            self.assertEqual((movimiento.cantidad, movimiento.motivo, movimiento.creado_por), (50, "Taller presencial", self.admin.id))
        self.assertIn("Taller presencial", web.get(f"/admin/movimientos?dni={ALUMNO}").text)

    def test_cierre_del_curso_paga_el_podio_una_sola_vez(self):
        with SessionLocal() as db:
            antes = {f["alumno_id"]: f for f in ledger.podio(db, self.curso.id)}
        web = self.cliente(ADMIN)
        self.assertEqual(web.post(f"/admin/cursos/{self.curso.id}/cerrar", data={"_csrf": self.csrf(ADMIN)}).status_code, 400)
        for _ in range(2):
            r = web.post(f"/admin/cursos/{self.curso.id}/cerrar", data={"_csrf": self.csrf(ADMIN), "confirmo": "si"})
            self.assertIn(r.status_code, (303,))
        with SessionLocal() as db:
            pagos = db.execute(select(Movimiento.alumno_id, Movimiento.cantidad).where(
                Movimiento.origen == "podio_final")).all()
            self.assertEqual(db.get(Curso, self.curso.id).estado, "cerrado")
        primeros = sorted((f for f in antes.values() if f["exp"] > 0), key=lambda f: f["puesto"])[:3]
        self.assertEqual(sorted(c for _, c in pagos), [60, 90, 120])
        self.assertEqual(dict(pagos)[primeros[0]["alumno_id"]], 120)
        csv = web.get(f"/admin/cursos/{self.curso.id}/top3.csv").text
        self.assertEqual(len(csv.strip().splitlines()), 4)
        self.assertIn(primeros[0]["apellido"], csv)

    def test_menos_de_tres_alumnos_con_exp_paga_solo_los_que_existen(self):
        with SessionLocal.begin() as db:
            curso = Curso(nombre="Curso corto")
            db.add(curso)
            db.flush()
            for usuario in db.scalars(select(Usuario).where(Usuario.dni.in_(("70000001", "70000002")))):
                admin.inscribir(db, usuario, curso)
            ledger.registrar(db, alumno_id=self.lucia.id, curso_id=curso.id, tipo="EXP", origen="reto",
                             referencia="x", cantidad=10)
            podio = admin.cerrar_curso(db, self.admin.id, curso, DEFAULT_PARAMS)
        self.assertEqual(len(podio), 1)
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Movimiento).where(
                Movimiento.origen == "podio_final", Movimiento.curso_id == curso.id)), 1)

    def test_coins_en_pausa_no_se_pagan(self):
        with SessionLocal.begin() as db:
            db.get(Usuario, self.lucia.id).coins_pausadas = True
            ledger.registrar(db, alumno_id=self.lucia.id, curso_id=self.curso.id, tipo="EXP", origen="reto",
                             referencia="x", cantidad=99999)
            admin.cerrar_curso(db, self.admin.id, db.get(Curso, self.curso.id), DEFAULT_PARAMS)
        self.assertEqual(self.saldo(), 0)

    def test_canjes_listados_para_el_admin(self):
        self.sumar(1000)
        with SessionLocal.begin() as db:
            canjear(db, db.get(Usuario, self.lucia.id), 50, DEFAULT_PARAMS)
        texto = apoyo.texto_visible(self.cliente(ADMIN).get("/admin/canjes").text)
        self.assertIn("Lucía Torres", texto)
        self.assertIn("50 %", texto)
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(Canje.saldo_posterior)), 0)

"""Declared profiles, ownership and concurrent once-only paired Coins credits."""
import apoyo  # noqa: F401

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from sqlalchemy import func, select, text

from db.models import Movimiento, PerfilUsuario, Usuario
from db.session import SessionLocal, engine
from db.upgrade_profile import ampliar_origen_perfil
from rules.calendar import ahora
from services import ledger, profiles


class PerfilesTest(apoyo.Caso):
    def setUp(self):
        super().setUp()
        self.curso = self.demo(actividad=True)
        self.alumna = self.usuario('70000001')
        self.web = self.cliente('70000001')
        self.aceptar_consentimiento(self.web, '70000001')
        with SessionLocal.begin() as db:
            profiles.preparar_existentes(db)
        self.datos = profiles.ejemplos(self.alumna)

    def guardar(self, datos=None, version=0, **extra):
        return self.web.post('/perfil', data={**(self.datos if datos is None else datos),
            '_csrf': self.csrf('70000001'), 'version': str(version), 'confirmo': 'si', **extra})

    def bono(self):
        with SessionLocal() as db:
            return int(db.scalar(select(func.coalesce(func.sum(Movimiento.cantidad), 0)).where(
                Movimiento.alumno_id == self.alumna.id, Movimiento.origen == 'perfil')))

    def test_ejemplos_coherentes_para_todos_sin_premios_y_sin_sobrescribir(self):
        with SessionLocal.begin() as db:
            usuarios = db.scalars(select(Usuario)).all()
            self.assertEqual(db.scalar(select(func.count()).select_from(PerfilUsuario)), len(usuarios))
            for u in usuarios:
                p = db.get(PerfilUsuario, u.id)
                self.assertEqual(set(p.datos), set(profiles.CLAVES))
                self.assertEqual(profiles.validar(p.datos), p.datos)
                self.assertTrue(p.es_ejemplo)
                self.assertEqual(p.campos_reconocidos, [])
            self.assertEqual(profiles.preparar_existentes(db), 0)
        self.assertEqual(self.bono(), 0)

    def test_consulta_bloqueada_y_edicion_con_valores_precargados(self):
        r = self.web.get('/perfil')
        self.assertEqual(r.status_code, 200)
        self.assertIn('Editar perfil', r.text)
        self.assertNotIn('data-profile-edit', r.text)
        self.assertEqual(r.text.count('<dt>'), 14)
        self.assertIn('0,5 DMC Coin por cada campo', r.text)
        r = self.web.get('/perfil/editar')
        self.assertEqual(r.status_code, 200)
        self.assertIn('name="version" value="0"', r.text)
        for clave, valor in self.datos.items():
            self.assertIn(f'name="{clave}"', r.text)
            self.assertIn(valor, r.text)
        self.assertEqual(self.bono(), 0)

    def test_doce_campos_dan_seis_coins_una_vez_en_historial_sin_exp(self):
        with SessionLocal() as db:
            saldo = ledger.saldo_coins(db, self.alumna.id)
            exp = ledger.exp_curso(db, self.alumna.id, self.curso.id)
        self.assertEqual(self.guardar().status_code, 303)
        self.assertEqual(self.guardar(version=1).status_code, 303)
        self.assertEqual(self.bono(), 6)
        with SessionLocal() as db:
            p = db.get(PerfilUsuario, self.alumna.id)
            self.assertFalse(p.es_ejemplo)
            self.assertIsNotNone(p.confirmado_en)
            self.assertEqual(ledger.saldo_coins(db, self.alumna.id), saldo + 6)
            self.assertEqual(ledger.exp_curso(db, self.alumna.id, self.curso.id), exp)
        self.assertIn('Perfil completado', self.web.get('/alumno/coins').text)

    def test_impares_pendientes_cero_cuenta_y_borrar_rellenar_no_duplica(self):
        datos = {'edad': '25', 'experiencia_anios': '0', 'carrera': 'Estadística'}
        self.assertEqual(self.guardar(datos).status_code, 303)
        self.assertEqual(self.bono(), 1)
        self.assertIn('0,5 Coin pendiente', self.web.get('/perfil').text)
        self.assertEqual(self.guardar(datos | {'herramientas':'Excel'}, version=1).status_code, 303)
        self.assertEqual(self.bono(), 2)
        self.assertEqual(self.guardar({}, version=2).status_code, 303)
        self.assertEqual(self.guardar(datos | {'herramientas':'Python'}, version=3).status_code, 303)
        self.assertEqual(self.bono(), 2)

    def test_confirmacion_csrf_y_coherencia_obligatorias(self):
        self.assertEqual(self.guardar(confirmo='').status_code, 400)
        self.assertEqual(self.web.post('/perfil', data=self.datos).status_code, 403)
        for cambios in ({'edad':'-1'}, {'edad':'20','experiencia_anios':'20'}, {'situacion':'falso'},
                        {'horas_semana':'0'}, {'ingreso_dmc':(ahora().date()+timedelta(days=1)).isoformat()}):
            with self.subTest(cambios=cambios):
                r = self.guardar(self.datos | cambios)
                self.assertEqual(r.status_code, 400)
                self.assertIn('data-profile-edit', r.text)
        self.assertEqual(self.bono(), 0)

    def test_pestana_obsoleta_no_pisa_perfil(self):
        self.assertEqual(self.guardar().status_code, 303)
        r = self.guardar(self.datos | {'ocupacion':'No debe persistir'})
        self.assertEqual(r.status_code, 409)
        with SessionLocal() as db:
            self.assertEqual(db.get(PerfilUsuario, self.alumna.id).datos['ocupacion'], self.datos['ocupacion'])
        self.assertEqual(self.bono(), 6)

    def test_coins_en_pausa_se_acreditan_al_guardar_tras_reanudar(self):
        with SessionLocal.begin() as db:
            db.get(Usuario, self.alumna.id).coins_pausadas = True
        self.assertEqual(self.guardar().status_code, 303)
        self.assertEqual(self.bono(), 0)
        with SessionLocal.begin() as db:
            db.get(Usuario, self.alumna.id).coins_pausadas = False
        self.assertEqual(self.guardar(version=1).status_code, 303)
        self.assertEqual(self.bono(), 6)

    def test_privacidad_curso_rol_consentimiento_y_escritura_solo_propia(self):
        self.assertEqual(self.cliente().get('/perfil').status_code, 303)
        self.assertIn('/consentimiento', self.cliente('70000006').get('/perfil').headers['location'])
        url = f'/docente/cursos/{self.curso.id}/alumnos/{self.alumna.id}/perfil'
        docente = self.cliente('20000001')
        r = docente.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertIn('Solo su titular puede editarlo', r.text)
        self.assertNotIn('Editar perfil', r.text)
        self.assertEqual(self.cliente('20000002').get(url).status_code, 404)
        self.assertEqual(self.web.get(url).status_code, 403)
        admin_url = f'/admin/usuarios/{self.alumna.id}/perfil'
        self.assertEqual(self.cliente('10000001').get(admin_url).status_code, 200)
        self.assertEqual(self.web.get(admin_url).status_code, 403)
        self.assertEqual(docente.get(admin_url).status_code, 403)
        otro_id = self.usuario('70000002').id
        self.assertEqual(self.guardar(usuario_id=otro_id, rol='admin').status_code, 303)
        with SessionLocal() as db:
            self.assertEqual(db.get(Usuario, self.alumna.id).rol, 'alumno')
            self.assertTrue(db.get(PerfilUsuario, otro_id).es_ejemplo)

    def test_staff_edita_sin_bonificacion_de_alumno(self):
        for dni in ('20000001','10000001'):
            cliente, usuario = self.cliente(dni), self.usuario(dni)
            self.assertEqual(cliente.get('/perfil').status_code, 200)
            r = cliente.post('/perfil', data=profiles.ejemplos(usuario) | {
                '_csrf': self.csrf(dni), 'confirmo':'si', 'version':'0'})
            self.assertEqual(r.status_code, 303)
            with SessionLocal() as db:
                self.assertFalse(db.get(PerfilUsuario, usuario.id).es_ejemplo)
                self.assertEqual(ledger.saldo_coins(db, usuario.id), 0)

    def test_dos_guardados_concurrentes_acreditan_solo_seis(self):
        barrera = Barrier(2)
        def enviar(_):
            with SessionLocal() as db:
                barrera.wait(timeout=5)
                try:
                    n = profiles.guardar(db, self.alumna.id, self.datos, version=0, confirmo='si')
                    db.commit()
                    return n
                except profiles.PerfilDesactualizado:
                    db.rollback()
                    return 'obsoleto'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(enviar, range(2))), [6,'obsoleto'])
        self.assertEqual(self.bono(), 6)

    def test_migracion_idempotente_conserva_movimientos_y_admite_perfil(self):
        with engine.begin() as c:
            antes = c.execute(text('SELECT id,cantidad,origen FROM movimientos ORDER BY id')).all()
            c.execute(text('ALTER TABLE movimientos DROP CONSTRAINT movimiento_origen'))
            c.execute(text("ALTER TABLE movimientos ADD CONSTRAINT movimiento_origen CHECK (origen IN ('reto','quiz','reto_semanal','podio_final','ajuste_admin','ajuste_reclamo','canje','devolucion_canje'))"))
        ampliar_origen_perfil(engine)
        ampliar_origen_perfil(engine)
        with engine.begin() as c:
            self.assertEqual(c.execute(text('SELECT id,cantidad,origen FROM movimientos ORDER BY id')).all(), antes)
        self.assertEqual(self.guardar().status_code, 303)
        self.assertEqual(self.bono(), 6)

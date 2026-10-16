"""The public presentation login cannot select arbitrary users or bypass session protections."""
import apoyo  # noqa: F401

import re
from unittest.mock import patch

from sqlalchemy import func, select

from auth import demo, sessions
from db.models import Sesion, Usuario
from db.session import SessionLocal


class DemoLoginTest(apoyo.Caso):
    def setUp(self):
        super().setUp()
        self.demo()
        apoyo.configurar(self, PUBLIC_DEMO_LOGIN=True)
        demo._ACCESOS.clear()
        self.addCleanup(demo._ACCESOS.clear)

    def formulario(self, web):
        response = web.get('/ingresar/demo')
        self.assertEqual(response.status_code, 200)
        return re.search(r'name="_demo_csrf" value="([^"]+)"', response.text).group(1)

    def acceder(self, web, clave, **extra):
        return web.post('/ingresar/demo', data={'participante':clave, '_demo_csrf':self.formulario(web)}, **extra)

    def test_cinco_cuentas_rol_nombre_sin_credenciales_y_sesiones_normales(self):
        with SessionLocal() as db:
            hashes = {u.id:u.password_hash for u in db.scalars(select(Usuario))}
        for clave, dni, rol in demo.CUENTAS:
            web = self.cliente()
            response = web.get('/ingresar/demo')
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(response.text.count('class="demo-participant"'), 5)
            for _, number, _ in demo.CUENTAS:
                self.assertNotIn(number, response.text)
            self.assertNotIn('name="password"', response.text)
            self.assertNotIn('name="dni"', response.text)
            usuario = self.usuario(dni)
            self.assertIn(usuario.nombre_completo, response.text)
            csrf = re.search(r'name="_demo_csrf" value="([^"]+)"', response.text).group(1)
            result = web.post('/ingresar/demo', data={'participante':clave,'_demo_csrf':csrf})
            self.assertEqual(result.status_code, 303)
            token = web.cookies.get(sessions.COOKIE)
            self.assertTrue(token)
            self.assertIsNone(web.cookies.get(demo.COOKIE))
            with SessionLocal() as db:
                session, user = sessions.buscar(db, token)
                self.assertEqual((user.id,user.rol), (usuario.id,rol))
                self.assertNotEqual(session.token_hash, token)
                actual_csrf = session.csrf
            self.assertIn('HttpOnly', result.headers.get('set-cookie'))
            self.assertEqual(web.post('/salir',data={'_csrf':actual_csrf}).status_code, 303)
            self.assertIsNone(web.cookies.get(sessions.COOKIE))
        with SessionLocal() as db:
            self.assertEqual(hashes, {u.id:u.password_hash for u in db.scalars(select(Usuario))})

    def test_desactivado_no_muestra_boton_ni_admite_rutas(self):
        web=self.cliente()
        self.assertIn('Probar DEMO', web.get('/ingresar').text)
        csrf=self.formulario(web)
        apoyo.configurar(self,PUBLIC_DEMO_LOGIN=False)
        self.assertNotIn('Probar DEMO', web.get('/ingresar').text)
        self.assertEqual(web.get('/ingresar/demo').status_code,404)
        self.assertEqual(web.post('/ingresar/demo',data={'participante':'administrador','_demo_csrf':csrf}).status_code,404)
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Sesion)),0)

    def test_csrf_cookie_y_origen_validos_antes_de_iniciar_sesion(self):
        web=self.cliente()
        self.assertEqual(web.post('/ingresar/demo',data={'participante':'administrador'}).status_code,403)
        csrf=self.formulario(web)
        self.assertEqual(web.post('/ingresar/demo',data={'participante':'administrador','_demo_csrf':'0'*64}).status_code,403)
        otro=self.cliente()
        self.assertEqual(otro.post('/ingresar/demo',data={'participante':'administrador','_demo_csrf':csrf}).status_code,403)
        self.assertEqual(web.post('/ingresar/demo',headers={'origin':'https://externo.example'},
            data={'participante':'administrador','_demo_csrf':csrf}).status_code,403)
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Sesion)),0)

    def test_no_admite_otros_usuarios_inactivos_ni_cambios_de_rol(self):
        web=self.cliente()
        for clave in ('70000003',str(self.usuario('70000003').id),'admin','otro'):
            self.assertEqual(self.acceder(web,clave).status_code,404)
        with SessionLocal.begin() as db:
            db.get(Usuario,self.usuario('70000001').id).activo=False
            db.get(Usuario,self.usuario('20000002').id).rol='admin'
        response=web.get('/ingresar/demo')
        self.assertEqual(response.text.count('class="demo-participant"'),3)
        self.assertEqual(self.acceder(web,'alumno-1').status_code,404)
        self.assertEqual(self.acceder(web,'docente-2').status_code,404)

    def test_no_reemplaza_una_sesion_ya_autenticada(self):
        web=self.cliente('70000001')
        token=web.cookies.get(sessions.COOKIE)
        self.assertEqual(web.get('/ingresar/demo').status_code,303)
        self.assertEqual(web.post('/ingresar/demo',data={'participante':'administrador'}).status_code,303)
        self.assertEqual(web.cookies.get(sessions.COOKIE),token)
        with SessionLocal() as db:
            self.assertEqual(sessions.buscar(db,token)[1].rol,'alumno')

    def test_limite_demo_independiente_del_login_con_contrasena(self):
        web=self.cliente()
        with patch.object(demo,'LIMITE',1):
            self.assertEqual(self.acceder(web,'docente-1').status_code,303)
            self.assertEqual(web.post('/salir',data={'_csrf':self.csrf('20000001')}).status_code,303)
            self.assertEqual(self.acceder(web,'docente-2').status_code,429)
            self.cliente('20000002')  # Normal authentication remains available.

    def test_alumno_pendiente_conserva_su_flujo_de_consentimiento(self):
        with SessionLocal.begin() as db:
            db.get(Usuario,self.usuario('70000001').id).consentimiento_en=None
        response=self.acceder(self.cliente(),'alumno-1')
        self.assertEqual(response.status_code,303)
        self.assertTrue(response.headers['location'].endswith('/consentimiento'))
        self.assertIsNone(self.usuario('70000001').consentimiento_en)

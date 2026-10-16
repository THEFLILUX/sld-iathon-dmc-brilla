"""Every screen renders for its role, and roles cannot cross into each other's screens."""

import apoyo  # noqa: F401  (must be first)

import re

from sqlalchemy import select

from db.models import Clase, Curso, Inscripcion, Reto, Usuario
from db.session import SessionLocal

ALUMNO, DOCENTE, ADMIN = "70000001", "20000001", "10000001"


class PantallasTest(apoyo.Caso):
    def setUp(self):
        super().setUp()
        self.curso = self.demo(actividad=True)
        with SessionLocal() as db:
            self.clase_1 = db.scalar(select(Clase).where(Clase.curso_id == self.curso.id, Clase.numero == 1))
            self.clase_2 = db.scalar(select(Clase).where(Clase.curso_id == self.curso.id, Clase.numero == 2))
            self.alumno_id = db.scalar(select(Usuario.id).where(Usuario.dni == ALUMNO))

    def test_login_incorrecto_no_revela_si_existe_el_dni(self):
        cliente = self.cliente()
        malo = cliente.post("/ingresar", data={"dni": ALUMNO, "password": "otra-clave"})
        inexistente = cliente.post("/ingresar", data={"dni": "99999999", "password": "otra-clave"})
        self.assertEqual(malo.status_code, 400)
        self.assertIn("DNI o contraseña incorrectos", malo.text)
        self.assertIn("DNI o contraseña incorrectos", inexistente.text)

    def test_alumno_sin_consentimiento_va_al_aviso(self):
        nuevo = "70000006"
        cliente = self.cliente(nuevo)
        respuesta = cliente.get(f"/alumno/cursos/{self.curso.id}")
        self.assertEqual(respuesta.status_code, 303)
        self.assertTrue(respuesta.headers["location"].endswith("/consentimiento"))
        aviso = cliente.get("/consentimiento")
        self.assertIn("nombre y apellido", aviso.text)
        self.assertIn("La IA no ve tu DNI", aviso.text)
        self.aceptar_consentimiento(cliente, nuevo)
        self.assertIsNotNone(self.usuario(nuevo).consentimiento_en)

    def test_pantallas_del_alumno(self):
        cliente = self.cliente(ALUMNO)
        self.aceptar_consentimiento(cliente, ALUMNO)
        inicio = cliente.get(f"/alumno/cursos/{self.curso.id}")
        self.assertEqual(inicio.status_code, 200, inicio.text[:2000])
        texto = apoyo.texto_visible(inicio.text)
        self.assertIn("QUIZ CLASE 1", texto)
        self.assertIn("Generar", texto)
        self.assertIn("¡Ya se subió el video de clase! Recuerda hacer tus EXP", texto)
        self.assertIn("RETO SEMANAL", texto)
        # Class 2 is still being validated: students do not see it.
        self.assertNotIn("QUIZ CLASE 2", texto)
        for ruta in (f"/alumno/cursos/{self.curso.id}/progreso", f"/alumno/cursos/{self.curso.id}/podio",
                     "/alumno/coins", f"/alumno/cursos/{self.curso.id}/semanal"):
            respuesta = cliente.get(ruta)
            self.assertEqual(respuesta.status_code, 200, f"{ruta}: {respuesta.text[:1500]}")
        # Messages are shown once.
        otra_vez = apoyo.texto_visible(cliente.get(f"/alumno/cursos/{self.curso.id}").text)
        self.assertNotIn("¡Ya se subió el video de clase!", otra_vez)

    def test_mis_cursos_docente_con_un_curso_no_redirige(self):
        cliente = self.cliente(DOCENTE)
        respuesta = cliente.get("/docente")
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("Mis cursos", apoyo.texto_visible(respuesta.text))
        self.assertIn(self.curso.nombre, respuesta.text)
        self.assertEqual(respuesta.text.count('class="course-card"'), 1)
        self.assertNotIn('aria-label="Navegación del curso"', respuesta.text)

    def test_docente_elige_curso_y_sube_clase_en_el_curso_elegido(self):
        with SessionLocal.begin() as db:
            docente_id = db.scalar(select(Usuario.id).where(Usuario.dni == DOCENTE))
            otro = Curso(nombre="Segundo curso del mismo docente")
            db.add(otro)
            db.flush()
            db.add(Inscripcion(usuario_id=docente_id, curso_id=otro.id, rol_en_curso="docente"))
            otro_id = otro.id
        cliente = self.cliente(DOCENTE)
        listado = cliente.get("/docente")
        self.assertEqual(listado.status_code, 200)
        entradas = re.findall(r'<a class="btn" href="([^"]+)">Entrar al curso</a>', listado.text)
        self.assertEqual(len(entradas), 2)
        for curso_id in (self.curso.id, otro_id):
            url = next(url for url in entradas if url.endswith(f"/cursos/{curso_id}"))
            curso = cliente.get(url)
            self.assertEqual(curso.status_code, 200)
            menu = re.search(r'<nav[^>]*aria-label="Navegación del curso"[^>]*>(.*?)</nav>', curso.text, re.S).group(1)
            enlaces = re.findall(r'<a\b([^>]*)>(.*?)</a>', menu, re.S)
            subida = next(attrs for attrs, label in enlaces if apoyo.texto_visible(label).strip() == "Subir clase")
            url_subida = re.search(r'href="([^"]+)"', subida).group(1)
            self.assertTrue(url_subida.endswith(f"/cursos/{curso_id}/clases/nueva"))
            formulario = cliente.get(url_subida)
            self.assertEqual(formulario.status_code, 200)
            self.assertIn(f'action="{url_subida}"', formulario.text)
            self.assertIn('name="fuente"', formulario.text)
            self.assertIn('name="transcript_texto"', formulario.text)
            self.assertIn('aria-current="page"', formulario.text)
            # The global link always returns to the chooser, even after opening a course.
            self.assertEqual(cliente.get("/docente").status_code, 200)

    def test_pantallas_del_docente(self):
        cliente = self.cliente(DOCENTE)
        rutas = [f"/docente/cursos/{self.curso.id}", f"/docente/cursos/{self.curso.id}/clases/nueva",
                 f"/docente/clases/{self.clase_1.id}", f"/docente/clases/{self.clase_2.id}",
                 f"/docente/clases/{self.clase_1.id}/reporte", f"/docente/cursos/{self.curso.id}/alumnos",
                 f"/docente/cursos/{self.curso.id}/riesgo", f"/docente/cursos/{self.curso.id}/revision",
                 f"/docente/cursos/{self.curso.id}/malla", f"/docente/cursos/{self.curso.id}/podio",
                 f"/docente/cursos/{self.curso.id}/alumnos/{self.alumno_id}",
                 f"/docente/clases/{self.clase_2.id}/retos/nuevo"]
        with SessionLocal() as db:
            reto = db.scalar(select(Reto).where(Reto.clase_id == self.clase_2.id).limit(1))
        rutas.append(f"/docente/retos/{reto.id}/editar?nivel=avanzado")
        for ruta in rutas:
            respuesta = cliente.get(ruta)
            self.assertEqual(respuesta.status_code, 200, f"{ruta}: {respuesta.text[:1500]}")
        validar = apoyo.texto_visible(cliente.get(f"/docente/clases/{self.clase_2.id}").text)
        self.assertIn("Tiempo restante", validar)
        self.assertIn("Publicar ahora", validar)
        self.assertEqual(validar.count("Rechazar"), 4)
        riesgo = apoyo.texto_visible(cliente.get(f"/docente/cursos/{self.curso.id}/riesgo").text)
        self.assertIn("Camila Rojas", riesgo)

    def test_pantallas_del_admin(self):
        cliente = self.cliente(ADMIN)
        for ruta in ("/admin", f"/admin/cursos/{self.curso.id}", "/admin/usuarios", "/admin/coins", "/admin/canjes",
                     f"/admin/movimientos?dni={ALUMNO}", "/admin/parametros", f"/admin/cursos/{self.curso.id}/top3.csv",
                     f"/docente/cursos/{self.curso.id}"):
            respuesta = cliente.get(ruta)
            self.assertEqual(respuesta.status_code, 200, f"{ruta}: {respuesta.text[:1500]}")

    def test_roles_no_se_cruzan(self):
        alumno = self.cliente(ALUMNO)
        self.aceptar_consentimiento(alumno, ALUMNO)
        self.assertEqual(alumno.get(f"/docente/cursos/{self.curso.id}").status_code, 403)
        self.assertEqual(alumno.get("/admin").status_code, 403)
        docente = self.cliente(DOCENTE)
        self.assertEqual(docente.get("/admin").status_code, 403)
        self.assertEqual(docente.get(f"/alumno/cursos/{self.curso.id}").status_code, 403)
        # A teacher only sees their courses.
        with SessionLocal.begin() as db:
            otro = Curso(nombre="Otro curso")
            db.add(otro)
        with SessionLocal() as db:
            otro_id = db.scalar(select(Curso.id).where(Curso.nombre == "Otro curso"))
        self.assertEqual(docente.get(f"/docente/cursos/{otro_id}").status_code, 404)
        self.assertEqual(alumno.get(f"/alumno/cursos/{otro_id}").status_code, 404)

    def test_post_sin_csrf_es_rechazado(self):
        cliente = self.cliente(ALUMNO)
        respuesta = cliente.post("/consentimiento", data={"acepto": "si"})
        self.assertEqual(respuesta.status_code, 403)
        otro_origen = cliente.post("/consentimiento", data={"acepto": "si", "_csrf": self.csrf(ALUMNO)},
                                   headers={"origin": "https://malicioso.example"})
        self.assertEqual(otro_origen.status_code, 403)

    def test_sin_sesion_redirige_al_login(self):
        respuesta = self.cliente().get(f"/alumno/cursos/{self.curso.id}")
        self.assertEqual(respuesta.status_code, 303)
        self.assertTrue(respuesta.headers["location"].endswith("/ingresar"))

    def test_salir_cierra_la_sesion(self):
        cliente = self.cliente(DOCENTE)
        self.assertEqual(cliente.post("/salir", data={"_csrf": self.csrf(DOCENTE)}).status_code, 303)
        self.assertEqual(cliente.get(f"/docente/cursos/{self.curso.id}").status_code, 303)

    def test_cabeceras_de_seguridad(self):
        respuesta = self.cliente().get("/ingresar")
        self.assertIn("script-src 'self'", respuesta.headers["content-security-policy"])
        self.assertEqual(respuesta.headers["x-content-type-options"], "nosniff")
        self.assertIsNone(re.search(r"<script>[^<]", respuesta.text))

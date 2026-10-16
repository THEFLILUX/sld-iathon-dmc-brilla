"""PDF import review and destructive course deletion, isolated PostgreSQL and fake AI only."""

import apoyo  # noqa: F401

import html
import io
import json
import re
import tempfile
from pathlib import Path
from unittest import mock

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.dml import Delete

from ai import jobs
from db.models import (
    Base, Clase, Curso, FuenteSemanal, Intento, LlamadaIA, Revision, Reto,
    RetoReporte, RetoSemanal, RetoSemanalAlumno, Tema, Usuario,
)
from db.session import SessionLocal
from falso_llm import FalsoModelo
from rules.calendar import ahora, semana_de
from rules.params import DEFAULT_PARAMS
from services import admin, course_deletion, curriculum, ledger
from services.redemption import canjear, corregir
from services.validation import versiones_vigentes

ADMIN, DOCENTE, ALUMNO = "10000001", "20000001", "70000001"


def pdf(texto=None, protegido=False):
    escritor = PdfWriter()
    pagina = escritor.add_blank_page(width=595, height=842)
    if texto:
        fuente = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                   NameObject("/Subtype"): NameObject("/Type1"),
                                   NameObject("/BaseFont"): NameObject("/Helvetica")})
        pagina[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): escritor._add_object(fuente)})})
        flujo = DecodedStreamObject()
        limpio = texto.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        flujo.set_data(f"BT /F1 12 Tf 40 700 Td ({limpio}) Tj ET".encode())
        pagina[NameObject("/Contents")] = escritor._add_object(flujo)
    if protegido:
        escritor.encrypt("clave-de-ejemplo")
    salida = io.BytesIO()
    escritor.write(salida)
    return salida.getvalue()


class MallaPdfTest(apoyo.Caso):
    def setUp(self):
        super().setUp()
        self.demo()
        with SessionLocal.begin() as db:
            nuevo = Curso(nombre="SQL para analistas PDF")
            db.add(nuevo)
            db.flush()
            self.curso_id = nuevo.id
        self.web = self.cliente(ADMIN)
        self.token = self.csrf(ADMIN)
        self.modelo = FalsoModelo()
        apoyo.activar_ia(self, self.modelo)

    def subir(self, contenido):
        return self.web.post(f"/admin/cursos/{self.curso_id}/malla", data={"_csrf": self.token},
                             files={"archivo": ("malla.pdf", contenido, "application/pdf")})

    def test_pdf_real_preview_sin_guardar_confirmacion_y_propuesta(self):
        respuesta = self.subir(pdf("Malla SQL. Fundamentos: SELECT, JOIN. Objetivo: consultar columnas de una tabla."))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("Confirmar y guardar malla", respuesta.text)
        self.assertIn("Objetivo propuesto por IA", respuesta.text)
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Tema).where(Tema.curso_id == self.curso_id)), 0)
        self.assertEqual(self.modelo.componentes, ["importador_malla"])
        self.assertIn("Malla SQL", self.modelo.payloads[0])
        datos = html.unescape(re.search(r'name="temas_json" value="([^"]+)"', respuesta.text).group(1))
        confirmacion = {"_csrf": self.token, "temas_json": datos, "confirmo": "si"}
        self.assertEqual(self.web.post(f"/admin/cursos/{self.curso_id}/malla/confirmar", data=confirmacion).status_code, 200)
        with SessionLocal() as db:
            temas = db.scalars(select(Tema).where(Tema.curso_id == self.curso_id).order_by(Tema.orden)).all()
            self.assertEqual([(t.nombre, t.subtema) for t in temas], [("Consultas SQL", "SELECT"), ("Consultas SQL", "JOIN")])
        self.assertEqual(self.modelo.componentes, ["importador_malla", "proponedor"])

    def test_pdf_escaneado_protegido_invalido_no_llama_ia_ni_guarda(self):
        for contenido, mensaje in ((pdf(), "texto legible"), (pdf("Malla de ejemplo", True), "contraseña"),
                                   (b"archivo roto", "PDF")):
            with self.subTest(mensaje=mensaje):
                respuesta = self.subir(contenido)
                self.assertEqual(respuesta.status_code, 400)
                self.assertIn(mensaje, respuesta.text)
        self.assertEqual(self.modelo.componentes, [])

    def test_pdf_sin_ia_y_fallo_proveedor_conservan_malla(self):
        with SessionLocal.begin() as db:
            db.add(Tema(curso_id=self.curso_id, nombre="Tema anterior", subtema="", objetivo="Comprender SQL", orden=1))
        contenido = pdf("Malla SQL con temas de SELECT y JOIN y objetivos del curso")
        apoyo.configurar(self, OPENAI_API_KEY="")
        self.assertEqual(self.subir(contenido).status_code, 400)
        apoyo.configurar(self, OPENAI_API_KEY="clave-falsa")
        self.modelo.fallar.add("importador_malla")
        self.assertEqual(self.subir(contenido).status_code, 400)
        with SessionLocal() as db:
            self.assertEqual(list(db.scalars(select(Tema.nombre).where(Tema.curso_id == self.curso_id))), ["Tema anterior"])

    def test_confirmacion_revalida_datos_permiso_y_csrf(self):
        path = f"/admin/cursos/{self.curso_id}/malla/confirmar"
        datos = json.dumps([{"tema": "Duplicado", "objetivo": "Comprender SQL"}] * 2)
        self.assertEqual(self.web.post(path, data={"_csrf": self.token, "temas_json": datos}).status_code, 400)
        self.assertEqual(self.web.post(path, data={"_csrf": self.token, "temas_json": datos, "confirmo": "si"}).status_code, 400)
        self.assertEqual(self.web.post(path, data={"temas_json": "[]", "confirmo": "si"}).status_code, 403)
        docente = self.cliente(DOCENTE)
        self.assertEqual(docente.post(path, data={"_csrf": self.csrf(DOCENTE), "temas_json": datos, "confirmo": "si"}).status_code, 403)
        with mock.patch("ai.components.extraer_malla_pdf", return_value={"temas": [
                {"tema": "Falta objetivo", "objetivo": "", "objetivo_propuesto": False}], "avisos": []}):
            with self.assertRaises(curriculum.MallaInvalida):
                curriculum.leer_malla_pdf(pdf("Malla SQL con SELECT, JOIN y distintos temas de aprendizaje"))


class EliminarCursoTest(apoyo.Caso):
    def setUp(self):
        super().setUp()
        self.curso = self.demo(actividad=True)
        self.web = self.cliente(ADMIN)
        self.token = self.csrf(ADMIN)
        self.alumno = self.usuario(ALUMNO)
        self.admin = self.usuario(ADMIN)
        temporal = tempfile.TemporaryDirectory(prefix="dmc-delete-test-")
        self.addCleanup(temporal.cleanup)
        self.uploads = Path(temporal.name)
        apoyo.configurar(self, UPLOAD_DIR=self.uploads)
        self.archivo = self.uploads / "grabacion-correcta.txt"
        self.archivo.write_text("transcript de prueba")
        with SessionLocal.begin() as db:
            clase = db.scalar(select(Clase).where(Clase.curso_id == self.curso.id).order_by(Clase.numero))
            clase.fuente_archivo = self.archivo.name
            reto = db.scalar(select(Reto).where(Reto.clase_id == clase.id, Reto.uso == "clase").order_by(Reto.id))
            version = versiones_vigentes(db, reto)["intermedio"]
            semanal = RetoSemanal(curso_id=self.curso.id, semana=semana_de(ahora()), estado="listo",
                                  reto_id=reto.id, tema_id=reto.tema_id, tema_visto=True)
            db.add(semanal)
            db.flush()
            db.add(RetoSemanalAlumno(alumno_id=self.alumno.id, semanal_id=semanal.id,
                                     nivel="intermedio", reto_version_id=version.id))
            db.add(FuenteSemanal(semanal_id=semanal.id, clase_id=clase.id))
            db.add(RetoReporte(reto_id=reto.id, alumno_id=self.alumno.id, motivo="Revisar pregunta"))
            intento = db.scalar(select(Intento).where(Intento.curso_id == self.curso.id))
            db.add(Revision(curso_id=self.curso.id, tipo="marcado_ia", referencia=f"intento:{intento.id}",
                            intento_id=intento.id, reto_id=intento.reto_id, alumno_id=intento.alumno_id))
            for ref in (f"curso:{self.curso.id}:malla_pdf", f"clase:{clase.id}:previo", f"intento:{intento.id}",
                        f"curso:{self.curso.id}111"):
                db.add(LlamadaIA(componente="ejemplo", modelo="simulado", referencia=ref, ok=True))
        self.path = f"/admin/cursos/{self.curso.id}/eliminar"

    def eliminar(self, **extra):
        return self.web.post(self.path, data={"_csrf": self.token, "nombre_confirmado": self.curso.nombre,
                                             "confirmo": "si", **extra})

    def test_borrado_curso_cerrado_todas_relaciones_otros_cursos_y_cuentas_intactos(self):
        with SessionLocal.begin() as db:
            admin.sumar_coins(db, self.admin.id, db.get(Usuario, self.alumno.id), 1000, "Prueba de canje global")
            canjear(db, db.get(Usuario, self.alumno.id), 30, DEFAULT_PARAMS)
            admin.cerrar_curso(db, self.admin.id, db.get(Curso, self.curso.id), DEFAULT_PARAMS)
        esperados = {}
        with SessionLocal() as db:
            filtros = dict(course_deletion._filtros(db, self.curso.id))
            tablas = {m.__table__: filtro for m, filtro in filtros.items()}
            for tabla in Base.metadata.sorted_tables:
                consulta = select(tabla).order_by(*tabla.primary_key.columns)
                todos = db.execute(consulta).all()
                borrados = db.execute(consulta.where(tablas[tabla])).all() if tabla in tablas else []
                esperados[tabla.name] = [f for f in todos if f not in borrados]
        vista = self.web.get(self.path)
        self.assertEqual(vista.status_code, 200)
        self.assertIn("Eliminar curso definitivamente", vista.text)
        self.assertEqual(self.eliminar().status_code, 303)
        with SessionLocal() as db:
            for tabla in Base.metadata.sorted_tables:
                filas = db.execute(select(tabla).order_by(*tabla.primary_key.columns)).all()
                self.assertEqual(filas, esperados[tabla.name], tabla.name)
        self.assertFalse(self.archivo.exists())
        self.assertEqual(self.web.get(f"/admin/cursos/{self.curso.id}").status_code, 404)

    def test_permiso_csrf_nombre_y_confirmacion_obligatorios(self):
        self.assertEqual(self.eliminar(nombre_confirmado="Otro curso").status_code, 400)
        self.assertEqual(self.eliminar(confirmo="").status_code, 400)
        self.assertEqual(self.eliminar(_csrf="incorrecto").status_code, 403)
        for dni in (DOCENTE, ALUMNO):
            usuario = self.cliente(dni)
            self.assertEqual(usuario.get(self.path).status_code, 403)
            self.assertEqual(usuario.post(self.path, data={"_csrf": self.csrf(dni), "confirmo": "si",
                                                          "nombre_confirmado": self.curso.nombre}).status_code, 403)
        self.assertTrue(self.archivo.exists())

    def test_coins_canjeadas_bloquean_borrado_hasta_corregir_canje(self):
        with SessionLocal.begin() as db:
            ledger.registrar(db, alumno_id=self.alumno.id, curso_id=self.curso.id, tipo="COINS",
                             origen="podio_final", referencia="curso:prueba", cantidad=800)
            canje = canjear(db, db.get(Usuario, self.alumno.id), 30, DEFAULT_PARAMS)
            canje_id = canje.id
        r = self.eliminar()
        self.assertEqual(r.status_code, 400)
        self.assertIn("ya se canjearon", r.text)
        with SessionLocal.begin() as db:
            from db.models import Canje
            corregir(db, db.get(Canje, canje_id), self.admin.id, "Curso de prueba creado por error")
        self.assertEqual(self.eliminar().status_code, 303)
        with SessionLocal() as db:
            self.assertEqual(ledger.saldo_coins(db, self.alumno.id), 0)

    def test_trabajo_ia_en_curso_o_pendiente_impide_borrado(self):
        with jobs.usando_curso(self.curso.id):
            self.assertEqual(self.eliminar().status_code, 400)
        with SessionLocal.begin() as db:
            db.get(Curso, self.curso.id).propuesta_estado = "generando"
        self.assertEqual(self.eliminar().status_code, 400)
        with SessionLocal() as db:
            self.assertIsNotNone(db.get(Curso, self.curso.id))

    def test_fallo_base_revierte_datos_y_recupera_archivo(self):
        with SessionLocal() as db:
            original = db.execute
            def ejecutar(sentencia, *args, **kwargs):
                if isinstance(sentencia, Delete) and sentencia.table.name == "cursos":
                    raise IntegrityError("fallo simulado", {}, RuntimeError("referencia"))
                return original(sentencia, *args, **kwargs)
            with mock.patch.object(db, "execute", side_effect=ejecutar):
                with self.assertRaises(IntegrityError):
                    course_deletion.eliminar_curso(db, self.curso.id, nombre_confirmado=self.curso.nombre, confirmo="si")
            self.assertIsNotNone(db.get(Curso, self.curso.id))
            self.assertGreater(db.scalar(select(func.count()).select_from(Intento).where(Intento.curso_id == self.curso.id)), 0)
        self.assertEqual(self.archivo.read_text(), "transcript de prueba")
        self.assertEqual(list(self.uploads.iterdir()), [self.archivo])

    def test_no_elimina_archivos_compartidos(self):
        with SessionLocal.begin() as db:
            otra = db.scalar(select(Clase).where(Clase.curso_id != self.curso.id))
            otra.fuente_archivo = self.archivo.name
        self.assertEqual(self.eliminar().status_code, 303)
        self.assertTrue(self.archivo.exists())

    def test_ruta_fuera_de_uploads_no_borra_archivo_ni_curso(self):
        with SessionLocal.begin() as db:
            clase = db.scalar(select(Clase).where(Clase.curso_id == self.curso.id).order_by(Clase.numero))
            clase.fuente_archivo = "../documento-ajeno.txt"
        self.assertEqual(self.eliminar().status_code, 400)
        self.assertTrue(self.archivo.exists())
        with SessionLocal() as db:
            self.assertIsNotNone(db.get(Curso, self.curso.id))

    def test_curso_activo_vacio_se_elimina_sin_pagar_podio(self):
        with SessionLocal.begin() as db:
            vacio = Curso(nombre="Creado por error")
            db.add(vacio)
            db.flush()
            curso_id = vacio.id
            from db.models import Movimiento
            movimientos = db.scalar(select(func.count()).select_from(Movimiento))
        r = self.web.post(f"/admin/cursos/{curso_id}/eliminar", data={"_csrf": self.token,
                              "nombre_confirmado": "Creado por error", "confirmo": "si"})
        self.assertEqual(r.status_code, 303)
        with SessionLocal() as db:
            self.assertIsNone(db.get(Curso, curso_id))
            self.assertEqual(db.scalar(select(func.count()).select_from(Movimiento)), movimientos)

    def test_interrupcion_antes_commit_restaura_archivos_y_respeta_operacion_activa(self):
        carpeta = self.uploads / f".eliminar-{self.curso.id}-interrumpido"
        carpeta.mkdir()
        self.archivo.rename(carpeta / self.archivo.name)
        with jobs.eliminando_curso(self.curso.id):
            course_deletion.reconciliar_archivos_eliminados()
            self.assertFalse(self.archivo.exists())
        course_deletion.reconciliar_archivos_eliminados()
        self.assertEqual(self.archivo.read_text(), "transcript de prueba")
        self.assertFalse(carpeta.exists())

    def test_fallo_limpieza_despues_commit_se_completa_en_reintento(self):
        with mock.patch("services.course_deletion.shutil.rmtree", side_effect=OSError("fallo simulado")):
            with self.assertLogs("aulavirtualdmc.eliminar_curso", level="ERROR"):
                r = self.eliminar()
        self.assertEqual(r.status_code, 200)
        self.assertIn("reintentará", r.text)
        self.assertFalse(self.archivo.exists())
        self.assertTrue(list(self.uploads.glob(".eliminar-*")))
        course_deletion.reconciliar_archivos_eliminados()
        self.assertEqual(list(self.uploads.iterdir()), [])

"""Student study summaries: publication, privacy, bounded retries and complete deletion."""

import apoyo  # noqa: F401

from datetime import date, timedelta

from sqlalchemy import func, select

from ai import jobs
from ai.summaries import MAX_FRAGMENTO, generar as resumir
from db.models import Clase, Curso, LlamadaIA, ResumenClase
from db.session import SessionLocal
from falso_llm import FalsoModelo
from rules.calendar import ahora
from services import class_deletion, course_deletion, summaries, validation


class ResumenesTest(apoyo.Caso):
    def setUp(self):
        super().setUp()
        self.curso = self.demo()
        self.falso = FalsoModelo()
        apoyo.activar_ia(self, self.falso)
        self.docente = self.cliente("20000001")
        self.csrf_docente = self.csrf("20000001")

    def subir(self, numero=1):
        respuesta = self.docente.post(f"/docente/cursos/{self.curso.id}/clases/nueva", data={
            "_csrf": self.csrf_docente, "numero": str(numero), "fecha": date.today().isoformat(),
            "titulo": "Agrupaciones con pandas", "tarea": "Practicar con ventas.",
            "transcript_texto": "Soy la profesora Fernanda Ríos. Mi correo es fernanda@dmc.pe. "
                "En la sesión cargamos un Excel con pandas y agrupamos ventas por ciudad con groupby y sum."})
        self.assertEqual(respuesta.status_code, 303, respuesta.text[:400])
        with SessionLocal() as db:
            return db.scalar(select(Clase).where(Clase.curso_id == self.curso.id, Clase.numero == numero))

    def test_se_genera_una_vez_y_solo_se_muestra_al_publicar(self):
        clase = self.subir()
        with SessionLocal() as db:
            resumen = db.get(ResumenClase, clase.id)
            self.assertEqual((resumen.estado, resumen.intentos), ("listo", 1))
            self.assertIn("Agrupar ventas", resumen.contenido["secciones"][0]["titulo"])
        alumno = self.cliente("70000001")
        self.aceptar_consentimiento(alumno, "70000001")
        url = f"/alumno/cursos/{self.curso.id}"
        self.assertNotIn("Agrupar ventas con pandas", alumno.get(url).text)
        self.docente.post(f"/docente/clases/{clase.id}/publicar", data={"_csrf": self.csrf_docente})
        llamadas = len(self.falso.componentes)
        for _ in range(2):
            pagina = alumno.get(url)
            self.assertEqual(pagina.status_code, 200)
            self.assertIn("Agrupar ventas con pandas", pagina.text)
            self.assertLess(pagina.text.index('id="t-quizzes"'), pagina.text.index('id="t-resumenes"'))
            self.assertLess(pagina.text.index('id="t-resumenes"'), pagina.text.index('id="t-tareas"'))
            self.assertNotIn("fernanda@dmc.pe", pagina.text)
        self.assertEqual(len(self.falso.componentes), llamadas)
        self.assertEqual(self.falso.componentes.count("resumidor"), 1)
        for payload in self.falso.payloads:
            self.assertNotIn("Fernanda Ríos", payload)
            self.assertNotIn("fernanda@dmc.pe", payload)
        with SessionLocal.begin() as db:
            self.assertFalse(summaries.programar(db, db.get(Clase, clase.id)))

    def test_error_del_resumen_no_bloquea_quiz_y_tiene_reintento_protegido(self):
        self.falso.fallar.add("resumidor")
        clase = self.subir()
        with SessionLocal() as db:
            self.assertEqual(db.get(Clase, clase.id).estado, "por_validar")
            self.assertEqual(db.get(ResumenClase, clase.id).estado, "error")
        url = f"/docente/clases/{clase.id}/resumen/reintentar"
        pagina = self.docente.get(f"/docente/clases/{clase.id}")
        self.assertIn("Reintentar resumen", pagina.text)
        self.assertIn("data-ai-action", pagina.text)
        self.assertEqual(self.docente.post(url).status_code, 403)
        otro = self.cliente("20000002")
        self.assertEqual(otro.post(url, data={"_csrf": self.csrf("20000002")}).status_code, 404)
        alumno = self.cliente("70000001")
        self.aceptar_consentimiento(alumno, "70000001")
        self.assertEqual(alumno.post(url, data={"_csrf": self.csrf("70000001")}).status_code, 403)
        self.falso.fallar.clear()
        self.assertEqual(self.docente.post(url, data={"_csrf": self.csrf_docente}).status_code, 303)
        with SessionLocal() as db:
            self.assertEqual(db.get(ResumenClase, clase.id).estado, "listo")
        llamadas = self.falso.componentes.count("resumidor")
        self.assertEqual(self.docente.post(url, data={"_csrf": self.csrf_docente}).status_code, 400)
        self.assertEqual(self.falso.componentes.count("resumidor"), llamadas)

    def test_mapeo_fallido_tambien_conserva_el_resumen_independiente(self):
        self.falso.fallar.add("mapeador")
        clase = self.subir()
        with SessionLocal() as db:
            self.assertEqual(db.get(Clase, clase.id).estado, "error")
            self.assertEqual(db.get(ResumenClase, clase.id).estado, "listo")

    def test_rellena_clases_existentes_y_recupera_reinicio_sin_repetir_listos(self):
        with SessionLocal.begin() as db:
            clase = Clase(curso_id=self.curso.id, numero=8, fecha=date.today(), fuente_tipo="texto",
                          transcript="En esta clase se comparó groupby con una tabla dinámica.", estado="publicada")
            db.add(clase)
            db.flush()
            clase_id = clase.id
        summaries.completar_pendientes(reinicio=True)
        summaries.completar_pendientes()
        with SessionLocal() as db:
            self.assertEqual(db.get(ResumenClase, clase_id).estado, "listo")
        self.assertEqual(self.falso.componentes.count("resumidor"), 1)
        with SessionLocal.begin() as db:
            resumen = db.get(ResumenClase, clase_id)
            resumen.estado, resumen.contenido = "generando", None
        summaries.completar_pendientes(reinicio=True)
        with SessionLocal() as db:
            self.assertEqual(db.get(ResumenClase, clase_id).estado, "listo")
        self.assertEqual(self.falso.componentes.count("resumidor"), 2)

    def test_reintentos_automaticos_limitados_y_sin_generacion_en_cada_tick(self):
        self.falso.fallar.add("resumidor")
        clase = self.subir()
        summaries.completar_pendientes()
        self.assertEqual(self.falso.componentes.count("resumidor"), 1)
        for _ in range(3):
            with SessionLocal.begin() as db:
                db.get(ResumenClase, clase.id).proximo_intento_en = ahora() - timedelta(seconds=1)
            summaries.completar_pendientes()
        self.assertEqual(self.falso.componentes.count("resumidor"), 3)
        with SessionLocal() as db:
            self.assertEqual(db.get(ResumenClase, clase.id).intentos, 3)

    def test_transcript_largo_incluye_el_final_y_consolida_fragmentos(self):
        texto = "Inicio de la sesión. " + "contenido académico " * (MAX_FRAGMENTO // 15) + " FINAL_UNICO_DE_LA_SESION"
        resultado = resumir(texto, referencia="clase:999:resumen")
        self.assertIn("secciones", resultado)
        entradas = "\n".join(self.falso.payloads)
        self.assertIn("FINAL_UNICO_DE_LA_SESION", entradas)
        self.assertIn("resumenes_parciales_en_orden", entradas)
        self.assertGreaterEqual(self.falso.componentes.count("resumidor"), 3)

    def test_contenido_escapado_y_datos_de_otro_curso_ocultos(self):
        clase = self.subir()
        with SessionLocal.begin() as db:
            validation.publicar(db, clase.id, None)
            contenido = dict(db.get(ResumenClase, clase.id).contenido)
            contenido["introduccion"] = '<script>alert("inseguro")</script>'
            db.get(ResumenClase, clase.id).contenido = contenido
            otro = Curso(nombre="Curso privado")
            db.add(otro)
            db.flush()
            privada = Clase(curso_id=otro.id, numero=1, fecha=date.today(), fuente_tipo="texto", estado="publicada")
            db.add(privada)
            db.flush()
            db.add(ResumenClase(clase_id=privada.id, estado="listo", contenido={"introduccion": "SECRETO_OTRO_CURSO"}))
        alumno = self.cliente("70000001")
        self.aceptar_consentimiento(alumno, "70000001")
        html = alumno.get(f"/alumno/cursos/{self.curso.id}").text
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn('<script>alert("inseguro")', html)
        self.assertNotIn("SECRETO_OTRO_CURSO", html)

    def test_borrar_clase_o_curso_borra_resumen_y_registro_ia(self):
        for alcance in ("clase", "curso"):
            with self.subTest(alcance=alcance):
                clase = self.subir(numero=1 if alcance == "clase" else 2)
                with SessionLocal() as db:
                    self.assertIsNotNone(db.get(ResumenClase, clase.id))
                with SessionLocal() as db:
                    if alcance == "clase":
                        class_deletion.eliminar_clase(db, clase.id, confirmo="si")
                    else:
                        course_deletion.eliminar_curso(db, self.curso.id, nombre_confirmado=self.curso.nombre, confirmo="si")
                # A previously queued task cannot reinsert content or log another AI call.
                summaries.generar(clase.id)
                with SessionLocal() as db:
                    self.assertIsNone(db.get(ResumenClase, clase.id))
                    self.assertEqual(db.scalar(select(func.count()).select_from(LlamadaIA).where(
                        LlamadaIA.referencia == f"clase:{clase.id}:resumen")), 0)

    def test_rollback_no_lanza_resumen_y_trabajo_activo_impide_borrar(self):
        clase = self.subir()
        with SessionLocal.begin() as db:
            db.delete(db.get(ResumenClase, clase.id))
        llamadas = self.falso.componentes.count("resumidor")
        with SessionLocal() as db:
            summaries.programar(db, db.get(Clase, clase.id))
            db.rollback()
        self.assertEqual(self.falso.componentes.count("resumidor"), llamadas)
        with jobs.usando_curso(self.curso.id), SessionLocal() as db:
            with self.assertRaises(jobs.CursoEnUso):
                class_deletion.eliminar_clase(db, clase.id, confirmo="si")

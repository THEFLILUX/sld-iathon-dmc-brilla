"""AI action markers match actual HTTP flows, independent of the configured provider."""

import apoyo  # noqa: F401

import re

from sqlalchemy import select

from db.models import Clase, Curso, Quiz, QuizItem, Reto, RetoVersion, Tema
from db.session import SessionLocal
from falso_llm import FalsoModelo


def botones(html):
    return [(attrs, apoyo.texto_visible(label).strip())
            for attrs, label in re.findall(r'<button\b([^>]*)>(.*?)</button>', html, re.S)]


class BrillaTest(apoyo.Caso):
    def setUp(self):
        super().setUp()
        self.curso = self.demo(actividad=True)
        with SessionLocal() as db:
            self.clase = db.scalar(select(Clase).where(Clase.curso_id == self.curso.id, Clase.numero == 1))
        apoyo.activar_ia(self, FalsoModelo())

    def accion(self, html, label, usa_ia):
        encontrados = [(attrs, text) for attrs, text in botones(html) if text.endswith(label)]
        self.assertEqual(len(encontrados), 1, label)
        self.assertEqual('data-ai-action' in encontrados[0][0], usa_ia, label)
        return encontrados[0][0]

    def test_admin_misma_mascota_para_openai_y_gemini(self):
        web = self.cliente('10000001')
        for proveedor in ('openai', 'gemini'):
            apoyo.configurar(self, LLM_PROVIDER=proveedor)
            pagina = web.get(f'/admin/cursos/{self.curso.id}')
            self.assertEqual(pagina.status_code, 200)
            for label in ('Cargar malla', 'Subir brochure', 'Volver a pedir la propuesta a la IA'):
                self.accion(pagina.text, label, True)
            for label in ('Agregar tema', 'Inscribir', 'Cerrar curso'):
                self.accion(pagina.text, label, False)
            self.assertEqual(pagina.text.count('img/brilla-ai.png'), 3)
        asset = web.get('/static/img/brilla-ai.png')
        self.assertEqual(asset.status_code, 200)
        self.assertEqual(asset.headers['content-type'], 'image/png')

    def test_brochure_sin_temas_no_inicia_propuesta(self):
        with SessionLocal.begin() as db:
            curso = Curso(nombre='Curso sin malla')
            db.add(curso)
            db.flush()
            curso_id = curso.id
        pagina = self.cliente('10000001').get(f'/admin/cursos/{curso_id}')
        self.accion(pagina.text, 'Subir brochure', False)
        self.accion(pagina.text, 'Cargar malla', True)

    def test_docente_procesamiento_y_rechazo_solo_si_hay_reemplazo(self):
        web = self.cliente('20000001')
        pagina = web.get(f'/docente/cursos/{self.curso.id}/clases/nueva')
        attrs = self.accion(pagina.text, 'Procesar clase', True)
        self.assertIn('data-submit', attrs)
        with SessionLocal.begin() as db:
            clase = db.get(Clase, self.clase.id)
            clase.estado = 'error'
            retos = db.scalars(select(Reto).where(Reto.clase_id == clase.id, Reto.uso == 'clase')).all()
            retos[0].estado = 'error'
        pagina = web.get(f'/docente/clases/{self.clase.id}')
        self.assertEqual(pagina.status_code, 200)
        self.accion(pagina.text, 'Reintentar', True)
        self.accion(pagina.text, 'Generar otro', True)
        for form in re.findall(r'<form\b.*?</form>', pagina.text, re.S):
            accion = re.search(r'/retos/(\d+)/rechazar', form)
            if accion:
                with SessionLocal() as db:
                    reto = db.get(Reto, int(accion.group(1)))
                    esperado = reto.uso == 'clase' and reto.posicion is not None
                self.accion(form, 'Rechazar', esperado)

    def test_alumno_solo_enviar_respuesta_abierta_usa_ia(self):
        web = self.cliente('70000001')
        self.aceptar_consentimiento(web, '70000001')
        ruta = f'/alumno/cursos/{self.curso.id}/clases/{self.clase.id}'
        pagina = web.get(f'/alumno/cursos/{self.curso.id}')
        self.accion(pagina.text, 'Generar', False)
        self.assertEqual(web.post(ruta + '/generar', data={'_csrf': self.csrf('70000001')}).status_code, 303)
        web.get(ruta + '/quiz')
        with SessionLocal() as db:
            quiz = db.scalar(select(Quiz).where(Quiz.clase_id == self.clase.id, Quiz.alumno_id == self.usuario('70000001').id))
            item = db.scalar(select(QuizItem).where(QuizItem.quiz_id == quiz.id).order_by(QuizItem.orden))
            version_id = item.reto_version_id
        for tipo in ('alternativas', 'completar', 'definir', 'caso'):
            with SessionLocal.begin() as db:
                db.get(RetoVersion, version_id).tipo = tipo
            pagina = web.get(ruta + '/quiz')
            self.assertEqual(pagina.status_code, 200)
            self.accion(pagina.text, 'Enviar', tipo in ('definir', 'caso'))
            self.accion(pagina.text, 'Pedir pista (0/3)', False)

    def test_reto_propio_basico_no_completa_otros_niveles(self):
        with SessionLocal.begin() as db:
            db.query(Tema).filter(Tema.curso_id == self.curso.id).update({'nivel_maximo': 'basico'})
        pagina = self.cliente('20000001').get(f'/docente/clases/{self.clase.id}/retos/nuevo')
        self.assertEqual(pagina.status_code, 200)
        self.accion(pagina.text, 'Guardar reto', False)
        self.assertIn('data-ai-topic-form', pagina.text)

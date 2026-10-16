"""Grounding, live retrieval, privacy, role/course isolation and safe failure of the teacher RAG."""
import apoyo  # noqa: F401

import json
from datetime import timedelta
from unittest.mock import patch

from sqlalchemy import func, select

from ai import jobs
from ai.assistant import RespuestaAsistenteIA
from ai.llm import IAError
from db.models import (Base, Clase, Curso, Inscripcion, Intento, LlamadaIA, PerfilUsuario,
                       Sesion, TareaHecha, Usuario)
from db.session import SessionLocal
from falso_llm import FalsoModelo
from rules.calendar import ahora
from services import assistant, profiles


class AsistenteTest(apoyo.Caso):
    def setUp(self):
        super().setUp()
        self.curso = self.demo(actividad=True)
        self.alumna = self.usuario('70000001')
        self.docente = self.usuario('20000001')
        self.web = self.cliente('20000001')
        self.ruta = f'/docente/cursos/{self.curso.id}/asistente'
        self.modelo = FalsoModelo()
        apoyo.activar_ia(self, self.modelo)
        with SessionLocal.begin() as db:
            profiles.preparar_existentes(db)

    def preguntar(self, **datos):
        return self.web.post(self.ruta, data={'_csrf': self.csrf('20000001'),
            'pregunta': '¿Qué temas debería reforzar según los registros?', 'alumno_id': str(self.alumna.id),
            'periodo': '30', **datos})

    def contexto(self, **datos):
        with SessionLocal() as db:
            return assistant.recuperar(db, db.get(Curso, self.curso.id),
                datos.pop('pregunta', '¿Qué temas debería reforzar según los registros?'), **datos)

    def test_vista_navegacion_y_accion_brilla_sin_consumo_al_abrir(self):
        r = self.web.get(self.ruta)
        self.assertEqual(r.status_code, 200)
        self.assertIn('data-ai-action', r.text)
        self.assertIn('img/brilla-ai.png', r.text)
        self.assertIn('data-assistant-form', r.text)
        self.assertEqual(r.headers['cache-control'], 'no-store')
        self.assertEqual(self.modelo.componentes, [])
        self.assertIn('Asistente Brilla', self.web.get(f'/docente/cursos/{self.curso.id}').text)
        self.assertIn('Consultar a Brilla', self.web.get(f'/docente/cursos/{self.curso.id}/alumnos/{self.alumna.id}').text)

    def test_roles_cursos_y_csrf_antes_de_ia(self):
        for web, esperado in ((self.cliente(), 303), (self.cliente('70000001'), 403),
                              (self.cliente('20000002'), 404)):
            self.assertEqual(web.get(self.ruta).status_code, esperado)
            self.assertEqual(web.post(self.ruta, data={'_csrf': 'x', 'pregunta': 'Consulta de otro curso'}).status_code,
                             403)
        self.assertEqual(self.web.post(self.ruta, data={'pregunta': 'Sin protección CSRF'}).status_code, 403)
        otra = self.cliente('20000002')
        self.assertEqual(otra.post(self.ruta, data={'_csrf': self.csrf('20000002'),
            'pregunta': 'Consulta de otro curso'}).status_code, 404)
        self.assertEqual(self.cliente('10000001').get(self.ruta).status_code, 200)
        self.assertEqual(self.modelo.componentes, [])

    def test_alumno_ajeno_curso_y_valores_invalidos(self):
        with SessionLocal.begin() as db:
            ajeno = Usuario(dni='99999991', nombre='Persona', apellido='Restringida', rol='alumno',
                            password_hash='sin-acceso')
            db.add(ajeno); db.flush(); ajeno_id = ajeno.id
        self.assertEqual(self.web.get(self.ruta + f'?alumno_id={ajeno_id}').status_code, 404)
        for datos in ({'alumno_id': str(ajeno_id)}, {'periodo': '999'}, {'pregunta': 'corta'}, {'pregunta': 'x'*1201}):
            r = self.preguntar(**datos)
            self.assertEqual(r.status_code, 400)
            self.assertIn('data-notification-close', r.text)
        self.assertEqual(self.modelo.componentes, [])

    def test_respuesta_citas_enlaces_y_nombres_solo_en_navegador(self):
        r = self.preguntar(pregunta=f'¿Cómo puede mejorar {self.alumna.nombre_completo}?')
        self.assertEqual(r.status_code, 200, r.text[-1500:])
        self.assertIn(self.alumna.nombre_completo, r.text)
        self.assertIn('href="#fuente-F2"', r.text)
        self.assertIn(f'/alumnos/{self.alumna.id}/perfil', r.text)
        self.assertIn('sin_notas_oficiales', self.modelo.payloads[-1])
        texto = self.modelo.payloads[-1]
        self.assertNotIn(self.alumna.nombre_completo, texto)
        self.assertNotIn(self.alumna.dni, texto)
        self.assertIn(self.alumna.alias, texto)
        with SessionLocal() as db:
            uso = db.scalar(select(LlamadaIA).where(LlamadaIA.componente == 'asistente_docente'))
            self.assertEqual(uso.referencia, f'curso:{self.curso.id}:asistente')
            self.assertEqual(uso.tokens_entrada, 120)

    def test_aislamiento_fuentes_y_anonimizacion_todos_los_textos(self):
        with SessionLocal.begin() as db:
            otro = Curso(nombre='CURSO SECRETO EXTERNO'); db.add(otro); db.flush()
            db.add(Clase(curso_id=otro.id, numero=1, fecha=ahora().date(), fuente_tipo='texto',
                         titulo='SENTINELA EXTERNA', transcript='pandas SENTINELA EXTERNA', estado='publicada'))
            p = db.get(PerfilUsuario, self.alumna.id)
            p.datos = {**p.datos, 'objetivo': f'{self.alumna.nombre_completo}, DNI {self.alumna.dni}, privado@example.com, 999123456'}
        ctx = self.contexto(alumno_id=self.alumna.id)
        salida = json.dumps([f['datos'] for f in ctx['fuentes']], ensure_ascii=False)
        for prohibido in ('SENTINELA EXTERNA', 'CURSO SECRETO EXTERNO', self.alumna.nombre_completo,
                          self.alumna.dni, 'privado@example.com', '999123456'):
            self.assertNotIn(prohibido, salida)
        perfiles = next(f for f in ctx['fuentes'] if 'perfil' in f['datos'])
        self.assertFalse(perfiles['datos']['revisado_por_titular'])
        self.assertNotIn('edad', perfiles['datos']['perfil'])

    def test_tareas_declaradas_no_entregas_y_sin_datos_no_cero(self):
        with SessionLocal.begin() as db:
            clase = db.scalar(select(Clase).where(Clase.curso_id == self.curso.id, Clase.estado == 'publicada'))
            clase.tarea = 'Practicar con un dataset.'
            db.add(TareaHecha(alumno_id=self.alumna.id, clase_id=clase.id))
            db.query(Intento).filter(Intento.alumno_id == self.alumna.id).delete()
        ctx = self.contexto(alumno_id=self.alumna.id)
        tarea = next(f['datos'] for f in ctx['fuentes'] if 'marcadas_listas' in f['datos'])
        rendimiento = next(f['datos'] for f in ctx['fuentes'] if 'promedio_puntajes_0_a_100' in f['datos'] and 'alumno' in f['datos'])
        self.assertEqual(tarea['marcadas_listas'], 1)
        self.assertIn('No se registran entregas', tarea['limite'])
        self.assertIsNone(rendimiento['promedio_puntajes_0_a_100'])
        self.assertEqual(rendimiento['intentos'], 0)

    def test_metricas_periodo_excluyen_pendientes_y_hay_lectura_fresca(self):
        alumno_id = self.usuario('70000002').id
        with SessionLocal.begin() as db:
            intentos = db.scalars(select(Intento).where(Intento.alumno_id == alumno_id, Intento.curso_id == self.curso.id)).all()
            self.assertTrue(intentos)
            for intento in intentos:
                intento.creado_en = ahora() - timedelta(days=10)
                intento.estado, intento.puntaje = 'completado', 80
        corto, largo = self.contexto(alumno_id=alumno_id, periodo=7), self.contexto(alumno_id=alumno_id, periodo=30)
        def rendimiento(c):
            return next(f['datos'] for f in c['fuentes'] if 'intentos' in f['datos'])
        self.assertEqual(rendimiento(corto)['intentos'], 0)
        self.assertEqual(rendimiento(largo)['promedio_puntajes_0_a_100'], 80)
        with SessionLocal.begin() as db:
            db.query(Intento).filter(Intento.alumno_id == alumno_id, Intento.curso_id == self.curso.id).update({'estado':'pendiente', 'puntaje':None})
        actual = rendimiento(self.contexto(alumno_id=alumno_id, periodo=30))
        self.assertIsNone(actual['promedio_puntajes_0_a_100'])
        self.assertEqual(actual['completados'], 0)

    def test_mencion_por_nombre_sin_tildes_y_filtro_no_confunde_otro_alumno(self):
        ctx = self.contexto(pregunta=f'¿Cómo va {assistant._normal(self.alumna.nombre_completo)}?')
        self.assertEqual(ctx['alcance']['alumnos_con_detalle'], [self.alumna.alias])
        self.assertIn(self.alumna.alias, ctx['pregunta_anon'])
        otro = self.usuario('70000002')
        r = self.preguntar(pregunta=f'¿Cómo va {otro.nombre_completo}?')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.modelo.componentes, [])

    def test_contexto_limitado_sin_perder_total_del_grupo(self):
        with SessionLocal.begin() as db:
            for i in range(20):
                a = Usuario(dni=f'99000{i:03}', nombre=f'Participante{i}', apellido='Curso', rol='alumno', password_hash='x')
                db.add(a); db.flush()
                db.add(Inscripcion(usuario_id=a.id, curso_id=self.curso.id, rol_en_curso='alumno'))
        ctx = self.contexto()
        self.assertEqual(len(ctx['alcance']['alumnos_con_detalle']), assistant.MAX_DETALLE)
        self.assertGreater(ctx['fuentes'][0]['datos']['alumnos_activos_inscritos'], assistant.MAX_DETALLE)
        self.assertTrue(ctx['fuentes'][0]['datos']['detalle_parcial_del_grupo'])

    def test_fragmento_relevante_al_final_y_texto_actualizado_sin_indice_obsoleto(self):
        with SessionLocal.begin() as db:
            c = db.scalar(select(Clase).where(Clase.curso_id == self.curso.id, Clase.estado == 'publicada'))
            c.transcript_anon = 'Introducción y contexto. ' * 700 + ' Fotogrametría: reconstruir volúmenes con imágenes.'
        ctx = self.contexto(pregunta='¿Qué se enseñó sobre fotogrametría?')
        partes = [f for f in ctx['fuentes'] if 'fragmento' in f['datos']]
        self.assertTrue(any('Fotogrametría' in f['datos']['texto'] for f in partes))
        # Removing the current text immediately removes it from retrieval; no secondary index exists.
        with SessionLocal.begin() as db:
            db.get(Clase, c.id).transcript_anon = 'Contenido actualizado sin el concepto anterior.'
        siguiente = self.contexto(pregunta='¿Qué se enseñó sobre fotogrametría?')
        self.assertFalse(any('Fotogrametría' in str(f['datos']) for f in siguiente['fuentes']))

    def test_referencia_inventada_bloqueada_y_proveedor_caido_recuperable(self):
        mala = {'hallazgos':[{'texto':'Dato inventado', 'fuentes':['F99999']}], 'recomendaciones':[], 'limites':['Sin datos']}
        with patch.object(self.modelo, 'asistente_docente', return_value=mala):
            r = self.preguntar()
            self.assertEqual(r.status_code, 503)
            self.assertNotIn('Dato inventado', r.text)
        self.modelo.fallar.add('asistente_docente')
        self.assertEqual(self.preguntar().status_code, 503)
        self.modelo.fallar.clear()
        self.assertEqual(self.preguntar().status_code, 200)

    def test_xss_escapado_y_sin_mutacion_de_datos_academicos(self):
        with SessionLocal() as db:
            tablas = [t for t in Base.metadata.sorted_tables if t.name not in (Sesion.__tablename__, LlamadaIA.__tablename__)]
            antes = {t.name: [tuple(str(v) for v in row) for row in db.execute(select(t).order_by(*t.primary_key.columns))]
                     for t in tablas}
        mal = {'hallazgos':[{'texto':'<script>alert(1)</script>', 'fuentes':['F1']}],
               'recomendaciones':[], 'limites':['Sin notas oficiales.']}
        with patch.object(self.modelo, 'asistente_docente', return_value=mal):
            r = self.preguntar(pregunta='¿Qué dice <img src=x onerror=alert(1)>?')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('<script>alert(1)</script>', r.text)
        self.assertIn('&lt;script&gt;', r.text)
        with SessionLocal() as db:
            despues = {t.name: [tuple(str(v) for v in row) for row in db.execute(select(t).order_by(*t.primary_key.columns))]
                       for t in tablas}
        self.assertEqual(antes, despues)

    def test_cupos_y_consultas_simultaneas_no_duplican(self):
        assistant._ACTIVOS.add(self.docente.id)
        try:
            self.assertEqual(self.preguntar().status_code, 400)
        finally:
            assistant._ACTIVOS.discard(self.docente.id)
        with jobs.eliminando_curso(self.curso.id):
            self.assertEqual(self.modelo.componentes, [])
        self.assertEqual(self.preguntar().status_code, 200)

    def test_curso_sin_alumnos_informa_cero_y_no_inventa_detalle(self):
        with SessionLocal.begin() as db:
            curso = Curso(nombre='Curso sin alumnos'); db.add(curso); db.flush(); cid = curso.id
        with SessionLocal() as db:
            ctx = assistant.recuperar(db, db.get(Curso, cid), '¿Cómo va el grupo del curso?')
        self.assertEqual(ctx['alcance']['alumnos_con_detalle'], [])
        self.assertEqual(ctx['fuentes'][0]['datos']['alumnos_activos_inscritos'], 0)
        self.assertIsNone(ctx['fuentes'][0]['datos']['promedio_puntajes_0_a_100'])

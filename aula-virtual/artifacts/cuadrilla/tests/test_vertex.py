"""Real LangChain Vertex transports plus admin switching, verification and immutable job snapshots."""
import apoyo  # noqa: F401

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from google.oauth2.credentials import Credentials
from sqlalchemy import func, select

from ai import jobs, llm, proveedores, runtime
from ai.assistant import RespuestaAsistenteIA
from ai.schemas import MapeoIA
from config import APP_DIR, Settings, settings
from db.models import ConfiguracionIA, LlamadaIA
from db.session import SessionLocal
from falso_llm import FalsoModelo
from services import ai_settings
from services.ai_settings import ConexionIA
from test_proveedores import EJEMPLOS, http_simulado, respuesta_gemini


class VertexTransporteTest(apoyo.Caso):
    def setUp(self):
        super().setUp(); self.demo()
        apoyo.configurar(self, LLM_PROVIDER='vertex', TRANSCRIPTION_PROVIDER='vertex', LLM_MODEL='',
            TRANSCRIPTION_MODEL='', GOOGLE_CLOUD_PROJECT='proyecto-prueba', GOOGLE_CLOUD_LOCATION='global',
            OPENAI_API_KEY='', GOOGLE_API_KEY='no-usar-esta-clave', VERTEX_MODEL='gemini-3.5-flash-lite')
        self.cred = Credentials(token='token-vertex-prueba')
        self.adc = patch('google.auth.default',return_value=(self.cred,'proyecto-prueba')).start()
        self.addCleanup(patch.stopall)

    def test_vertex_adc_sin_api_key_y_esquema_estructurado(self):
        with http_simulado(lambda r:(200,respuesta_gemini(json.dumps(EJEMPLOS[MapeoIA]())))) as capturas:
            salida = llm.llamar('mapeador',MapeoIA,'sistema',{'transcript':'clase'}, referencia='clase:1')
        self.assertEqual(len(salida.temas),2)
        r = capturas[0]
        self.assertEqual(r.url.host,'aiplatform.googleapis.com')
        self.assertIn('/projects/proyecto-prueba/locations/global/publishers/google/models/gemini-3.5-flash-lite:generateContent',r.url.path)
        self.assertEqual(r.headers['authorization'],'Bearer token-vertex-prueba')
        self.assertNotIn('x-goog-api-key',r.headers)
        self.assertIn('responseJsonSchema',json.loads(r.content)['generationConfig'])
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(LlamadaIA.modelo)), 'vertex:gemini-3.5-flash-lite')

    def test_todos_los_contratos_de_la_aplicacion_en_vertex(self):
        ejemplos = {**EJEMPLOS, RespuestaAsistenteIA:lambda: {'hallazgos':[], 'recomendaciones':[], 'limites':['Sin datos']},
                    ConexionIA:lambda:{'estado':'ok'}}
        for schema, ejemplo in ejemplos.items():
            with self.subTest(schema=schema.__name__), http_simulado(lambda r:(200,respuesta_gemini(json.dumps(ejemplo())))):
                self.assertIsInstance(llm.llamar('verificacion',schema,'sistema',{'texto':'clase'}),schema)

    def test_transcripcion_vertex_usa_audio_y_el_mismo_modelo(self):
        with http_simulado(lambda r:(200,respuesta_gemini('Hoy usamos Python para analizar datos de ventas.'))) as capturas:
            texto = proveedores.transcribir(APP_DIR/'ai/fixtures/conexion.mp3','Transcribe literalmente.')
        self.assertIn('ventas',texto)
        cuerpo = json.loads(capturas[0].content)
        self.assertTrue(any('inlineData' in p for p in cuerpo['contents'][0]['parts']))
        self.assertIn('gemini-3.5-flash-lite',capturas[0].url.path)

    def test_falta_adc_error_seguro_y_registrado(self):
        from google.auth.exceptions import DefaultCredentialsError
        self.adc.side_effect = DefaultCredentialsError('ruta/privada-con-secreto')
        with self.assertRaises(llm.IAError) as error:
            llm.llamar('mapeador',MapeoIA,'sistema',{})
        self.assertIn('cuenta de servicio',str(error.exception))
        self.assertNotIn('ruta/privada',str(error.exception))
        with SessionLocal() as db:self.assertFalse(db.scalar(select(LlamadaIA.ok)))


class ConfiguracionIATest(apoyo.Caso):
    def setUp(self):
        super().setUp(); self.demo()
        self.web = self.cliente('10000001'); self.admin = self.usuario('10000001')
        self.modelo = FalsoModelo(); apoyo.activar_ia(self,self.modelo)
        apoyo.configurar(self,GOOGLE_CLOUD_PROJECT='proyecto-prueba',GOOGLE_CLOUD_LOCATION='global')
        self.audio = patch.object(proveedores,'transcribir',return_value='Hoy usamos Python para analizar datos de ventas.').start()
        self.addCleanup(patch.stopall)

    def enviar(self, **extra):
        return self.web.post('/admin/ia',data={'_csrf':self.csrf('10000001'),'proveedor':'vertex',
            'modelo_openai':'gpt-6-luna','audio_openai':'gpt-4o-mini-transcribe','modelo_vertex':'gemini-3.5-flash-lite',
            'version':'0','accion':'activar',**extra})

    def contar(self):
        with SessionLocal() as db:return db.scalar(select(func.count()).select_from(ConfiguracionIA))

    def test_pagina_exclusiva_admin_csrf_y_secretos_ausentes(self):
        r=self.web.get('/admin/ia');self.assertEqual(r.status_code,200)
        self.assertIn('gemini-3.5-flash-lite',r.text)
        self.assertIn('data-ai-action',r.text)
        self.assertNotIn('clave-falsa',r.text)
        for dni in ('20000001','70000001'):
            web=self.cliente(dni)
            self.assertEqual(web.get('/admin/ia').status_code,403)
            self.assertEqual(web.post('/admin/ia',data={'_csrf':self.csrf(dni)}).status_code,403)
        self.assertEqual(self.web.post('/admin/ia',data={}).status_code,403)
        self.assertEqual(self.contar(),0)

    def test_probar_no_activa_y_fallo_no_sustituye_proveedor(self):
        r=self.enviar(accion='probar')
        self.assertEqual(r.status_code,200);self.assertEqual(self.contar(),0)
        self.assertEqual(runtime.actual().proveedor,'openai')
        self.assertIn('La conexión de texto y transcripción funciona',r.text)
        self.audio.side_effect=RuntimeError('secreto-interno')
        r=self.enviar();self.assertEqual(r.status_code,503)
        self.assertNotIn('secreto-interno',r.text);self.assertEqual(self.contar(),0)

    def test_switch_persistido_en_toda_la_app_y_vuelta_a_openai(self):
        self.assertEqual(self.enviar().status_code,303)
        confirmacion=self.web.get('/admin/ia?ok=ia_configurada')
        self.assertIn('Proveedor de IA activado',confirmacion.text)
        self.assertIn('data-notification-close',confirmacion.text)
        config=runtime.cargar();self.assertEqual(config.proveedor,'vertex')
        self.assertEqual(config.modelo_audio,'gemini-3.5-flash-lite')
        self.assertTrue(settings.ai_enabled)
        self.assertEqual(settings.modelo_llm,'gemini-3.5-flash-lite')
        self.assertEqual(settings.modelo_transcripcion,'gemini-3.5-flash-lite')
        self.assertIn('Gemini · Vertex AI',self.web.get('/admin').text)
        self.assertEqual(self.enviar(proveedor='openai',version=str(config.version)).status_code,303)
        self.assertEqual(runtime.actual().proveedor,'openai')
        self.assertEqual(runtime.actual().modelo_audio,'gpt-4o-mini-transcribe')
        self.assertEqual(self.contar(),2)
        with SessionLocal() as db:
            for fila in db.scalars(select(ConfiguracionIA)):
                self.assertEqual(fila.cambiado_por,self.admin.id)
                self.assertIsNotNone(fila.verificado_en)
                self.assertNotIn('key',json.dumps(fila.opciones).lower())

    def test_modelos_editables_y_no_hay_cambio_con_formulario_obsoleto(self):
        self.assertEqual(self.enviar(modelo_vertex='gemini-3.5-flash-lite-nueva-version').status_code,303)
        self.assertEqual(runtime.actual().modelo,'gemini-3.5-flash-lite-nueva-version')
        llamadas=len(self.modelo.componentes)
        self.assertEqual(self.enviar().status_code,400)
        self.assertEqual(len(self.modelo.componentes),llamadas)
        self.assertEqual(self.contar(),1)

    def test_invalida_no_gasta_ia_ni_acepta_endpoints_claves_o_proyectos(self):
        for datos in ({'proveedor':'otro'},{'modelo_vertex':'https://sitio.example/modelo'},
                      {'modelo_openai':'x\nOPENAI_API_KEY=secreto'},{'modelo_vertex':'gpt-6-luna'}):
            self.assertEqual(self.enviar(**datos).status_code,400)
        self.assertEqual(self.modelo.componentes,[])
        self.assertEqual(self.contar(),0)
        self.enviar(GOOGLE_CLOUD_PROJECT='otro-proyecto',api_key='no-guardar')
        self.assertEqual(runtime.actual().proyecto,'proyecto-prueba')

    def test_no_activa_si_audio_vacio_o_modelo_no_disponible(self):
        self.audio.return_value=''
        self.assertEqual(self.enviar().status_code,503)
        self.assertEqual(self.contar(),0)
        self.audio.return_value='Hoy analizamos datos de ventas.'
        self.modelo.fallar.add('conexion_ia')
        self.assertEqual(self.enviar().status_code,503)
        self.assertEqual(self.contar(),0)

    def test_snapshot_de_trabajo_no_cambia_si_admin_activa_otro(self):
        anterior=runtime.actual()
        with runtime.usar(anterior):
            self.assertEqual(self.enviar().status_code,303)
            self.assertEqual(runtime.actual().proveedor,'openai')
            self.assertEqual(proveedores.nombre_modelo(),'openai:gpt-6-luna')
        self.assertEqual(runtime.actual().proveedor,'vertex')
        resultado=[]
        jobs._ejecutar(lambda:resultado.append(runtime.actual().proveedor),())
        self.assertEqual(resultado,['vertex'])

    def test_dos_activaciones_concurrentes_solo_una_version(self):
        config=ai_settings.candidata({'proveedor':'vertex',**runtime.actual().opciones},runtime.actual())
        barrera=Barrier(2)
        def guardar():
            with SessionLocal.begin() as db:
                barrera.wait()
                try:ai_settings.activar(db,config,self.admin.id,'0');return 'ok'
                except ai_settings.ConfiguracionInvalida:db.rollback();return 'obsoleto'
        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados=list(pool.map(lambda _:guardar(),range(2)))
        self.assertCountEqual(resultados,['ok','obsoleto']);self.assertEqual(self.contar(),1)

    def test_settings_locales_y_configuracion_inicial_se_conservan(self):
        e=Settings(LLM_PROVIDER='vertex',TRANSCRIPTION_PROVIDER='vertex',LLM_MODEL='',TRANSCRIPTION_MODEL='',
            GOOGLE_CLOUD_PROJECT='p-local',VERTEX_MODEL='gemini-3.5-flash-lite')
        self.assertEqual(e.modelo_llm,'gemini-3.5-flash-lite');self.assertTrue(e.ai_enabled)
        self.assertEqual(e.variable_clave(),'Credenciales de Google Cloud (ADC)')

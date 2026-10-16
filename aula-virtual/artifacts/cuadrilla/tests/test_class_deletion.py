"""Destructive class purge: permissions, dependency graph, rewards and file atomicity."""
import apoyo  # noqa: F401

import tempfile
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from threading import Event, Thread
from unittest import mock

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.dml import Delete

from ai import jobs
from db.models import (
    Base, Canje, Clase, ClaseTema, DominioTema, FuenteSemanal, Intento, LlamadaIA, Movimiento, Quiz, QuizItem,
    Reto, RetoSemanal, RetoSemanalAlumno, RetoVersion, TareaHecha, Tema, Usuario,
)
from db.session import SessionLocal
from rules.calendar import ahora, semana_de
from rules.params import DEFAULT_PARAMS
from services import attempts, class_deletion, ledger, quiz, validation, weekly
from services.redemption import canjear, corregir
from services.validation import versiones_vigentes


class EliminarClaseTest(apoyo.Caso):
    def setUp(self):
        super().setUp()
        self.curso = self.demo(actividad=True)
        self.web = self.cliente('20000001')
        self.token = self.csrf('20000001')
        self.lucia = self.usuario('70000001')
        temp = tempfile.TemporaryDirectory(prefix='dmc-class-purge-')
        self.addCleanup(temp.cleanup)
        self.uploads = Path(temp.name)
        apoyo.configurar(self, UPLOAD_DIR=self.uploads)
        self.archivo = self.uploads / 'clase-a-borrar.md'
        self.archivo.write_text('transcript secreto de prueba')
        with SessionLocal.begin() as db:
            self.clase = db.scalar(select(Clase).where(Clase.curso_id == self.curso.id, Clase.numero == 1))
            self.clase.fuente_archivo = self.archivo.name
            self.clase_id = self.clase.id
        self.path = f'/docente/clases/{self.clase_id}/eliminar'

    def eliminar(self, **datos):
        return self.web.post(self.path, data={'_csrf': self.token, 'confirmo': 'si', **datos})

    def test_purga_publicada_completa_y_conserva_otro_curso_y_cuentas(self):
        with SessionLocal.begin() as db:
            retos = set(db.scalars(select(Reto.id).where(Reto.clase_id == self.clase_id)))
            for ref in (f'clase:{self.clase_id}', f'clase:{self.clase_id}:previo', f'reto:{min(retos)}'):
                db.add(LlamadaIA(componente='ejemplo', modelo='simulado', referencia=ref))
            db.add(LlamadaIA(componente='ejemplo', modelo='simulado', referencia=f'clase:{self.clase_id}000'))
        with SessionLocal() as db:
            plan = class_deletion._plan(db, db.get(Clase, self.clase_id))
            otras_clases = list(db.scalars(select(Clase.id).where(Clase.id != self.clase_id)))
            cuentas = db.execute(select(Usuario.__table__).order_by(Usuario.id)).all()
            otra_malla = db.execute(select(Tema.__table__).where(Tema.curso_id != self.curso.id).order_by(Tema.id)).all()
            antes_otro = list(db.scalars(select(Movimiento.id).where(Movimiento.curso_id != self.curso.id)))
        vista = self.web.get(self.path)
        self.assertEqual(vista.status_code, 200)
        self.assertIn('data-delete', vista.text)
        self.assertIn('data-confirm-dialog', vista.text)
        self.assertEqual(self.eliminar().status_code, 303)
        with SessionLocal() as db:
            self.assertIsNone(db.get(Clase, self.clase_id))
            self.assertEqual(list(db.scalars(select(Clase.id).order_by(Clase.id))), sorted(otras_clases))
            for model, ids in ((Reto, plan['retos']), (RetoVersion, plan['versiones']),
                               (Intento, plan['intentos']), (Quiz, plan['quizzes']), (QuizItem, plan['items'])):
                self.assertEqual(db.scalar(select(func.count()).select_from(model).where(model.id.in_(ids))), 0)
            self.assertEqual(db.execute(select(Usuario.__table__).order_by(Usuario.id)).all(), cuentas)
            self.assertEqual(db.execute(select(Tema.__table__).where(Tema.curso_id != self.curso.id).order_by(Tema.id)).all(), otra_malla)
            self.assertEqual(list(db.scalars(select(Movimiento.id).where(Movimiento.curso_id != self.curso.id))), antes_otro)
            self.assertEqual(list(db.scalars(select(LlamadaIA.referencia))), [f'clase:{self.clase_id}000'])
        self.assertFalse(self.archivo.exists())
        self.assertEqual(list(self.uploads.iterdir()), [])
        self.assertEqual(self.web.get(f'/docente/clases/{self.clase_id}').status_code, 404)
        self.assertEqual(self.eliminar().status_code, 404)

    def test_confirmacion_csrf_y_permisos_en_ambos_metodos(self):
        self.assertEqual(self.eliminar(confirmo='').status_code, 400)
        self.assertEqual(self.eliminar(_csrf='incorrecto').status_code, 403)
        otro_docente = self.cliente('20000002')
        alumno = self.cliente('70000001')
        for cliente, dni, status in ((otro_docente, '20000002', 404), (alumno, '70000001', 403)):
            self.assertEqual(cliente.get(self.path).status_code, status)
            self.assertEqual(cliente.post(self.path, data={'_csrf': self.csrf(dni), 'confirmo': 'si'}).status_code, status)
        self.assertTrue(self.archivo.exists())

    def test_clase_con_error_se_elimina_y_libera_su_numero(self):
        with SessionLocal.begin() as db:
            nueva = Clase(curso_id=self.curso.id, numero=20, fecha=ahora().date(), fuente_tipo='texto',
                          transcript='Texto equivocado', estado='error')
            db.add(nueva)
            db.flush()
            clase_id = nueva.id
        admin = self.cliente('10000001')
        respuesta = admin.post(f'/docente/clases/{clase_id}/eliminar', data={'_csrf': self.csrf('10000001'), 'confirmo': 'si'})
        self.assertEqual(respuesta.status_code, 303)
        with SessionLocal.begin() as db:
            db.add(Clase(curso_id=self.curso.id, numero=20, fecha=ahora().date(), fuente_tipo='texto', estado='error'))
        with SessionLocal() as db:
            self.assertIsNone(db.get(Clase, clase_id))

    def test_clase_sin_publicar_ni_practica_no_altera_otros_datos_del_curso(self):
        with SessionLocal.begin() as db:
            clase = Clase(curso_id=self.curso.id, numero=20, fecha=ahora().date(), fuente_tipo='texto',
                          transcript='Clase equivocada', estado='error')
            db.add(clase)
            db.flush()
            clase_id = clase.id
            tema_id = db.scalar(select(Tema.id).where(Tema.curso_id == self.curso.id))
            db.add(ClaseTema(clase_id=clase_id, tema_id=tema_id, origen='docente'))
        def filas(db):
            resultado = {}
            for tabla in Base.metadata.sorted_tables:
                consulta = select(tabla).order_by(*tabla.primary_key.columns)
                if tabla.name == 'clases':
                    consulta = consulta.where(Clase.id != clase_id)
                if tabla.name == 'clase_tema':
                    consulta = consulta.where(ClaseTema.clase_id != clase_id)
                resultado[tabla.name] = db.execute(consulta).all()
            return resultado
        with SessionLocal() as db:
            antes = filas(db)
        respuesta = self.web.post(f'/docente/clases/{clase_id}/eliminar', data={'_csrf': self.token, 'confirmo': 'si'})
        self.assertEqual(respuesta.status_code, 303)
        with SessionLocal() as db:
            self.assertEqual(filas(db), antes)

    def _quiz_con_repaso(self, completado):
        with SessionLocal.begin() as db:
            clase2 = db.scalar(select(Clase).where(Clase.curso_id == self.curso.id, Clase.numero == 2))
            clase2.estado, clase2.publicada_en = 'publicada', ahora()
            retos = db.scalars(select(Reto).where(Reto.clase_id == clase2.id).order_by(Reto.id)).all()[:3]
            for r in retos:
                r.estado = 'aprobado'
            repaso = db.scalar(select(Reto).where(Reto.clase_id == self.clase_id, Reto.uso == 'clase').order_by(Reto.id))
            q = Quiz(alumno_id=self.lucia.id, curso_id=self.curso.id, clase_id=clase2.id,
                     indice_actual=3, tiene_repaso=True, nivel_coins='basico', tema_principal_id=retos[0].tema_id)
            db.add(q)
            db.flush()
            for orden, reto in enumerate([*retos, repaso], 1):
                version = versiones_vigentes(db, reto)['basico']
                item = QuizItem(quiz_id=q.id, orden=orden, reto_id=reto.id, nivel='basico',
                                reto_version_id=version.id, etiqueta='repaso' if orden == 4 else 'clase')
                db.add(item)
                db.flush()
                if orden < 4 or completado:
                    intento = attempts.crear_intento(db, alumno=db.get(Usuario, self.lucia.id), curso_id=self.curso.id,
                        reto=reto, version=version, origen='repaso' if orden == 4 else 'quiz', es_repaso=orden == 4,
                        cuenta_para_dominio=True, respuesta='Prueba', pistas=0, presentado_en=None,
                        envio_id=f'delete-{q.id}-{orden}', quiz_item_id=item.id)
                    attempts.finalizar(db, intento, 'correcto', {}, DEFAULT_PARAMS)
            if completado:
                quiz.cerrar(db, q, DEFAULT_PARAMS)
            return q.id, clase2.id

    def test_repaso_en_otro_quiz_completado_se_purga_sin_borrar_sus_otras_respuestas(self):
        q_id, clase2_id = self._quiz_con_repaso(True)
        self.assertEqual(self.eliminar().status_code, 303)
        with SessionLocal() as db:
            q = db.get(Quiz, q_id)
            self.assertEqual(q.estado, 'completado')
            self.assertEqual(len(quiz.items(db, q)), 3)
            self.assertFalse(q.tiene_repaso)
            self.assertEqual(db.scalar(select(func.count()).select_from(Intento).join(QuizItem).where(QuizItem.quiz_id == q_id)), 3)
            self.assertGreater(q.exp_obtenido, 0)
            self.assertIsNotNone(db.get(Clase, clase2_id))

    def test_repaso_actual_eliminado_permite_terminar_quiz(self):
        q_id, clase2_id = self._quiz_con_repaso(False)
        self.assertEqual(self.eliminar().status_code, 303)
        with SessionLocal() as db:
            q = db.get(Quiz, q_id)
            self.assertEqual(q.indice_actual, 2)
            self.assertIsNotNone(quiz.item_actual(db, q))
        alumno = self.cliente('70000001')
        self.aceptar_consentimiento(alumno, '70000001')
        ruta = f'/alumno/cursos/{self.curso.id}/clases/{clase2_id}/quiz'
        self.assertEqual(alumno.get(ruta).status_code, 200)
        self.assertEqual(alumno.post(ruta+'/seguir', data={'_csrf': self.csrf('70000001')}).status_code, 303)
        self.assertEqual(alumno.get(ruta+'/final').status_code, 200)

    def test_reto_semanal_derivado_y_sus_respuestas_se_eliminan(self):
        with SessionLocal.begin() as db:
            fuente = db.scalar(select(Reto).where(Reto.clase_id == self.clase_id, Reto.uso == 'clase'))
            nuevo = Reto(curso_id=self.curso.id, tema_id=fuente.tema_id, uso='semanal', estado='aprobado',
                         fuente_ref='Contenido derivado de la clase')
            db.add(nuevo)
            db.flush()
            datos = {c.name: getattr(versiones_vigentes(db, fuente)['basico'], c.name) for c in RetoVersion.__table__.columns
                     if c.name not in ('id', 'reto_id', 'creado_en')}
            version = RetoVersion(reto_id=nuevo.id, **datos)
            db.add(version)
            db.flush()
            semanal = RetoSemanal(curso_id=self.curso.id, semana=semana_de(ahora()), estado='listo', tema_visto=True,
                                  tema_id=fuente.tema_id, reto_id=nuevo.id)
            db.add(semanal)
            db.flush()
            db.add(RetoSemanalAlumno(alumno_id=self.lucia.id, semanal_id=semanal.id, nivel='basico', reto_version_id=version.id))
            ids = nuevo.id, semanal.id, version.id
        self.assertEqual(self.eliminar().status_code, 303)
        with SessionLocal() as db:
            for modelo, id_ in zip((Reto, RetoSemanal, RetoVersion), ids):
                self.assertIsNone(db.get(modelo, id_))

    def test_coins_canjeadas_bloquean_borrado_sin_saldo_negativo(self):
        self._quiz_con_repaso(True)
        admin_id = self.usuario('10000001').id
        with SessionLocal.begin() as db:
            alumno = db.get(Usuario, self.lucia.id)
            raiz = Quiz(alumno_id=alumno.id, curso_id=self.curso.id, clase_id=self.clase_id, estado='completado')
            db.add(raiz)
            db.flush()
            ledger.registrar(db, alumno_id=alumno.id, curso_id=self.curso.id, tipo='COINS', origen='quiz',
                             referencia=f'quiz:{raiz.id}', cantidad=5)
            saldo = ledger.saldo_coins(db, alumno.id)
            ledger.registrar(db, alumno_id=alumno.id, tipo='COINS', origen='ajuste_admin', referencia='saldo-prueba', cantidad=600-saldo)
            canje = canjear(db, alumno, 30, DEFAULT_PARAMS)
            canje_id = canje.id
        respuesta = self.eliminar()
        self.assertEqual(respuesta.status_code, 400)
        self.assertTrue(self.archivo.exists())
        with SessionLocal() as db:
            self.assertIsNotNone(db.get(Clase, self.clase_id))
        with SessionLocal.begin() as db:
            corregir(db, db.get(Canje, canje_id), admin_id, 'Corregir para eliminar clase de prueba')
        self.assertEqual(self.eliminar().status_code, 303)

    def test_ia_activa_o_pendiente_impide_borrado(self):
        with jobs.usando_curso(self.curso.id):
            self.assertEqual(self.eliminar().status_code, 400)
        with SessionLocal.begin() as db:
            db.get(Clase, self.clase_id).estado = 'procesando'
        self.assertEqual(self.eliminar().status_code, 400)
        self.assertTrue(self.archivo.exists())

    def test_fallo_db_revierte_todo_y_recupera_archivo(self):
        with SessionLocal() as db:
            original = db.execute
            def ejecutar(sentencia, *args, **kwargs):
                if isinstance(sentencia, Delete) and sentencia.table.name == 'clases':
                    raise IntegrityError('fallo simulado', {}, RuntimeError('referencia'))
                return original(sentencia, *args, **kwargs)
            with mock.patch.object(db, 'execute', side_effect=ejecutar):
                with self.assertRaises(IntegrityError):
                    class_deletion.eliminar_clase(db, self.clase_id, confirmo='si')
            self.assertIsNotNone(db.get(Clase, self.clase_id))
        self.assertEqual(self.archivo.read_text(), 'transcript secreto de prueba')
        self.assertEqual(list(self.uploads.iterdir()), [self.archivo])

    def test_archivo_compartido_y_ruta_invalida_bloquean_borrado(self):
        with SessionLocal.begin() as db:
            otra = db.scalar(select(Clase).where(Clase.id != self.clase_id))
            otra.fuente_archivo = self.archivo.name
        self.assertEqual(self.eliminar().status_code, 400)
        with SessionLocal.begin() as db:
            db.get(Clase, self.clase_id).fuente_archivo = '../ajeno.txt'
        self.assertEqual(self.eliminar().status_code, 400)
        self.assertTrue(self.archivo.exists())

    def test_limpieza_pendiente_y_recuperacion_tras_interrupcion(self):
        carpeta = self.uploads / f'.eliminar-clase-{self.curso.id}-{self.clase_id}-interrumpido'
        carpeta.mkdir()
        self.archivo.rename(carpeta / self.archivo.name)
        class_deletion.reconciliar_archivos_eliminados()
        self.assertTrue(self.archivo.exists())
        with mock.patch('services.class_deletion.shutil.rmtree', side_effect=OSError('fallo simulado')):
            with self.assertLogs('aulavirtualdmc.eliminar_clase', level='ERROR'):
                self.assertEqual(self.eliminar().status_code, 200)
        class_deletion.reconciliar_archivos_eliminados()
        self.assertEqual(list(self.uploads.iterdir()), [])

    def test_progreso_sin_evidencia_restante_desaparece(self):
        with SessionLocal() as db:
            pares = set(db.execute(select(DominioTema.alumno_id, DominioTema.tema_id).join(Tema).where(
                Tema.curso_id == self.curso.id)).all())
        self.assertTrue(pares)
        self.assertEqual(self.eliminar().status_code, 303)
        with SessionLocal() as db:
            for alumno_id, tema_id in pares:
                restante = db.scalar(select(Intento.id).where(Intento.alumno_id == alumno_id, Intento.tema_id == tema_id,
                    Intento.cuenta_para_dominio.is_(True), Intento.estado == 'completado').limit(1))
                if restante is None:
                    self.assertIsNone(db.get(DominioTema, (alumno_id, tema_id)))

    def test_semanal_con_fuentes_de_otra_clase_se_conserva(self):
        with SessionLocal.begin() as db:
            clase2 = db.scalar(select(Clase).where(Clase.curso_id == self.curso.id, Clase.id != self.clase_id))
            tema_id = db.scalar(select(Reto.tema_id).where(Reto.clase_id == self.clase_id))
            reto = Reto(curso_id=self.curso.id, tema_id=tema_id, uso='semanal', estado='aprobado')
            db.add(reto)
            db.flush()
            semanal = RetoSemanal(curso_id=self.curso.id, semana=semana_de(ahora()), estado='listo',
                                  tema_id=tema_id, tema_visto=True, reto_id=reto.id)
            db.add(semanal)
            db.flush()
            db.add(FuenteSemanal(semanal_id=semanal.id, clase_id=clase2.id))
            semanal_id, reto_id = semanal.id, reto.id
        self.assertEqual(self.eliminar().status_code, 303)
        with SessionLocal() as db:
            self.assertIsNotNone(db.get(RetoSemanal, semanal_id))
            self.assertIsNotNone(db.get(Reto, reto_id))

    def test_generacion_semanal_registra_sus_clases_fuente(self):
        from falso_llm import FalsoModelo
        apoyo.activar_ia(self, FalsoModelo())
        with SessionLocal.begin() as db:
            tema_id = db.scalar(select(Reto.tema_id).where(Reto.clase_id == self.clase_id))
            semanal = RetoSemanal(curso_id=self.curso.id, semana=semana_de(ahora()), estado='generando',
                                  tema_id=tema_id, tema_visto=True)
            db.add(semanal)
            db.flush()
            semanal_id = semanal.id
        weekly.generar(semanal_id)
        with SessionLocal() as db:
            self.assertEqual(db.get(RetoSemanal, semanal_id).estado, 'listo')
            self.assertIn(self.clase_id, set(db.scalars(select(FuenteSemanal.clase_id).where(FuenteSemanal.semanal_id == semanal_id))))
        self.assertEqual(self.eliminar().status_code, 303)
        with SessionLocal() as db:
            self.assertIsNone(db.get(RetoSemanal, semanal_id))

    def test_semanal_legado_de_tema_anterior_al_ajuste_se_elimina(self):
        with SessionLocal.begin() as db:
            tema_id = db.scalar(select(Reto.tema_id).where(Reto.clase_id == self.clase_id))
            db.execute(delete(ClaseTema).where(ClaseTema.clase_id == self.clase_id, ClaseTema.tema_id == tema_id))
            reto = Reto(curso_id=self.curso.id, tema_id=tema_id, uso='semanal', estado='aprobado')
            db.add(reto)
            db.flush()
            semanal = RetoSemanal(curso_id=self.curso.id, semana=semana_de(ahora()), estado='listo',
                                  tema_id=tema_id, tema_visto=True, reto_id=reto.id)
            db.add(semanal)
            db.flush()
            semanal_id, reto_id = semanal.id, reto.id
        self.assertEqual(self.eliminar().status_code, 303)
        with SessionLocal() as db:
            self.assertIsNone(db.get(RetoSemanal, semanal_id))
            self.assertIsNone(db.get(Reto, reto_id))

    def test_fallo_commit_recupera_archivo_ya_movido(self):
        with SessionLocal() as db:
            with mock.patch.object(db, 'commit', side_effect=IntegrityError('fallo simulado', {}, RuntimeError('commit'))):
                with self.assertRaises(IntegrityError):
                    class_deletion.eliminar_clase(db, self.clase_id, confirmo='si')
            self.assertIsNotNone(db.get(Clase, self.clase_id))
        self.assertEqual(self.archivo.read_text(), 'transcript secreto de prueba')
        self.assertEqual(list(self.uploads.iterdir()), [self.archivo])

    def test_borrado_espera_peticion_activa_e_incluye_su_ultima_tarea(self):
        from auth.deps import curso_de_alumno
        iniciado, terminado = Event(), Event()
        errores = []
        original = jobs.eliminando_curso
        @contextmanager
        def guard(curso_id):
            with original(curso_id):
                iniciado.set()
                yield
        def borrar():
            try:
                with SessionLocal() as db:
                    class_deletion.eliminar_clase(db, self.clase_id, confirmo='si')
            except Exception as error:
                errores.append(error)
            finally:
                terminado.set()
        with SessionLocal() as db:
            curso_de_alumno(db, self.lucia, self.curso.id)
            with mock.patch('services.class_deletion.jobs.eliminando_curso', side_effect=guard):
                hilo = Thread(target=borrar, daemon=True)
                hilo.start()
                self.assertTrue(iniciado.wait(3))
                self.assertFalse(terminado.wait(.1))
                db.add(TareaHecha(alumno_id=self.lucia.id, clase_id=self.clase_id))
                db.commit()
                hilo.join(5)
        self.assertTrue(terminado.is_set())
        self.assertEqual(errores, [])
        with SessionLocal() as db:
            self.assertIsNone(db.get(Clase, self.clase_id))
            self.assertIsNone(db.get(TareaHecha, (self.lucia.id, self.clase_id)))

    def test_publicacion_automatica_no_bloquea_un_borrado_en_curso(self):
        from db.models import Curso
        with SessionLocal.begin() as db:
            clase2 = db.scalar(select(Clase).where(Clase.curso_id == self.curso.id, Clase.numero == 2))
            clase2.vence_validacion_en = ahora() - timedelta(minutes=1)
            clase2_id = clase2.id
        with SessionLocal.begin() as bloqueo:
            bloqueo.scalar(select(Curso).where(Curso.id == self.curso.id).with_for_update())
            with SessionLocal.begin() as db:
                self.assertEqual(validation.publicar_vencidas(db), 0)
                self.assertEqual(db.get(Clase, clase2_id).estado, 'por_validar')
        with SessionLocal.begin() as db:
            self.assertEqual(validation.publicar_vencidas(db), 1)
            self.assertEqual(db.get(Clase, clase2_id).estado, 'publicada')

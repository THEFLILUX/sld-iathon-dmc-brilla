"""Teacher flows: upload, validation in one hour, editing with versions, reports, risk and the malla."""

import apoyo  # noqa: F401  (must be first)

from datetime import date, timedelta

from sqlalchemy import func, select, update

from db.models import (
    AuditoriaReto, Clase, ClaseTema, Curso, DominioTema, Inscripcion, Intento, Mensaje, Reto, RetoVersion,
    SenalRiesgo, Tema, Usuario,
)
from db.session import SessionLocal
from rules.calendar import ahora
from rules.params import DEFAULT_PARAMS
from services import curriculum, reports

DOCENTE, ADMIN = "20000001", "10000001"


class ValidacionTest(apoyo.Caso):
    def setUp(self):
        super().setUp()
        self.curso = self.demo(actividad=True)
        with SessionLocal() as db:
            self.clase_1 = db.scalar(select(Clase).where(Clase.curso_id == self.curso.id, Clase.numero == 1))
            self.clase_2 = db.scalar(select(Clase).where(Clase.curso_id == self.curso.id, Clase.numero == 2))
        self.web = self.cliente(DOCENTE)
        self.token = self.csrf(DOCENTE)

    def test_sin_accion_en_una_hora_se_publica_con_los_propuestos(self):
        with SessionLocal.begin() as db:
            db.execute(update(Clase).where(Clase.id == self.clase_2.id).values(vence_validacion_en=ahora() - timedelta(seconds=1)))
        self.web.get(f"/docente/cursos/{self.curso.id}")   # any page applies the rule
        with SessionLocal() as db:
            self.assertEqual(db.get(Clase, self.clase_2.id).estado, "publicada")
            estados = set(db.scalars(select(Reto.estado).where(Reto.clase_id == self.clase_2.id)))
            self.assertEqual(estados, {"aprobado"})
            self.assertEqual(db.scalar(select(func.count()).select_from(AuditoriaReto).where(
                AuditoriaReto.accion == "aprobado_por_defecto")), 4)
            self.assertEqual(db.scalar(select(func.count()).select_from(Mensaje).where(
                Mensaje.referencia == f"clase:{self.clase_2.id}")), 6)

    def test_aprobar_editar_y_auditar(self):
        with SessionLocal() as db:
            reto = db.scalar(select(Reto).where(Reto.clase_id == self.clase_2.id, Reto.posicion == 1))
        self.assertEqual(self.web.post(f"/docente/retos/{reto.id}/aprobar", data={"_csrf": self.token}).status_code, 303)
        self.assertEqual(self.web.post(f"/docente/retos/{reto.id}/aprobar", data={"_csrf": self.token}).status_code, 400)
        datos = {"_csrf": self.token, "nivel": "basico", "tipo": "alternativas", "enunciado": "¿Qué es pandas en Python?",
                 "opciones": "Una librería\nUn programa\nUn gráfico", "respuesta_correcta": "Una librería",
                 "explicacion": "Es una librería.", "pista_1": "a", "pista_2": "b", "pista_3": "c", "error_comun": "x"}
        mala = self.web.post(f"/docente/retos/{reto.id}/editar", data={**datos, "respuesta_correcta": "Otra"})
        self.assertEqual(mala.status_code, 400)
        self.assertIn("exactamente una de las alternativas", mala.text)
        self.assertEqual(self.web.post(f"/docente/retos/{reto.id}/editar", data=datos).status_code, 303)
        with SessionLocal() as db:
            reto = db.get(Reto, reto.id)
            self.assertEqual((reto.estado, reto.revision), ("editado", 1))   # before publication: in place
            basico = db.scalar(select(RetoVersion).where(RetoVersion.reto_id == reto.id, RetoVersion.nivel == "basico"))
            self.assertEqual(basico.enunciado, "¿Qué es pandas en Python?")
            acciones = db.scalars(select(AuditoriaReto.accion).where(AuditoriaReto.reto_id == reto.id)).all()
            self.assertEqual(acciones, ["aprobo", "edito"])

    def test_editar_tras_publicar_crea_version_y_conserva_intentos(self):
        with SessionLocal() as db:
            intento = db.scalar(select(Intento).join(Reto, Reto.id == Intento.reto_id).where(
                Reto.clase_id == self.clase_1.id, Intento.tipo == "alternativas").limit(1))
            version_original = db.get(RetoVersion, intento.reto_version_id)
        datos = {"_csrf": self.token, "nivel": version_original.nivel, "tipo": "alternativas",
                 "enunciado": "Enunciado corregido por la docente", "opciones": "Sí\nNo\nTal vez",
                 "respuesta_correcta": "Sí", "explicacion": "Porque sí.", "pista_1": "a", "pista_2": "b", "pista_3": "c"}
        self.assertEqual(self.web.post(f"/docente/retos/{intento.reto_id}/editar", data=datos).status_code, 303)
        with SessionLocal() as db:
            reto = db.get(Reto, intento.reto_id)
            self.assertEqual(reto.revision, 2)
            self.assertEqual(db.get(Intento, intento.id).reto_version_id, version_original.id)
            self.assertEqual(db.get(RetoVersion, version_original.id).enunciado, version_original.enunciado)
            nuevas = db.scalars(select(RetoVersion).where(RetoVersion.reto_id == reto.id, RetoVersion.revision == 2)).all()
            self.assertEqual(len(nuevas), len(db.scalars(select(RetoVersion).where(
                RetoVersion.reto_id == reto.id, RetoVersion.revision == 1)).all()))

    def test_reto_propio_reemplaza_la_posicion_y_siempre_quedan_4(self):
        with SessionLocal() as db:
            reto = db.scalar(select(Reto).where(Reto.clase_id == self.clase_2.id, Reto.posicion == 3))
        datos = {"_csrf": self.token, "reemplaza": str(reto.id), "tema_id": str(reto.tema_id), "nivel": "intermedio",
                 "tipo": "caso", "enunciado": "Describe un caso de tu trabajo donde automatizarías un reporte.",
                 "puntos_clave": "Identifica la tarea repetitiva\nPropone el bloque de código", "respuesta_correcta": "",
                 "explicacion": "Se automatiza lo repetitivo.", "pista_1": "a", "pista_2": "b", "pista_3": "c"}
        self.assertEqual(self.web.post(f"/docente/clases/{self.clase_2.id}/retos/nuevo", data=datos).status_code, 303)
        with SessionLocal() as db:
            activos = db.scalars(select(Reto).where(Reto.clase_id == self.clase_2.id, Reto.uso == "clase",
                                                    Reto.posicion.is_not(None), Reto.estado != "rechazado")).all()
            self.assertEqual(sorted(r.posicion for r in activos), [1, 2, 3, 4])
            nuevo = next(r for r in activos if r.posicion == 3)
            self.assertEqual((nuevo.origen, nuevo.estado), ("docente", "aprobado"))
            self.assertEqual(db.get(Reto, reto.id).estado, "rechazado")

    def test_ajustar_temas_solo_de_la_malla(self):
        with SessionLocal.begin() as db:
            otro = Curso(nombre="Otro")
            db.add(otro)
            db.flush()
            ajeno = Tema(curso_id=otro.id, nombre="Ajeno", subtema="", orden=1, objetivo="x")
            db.add(ajeno)
            db.flush()
            propio = db.scalar(select(Tema.id).where(Tema.curso_id == self.curso.id, Tema.orden == 10))
            ajeno_id = ajeno.id
        r = self.web.post(f"/docente/clases/{self.clase_2.id}/temas", data={"_csrf": self.token, "tema_id": [str(propio), str(ajeno_id)]})
        self.assertEqual(r.status_code, 303)
        with SessionLocal() as db:
            temas = set(db.scalars(select(ClaseTema.tema_id).where(ClaseTema.clase_id == self.clase_2.id)))
        self.assertEqual(temas, {propio})

    def test_subir_clase_sin_ia_queda_en_error_con_reintento(self):
        r = self.web.post(f"/docente/cursos/{self.curso.id}/clases/nueva", data={
            "_csrf": self.token, "numero": "5", "fecha": date.today().isoformat(),
            "transcript_texto": "Clase sobre gráficos con seaborn."})
        self.assertEqual(r.status_code, 303)
        with SessionLocal() as db:
            clase = db.scalar(select(Clase).where(Clase.numero == 5))
            self.assertEqual(clase.estado, "error")
            self.assertIn("OPENAI_API_KEY", clase.error_mensaje)
        duplicada = self.web.post(f"/docente/cursos/{self.curso.id}/clases/nueva", data={
            "_csrf": self.token, "numero": "5", "fecha": date.today().isoformat(), "transcript_texto": "x"})
        self.assertEqual(duplicada.status_code, 400)
        self.assertIn("Ya existe la clase 5", duplicada.text)

    def test_reporte_de_clase(self):
        with SessionLocal() as db:
            reporte = reports.reporte_clase(db, db.get(Clase, self.clase_1.id), DEFAULT_PARAMS)
        self.assertEqual((reporte["participacion"], reporte["inscritos"]), (4, 6))
        self.assertTrue(all(not f["dominado_por_clase"] for f in reporte["temas"]))   # fewer than 5 with data
        self.assertTrue(reporte["ranking"])
        texto = apoyo.texto_visible(self.web.get(f"/docente/clases/{self.clase_1.id}/reporte").text)
        self.assertIn("4 de 6 alumnos practicaron", texto)
        self.assertIn("Andrés Salazar", texto)

    def test_reporte_por_alumno_marca_no_visto(self):
        with SessionLocal() as db:
            andres = db.scalar(select(Usuario).where(Usuario.dni == "70000004"))
            reporte = reports.reporte_alumno(db, self.curso.id, andres)
        estados = {f["tema"].nombre: f["estado"] for f in reporte["temas"]}
        self.assertEqual(estados["Python frente a Power BI"], "no_visto")
        self.assertEqual(estados["Etapas de la analítica de datos"], "debil")

    def test_alumnos_en_riesgo_y_contactado(self):
        texto = apoyo.texto_visible(self.web.get(f"/docente/cursos/{self.curso.id}/riesgo").text)
        self.assertIn("Camila Rojas", texto)
        self.assertNotIn("Diego Ramírez", texto)
        with SessionLocal() as db:
            senal = db.scalar(select(SenalRiesgo).join(Usuario, Usuario.id == SenalRiesgo.alumno_id).where(Usuario.dni == "70000005"))
        r = self.web.post(f"/docente/cursos/{self.curso.id}/riesgo/{senal.id}/contactado", data={"_csrf": self.token})
        self.assertEqual(r.status_code, 303)
        with SessionLocal() as db:
            self.assertEqual(db.get(SenalRiesgo, senal.id).estado, "contactado")
            self.assertEqual(db.scalar(select(func.count()).select_from(Mensaje).where(Mensaje.tipo == "inactividad")), 0)

    def test_nivel_maximo_y_rubrica(self):
        with SessionLocal() as db:
            tema = db.scalar(select(Tema).where(Tema.curso_id == self.curso.id, Tema.orden == 1))
        base = {"_csrf": self.token, "objetivo": "Explicar las etapas.", "nivel_maximo": "maestria", "es_fundamental": "si"}
        self.assertEqual(self.web.post(f"/docente/temas/{tema.id}", data=base).status_code, 400)
        rubrica = {f"criterio_{i}": f"Criterio {i}" for i in (1, 2, 3)}
        self.assertEqual(self.web.post(f"/docente/temas/{tema.id}", data={**base, **rubrica}).status_code, 303)
        self.assertEqual(self.web.post(f"/docente/temas/{tema.id}", data={**base, "nivel_maximo": "basico"}).status_code, 303)
        with SessionLocal() as db:
            tema = db.get(Tema, tema.id)
            self.assertEqual((tema.nivel_maximo, tema.rubrica, tema.ajustado_por_docente), ("basico", [], True))
            # Nobody receives a challenge above the new maximum.
            dominio = DominioTema(alumno_id=1, tema_id=tema.id, nivel_actual="avanzado")
            from services.progress import nivel_guardado
            db.add(dominio)
            db.flush()
            self.assertEqual(nivel_guardado(db, 1, tema), "basico")
            db.rollback()


class MallaTest(apoyo.Caso):
    def setUp(self):
        super().setUp()
        self.demo()
        self.web = self.cliente(ADMIN)
        self.token = self.csrf(ADMIN)
        with SessionLocal.begin() as db:
            curso = Curso(nombre="SQL para Analistas")
            db.add(curso)
            db.flush()
            self.curso_id = curso.id

    def test_csv_con_punto_y_coma_y_tildes(self):
        contenido = ("Módulo;Tema;Subtema;Objetivo\n"
                     "Fundamentos;Consultas;SELECT;Escribir consultas SELECT con filtros\n"
                     "Fundamentos;Consultas;JOIN;Unir tablas con JOIN\n").encode("cp1252")
        temas = curriculum.leer_malla("malla.csv", contenido)
        self.assertEqual([(t["modulo"], t["nombre"], t["subtema"]) for t in temas],
                         [("Fundamentos", "Consultas", "SELECT"), ("Fundamentos", "Consultas", "JOIN")])

    def test_errores_por_fila_y_no_guarda_nada(self):
        contenido = b"tema,objetivo\nConsultas,Escribir consultas\n,Sin tema\nConsultas,Repetido\nAgrupar,\n"
        r = self.web.post(f"/admin/cursos/{self.curso_id}/malla", data={"_csrf": self.token},
                          files={"archivo": ("malla.csv", contenido, "text/csv")})
        self.assertEqual(r.status_code, 400)
        texto = apoyo.texto_visible(r.text)
        self.assertIn("Fila 3: falta el tema.", texto)
        self.assertIn("Fila 4: el tema «Consultas» está repetido (fila 2).", texto)
        self.assertIn("Fila 5: falta el objetivo de aprendizaje.", texto)
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Tema).where(Tema.curso_id == self.curso_id)), 0)

    def test_json_y_actualizacion_sin_borrar(self):
        primero = b'{"temas": [{"modulo": "M1", "tema": "Consultas", "objetivo": "SELECT"}, {"tema": "Joins", "objetivo": "JOIN"}]}'
        r = self.web.post(f"/admin/cursos/{self.curso_id}/malla", data={"_csrf": self.token},
                          files={"archivo": ("malla.json", primero, "application/json")})
        self.assertEqual(r.status_code, 200)
        self.assertIn("2 temas nuevos", apoyo.texto_visible(r.text))
        segundo = b'[{"tema": "Consultas", "objetivo": "SELECT con WHERE"}]'
        self.web.post(f"/admin/cursos/{self.curso_id}/malla", data={"_csrf": self.token},
                      files={"archivo": ("malla.json", segundo, "application/json")})
        with SessionLocal() as db:
            temas = {t.nombre: t for t in db.scalars(select(Tema).where(Tema.curso_id == self.curso_id))}
        self.assertEqual(set(temas), {"Consultas", "Joins"})
        self.assertEqual((temas["Consultas"].objetivo, temas["Consultas"].modulo), ("SELECT con WHERE", "M1"))

    def test_usuario_e_inscripcion(self):
        r = self.web.post("/admin/usuarios", data={"_csrf": self.token, "dni": "45678912", "nombre": "Rosa",
                                                   "apellido": "Paredes", "rol": "docente", "password": "segura-123",
                                                   "curso_id": str(self.curso_id)})
        self.assertEqual(r.status_code, 303)
        repetido = self.web.post("/admin/usuarios", data={"_csrf": self.token, "dni": "45678912", "nombre": "X",
                                                          "apellido": "Y", "rol": "alumno", "password": "segura-123"})
        self.assertEqual(repetido.status_code, 400)
        docente = self.cliente("45678912", "segura-123")
        self.assertEqual(docente.get(f"/docente/cursos/{self.curso_id}").status_code, 200)
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(Inscripcion.rol_en_curso).join(Usuario, Usuario.id == Inscripcion.usuario_id)
                                       .where(Usuario.dni == "45678912")), "docente")

    def test_parametros_con_historial(self):
        r = self.web.post("/admin/parametros", data={"_csrf": self.token, "riesgo_inactividad_dias": "7"})
        self.assertEqual(r.status_code, 303)
        fuera = self.web.post("/admin/parametros", data={"_csrf": self.token, "nivel_sube": "150"})
        self.assertEqual(fuera.status_code, 400)
        from services.params import cargar, historial
        with SessionLocal() as db:
            self.assertEqual(cargar(db).riesgo_inactividad_dias, 7)
            cambio = historial(db)[0]
            self.assertEqual((cambio.clave, cambio.valor_anterior, cambio.valor), ("riesgo_inactividad_dias", 5, 7))
        self.assertIn("Historial de cambios", self.web.get("/admin/parametros").text)

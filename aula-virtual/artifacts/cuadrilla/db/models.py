"""Cuadrilla schema, after the functional spec §3 (data model).

Table names are Spanish, so the tables of the previous MVP stay untouched.
EXP and Coins are only ever stored as movements; balances are sums.
"""

import secrets
from datetime import date, datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, event, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NIVELES = ("basico", "intermedio", "avanzado", "maestria")
TIPOS_RETO = ("alternativas", "completar", "definir", "caso", "codigo")
VERIFICABLES = frozenset({"alternativas", "completar", "codigo"})
ROLES = ("alumno", "docente", "admin")
ORIGENES_MOVIMIENTO = ("reto", "quiz", "reto_semanal", "podio_final", "ajuste_admin", "ajuste_reclamo",
                      "canje", "devolucion_canje", "perfil")


def _one_of(column: str, values, name: str) -> CheckConstraint:
    return CheckConstraint(f"{column} IN ({', '.join(repr(v) for v in values)})", name=name)


def _alias() -> str:
    return "A-" + secrets.token_hex(4)


class Base(DeclarativeBase):
    pass


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = (
        _one_of("rol", ROLES, "usuario_rol"),
        CheckConstraint("dni ~ '^[0-9A-Za-z]{8,12}$'", name="usuario_dni"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    dni: Mapped[str] = mapped_column(String(12), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    nombre: Mapped[str] = mapped_column(String(100))
    apellido: Mapped[str] = mapped_column(String(100))
    # The only identifier that may reach the AI (AI behavior spec §11).
    alias: Mapped[str] = mapped_column(String(20), unique=True, default=_alias)
    rol: Mapped[str] = mapped_column(String(10))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    coins_pausadas: Mapped[bool] = mapped_column(Boolean, default=False)
    consentimiento_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombre} {self.apellido}".strip()


class PerfilUsuario(Base):
    __tablename__ = "perfiles_usuario"
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), primary_key=True)
    datos: Mapped[dict] = mapped_column(JSONB, default=dict)
    campos_reconocidos: Mapped[list] = mapped_column(JSONB, default=list)
    es_ejemplo: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=0)
    confirmado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Sesion(Base):
    __tablename__ = "sesiones"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    csrf: Mapped[str] = mapped_column(String(64))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Curso(Base):
    __tablename__ = "cursos"
    __table_args__ = (
        _one_of("estado", ("activo", "cerrado"), "curso_estado"),
        _one_of("propuesta_estado", ("sin_propuesta", "generando", "lista", "error"), "curso_propuesta_estado"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(250), unique=True)
    estado: Mapped[str] = mapped_column(String(10), default="activo")
    fecha_inicio: Mapped[date | None] = mapped_column(Date)
    fecha_fin: Mapped[date | None] = mapped_column(Date)
    brochure_nombre: Mapped[str | None] = mapped_column(String(300))
    brochure_texto: Mapped[str | None] = mapped_column(Text)
    lenguajes: Mapped[list] = mapped_column(JSONB, default=list)
    propuesta_estado: Mapped[str] = mapped_column(String(15), default="sin_propuesta")
    propuesta_error: Mapped[str | None] = mapped_column(Text)
    cerrado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Inscripcion(Base):
    __tablename__ = "inscripciones"
    __table_args__ = (_one_of("rol_en_curso", ("alumno", "docente"), "inscripcion_rol"),)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), primary_key=True)
    curso_id: Mapped[int] = mapped_column(ForeignKey("cursos.id"), primary_key=True, index=True)
    rol_en_curso: Mapped[str] = mapped_column(String(10))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Tema(Base):
    """One row of the malla. subtema is '' when absent so (curso, nombre, subtema) is unique."""
    __tablename__ = "temas"
    __table_args__ = (
        UniqueConstraint("curso_id", "nombre", "subtema", name="tema_unico"),
        _one_of("nivel_maximo", NIVELES, "tema_nivel_maximo"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    curso_id: Mapped[int] = mapped_column(ForeignKey("cursos.id"), index=True)
    modulo: Mapped[str | None] = mapped_column(String(200))
    nombre: Mapped[str] = mapped_column(String(200))
    subtema: Mapped[str] = mapped_column(String(200), default="")
    orden: Mapped[int] = mapped_column(Integer)
    objetivo: Mapped[str] = mapped_column(Text)
    nivel_maximo: Mapped[str] = mapped_column(String(12), default="avanzado")
    es_fundamental: Mapped[bool] = mapped_column(Boolean, default=False)
    rubrica: Mapped[list] = mapped_column(JSONB, default=list)
    lenguaje: Mapped[str | None] = mapped_column(String(50))
    propuesto_por_ia: Mapped[bool] = mapped_column(Boolean, default=False)
    ajustado_por_docente: Mapped[bool] = mapped_column(Boolean, default=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def etiqueta(self) -> str:
        return f"{self.nombre} · {self.subtema}" if self.subtema else self.nombre


class Clase(Base):
    __tablename__ = "clases"
    __table_args__ = (
        UniqueConstraint("curso_id", "numero", name="clase_numero_unico"),
        CheckConstraint("numero > 0", name="clase_numero_positivo"),
        _one_of("fuente_tipo", ("video", "audio", "texto"), "clase_fuente_tipo"),
        _one_of("estado", ("procesando", "por_validar", "publicada", "error"), "clase_estado"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    curso_id: Mapped[int] = mapped_column(ForeignKey("cursos.id"), index=True)
    numero: Mapped[int] = mapped_column(Integer)
    fecha: Mapped[date] = mapped_column(Date)
    titulo: Mapped[str] = mapped_column(String(250), default="")
    fuente_tipo: Mapped[str] = mapped_column(String(10))
    fuente_archivo: Mapped[str | None] = mapped_column(String(500))
    fuente_nombre: Mapped[str] = mapped_column(String(500), default="")
    transcript: Mapped[str | None] = mapped_column(Text)
    transcript_anon: Mapped[str | None] = mapped_column(Text)
    recursos: Mapped[list] = mapped_column(JSONB, default=list)
    recursos_texto: Mapped[str | None] = mapped_column(Text)
    tarea: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(15), default="procesando", index=True)
    paso: Mapped[str | None] = mapped_column(String(30))
    error_mensaje: Mapped[str | None] = mapped_column(Text)
    aviso_docente_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    vence_validacion_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    publicada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def nombre(self) -> str:
        return f"Clase {self.numero}" + (f" · {self.titulo}" if self.titulo else "")


class ResumenClase(Base):
    """One shared, persisted AI study summary per class; no per-student generation."""
    __tablename__ = "resumenes_clase"
    __table_args__ = (
        _one_of("estado", ("pendiente", "generando", "listo", "error"), "resumen_clase_estado"),
    )
    clase_id: Mapped[int] = mapped_column(ForeignKey("clases.id"), primary_key=True)
    estado: Mapped[str] = mapped_column(String(12), default="pendiente", index=True)
    contenido: Mapped[dict | None] = mapped_column(JSONB)
    modelo: Mapped[str | None] = mapped_column(String(80))
    intentos: Mapped[int] = mapped_column(Integer, default=0)
    error_mensaje: Mapped[str | None] = mapped_column(Text)
    proximo_intento_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClaseTema(Base):
    __tablename__ = "clase_tema"
    __table_args__ = (_one_of("origen", ("ia", "docente"), "clase_tema_origen"),)
    clase_id: Mapped[int] = mapped_column(ForeignKey("clases.id"), primary_key=True)
    tema_id: Mapped[int] = mapped_column(ForeignKey("temas.id"), primary_key=True, index=True)
    evidencia: Mapped[str] = mapped_column(Text, default="")
    confianza: Mapped[float] = mapped_column(Float, default=0.0)
    origen: Mapped[str] = mapped_column(String(10), default="ia")


class Reto(Base):
    """A challenge. Its content lives in RetoVersion rows: one per level and revision."""
    __tablename__ = "retos"
    __table_args__ = (
        _one_of("uso", ("clase", "previo", "semanal"), "reto_uso"),
        _one_of("origen", ("ia", "docente"), "reto_origen"),
        _one_of("estado", ("generando", "propuesto", "aprobado", "editado", "rechazado", "retirado", "error"),
                "reto_estado"),
        CheckConstraint("posicion IS NULL OR posicion BETWEEN 1 AND 4", name="reto_posicion"),
        Index("reto_posicion_activa", "clase_id", "posicion", unique=True,
              postgresql_where=text("posicion IS NOT NULL AND estado <> 'rechazado' AND uso = 'clase'")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    curso_id: Mapped[int] = mapped_column(ForeignKey("cursos.id"), index=True)
    clase_id: Mapped[int | None] = mapped_column(ForeignKey("clases.id"), index=True)
    tema_id: Mapped[int] = mapped_column(ForeignKey("temas.id"), index=True)
    uso: Mapped[str] = mapped_column(String(10), default="clase")
    posicion: Mapped[int | None] = mapped_column(Integer)
    origen: Mapped[str] = mapped_column(String(10), default="ia")
    estado: Mapped[str] = mapped_column(String(12), default="propuesto")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    error_comun: Mapped[str] = mapped_column(Text, default="")
    fuente_tipo: Mapped[str] = mapped_column(String(12), default="transcript")
    fuente_ref: Mapped[str] = mapped_column(Text, default="")
    avisos: Mapped[list] = mapped_column(JSONB, default=list)
    es_variante_de: Mapped[int | None] = mapped_column(ForeignKey("retos.id"))
    reemplaza_a: Mapped[int | None] = mapped_column(ForeignKey("retos.id"))
    vence_validacion_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_mensaje: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    versiones: Mapped[list["RetoVersion"]] = relationship(order_by="RetoVersion.id", viewonly=True)

    @property
    def usable(self) -> bool:
        return self.estado in ("aprobado", "editado")


class RetoVersion(Base):
    __tablename__ = "reto_versiones"
    __table_args__ = (
        UniqueConstraint("reto_id", "revision", "nivel", name="reto_version_unica"),
        _one_of("nivel", NIVELES, "reto_version_nivel"),
        _one_of("tipo", TIPOS_RETO, "reto_version_tipo"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    reto_id: Mapped[int] = mapped_column(ForeignKey("retos.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    nivel: Mapped[str] = mapped_column(String(12))
    tipo: Mapped[str] = mapped_column(String(15))
    enunciado: Mapped[str] = mapped_column(Text)
    opciones: Mapped[list] = mapped_column(JSONB, default=list)
    respuesta_correcta: Mapped[str] = mapped_column(Text, default="")
    respuestas_aceptadas: Mapped[list] = mapped_column(JSONB, default=list)
    puntos_clave: Mapped[list] = mapped_column(JSONB, default=list)
    casos_de_prueba: Mapped[list] = mapped_column(JSONB, default=list)
    explicacion: Mapped[str] = mapped_column(Text, default="")
    pistas: Mapped[list] = mapped_column(JSONB, default=list)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def verificable(self) -> bool:
        return self.tipo in VERIFICABLES


class RetoReporte(Base):
    __tablename__ = "reto_reportes"
    __table_args__ = (UniqueConstraint("reto_id", "alumno_id", name="reporte_unico_por_alumno"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    reto_id: Mapped[int] = mapped_column(ForeignKey("retos.id"), index=True)
    alumno_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    motivo: Mapped[str] = mapped_column(Text, default="")
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditoriaReto(Base):
    __tablename__ = "auditoria_retos"
    id: Mapped[int] = mapped_column(primary_key=True)
    reto_id: Mapped[int] = mapped_column(ForeignKey("retos.id"), index=True)
    accion: Mapped[str] = mapped_column(String(30))
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    detalle: Mapped[str] = mapped_column(Text, default="")
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Quiz(Base):
    __tablename__ = "quizzes"
    __table_args__ = (
        UniqueConstraint("alumno_id", "clase_id", name="quiz_unico_por_clase"),
        _one_of("estado", ("en_curso", "completado"), "quiz_estado"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    alumno_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    curso_id: Mapped[int] = mapped_column(ForeignKey("cursos.id"), index=True)
    clase_id: Mapped[int] = mapped_column(ForeignKey("clases.id"), index=True)
    estado: Mapped[str] = mapped_column(String(12), default="en_curso")
    indice_actual: Mapped[int] = mapped_column(Integer, default=0)
    tiene_repaso: Mapped[bool] = mapped_column(Boolean, default=True)
    tema_principal_id: Mapped[int | None] = mapped_column(ForeignKey("temas.id"))
    nivel_coins: Mapped[str] = mapped_column(String(12), default="basico")
    puesto_inicial: Mapped[int | None] = mapped_column(Integer)
    exp_obtenido: Mapped[int] = mapped_column(Integer, default=0)
    coins_obtenidas: Mapped[int] = mapped_column(Integer, default=0)
    puntaje_verificable: Mapped[float | None] = mapped_column(Float)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    items: Mapped[list["QuizItem"]] = relationship(order_by="QuizItem.orden", viewonly=True)


class QuizItem(Base):
    __tablename__ = "quiz_items"
    __table_args__ = (
        UniqueConstraint("quiz_id", "orden", name="quiz_item_orden"),
        CheckConstraint("orden BETWEEN 1 AND 4", name="quiz_item_orden_rango"),
        CheckConstraint("pistas_usadas BETWEEN 0 AND 3", name="quiz_item_pistas"),
        _one_of("etiqueta", ("clase", "repaso"), "quiz_item_etiqueta"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"), index=True)
    orden: Mapped[int] = mapped_column(Integer)
    reto_id: Mapped[int] = mapped_column(ForeignKey("retos.id"))
    etiqueta: Mapped[str] = mapped_column(String(10), default="clase")
    es_previo: Mapped[bool] = mapped_column(Boolean, default=False)
    nivel: Mapped[str | None] = mapped_column(String(12))
    reto_version_id: Mapped[int | None] = mapped_column(ForeignKey("reto_versiones.id"))
    pistas_usadas: Mapped[int] = mapped_column(Integer, default=0)
    solucion_vista: Mapped[bool] = mapped_column(Boolean, default=False)
    intervalo_repaso: Mapped[int | None] = mapped_column(Integer)
    presentado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Intento(Base):
    __tablename__ = "intentos"
    __table_args__ = (
        UniqueConstraint("alumno_id", "envio_id", name="intento_envio_unico"),
        UniqueConstraint("quiz_item_id", name="intento_unico_por_item"),
        UniqueConstraint("alumno_id", "semanal_id", name="intento_semanal_unico"),
        _one_of("origen", ("quiz", "repaso", "semanal"), "intento_origen"),
        _one_of("estado", ("evaluando", "completado", "pendiente"), "intento_estado"),
        CheckConstraint("resultado IS NULL OR resultado IN ('correcto','parcial','incorrecto')",
                        name="intento_resultado"),
        CheckConstraint("pistas_usadas BETWEEN 0 AND 3", name="intento_pistas"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    alumno_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    curso_id: Mapped[int] = mapped_column(ForeignKey("cursos.id"), index=True)
    reto_id: Mapped[int] = mapped_column(ForeignKey("retos.id"), index=True)
    reto_version_id: Mapped[int] = mapped_column(ForeignKey("reto_versiones.id"))
    tema_id: Mapped[int] = mapped_column(ForeignKey("temas.id"), index=True)
    nivel: Mapped[str] = mapped_column(String(12))
    tipo: Mapped[str] = mapped_column(String(15))
    origen: Mapped[str] = mapped_column(String(10))
    es_repaso: Mapped[bool] = mapped_column(Boolean, default=False)
    quiz_item_id: Mapped[int | None] = mapped_column(ForeignKey("quiz_items.id"))
    semanal_id: Mapped[int | None] = mapped_column(ForeignKey("retos_semanales.id"))
    respuesta: Mapped[str] = mapped_column(Text, default="")
    estado: Mapped[str] = mapped_column(String(12), default="evaluando")
    resultado: Mapped[str | None] = mapped_column(String(12))
    pistas_usadas: Mapped[int] = mapped_column(Integer, default=0)
    tiempo_respuesta_ms: Mapped[int | None] = mapped_column(Integer)
    error_tag: Mapped[str] = mapped_column(Text, default="")
    puntaje: Mapped[float | None] = mapped_column(Float)
    exp: Mapped[int] = mapped_column(Integer, default=0)
    cuenta_para_dominio: Mapped[bool] = mapped_column(Boolean, default=True)
    intervalo_repaso: Mapped[int | None] = mapped_column(Integer)
    calificacion: Mapped[dict | None] = mapped_column(JSONB)
    feedback: Mapped[dict | None] = mapped_column(JSONB)
    reintentos_ia: Mapped[int] = mapped_column(Integer, default=0)
    envio_id: Mapped[str] = mapped_column(String(64))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DominioTema(Base):
    __tablename__ = "dominio_alumno_tema"
    __table_args__ = (_one_of("nivel_actual", NIVELES, "dominio_nivel"),)
    alumno_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), primary_key=True)
    tema_id: Mapped[int] = mapped_column(ForeignKey("temas.id"), primary_key=True, index=True)
    nivel_actual: Mapped[str] = mapped_column(String(12), default="basico")
    # Attempts before this instant do not count for the stored-level window.
    nivel_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    dominio: Mapped[float | None] = mapped_column(Float)
    estado: Mapped[str] = mapped_column(String(12), default="sin_datos")
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgendaRepaso(Base):
    __tablename__ = "agenda_repaso"
    alumno_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), primary_key=True)
    tema_id: Mapped[int] = mapped_column(ForeignKey("temas.id"), primary_key=True, index=True)
    intervalo_actual: Mapped[int] = mapped_column(Integer, default=1)
    proxima_fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RetoSemanal(Base):
    __tablename__ = "retos_semanales"
    __table_args__ = (
        UniqueConstraint("curso_id", "semana", name="reto_semanal_unico"),
        _one_of("estado", ("generando", "listo", "error"), "reto_semanal_estado"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    curso_id: Mapped[int] = mapped_column(ForeignKey("cursos.id"), index=True)
    semana: Mapped[date] = mapped_column(Date)
    tema_id: Mapped[int | None] = mapped_column(ForeignKey("temas.id"))
    reto_id: Mapped[int | None] = mapped_column(ForeignKey("retos.id"))
    tema_visto: Mapped[bool] = mapped_column(Boolean, default=False)
    estado: Mapped[str] = mapped_column(String(10), default="generando")
    error_mensaje: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FuenteSemanal(Base):
    """Class material actually used to generate a weekly challenge; removed with that content."""
    __tablename__ = "fuentes_semanal"
    semanal_id: Mapped[int] = mapped_column(ForeignKey("retos_semanales.id"), primary_key=True)
    clase_id: Mapped[int] = mapped_column(ForeignKey("clases.id"), primary_key=True, index=True)


class RetoSemanalAlumno(Base):
    """The weekly challenge as shown to one student: version one level above theirs, hints used."""
    __tablename__ = "retos_semanales_alumno"
    __table_args__ = (CheckConstraint("pistas_usadas BETWEEN 0 AND 3", name="semanal_alumno_pistas"),)
    alumno_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), primary_key=True)
    semanal_id: Mapped[int] = mapped_column(ForeignKey("retos_semanales.id"), primary_key=True)
    nivel: Mapped[str] = mapped_column(String(12))
    reto_version_id: Mapped[int] = mapped_column(ForeignKey("reto_versiones.id"))
    pistas_usadas: Mapped[int] = mapped_column(Integer, default=0)
    solucion_vista: Mapped[bool] = mapped_column(Boolean, default=False)
    presentado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TareaHecha(Base):
    __tablename__ = "tareas_hechas"
    alumno_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), primary_key=True)
    clase_id: Mapped[int] = mapped_column(ForeignKey("clases.id"), primary_key=True)
    hecha_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Movimiento(Base):
    """Every EXP and Coin. Unique per student, type, origin and reference (EXP y Coins §7)."""
    __tablename__ = "movimientos"
    __table_args__ = (
        UniqueConstraint("alumno_id", "tipo", "origen", "referencia", name="movimiento_unico"),
        _one_of("tipo", ("EXP", "COINS"), "movimiento_tipo"),
        _one_of("origen", ORIGENES_MOVIMIENTO, "movimiento_origen"),
        CheckConstraint("tipo = 'COINS' OR curso_id IS NOT NULL", name="movimiento_exp_con_curso"),
        CheckConstraint(
            "cantidad > 0 OR (origen = 'canje' AND tipo = 'COINS' AND cantidad < 0) OR "
            "(tipo = 'EXP' AND origen IN ('ajuste_reclamo','ajuste_admin') AND cantidad <> 0)",
            name="movimiento_signo",
        ),
        Index("movimiento_curso_tipo", "curso_id", "tipo"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    alumno_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    curso_id: Mapped[int | None] = mapped_column(ForeignKey("cursos.id"))
    tipo: Mapped[str] = mapped_column(String(5))
    origen: Mapped[str] = mapped_column(String(20))
    referencia: Mapped[str] = mapped_column(String(100))
    cantidad: Mapped[int] = mapped_column(Integer)
    motivo: Mapped[str] = mapped_column(Text, default="")
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


@event.listens_for(Movimiento, "before_update")
@event.listens_for(Movimiento, "before_delete")
def _movements_are_append_only(mapper, connection, target):
    raise ValueError("Los movimientos solo se insertan. Las correcciones son movimientos nuevos.")


class Canje(Base):
    __tablename__ = "canjes"
    __table_args__ = (_one_of("porcentaje", (30, 35, 40, 45, 50), "canje_porcentaje"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    alumno_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    porcentaje: Mapped[int] = mapped_column(Integer)
    coins_usadas: Mapped[int] = mapped_column(Integer)
    saldo_posterior: Mapped[int] = mapped_column(Integer)
    corregido_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    corregido_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    correccion_motivo: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Mensaje(Base):
    """Predetermined in-platform message queue, ready for a future external channel."""
    __tablename__ = "cola_mensajes"
    __table_args__ = (
        UniqueConstraint("alumno_id", "curso_id", "tipo", "referencia", name="mensaje_unico"),
        _one_of("tipo", ("clase_nueva", "repaso", "reto_semanal", "inactividad", "podio"), "mensaje_tipo"),
        _one_of("estado", ("pendiente", "mostrado"), "mensaje_estado"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    alumno_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    curso_id: Mapped[int] = mapped_column(ForeignKey("cursos.id"))
    tipo: Mapped[str] = mapped_column(String(15))
    texto: Mapped[str] = mapped_column(Text)
    referencia: Mapped[str] = mapped_column(String(100))
    estado: Mapped[str] = mapped_column(String(10), default="pendiente")
    canal: Mapped[str] = mapped_column(String(15), default="plataforma")
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    mostrado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SenalRiesgo(Base):
    __tablename__ = "senales_riesgo"
    __table_args__ = (
        UniqueConstraint("alumno_id", "curso_id", "tipo", "referencia", name="senal_unica"),
        _one_of("tipo", ("inactividad", "caida"), "senal_tipo"),
        _one_of("estado", ("nuevo", "contactado"), "senal_estado"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    alumno_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    curso_id: Mapped[int] = mapped_column(ForeignKey("cursos.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(12))
    referencia: Mapped[str] = mapped_column(String(60))
    detalle: Mapped[str] = mapped_column(Text, default="")
    estado: Mapped[str] = mapped_column(String(12), default="nuevo")
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    contactado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    contactado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


class Revision(Base):
    """Teacher review inbox: claims, anomalies, reported errors and tutor flags."""
    __tablename__ = "revisiones_docente"
    __table_args__ = (
        UniqueConstraint("tipo", "referencia", name="revision_unica"),
        _one_of("tipo", ("reclamo", "anomalia", "error_reportado", "marcado_ia"), "revision_tipo"),
        _one_of("estado", ("pendiente", "resuelta", "desestimada"), "revision_estado"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    curso_id: Mapped[int] = mapped_column(ForeignKey("cursos.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(16))
    referencia: Mapped[str] = mapped_column(String(60))
    alumno_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    reto_id: Mapped[int | None] = mapped_column(ForeignKey("retos.id"))
    intento_id: Mapped[int | None] = mapped_column(ForeignKey("intentos.id"))
    motivo: Mapped[str] = mapped_column(Text, default="")
    estado: Mapped[str] = mapped_column(String(12), default="pendiente")
    resolucion: Mapped[str | None] = mapped_column(Text)
    resuelto_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    resuelto_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Parametro(Base):
    """Append-only parameter history. The latest row per clave is in force."""
    __tablename__ = "parametros"
    id: Mapped[int] = mapped_column(primary_key=True)
    clave: Mapped[str] = mapped_column(String(60), index=True)
    valor: Mapped[float] = mapped_column(Float)
    valor_anterior: Mapped[float | None] = mapped_column(Float)
    vigente_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cambiado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


class ConfiguracionIA(Base):
    """Append-only, non-secret provider/model revisions. A new request uses the latest row."""
    __tablename__ = "configuraciones_ia"
    __table_args__ = (_one_of("proveedor", ("openai", "vertex"), "configuracion_ia_proveedor"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    proveedor: Mapped[str] = mapped_column(String(12))
    opciones: Mapped[dict] = mapped_column(JSONB)
    cambiado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    verificado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LlamadaIA(Base):
    """Observability without personal data: component, model, tokens and outcome."""
    __tablename__ = "llamadas_ia"
    id: Mapped[int] = mapped_column(primary_key=True)
    componente: Mapped[str] = mapped_column(String(30))
    modelo: Mapped[str] = mapped_column(String(80))
    referencia: Mapped[str | None] = mapped_column(String(60))
    tokens_entrada: Mapped[int] = mapped_column(Integer, default=0)
    tokens_salida: Mapped[int] = mapped_column(Integer, default=0)
    duracion_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error_tipo: Mapped[str | None] = mapped_column(String(60))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

"""Declared educational profiles, coherent demo data and one-time paired Coins rewards."""

import calendar
import random
import re
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from db.models import Movimiento, PerfilUsuario, Usuario
from rules.calendar import ahora
from services import ledger

SITUACIONES = ("Estudio", "Trabajo", "Estudio y trabajo", "Busco empleo")
ESTUDIOS = ("En curso", "Egresado/a", "Titulado/a", "Posgrado en curso", "Posgrado completado")
SECTORES = ("Tecnología", "Educación", "Finanzas", "Comercio y retail", "Logística", "Servicios", "Industria", "Salud")
CAMPOS = (
    {"clave": "edad", "etiqueta": "Edad", "tipo": "number", "min": 16, "max": 90},
    {"clave": "situacion", "etiqueta": "Situación actual", "tipo": "select", "opciones": SITUACIONES},
    {"clave": "carrera", "etiqueta": "Carrera o formación", "tipo": "text", "max": 120},
    {"clave": "estado_estudios", "etiqueta": "Estado de estudios", "tipo": "select", "opciones": ESTUDIOS},
    {"clave": "ocupacion", "etiqueta": "Ocupación o puesto", "tipo": "text", "max": 120},
    {"clave": "sector", "etiqueta": "Sector de actividad o interés", "tipo": "select", "opciones": SECTORES},
    {"clave": "experiencia_anios", "etiqueta": "Años de experiencia laboral", "tipo": "number", "min": 0, "max": 60},
    {"clave": "ingreso_dmc", "etiqueta": "En DMC desde", "tipo": "date"},
    {"clave": "cursos_previos", "etiqueta": "Cursos previos en DMC", "tipo": "textarea", "max": 600,
     "ayuda": "Separa los cursos con comas. Si este es el primero, escribe «Ninguno»."},
    {"clave": "herramientas", "etiqueta": "Herramientas que conoces", "tipo": "text", "max": 300},
    {"clave": "objetivo", "etiqueta": "Objetivo de aprendizaje", "tipo": "textarea", "max": 600},
    {"clave": "horas_semana", "etiqueta": "Horas semanales para aprender", "tipo": "number", "min": 1, "max": 40},
)
CLAVES = tuple(c["clave"] for c in CAMPOS)


class PerfilInvalido(ValueError):
    pass


class PerfilDesactualizado(PerfilInvalido):
    pass


def ejemplos(usuario):
    """Stable examples per user, independent of real identity, courses or grades."""
    azar = random.Random(f"dmc-perfil-v1:{usuario.id}:{usuario.rol}")
    trayectorias = (
        ("Ingeniería de Sistemas", "Analista de datos", "Tecnología", "Excel, SQL, Python", "Aplicar Python al análisis de datos y automatizar reportes."),
        ("Ingeniería Industrial", "Analista de operaciones", "Logística", "Excel, Power BI", "Mejorar la visualización de indicadores y optimizar procesos."),
        ("Administración de Empresas", "Analista de negocios", "Comercio y retail", "Excel, Power BI, SQL", "Tomar decisiones comerciales con análisis de datos."),
        ("Estadística", "Analista de riesgos", "Finanzas", "Excel, R, Python", "Profundizar en modelos analíticos aplicados a riesgos."),
        ("Economía", "Analista financiero", "Finanzas", "Excel, SQL", "Automatizar informes financieros y crear dashboards."),
        ("Ingeniería Informática", "Desarrollador/a de software", "Tecnología", "Python, SQL, Git", "Fortalecer mis conocimientos de ingeniería de datos."),
    )
    carrera, ocupacion, sector, herramientas, objetivo = azar.choice(trayectorias)
    edad = azar.randint(20, 48) if usuario.rol == "alumno" else azar.randint(30, 55)
    experiencia = azar.randint(0, max(0, edad - 22))
    situacion, estado = azar.choice(("Trabajo", "Estudio y trabajo")), "Titulado/a"
    if edad < 24:
        situacion, estado = "Estudio y trabajo" if experiencia else "Estudio", "En curso"
        ocupacion = "Asistente de análisis de datos" if experiencia else "Estudiante de " + carrera
    if usuario.rol == "docente":
        ocupacion, sector, situacion = "Docente y consultor/a en analítica", "Educación", "Trabajo"
        estado, experiencia = "Posgrado completado", max(5, experiencia)
        objetivo = "Actualizar mis conocimientos y acompañar el aprendizaje en tecnología."
    elif usuario.rol == "admin":
        ocupacion, sector, situacion = "Coordinador/a de formación tecnológica", "Educación", "Trabajo"
        objetivo = "Mejorar la experiencia de formación y la gestión académica."
    hoy = ahora().date()
    meses = azar.randint(3, min(60, (edad - 17) * 12))
    mes_absoluto = hoy.year * 12 + hoy.month - 1 - meses
    anio, mes = divmod(mes_absoluto, 12)
    ingreso = date(anio, mes + 1, min(hoy.day, calendar.monthrange(anio, mes + 1)[1]))
    previos = azar.sample(("Excel para Análisis de Datos", "SQL Fundamentals", "Power BI Fundamentals", "Python Fundamentals"), azar.randint(1, min(3, 1 + meses // 12)))
    return dict(zip(CLAVES, (str(edad), situacion, carrera, estado, ocupacion, sector, str(experiencia),
                            ingreso.isoformat(), ", ".join(previos), herramientas, objetivo, str(azar.randint(3, 10)))))


def crear(db, usuario, *, con_ejemplo=False):
    db.execute(insert(PerfilUsuario).values(usuario_id=usuario.id, datos=ejemplos(usuario) if con_ejemplo else {},
        campos_reconocidos=[], es_ejemplo=con_ejemplo, version=0).on_conflict_do_nothing())
    return db.get(PerfilUsuario, usuario.id)


def preparar_existentes(db):
    usuarios = db.scalars(select(Usuario).where(
        ~select(PerfilUsuario.usuario_id).where(PerfilUsuario.usuario_id == Usuario.id).exists())).all()
    for usuario in usuarios:
        crear(db, usuario, con_ejemplo=True)
    return len(usuarios)


def validar(datos):
    limpios = {}
    for campo in CAMPOS:
        clave, tipo = campo["clave"], campo["tipo"]
        valor = " ".join(str(datos.get(clave, "")).split())
        if not valor:
            continue  # Optional fields do not count toward the reward.
        if tipo == "number":
            if not re.fullmatch(r"\d{1,2}", valor) or not campo["min"] <= int(valor) <= campo["max"]:
                raise PerfilInvalido(f"{campo['etiqueta']}: indica un número entre {campo['min']} y {campo['max']}.")
            valor = str(int(valor))
        elif tipo == "date":
            try:
                fecha = date.fromisoformat(valor)
                if not date(2000, 1, 1) <= fecha <= ahora().date():
                    raise ValueError
            except ValueError as error:
                raise PerfilInvalido("La fecha de ingreso a DMC debe ser válida y no estar en el futuro.") from error
        elif tipo == "select":
            if valor not in campo["opciones"]:
                raise PerfilInvalido(f"{campo['etiqueta']}: elige una opción de la lista.")
        elif len(valor) > campo["max"] or len(valor) < 3:
            raise PerfilInvalido(f"{campo['etiqueta']}: escribe entre 3 y {campo['max']} caracteres.")
        limpios[clave] = valor
    if "edad" in limpios and "experiencia_anios" in limpios and int(limpios["experiencia_anios"]) > int(limpios["edad"]) - 16:
        raise PerfilInvalido("Los años de experiencia no son coherentes con la edad indicada.")
    if "edad" in limpios and "ingreso_dmc" in limpios:
        antiguedad = (ahora().date() - date.fromisoformat(limpios["ingreso_dmc"])).days / 365.25
        if antiguedad > int(limpios["edad"]) - 15:
            raise PerfilInvalido("La fecha de ingreso a DMC no es coherente con la edad indicada.")
    return limpios


def guardar(db, usuario_id, datos, *, version, confirmo):
    if confirmo != "si":
        raise PerfilInvalido("Confirma que revisaste los datos del perfil antes de guardarlos.")
    limpios = validar(datos)
    usuario = db.scalar(select(Usuario).where(Usuario.id == usuario_id).with_for_update()
                        .execution_options(populate_existing=True))
    perfil = crear(db, usuario)
    db.refresh(perfil)
    if str(perfil.version) != str(version):
        raise PerfilDesactualizado("El perfil cambió en otra pestaña. Recarga la página para ver la versión actual.")
    reconocidos = set(perfil.campos_reconocidos or []) | set(limpios)
    perfil.datos, perfil.campos_reconocidos = limpios, [k for k in CLAVES if k in reconocidos]
    perfil.es_ejemplo, perfil.confirmado_en, perfil.actualizado_en = False, ahora(), ahora()
    perfil.version += 1
    coins = 0
    # Coins are an existing student benefit; staff still receive the same editable profile.
    if usuario.rol == "alumno" and not usuario.coins_pausadas:
        for par in range(1, len(perfil.campos_reconocidos) // 2 + 1):
            coins += int(ledger.registrar(db, alumno_id=usuario.id, tipo="COINS", origen="perfil",
                referencia=f"perfil:{usuario.id}:par:{par}", cantidad=1,
                motivo="Perfil: dos campos completados (0,5 Coin por campo)."))
    return coins


def detalle(db, usuario):
    perfil = crear(db, usuario)
    ganadas = int(db.scalar(select(func.coalesce(func.sum(Movimiento.cantidad), 0)).where(
        Movimiento.alumno_id == usuario.id, Movimiento.origen == "perfil", Movimiento.tipo == "COINS")))
    datos = perfil.datos or {}
    ingreso = date.fromisoformat(datos["ingreso_dmc"]) if datos.get("ingreso_dmc") else None
    meses = ((ahora().year - ingreso.year) * 12 + ahora().month - ingreso.month) if ingreso else None
    cursos = [c.strip() for c in re.split(r"[,;\n]", datos.get("cursos_previos", "")) if c.strip()]
    n_cursos = 0 if len(cursos) == 1 and cursos[0].casefold() == "ninguno" else len(cursos)
    return {"perfil": perfil, "campos": CAMPOS, "datos": datos, "completados": len([k for k in CLAVES if datos.get(k) is not None and datos.get(k) != ""]),
            "ganadas": ganadas, "medias_pendientes": len(perfil.campos_reconocidos or []) % 2,
            "antiguedad_meses": meses, "cursos_previos_cantidad": n_cursos}

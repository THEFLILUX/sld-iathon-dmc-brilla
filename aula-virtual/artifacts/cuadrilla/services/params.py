"""Parameters in force: documented defaults plus the latest administrator value per key."""

from sqlalchemy import select

from db.models import Parametro
from rules.params import POR_CLAVE, Params


def cargar(db) -> Params:
    filas = db.execute(select(Parametro.clave, Parametro.valor)
                       .order_by(Parametro.vigente_desde, Parametro.id)).all()
    # The history is short; later rows overwrite earlier ones.
    return Params({clave: valor for clave, valor in filas})


def guardar(db, admin_id: int, clave: str, valor: float) -> None:
    definicion = POR_CLAVE.get(clave)
    if definicion is None:
        raise ValueError("Parámetro desconocido.")
    if not definicion.minimo <= valor <= definicion.maximo:
        raise ValueError(f"{definicion.etiqueta}: usa un valor entre {definicion.minimo:g} y {definicion.maximo:g}.")
    if definicion.entero and valor != int(valor):
        raise ValueError(f"{definicion.etiqueta}: usa un número entero.")
    anterior = getattr(cargar(db), clave)
    if anterior == valor:
        return
    db.add(Parametro(clave=clave, valor=valor, valor_anterior=anterior, cambiado_por=admin_id))


def historial(db, limite: int = 50):
    return db.scalars(select(Parametro).order_by(Parametro.vigente_desde.desc(), Parametro.id.desc()).limit(limite)).all()

"""Coins redemption (EXP y Coins §4). Serialized per student so the balance can never go negative."""

from sqlalchemy import select

from db.models import Canje, Usuario
from rules import redemption
from rules.calendar import ahora
from services import ledger


class CanjeInvalido(ValueError):
    pass


def canjear(db, alumno: Usuario, porcentaje: int, params) -> Canje:
    if porcentaje not in redemption.PORCENTAJES:
        raise CanjeInvalido("Elige un descuento entre 30 % y 50 %, en pasos de 5 %.")
    db.scalar(select(Usuario.id).where(Usuario.id == alumno.id).with_for_update())
    saldo = ledger.saldo_coins(db, alumno.id)
    coins = redemption.coins_para(porcentaje, params)
    if saldo < coins:
        raise CanjeInvalido(f"Te faltan {coins - saldo} Coins para el {porcentaje} %.")
    canje = Canje(alumno_id=alumno.id, porcentaje=porcentaje, coins_usadas=coins, saldo_posterior=saldo - coins)
    db.add(canje)
    db.flush()
    ledger.registrar(db, alumno_id=alumno.id, tipo="COINS", origen="canje", referencia=f"canje:{canje.id}",
                     cantidad=-coins, motivo=f"Canje por {porcentaje} % de descuento")
    return canje


def corregir(db, canje: Canje, admin_id: int, motivo: str) -> None:
    """Only the administrator corrects a redemption, by returning the Coins with a reason."""
    motivo = motivo.strip()
    if not motivo:
        raise CanjeInvalido("Indica el motivo de la devolución.")
    canje = db.scalar(select(Canje).where(Canje.id == canje.id).with_for_update()
                      .execution_options(populate_existing=True))
    if canje.corregido_en is not None:
        raise CanjeInvalido("Este canje ya fue corregido.")
    ledger.registrar(db, alumno_id=canje.alumno_id, tipo="COINS", origen="devolucion_canje",
                     referencia=f"canje:{canje.id}", cantidad=canje.coins_usadas, motivo=motivo, creado_por=admin_id)
    canje.corregido_en, canje.corregido_por, canje.correccion_motivo = ahora(), admin_id, motivo[:1000]

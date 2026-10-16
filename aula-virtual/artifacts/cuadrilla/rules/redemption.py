"""Coins redemption (EXP y Coins §4): 30 % to 50 % in steps of 5 %, 1 Coin = 0,05 %."""

PORCENTAJES = (30, 35, 40, 45, 50)


def coins_para(porcentaje: int, params) -> int:
    return int(round(porcentaje / params.coin_porcentaje))


def opciones(saldo: int, params) -> list[dict]:
    return [
        {"porcentaje": pct, "coins": coins_para(pct, params), "alcanza": saldo >= coins_para(pct, params)}
        for pct in PORCENTAJES
    ]


def faltan_para_minimo(saldo: int, params) -> int:
    return max(0, coins_para(PORCENTAJES[0], params) - saldo)

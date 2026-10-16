"""Time rules. The weekly challenge renews on Monday 00:00, Lima time, for everyone."""

from datetime import date, datetime, time, timedelta, timezone

from config import LIMA


def ahora() -> datetime:
    return datetime.now(timezone.utc)


def semana_de(momento: datetime) -> date:
    local = momento.astimezone(LIMA)
    return local.date() - timedelta(days=local.weekday())


def inicio_semana(semana: date) -> datetime:
    return datetime.combine(semana, time(0), LIMA).astimezone(timezone.utc)


def fin_semana(semana: date) -> datetime:
    return inicio_semana(semana + timedelta(days=7))


def fecha_lima(momento: datetime | date | None) -> str:
    if momento is None:
        return "—"
    meses = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
    local = momento.astimezone(LIMA) if isinstance(momento, datetime) else momento
    return f"{local.day} {meses[local.month - 1]}"


def fecha_hora_lima(momento: datetime | None) -> str:
    if momento is None:
        return "—"
    local = momento.astimezone(LIMA)
    return f"{fecha_lima(momento)} · {local:%H:%M}"

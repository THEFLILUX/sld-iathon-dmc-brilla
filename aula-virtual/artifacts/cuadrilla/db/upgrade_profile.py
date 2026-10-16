"""Explicit, idempotent upgrade: allow the new profile reward in the existing ledger."""

from sqlalchemy import text

from db.models import ORIGENES_MOVIMIENTO


def ampliar_origen_perfil(engine):
    with engine.begin() as conexion:
        conexion.execute(text("SELECT pg_advisory_xact_lock(hashtext('dmc:perfil:movimiento_origen'))"))
        definicion = conexion.scalar(text("""SELECT pg_get_constraintdef(oid) FROM pg_constraint
            WHERE conrelid = 'movimientos'::regclass AND conname = 'movimiento_origen'"""))
        if definicion and "'perfil'" not in definicion:
            # Constant enum values only. Both DDL operations commit or roll back together.
            opciones = ", ".join(repr(v) for v in ORIGENES_MOVIMIENTO)
            conexion.execute(text("ALTER TABLE movimientos DROP CONSTRAINT movimiento_origen, "
                                  f"ADD CONSTRAINT movimiento_origen CHECK (origen IN ({opciones}))"))

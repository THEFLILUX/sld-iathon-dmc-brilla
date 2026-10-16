"""Set deployment-only passwords after restoring the local database.

Run once with the private credentials JSON mounted at /run/cloud-accounts.json.
The local database is never modified. Existing browser sessions are not migrated.
"""

import json
from pathlib import Path

from sqlalchemy import delete, select

from auth.passwords import hash_password
from db.models import Sesion, Usuario
from db.session import SessionLocal


def main():
    accounts = json.loads(Path("/run/cloud-accounts.json").read_text())
    with SessionLocal.begin() as db:
        for account in accounts:
            user = db.scalar(select(Usuario).where(Usuario.dni == account["dni"]))
            if user is None:
                raise RuntimeError("Una cuenta de la copia no está en la base restaurada.")
            user.password_hash = hash_password(account["password"])
        db.execute(delete(Sesion))
    print(f"Contraseñas de cloud configuradas para {len(accounts)} cuentas; sesiones locales excluidas.")


if __name__ == "__main__":
    main()

"""Create missing tables and apply the explicit, non-destructive ledger enum upgrade.

The app also runs it at startup unless DB_AUTO_CREATE=false.
"""

from db.models import Base
from db.session import engine


def crear_tablas() -> None:
    Base.metadata.create_all(engine)
    from db.upgrade_profile import ampliar_origen_perfil
    ampliar_origen_perfil(engine)


def main():
    crear_tablas()
    print("Tablas del aula virtual DMC listas.")


if __name__ == "__main__":
    main()

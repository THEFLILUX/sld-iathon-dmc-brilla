"""Predetermined messages (spec §11). Fixed, generic texts; no AI; no grades or personal data."""

TEXTOS = {
    "clase_nueva": "¡Ya se subió el video de clase! Recuerda hacer tus EXP",
    "repaso": "Tienes temas por repasar. Repasar hoy ayuda a que no se te olviden",
    "reto_semanal": "Ya está tu reto semanal. Es una sola pregunta y vale más EXP",
    "inactividad": "Hace unos días no te vemos por tu curso. Puedes retomar en unos minutos",
    "podio": "¡Subiste en el podio de tu curso! Mira tu posición",
}
PRIORIDAD = ("clase_nueva", "repaso", "reto_semanal", "inactividad", "podio")
MAXIMO_AL_INGRESAR = 2

"""Rule-based anonymization (PRD RF-05, AI behavior spec §11).

Runs on transcripts, teacher resources and student answers before they reach the
AI or are stored as answers. It removes contact data, DNIs, the names of people
registered in the platform, common first names and names introduced in speech
("mi nombre es…", "profesor…"). It is a heuristic: the privacy guard in
ai/privacy.py still verifies every outgoing payload.
"""

import re
from dataclasses import dataclass, field

PERSONA = "[persona]"
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
TELEFONO = re.compile(r"(?<![\w+])(?:\+?51[\s-]?)?9\d{2}[\s-]?\d{3}[\s-]?\d{3}(?![\w])")
DNI_CON_CONTEXTO = re.compile(r"(?i)\b(d\.?n\.?i\.?|documento(?: de identidad)?)\s*(?:n[°º.]?\s*|:\s*)?\d{8}\b")
TARJETA = re.compile(r"(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?!\d)")
_NOMBRE = r"[A-ZÁÉÍÓÚÑ][a-záéíóúñü]+"
PRESENTACION = re.compile(
    r"(?i:\b(me llamo|mi nombre es|soy la profesora|soy el profesor|la profesora|el profesor|profesora|profesor|"
    r"la docente|el docente|alumna|alumno|compañera|compañero|señora|señor|sra\.|sr\.|gracias,|hola,)\s+)"
    rf"({_NOMBRE}(?:\s+{_NOMBRE}){{0,2}})"
)
# Frequent first names in Peru and Latin America. Words that are also common nouns are excluded.
NOMBRES_COMUNES = frozenset("""
Aarón Abel Abigail Adolfo Adriana Adrián Agustín Alberto Alejandra Alejandro Alessandra Alexander Alfonso Alfredo
Alicia Alonso Álvaro Amanda Ana Andrea Andrés Ángel Ángela Angélica Antonella Antonio Ariana Armando Arturo
Beatriz Benjamín Bernardo Brenda Bruno Camila Carla Carlos Carmen Carolina Catalina César Christian Claudia
Cristian Cristina Daniel Daniela David Diana Diego Edgar Eduardo Elena Elizabeth Emilio Enrique Erick Ernesto
Esteban Eva Fabián Fabiola Fátima Federico Felipe Fer Fernanda Fernando Flor Francisco Gabriel Gabriela Gerardo
Gianella Gonzalo Graciela Gustavo Héctor Hugo Ignacio Isabel Isabella Iván Jaime Javier Jesús Jimena Joaquín
Jorge José Josué Juan Juana Julia Julio Karen Karina Katherine Kevin Laura Leonardo Liliana Lorena Lucas Lucía
Luciana Luis Luisa Manuel Marcela Marco Marcos Margarita María Mariana Mario Marisol Martha Martín Mateo Mauricio
Melissa Miguel Milagros Mónica Natalia Nicolás Noemí Óscar Pablo Patricia Paola Paula Pedro Rafael Ramiro Raúl
Rebeca Renato Renzo Ricardo Roberto Rodrigo Rosario Rubén Samuel Sandra Santiago Sara Sebastián Sergio Silvia
Sofía Susana Tatiana Teresa Tomás Valentina Valeria Vanessa Verónica Víctor Walter Ximena Yolanda
""".split())


@dataclass(frozen=True)
class Conocidos:
    """Personal data registered in the platform, used to anonymize and to guard AI calls."""
    nombres_completos: frozenset[str] = field(default_factory=frozenset)
    nombres: frozenset[str] = field(default_factory=frozenset)
    dnis: frozenset[str] = field(default_factory=frozenset)


def conocidos_desde(usuarios) -> Conocidos:
    completos, sueltos, dnis = set(), set(), set()
    for usuario in usuarios:
        nombre, apellido = (usuario.nombre or "").strip(), (usuario.apellido or "").strip()
        if nombre and apellido:
            completos.add(f"{nombre} {apellido}")
        for parte in f"{nombre} {apellido}".split():
            if len(parte) >= 3:
                sueltos.add(parte)
        if usuario.dni:
            dnis.add(usuario.dni)
    return Conocidos(frozenset(completos), frozenset(sueltos), frozenset(dnis))


def _reemplazar_palabras(texto: str, palabras) -> str:
    if not palabras:
        return texto
    patron = re.compile(r"(?<![\wÁÉÍÓÚÑáéíóúñü])(" + "|".join(
        re.escape(p) for p in sorted(palabras, key=len, reverse=True)
    ) + r")(?![\wÁÉÍÓÚÑáéíóúñü])")
    return patron.sub(PERSONA, texto)


def anonimizar(texto: str | None, conocidos: Conocidos | None = None) -> str:
    if not texto:
        return ""
    conocidos = conocidos or Conocidos()
    texto = EMAIL.sub("[correo]", texto)
    texto = DNI_CON_CONTEXTO.sub(lambda m: f"{m.group(1)} [dni]", texto)
    texto = TARJETA.sub("[dato]", texto)
    texto = TELEFONO.sub("[teléfono]", texto)
    for dni in conocidos.dnis:
        texto = re.sub(rf"(?<!\w){re.escape(dni)}(?!\w)", "[dni]", texto)
    texto = PRESENTACION.sub(lambda m: f"{m.group(1)} {PERSONA}", texto)
    texto = _reemplazar_palabras(texto, conocidos.nombres_completos)
    texto = _reemplazar_palabras(texto, conocidos.nombres | NOMBRES_COMUNES)
    return re.sub(rf"{re.escape(PERSONA)}(?:\s+{re.escape(PERSONA)})+", PERSONA, texto)

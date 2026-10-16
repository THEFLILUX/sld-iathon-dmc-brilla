# Aula virtual · DMC Institute

Plataforma web de refuerzo post-clase con IA para el aula virtual de DMC. La especificación está en
`documentacion/` y el detalle técnico en [artifacts/cuadrilla/README.md](artifacts/cuadrilla/README.md).

## Requisitos

- [uv](https://docs.astral.sh/uv/) (instala Python 3.12 automáticamente; `brew install uv` en macOS).
- Nada más para empezar: si no defines `DATABASE_URL`, la app levanta una **PostgreSQL embebida**
  (paquete `pgserver`) en `artifacts/cuadrilla/.local/`, y usa un **ffmpeg incluido** (`imageio-ffmpeg`)
  si no tienes uno instalado.
- Para usar IA: una clave de OpenAI **o** de Google Gemini.

## Puesta en marcha

```sh
uv sync                                                     # crea .venv con Python 3.12
cp artifacts/cuadrilla/.env.example artifacts/cuadrilla/.env    # y completa tu clave de IA
cd artifacts/cuadrilla
uv run python run.py                                        # http://127.0.0.1:8000
```

La primera vez se crean las tablas y, con `DEMO_MODE=true`, dos cursos («Python para Análisis de Datos»
y «Especialización en Big Data») con sus mallas y las cuentas de demostración (contraseña `cuadrilla`
salvo que definas `DEMO_PASSWORD`):

| Rol | DNI | Cursos |
|---|---|---|
| Alumna | `70000001` (Lucía Torres) | Python y Big Data |
| Docente | `20000001` (Fernanda Ríos) | Python |
| Docente | `20000002` (Ricardo Paredes) | Big Data |
| Administrador | `10000001` | Todos |

Como administrador, **Cargar datos de demostración** crea las clases (con retos escritos a mano) y
práctica simulada en ambos cursos, sin llamar a la IA. Lucía entra a **Mis cursos**: ya practicó en Big
Data y tiene pendiente el primer quiz de Python.

Detén el servidor con `Ctrl+C`: la base embebida se apaga con él y los datos se conservan para el
próximo arranque.

## Elegir el proveedor de IA (LangChain)

Toda la IA pasa por LangChain (`artifacts/cuadrilla/ai/proveedores.py`). Cambiar de proveedor es solo
configuración en `artifacts/cuadrilla/.env`:

```sh
# OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...

# Google Gemini
LLM_PROVIDER=gemini
GOOGLE_API_KEY=...
```

`LLM_MODEL` elige el modelo (por defecto `gpt-6-luna` u `gemini-3.5-flash`). La transcripción de
videos usa el mismo proveedor salvo que definas `TRANSCRIPTION_PROVIDER`. Reinicia el servidor tras
cambiar el `.env`.

## Pruebas

```sh
cd artifacts/cuadrilla
uv run python -m unittest discover -s tests -v
```

No necesitan base de datos ni claves: levantan una PostgreSQL embebida temporal, simulan los
proveedores de IA y bloquean cualquier acceso a la red.

## Con tu propia PostgreSQL o en un servidor

Define `DATABASE_URL=postgresql://usuario:clave@host:5432/base` en el `.env`. Para exponer la app en la
red local usa `HOST=0.0.0.0`; detrás de un proxy inverso, indica su IP en `FORWARDED_ALLOW_IPS`. En
producción: `DEMO_MODE=false` y `ADMIN_DNI` + `ADMIN_PASSWORD` para crear el primer administrador.
Ejecuta un solo proceso (`uv run python run.py`): los trabajos de IA corren en hilos de ese proceso.

La demo pública y las instrucciones de operación en Google Cloud están en
[deploy/gcp/README.md](deploy/gcp/README.md).

> Las carpetas `artifacts/api-server`, `artifacts/mockup-sandbox`, `lib/` y `scripts/` y los archivos de
> pnpm son restos de la plantilla de Replit; la app no los usa.

## Configuración actual de IA

Administración → **IA y modelos** permite probar y alternar OpenAI y Gemini en Vertex AI mediante LangChain, sin reiniciar. Vertex usa credenciales de Google Cloud (ADC), `GOOGLE_CLOUD_PROJECT` y `GOOGLE_CLOUD_LOCATION`; el modelo inicial es `gemini-3.5-flash-lite`. Esta selección administrativa tiene prioridad sobre el proveedor inicial del `.env`. Ver [configuración de Vertex AI](documentacion/vertex-ai-y-modelos.md).

Este componente está en `aula-virtual/`; ejecuta los comandos anteriores desde esa carpeta. Las grabaciones, bases de datos y credenciales del despliegue se mantienen fuera de Git.

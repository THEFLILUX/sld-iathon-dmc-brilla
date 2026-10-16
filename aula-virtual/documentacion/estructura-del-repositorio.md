# Estructura del repositorio

El repositorio reúne dos componentes: el chatbot de WhatsApp orquestado en n8n y el aula virtual
desarrollada con FastAPI. En GitHub, la carpeta `aula-virtual/` corresponde a la raíz del workspace
de la web. Las plantillas de partida están agrupadas en un archivo histórico independiente.

```text
sld-iathon-dmc-brilla/
├── README.md                         Descripción general e índice de componentes
├── workflows/                        Workflows n8n del chatbot y sus integraciones
├── docs/                             Arquitectura y costos del sistema de WhatsApp
└── aula-virtual/
    ├── README.md                     Instalación, ejecución y mapa de la web
    ├── pyproject.toml                Dependencias Python
    ├── uv.lock                       Versiones de dependencias fijadas
    ├── .python-version               Versión de Python
    ├── Dockerfile                    Imagen de la aplicación activa
    ├── artifacts/cuadrilla/
    │   ├── main.py, run.py           Aplicación FastAPI y servidor
    │   ├── config.py, .env.example   Configuración y ejemplo sin credenciales
    │   ├── web/                     Rutas y controladores del backend
    │   ├── auth/                    Sesiones, contraseñas y permisos
    │   ├── services/                Servicios de cursos, perfiles, quizzes y reportes
    │   ├── rules/                   Reglas académicas, progreso y recompensas
    │   ├── db/                      Modelos y acceso a PostgreSQL
    │   ├── ai/                      Integraciones, privacidad y procesamiento de IA
    │   │   ├── prompts.py           Prompts de los procesos académicos
    │   │   └── assistant.py         Prompt y contrato del Asistente Brilla docente
    │   ├── templates/               Frontend: páginas Jinja2
    │   ├── static/                  Frontend: CSS, JavaScript, imágenes y fuentes
    │   ├── tests/                   Pruebas automatizadas
    │   ├── sample_data/             Instrucciones para fuentes locales
    │   └── uploads/                 Marcador de carpeta; archivos privados excluidos
    ├── deploy/gcp/                  Compose, Caddy y scripts de instalación y respaldo
    ├── documentacion/               Especificaciones y documentación funcional y técnica
    └── archivo/replit/              Plantilla y requisitos históricos; sin uso en producción
```

## Separación de responsabilidades

La web es una aplicación que renderiza páginas en el servidor. Por ello, el frontend está en
`templates/` y `static/`, y el backend se reparte entre `web/`, `auth/`, `services/`, `rules/` y `db/`.
Los prompts y contratos de IA se mantienen en `ai/`; los scripts operativos están en `deploy/gcp/`.
Esta organización conserva los imports de Python y las rutas que usa el despliegue.

La plantilla React/Express, las librerías TypeScript, los archivos de pnpm y los requisitos originales
se conservan bajo `archivo/replit/`, con un [índice propio](../archivo/replit/README.md). No se instalan
para ejecutar la web y `.dockerignore` excluye ese archivo de la imagen de producción.

## Puntos de entrada

Desde `aula-virtual/` en una copia del repositorio:

```sh
uv sync
cp artifacts/cuadrilla/.env.example artifacts/cuadrilla/.env
cd artifacts/cuadrilla
uv run python run.py
```

Las pruebas se ejecutan desde la misma carpeta de la aplicación:

```sh
uv run python -m unittest discover -s tests -v
```

El Dockerfile mantiene su contexto en la raíz de `aula-virtual/`. Los comandos operativos se
documentan en [deploy/gcp/README.md](../deploy/gcp/README.md). Los workflows del chatbot conservan
sus nombres y ubicación; sus instrucciones están en el README principal del repositorio.

## Archivos privados y generados

`.gitignore` excluye `.env`, entornos virtuales, cachés, cargas de usuarios, bases de datos, respaldos
y configuración privada de despliegue. Las grabaciones históricas también están excluidas.
El repositorio conserva `.env.example`, `uploads/.gitkeep` y las instrucciones de `sample_data/`
para mostrar dónde se configura y almacena cada tipo de archivo.

# Aula virtual · DMC Institute

Plataforma web de refuerzo post-clase con IA, dentro del aula virtual de DMC. Después de cada clase,
el alumno resuelve un quiz corto de 4 retos construidos con lo que se vio en esa clase; la dificultad
se ajusta por tema (niveles de Bloom), cada tema vuelve antes de olvidarse (repaso espaciado) y el
docente ve, tema por tema, qué domina cada alumno y quién necesita apoyo. El alumno también puede
repasar un resumen de cada clase, generado automáticamente por IA a partir del transcript.

La especificación está en `documentacion/` (brief, PRD, especificación funcional, historias de usuario,
AI behavior spec y sistema de EXP y Coins). Este componente contiene la web; los workflows del
chatbot de WhatsApp están en `workflows/`, en la raíz del repositorio de GitHub. Los mensajes
predeterminados de la web se muestran en la plataforma y quedan en su cola de mensajes.

El [mapa del repositorio](../../documentacion/estructura-del-repositorio.md) detalla frontend
(`templates/`, `static/`), backend (`web/`, `services/`, `auth/`, `db/`, `rules/`), IA (`ai/`), pruebas
(`tests/`) y scripts operativos (`deploy/gcp/`). La plantilla original está en `archivo/replit/`,
separada de la aplicación activa.

## Ejecutar en local

La guía completa está en el [README de la raíz](../../README.md). En resumen, desde la raíz:

```sh
uv sync
cp artifacts/cuadrilla/.env.example artifacts/cuadrilla/.env   # clave de OpenAI o Gemini
cd artifacts/cuadrilla && uv run python run.py                # http://127.0.0.1:8000
```

- Sin `DATABASE_URL`, `db/local_pg.py` levanta una PostgreSQL embebida (`pgserver`) en `.local/postgres`;
  se apaga con la app y conserva los datos. Con `DATABASE_URL` usa tu servidor PostgreSQL.
- Al arrancar se crean las tablas que falten (`DB_AUTO_CREATE=true`); `python -m db.init` hace lo mismo
  a mano. La actualización de perfiles amplía explícitamente el CHECK de origen de movimientos para admitir `perfil`; conserva los registros existentes.
- Sin clave de IA la app funciona (cuentas, demo, quizzes publicados, retos verificables, Coins,
  reportes y resúmenes ya guardados), pero no transcribe, no genera resúmenes nuevos, no pregenera quizzes ni califica respuestas abiertas.
- `.env.example` documenta todas las variables. `/health` informa base de datos y estado de la IA.

### Cuentas de demostración (`DEMO_MODE=true`)

Al arrancar se crean dos cursos con su malla —«Python para Análisis de Datos» (10 temas) y
«Especialización en Big Data» (8 temas)— y estas cuentas ficticias (contraseña: `DEMO_PASSWORD`, o
`cuadrilla` si no está definida):

| Rol | DNI | Nombre | Cursos |
|---|---|---|---|
| Alumna | `70000001` | Lucía Torres | Python y Big Data |
| Alumnos | `70000002`–`70000004` | Diego, Valeria, Andrés | Python y Big Data |
| Alumnos | `70000005`–`70000006` | Camila, Mateo | Python |
| Docente | `20000001` | Fernanda Ríos | Python |
| Docente | `20000002` | Ricardo Paredes | Big Data |
| Administrador | `10000001` | Admin DMC | Todos |

En **Administración → Cargar datos de demostración** se crean, sin llamar a la IA:
- Python: la clase 1 publicada (retos escritos a mano a partir del transcript de la master class), la
  clase 2 por validar (con su hora corriendo) y práctica simulada de 4 alumnos (podio, reportes, una
  alumna en riesgo). Lucía tiene pendiente el quiz de la clase 1.
- Big Data: la clase 1 publicada y el quiz ya resuelto por Lucía, Diego y Valeria hace tres días, así
  que tienen repasos vencidos.

También se puede ejecutar `python -m db.demo`. Mateo (`70000006`) nunca entró: sirve para ver el aviso
de consentimiento.

### Mis cursos

El alumno ve todos sus cursos en **Mis cursos** (`/alumno`): EXP y puesto del podio de cada curso, temas
dominados, quizzes completados, pendientes (quizzes nuevos o en curso, repasos para hoy, reto semanal)
y la siguiente acción sugerida. Los cursos cerrados pasan a «Finalizados». Dentro de un curso, el menú
agrupa Clases, Mi progreso y Podio de ese curso, y un selector permite cambiar de curso. Las DMC Coins
son de la cuenta y se acumulan entre cursos; el historial indica de qué curso viene cada movimiento.

En producción: `DEMO_MODE=false` y `ADMIN_DNI` + `ADMIN_PASSWORD` en el `.env` para el primer administrador.

## Pruebas

```sh
uv run python -m unittest discover -s tests -v
```

No necesitan base de datos ni claves. Usan `TEST_DATABASE_URL` si existe; si no, una PostgreSQL embebida
en un directorio temporal, siempre en un *schema* propio que se elimina al terminar. Los trabajos en
segundo plano corren en línea y **toda conexión de red que no sea local queda bloqueada**: la IA se
simula con un modelo de chat falso de LangChain (`tests/falso_llm.py`), y `tests/test_proveedores.py`
ejercita las integraciones reales de OpenAI y Gemini interceptando su transporte HTTP. Incluyen los
ejemplos numéricos de los documentos, el flujo completo del quiz por HTTP, la prueba automática de
privacidad de HU-44 y concurrencia real en el canje de Coins.

## Arquitectura

```
config.py        variables de entorno (LLM_MODEL, DEMO_MODE, ADMIN_DNI…)
main.py          app FastAPI, cabeceras de seguridad, tarea periódica (publicación a la hora, reintentos)
auth/            DNI + contraseña (scrypt), sesiones en base de datos, CSRF, permisos por rol y curso
rules/           motor de reglas puro: niveles, EXP, Coins, dominio, repaso, calendario Lima, canje,
                 riesgo, mensajes. Sin IA ni base de datos; parámetros con valores documentados
services/        casos de uso: malla, clases, validación docente, quiz, reto semanal, movimientos,
                 progreso, reportes, riesgo, bandeja de revisión, canje, administración, parámetros
ai/              IA con LangChain: proveedores.py (OpenAI o Gemini, por configuración), llm.py (única
                 llamada al modelo: privacidad, salida estructurada, registro), anonimización, prompts de
                 los apéndices del AI behavior spec, transcripción y trabajos en hilos
db/              modelo de datos (tablas en español, §3 de la especificación), PostgreSQL embebida, seed y demo
web/             rutas y vistas Jinja2 por rol: alumno, docente, administrador
templates/       HTML renderizado en servidor; static/ con CSS propio y JS sin dependencias
```

Regla de oro (PRD §8): el modelo nunca decide puntos, niveles, fechas, EXP ni Coins. Solo genera retos,
genera resúmenes, propone mapeos y rúbricas, y califica respuestas abiertas con un resultado estructurado; el backend
calcula todo lo demás.

## Qué se implementó (PRD, módulos M1–M10)

| Módulo | Implementación |
|---|---|
| M1 Malla y clases | Carga de malla CSV/JSON/formulario con errores por fila; PDF con texto interpretado por IA y vista previa antes de guardar. Brochure PDF, propuesta de IA de nivel máximo, rúbrica de Maestría, temas fundamentales, módulos y lenguajes. Subida de clase (video/audio/transcript, recursos PDF/TXT, tarea), transcripción, anonimización, mapeo a la malla con evidencia y confianza, estados Procesando/Por validar/Publicada/Error con reintento, temas sin clase. Eliminación definitiva de clases por su docente o administrador, con vista previa y cuadro de confirmación; purga de archivos y datos asociados y reconstrucción del progreso. |
| M2 Retos y validación | 4 retos base con versiones Básico/Intermedio/Avanzado/Maestría, fuente, error común y 3 pistas; reto de conocimiento previo en la clase 1; panel con cuenta regresiva de 1 hora; aprobar, editar por versión, reemplazar (con reto propio) y rechazar (genera otro en la misma posición); retos propios (la IA completa los otros niveles); publicación automática al vencer la hora; ediciones tras publicar crean una nueva versión; auditoría; «Reportar error» (3 reportes retiran el reto). |
| M3 Quiz | «Generar» arma 3 retos de la clase (priorizando los temas más débiles del alumno) y 1 de REPASO; etiquetas CLASE n/REPASO y contador 1/3…3/3 (o 1/4…4/4); uno a la vez; reanuda en el mismo reto con sus pistas; sin cronómetro (el tiempo se guarda en silencio); 3 pistas graduales y solución solo tras la tercera o después de responder; confeti y serpentinas que respetan «reducir movimiento»; feedback en orden fijo; «No estoy de acuerdo»; pantalla final con desglose y podio; tareas con LISTO. |
| M4 Niveles | Nivel por alumno y tema desde Básico; ajuste dentro del quiz; nivel guardado con la regla de los últimos 5 (mínimo 3, ≥80 % sube, <50 % baja); techo por tema. |
| M5 Repaso | Agenda 1/3/7/14/30 días calculada por el backend; el repaso más vencido ocupa el reto de REPASO; el previo de la clase 1 no entra a la agenda. |
| M6 Reto semanal | Uno por curso y semana (lunes 00:00 hora Lima), sorteo ponderado, siempre verificable, un nivel por encima, un intento; temas no vistos no entran al dominio. Sin IA usa un reto aprobado del banco. |
| M7 EXP, podio, Coins | Movimientos únicos por alumno, origen y referencia; valores del documento 06; podio top 5 en tiempo real; Mis Coins con canje 30–50 %; Coins manuales; cierre del curso con 120/90/60 y exportación del top 3. Eliminación definitiva administrativa separada del cierre, sin pago de podio. |
| M8 Reportes | Intentos con tema, nivel, resultado, pistas, tiempo oculto y error; dominio y estados; Mi progreso; reporte por clase (participación siempre visible, mínimo de 5 alumnos para «dominado por la clase», errores frecuentes, ranking) y por alumno (incluye «No visto»). |
| M9 Riesgo y revisión | Inactividad o caída de dominio con motivo y «Contactado»; bandeja con reclamos, anomalías (respuestas muy rápidas, perfecto repentino) y errores reportados; nada se castiga automáticamente. |
| M10 Acceso y privacidad | DNI y contraseña, roles y permisos por curso, consentimiento en el primer ingreso, la IA solo ve un alias; prueba automática de que ninguna llamada lleva DNI, nombres ni contactos; registro de llamadas sin datos personales y tokens por componente; parámetros configurables con historial; cuadro de confirmación compartido para las eliminaciones y retiros. |

### Decisiones de interpretación

- **Feedback de retos verificables**: se arma al instante con la explicación, el error común y las
  pistas del propio reto (la especificación pide respuesta «casi inmediata»). La IA califica y redacta
  el feedback de las respuestas abiertas en una sola llamada estructurada.
- **Nivel guardado**: el porcentaje de aciertos usa el puntaje del intento (100/50/0, ×0,5 con pistas).
- **Dominado por la clase**: al menos 5 alumnos con datos y la mitad o más en estado «Dominado».
- **Reto semanal de nivel Básico** (tema con máximo Básico): paga como Intermedio (5 Coins).
- **Anonimización**: por reglas (correos, teléfonos, DNI, nombres registrados, nombres comunes y nombres
  presentados en el habla). La guardia de privacidad bloquea cualquier llamada que aún contenga datos.
- **Proveedor y modelo**: `LLM_PROVIDER` (`openai` o `gemini`) y `LLM_MODEL`; por defecto `gpt-6-luna`
  (el «luna» de la documentación) o `gemini-3.8-flash`. Ver «IA con LangChain» más abajo.

### Pendiente (P1 no incluido)

- Retos de código con casos de prueba y su entorno aislado de ejecución (RF-17, RF-67): el generador
  no produce retos de código; en cursos técnicos usa «completar» sobre una línea de código.
- Generación de variantes cuando un tema agota su banco (RF-16): el repaso ya evita repetir retos
  vistos hace menos de 30 días cuando hay alternativas.

## IA con LangChain

Todos los componentes (mapeador, generador, calificador con feedback y proponedor) llaman a
`ai/llm.py`, que pide a `ai/proveedores.py` un modelo de chat de LangChain y usa
`with_structured_output(..., method="json_schema")`: en OpenAI se traduce a `response_format` con
`json_schema` estricto y en Gemini a `responseJsonSchema`. La respuesta se vuelve a validar con los
modelos Pydantic de `ai/schemas.py`, y cada llamada pasa por la guardia de privacidad y queda registrada
(componente, `proveedor:modelo`, tokens) sin datos personales.

- **Cambiar de proveedor**: `LLM_PROVIDER=gemini` + `GOOGLE_API_KEY` (o `openai` + `OPENAI_API_KEY`).
- **Transcripción**: OpenAI usa su endpoint de transcripción (`gpt-4o-mini-transcribe`); Gemini recibe el
  audio en el modelo de chat multimodal vía LangChain. `TRANSCRIPTION_PROVIDER` permite mezclarlos.
- **Agregar otro proveedor** (por ejemplo Anthropic): una función en `FABRICAS` y otra en
  `TRANSCRIPTORES` de `ai/proveedores.py`, más su clave en `config.PROVEEDORES_IA`. Nada más cambia.
- `LLM_REASONING_EFFORT` se envía como `reasoning_effort` (OpenAI) o `thinking_level` (Gemini).

## Base de datos

Las tablas tienen nombres en español (`usuarios`, `cursos`, `temas`, `clases`, `retos`, `intentos`,
`movimientos`…). Si usas una base que viene del MVP anterior, sus tablas en inglés (`students`,
`classes`, `coin_ledger`, etc.) no se modifican ni se borran: quedan sin uso.

Un solo proceso: los trabajos de IA corren en hilos del proceso y una tarea periódica publica las clases
cuya hora venció (también se aplica al abrir cualquier página del curso).

Los resúmenes de clase son una ampliación solicitada el 15 de octubre de 2026. Ver [funcionamiento y verificación](../../documentacion/resumenes-clase-ia.md).

Los perfiles académicos y profesionales se consultan desde el avatar y permiten editar doce campos. Los alumnos reciben una única Coin por cada dos campos completados, hasta seis. Ver [perfiles y Coins](../../documentacion/perfiles-y-coins.md).

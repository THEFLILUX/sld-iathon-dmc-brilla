# Vertex AI y selección administrativa de modelos · 15 de octubre de 2026

**Modelo vigente: `gemini-3.8-flash`, para texto y transcripción.** Ver la [actualización a Gemini 3.8 Flash](gemini-3-8-flash.md).

Administración → **IA y modelos** permite seleccionar OpenAI con la API key del servidor o Gemini mediante Vertex AI. El modelo inicial de Vertex es **`gemini-3.8-flash`**, usado para texto y transcripción. OpenAI conserva `gpt-6-luna` y `gpt-4o-mini-transcribe` como valores iniciales. Los identificadores se pueden editar sin modificar código.

**Probar conexión** comprueba una respuesta estructurada y la transcripción de una frase fija, sin enviar registros académicos. **Probar y activar** exige ambas comprobaciones antes de guardar. Una comprobación fallida conserva el proveedor anterior. Los botones que consumen IA muestran Brilla. Las claves no tienen campos en el formulario: OpenAI se configura en el entorno y Vertex utiliza credenciales de Google Cloud (ADC).

## Configuración y alcance

- `configuraciones_ia` es un historial de revisiones con proveedor, identificadores, administrador y fecha de verificación, sin credenciales. La última revisión gobierna las nuevas solicitudes. Control de versión y bloqueo transaccional impiden que un formulario obsoleto sobrescriba otro cambio.
- `ai/runtime.py` carga una instantánea por solicitud y trabajo. `ContextVar` mantiene la misma configuración durante las llamadas y reintentos de un trabajo activo. El cambio de proveedor no reinicia el servidor ni vuelve a generar contenido existente.
- Todos los componentes mantienen el punto central `ai/llm.py`: mapeo a malla, generación/reemplazos/niveles/semanales, evaluación y feedback, propuestas, extracción de malla PDF, resúmenes y Asistente Brilla. La transcripción selecciona el mismo proveedor activo; OpenAI usa su endpoint de audio y Vertex usa entrada multimodal a través de LangChain.
- Vertex se construye con `ChatGoogleGenerativeAI(vertexai=True, credentials=ADC, project=…, location=…)`. La integración instalada `langchain-google-genai` 4.4.2 ya incorpora este backend. `google-auth` se declara como dependencia directa; no se requiere `langchain-google-vertexai` ni claves JSON de cuentas de servicio.
- Cada llamada registra proveedor/modelo/tokens/resultado sin prompts personales. Se conservan anonimización, guardias de privacidad y validación de esquemas. No hay sustitución silenciosa entre proveedores ante errores.
- Sin revisión administrativa se respetan los valores iniciales del entorno, incluida la compatibilidad previa con Gemini Developer API. La selección web es OpenAI o Vertex AI.

## GCP

Proyecto `project-ea6ff772-6759-45ec-925`, API `aiplatform.googleapis.com`, ubicación `global`, cuenta de servicio `aula-virtual-ia` con rol `roles/aiplatform.user`. La identidad se asigna a la VM y el contenedor obtiene credenciales temporales del servicio de metadatos. No se genera ni descarga una clave de cuenta de servicio.

Variables: `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION=global`, `VERTEX_MODEL=gemini-3.8-flash`. Se preserva `OPENAI_API_KEY`. En desarrollo local, ADC se puede configurar mediante `gcloud auth application-default login`; la web pública utiliza la identidad de su VM.

## Verificación inicial de la integración (Gemini 3.5 Flash-Lite)

188 pruebas aprobadas: las 175 previas y 13 nuevas. Cobertura de transporte real de LangChain interceptado, OAuth de Vertex sin API key, ocho contratos de salida, audio multimodal, permisos/CSRF, activación y reversión, errores de conexión, historial sin secretos, formularios obsoletos, concurrencia y configuración estable durante trabajos.

Publicado y verificado en GCP: 22 archivos comprobados por hash, 15 vistas/permisos por HTTPS, tres activaciones reales Vertex → OpenAI → Vertex con comprobación de texto y audio en cada una. Siete componentes reales adicionales funcionaron: mapeador, generador, calificador, proponedor, importador de malla, resumidor y asistente docente. Las 13 llamadas registradas fueron correctas; Asistente Brilla respondió en 2,41 segundos en esta comprobación puntual. No es una prueba de carga. Huellas de las 27 tablas anteriores idénticas; solo se añadieron revisiones de configuración, uso técnico y sesiones de comprobación que se cerraron.

Proveedor al terminar esa verificación inicial: **Vertex AI · gemini-3.5-flash-lite**, también para transcripción; posteriormente sustituido por Gemini 3.8 Flash. La VM quedó RUNNING y la aplicación/base saludables. Se mantuvieron IP, URL y credenciales previas de OpenAI. Fue necesario detener/iniciar la VM para asignar la cuenta de servicio; el directorio temporal se limpió durante el arranque y se volvieron a copiar los archivos de despliegue antes de aplicar la versión final. Chrome: escritorio, 390 y 320 px sin desbordamientos, botones de 50 px, activación y notificación flotante con equis. Entorno local de revisión cerrado y viewport restaurado. Evidencias privadas en `.local/deploy-gcp/vertex-verification.json`.

Referencias: [Gemini 3.5 Flash-Lite](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash-lite?hl=en), [integración de LangChain](https://docs.langchain.com/oss/python/integrations/chat/google_generative_ai).

# Gemini 3.8 Flash

El modelo de Gemini vigente es **`gemini-3.8-flash`**, tanto para las respuestas de texto como para
la transcripción de audio y video. Vertex AI utiliza la ubicación `global` y las credenciales
temporales de la cuenta de servicio de la VM a través de LangChain.

## Configuración y activación

Administración → **IA y modelos** permite probar y activar esta selección sin reiniciar la web.
Antes de guardar, la aplicación comprueba una respuesta estructurada y la transcripción de un audio
fijo sin información de alumnos. Una activación fallida conserva la configuración anterior.
Las solicitudes nuevas usan la revisión activada; los trabajos ya iniciados conservan su instantánea.

Los valores iniciales de `config.py` y `.env.example` también seleccionan Gemini 3.8 Flash para Vertex
y para la API directa de Gemini. Una selección previa guardada en PostgreSQL tiene prioridad sobre
esos valores: en otra instalación debe activarse el modelo desde Administración.

OpenAI sigue disponible en el selector con sus modelos y su API key del servidor. Las revisiones
históricas y el contenido ya generado conservan su procedencia; cambiar el modelo no regenera clases,
quizzes, resúmenes o calificaciones existentes.

## Verificación en GCP

La activación mediante el formulario administrativo verificó texto estructurado y transcripción
con Gemini 3.8 Flash. La página de configuración mostró la nueva selección y `/health` respondió
200. Las huellas de las 27 tablas académicas coincidieron antes y después; se conservó el historial
de configuración y se cerró la sesión administrativa de comprobación.

La actualización utiliza la integración de LangChain ya instalada. No requiere cambiar SDKs ni
reiniciar la VM para activar el modelo.

Referencia: [Gemini 3.8 Flash en Google Cloud](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-flash).

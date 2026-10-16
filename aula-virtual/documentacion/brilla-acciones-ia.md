# Brilla: indicador de acciones con IA

Se usa la mascota del logo 01, «PRIMARY LOGO», de la lámina BRILLA proporcionada por el usuario, sin la palabra BRILLA. El PNG transparente conserva el rostro blanco opaco, los colores y la estrella; se sirve localmente desde `artifacts/cuadrilla/static/img/brilla-ai.png`.

## Presentación y comportamiento

La macro compartida `templates/_ai.html` muestra la mascota de 32 px y una etiqueta IA sobre una base blanca con borde sutil. Así se distingue en botones azules, blancos y de acciones de rechazo. Los botones tienen una altura mínima de 50 px y permiten que su texto ocupe varias líneas en pantallas pequeñas.

El mismo recurso aparece a 36 px en los encabezados de resúmenes de alumnos y docentes, y a 52 px en el encabezado del Asistente Brilla. Las URL del PNG y del CSS llevan una versión para que el navegador descargue el cambio.

El texto accesible y el tooltip identifican a Brilla y el uso de inteligencia artificial. El indicador corresponde a la acción, con independencia de que el proveedor seleccionado sea OpenAI o Gemini.

- Administrador: carga de malla y confirmación de una malla PDF, nuevas propuestas de IA y carga de brochure cuando solicita una propuesta.
- Docente: procesamiento y reintentos de clase, generación y reemplazo de retos, resúmenes y consultas al Asistente Brilla. Guardar un reto propio lleva el indicador cuando puede completar otros niveles con IA.
- Alumno: envío de respuestas abiertas cuya evaluación requiere IA.

Las pistas almacenadas, las respuestas verificables, las aprobaciones manuales y la navegación conservan sus botones habituales.

La mascota saluda brevemente al pasar el cursor o recibir foco. Al enviar un formulario válido pulsa suavemente mientras la petición está pendiente. No se anima cuando se cancela la confirmación; se restaura al volver con el navegador. La animación respeta `prefers-reduced-motion`. No se deshabilitan los botones con nombre/valor para conservar la acción enviada al servidor.

## Verificación visual

Revisión en Chrome a tamaño de escritorio y a 390 y 320 px: imágenes cargadas, botones de varios estilos legibles, textos largos adaptados y sin desbordamiento horizontal. Se comprobó también el encabezado del Asistente Brilla a 320 px. La revisión local usa una base aislada y un proveedor simulado.

## Preparación del recurso

Se usó la herramienta integrada `image_gen.imagegen` para aislar la mascota del PRIMARY LOGO de la lámina original y preparar el PNG transparente. No se generan imágenes durante el uso de la plataforma.

Prompt exacto de la edición:

```text
Use case: background-extraction. Asset type: production transparent mascot for website AI action buttons and section headings. Edit target: the supplied BRILLA brand sheet. Isolate ONLY the full-color three-dimensional mascot from the upper-left panel 01, PRIMARY LOGO; do NOT use panel 02 or the simplified flat logo. Preserve the existing primary mascot's exact friendly face, navy blue eyes and mouth, pale opaque white face, cyan and blue glossy droplet body, yellow-tipped swept crest, both arms, golden four-point sparkle and small cyan/yellow accent strokes. Remove the word BRILLA completely, all typography and headings, the pale panel background, borders, and every other logo. Keep the mascot white face and eye highlights opaque, with genuine transparent background and all outer negative space transparent. Preserve original identity, pose, colors, shading and proportions; no redesign. Deliver one centered mascot and its sparkle, tightly framed together at near-full canvas size with only a small 3% transparent margin, clean smooth edges suitable at 32px. No text, no badge, no enclosing square, no panel, no broad cast shadow or glow. The golden sparkle and all appendages must fit completely inside the canvas.
```

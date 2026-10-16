# Brilla: indicador de acciones con IA

Se eligió únicamente el logo 06, «Simplified icon», de la lámina BRILLA proporcionada por el usuario. El PNG transparente se sirve localmente desde `artifacts/cuadrilla/static/img/brilla-ai.png`.

## Comportamiento

La macro compartida `templates/_ai.html` muestra la mascota de 24 px y una etiqueta IA en el botón. El texto accesible y el tooltip identifican a Brilla y el uso de inteligencia artificial. El mismo recurso identifica OpenAI y Gemini; no depende de una marca de proveedor.

- Administrador: Cargar malla, Confirmar y guardar malla PDF y Volver a pedir la propuesta a la IA. Subir brochure se marca si el curso ya tiene temas y la IA está configurada, porque entonces solicita una nueva propuesta.
- Docente: Procesar clase, Reintentar procesamiento, Generar otro reto y rechazar un reto que generará un reemplazo. En la bandeja de revisión se conserva el valor del botón Rechazar y reemplazar.
- Guardar reto propio muestra el indicador cuando el tema permite completar otros niveles con IA. Se actualiza al seleccionar otro tema y no aparece para un tema exclusivamente básico.
- Alumno: Enviar una respuesta de tipo Definir o Caso, cuya evaluación usa IA.

Las pistas almacenadas, la selección del quiz a partir del banco existente, las respuestas verificables, las aprobaciones manuales y la navegación conservan sus botones habituales.

El icono saluda brevemente al pasar el cursor o recibir foco. Al enviar un formulario válido pulsa suavemente mientras la petición está pendiente. No se anima cuando se cancela la confirmación; se restaura al volver con el navegador. La animación respeta `prefers-reduced-motion`. No se deshabilitan los botones con nombre/valor para conservar la acción enviada al servidor.

## Verificación

122 pruebas aprobadas, incluyendo cinco nuevas comprobaciones de marcadores por rol, proveedor y tipo de respuesta. Revisión visual en Chrome a tamaño de escritorio y 390 px, sin desbordamiento; comprobación del estado ocupado y del indicador condicional del reto propio. Pruebas en base aislada y con proveedor simulado, sin llamadas pagadas de IA.

## Preparación del recurso y prompts

Se usó la herramienta integrada `image_gen` (no CLI) para aislar el logo seleccionado de la lámina y preparar su transparencia. Originales conservados fuera del repositorio; la segunda salida es el recurso final. No se usa generación de imágenes en tiempo de ejecución de la plataforma.

Prompt de extracción:

```text
Use case: background-extraction. From the supplied BRILLA brand sheet, isolate ONLY the blue flat mascot in panel 06, labeled SIMPLIFIED ICON, in the lower right. Preserve its exact existing silhouette, smiling facial features, droplet crest, side arm, separate sparkle and short accent strokes. Keep the flat bright blue identity, approximately #0068FF; do not use the 3D mascot or any other variant. Remove the pale panel background, headings, borders, lettering and all other panels. Deliver a single centered, tightly framed, high resolution transparent PNG of that same simplified mascot and its sparkle. The face and all negative space must also be fully transparent, not white or pale blue. Clean crisp edges; no added shadow, no new details, no text, no container. This is a small button icon asset.
```

Prompt final de limpieza (edición de la primera salida):

```text
Clean up this exact blue BRILLA simplified mascot cutout for production as a small UI icon. Preserve the shape, placement, face and separate sparkle/accents exactly. Make every blue shape uniformly solid #0068FF with crisp antialiased edges. Remove ALL tiny stray blue pixels, speckles, texture, noise and edge artifacts, especially inside the face, crest cutout and surrounding negative space. All negative space and background fully transparent. No pale or white fills, no text, no shadows, no gradients, no new shapes. Center and tightly frame the existing mascot with a small transparent margin.
```

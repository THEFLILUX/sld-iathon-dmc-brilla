# Resúmenes de clase con IA · 15 de octubre de 2026

Ampliación solicitada por el usuario: además del quiz, el alumno recibe material de repaso generado a partir del transcript. Esta solicitud sustituye la exclusión de resúmenes del alcance documental del 13 de octubre.

## Uso

- En el curso del alumno, el recuadro **Resúmenes de clase** está debajo de **Quizzes de clase** y encima de **Tareas**, con 16 px de separación. Identificación de Brilla e IA, una entrada por clase y apertura/cierre mediante controles nativos accesibles con teclado.
- Cada resumen incluye una introducción, secciones explicativas y puntos para recordar. Solo aparecen clases publicadas del curso en el que el alumno está inscrito; no requiere completar el quiz ni consume Coins.
- El botón del quiz completado se llama **Ver resultados**, para distinguirlo del resumen del contenido de la clase.
- El docente puede leer el mismo resumen dentro de su clase antes de publicarla. Si falla su generación, tiene **Reintentar resumen**, con la mascota de Brilla. La ruta exige rol, asignación al curso y CSRF.
- Un video/audio primero se transcribe; un TXT/MD/VTT o texto pegado se usa como transcript. Después de anonimizarlo se programa el resumen. Los alumnos lo ven al publicarse la clase.

## Implementación

- `ai/summaries.py` utiliza el mismo proveedor configurado mediante `ai/llm.py`: OpenAI con la clave del servidor en la demo; compatible con Gemini por configuración. No se envía ninguna clave al navegador.
- Esquema Pydantic estricto: introducción, secciones y puntos clave. Se pide resumir lo académico, excluir publicidad y datos personales y distinguir las demostraciones de las herramientas apenas mencionadas. No utiliza respuestas de alumnos ni soluciones de los quizzes como fuente.
- Se procesa el transcript completo. Las sesiones largas se dividen en fragmentos de hasta 60 000 caracteres y se consolidan jerárquicamente; no se descarta el final ni se usa únicamente el texto inicial.
- Tanto entradas como salidas pasan por anonimización; las llamadas conservan la guardia de privacidad. Jinja escapa los textos generados: no se admite HTML ejecutable.
- Nueva tabla `resumenes_clase`, con FK a la clase y contenido JSON, estado, modelo, intentos, error seguro y fecha. Se crea al arrancar con `DB_AUTO_CREATE`; no se alteran las columnas existentes.
- Un resumen compartido por clase. Abrirlo no llama a la IA. Se reserva dentro de una transacción y se encola tras confirmar, con el mismo bloqueo de curso que protege el trabajo frente a las eliminaciones.
- La generación se ejecuta independientemente del mapeo y del quiz. Un error en cualquiera de estos procesos no invalida los resultados del otro. Hasta tres intentos automáticos, separados cinco minutos; después puede reintentar el docente.
- Al arrancar, recupera trabajos interrumpidos y programa resúmenes faltantes de transcripts existentes. El temporizador completa los pendientes en lotes de diez.
- La eliminación definitiva de clase/curso incluye el resumen y sus registros de IA. Un trabajo en cola comprueba que la clase y la reserva siguen existiendo y no reconstruye información borrada. Los respaldos históricos siguen el alcance aprobado por el usuario.

## Verificación

150 pruebas aprobadas, con PostgreSQL temporal y sin red externa. Incluyen nueve casos nuevos de publicación y permisos, anonimización, generación única, fallos independientes, reintentos limitados, recuperación, cobertura del final de un transcript largo, HTML escapado y eliminación completa. El esquema nuevo también se probó con los transportes simulados de OpenAI y Gemini.

Revisión visual con alumno y docente ficticios: escritorio, 390 px y 320 px; sin desplazamiento horizontal; separación de 16 px antes y después del nuevo recuadro; apertura/cierre con Enter/Espacio y contenido legible. Se cerraron las sesiones y el servidor aislado.

La calidad pedagógica sigue dependiendo del transcript y del modelo. El resumen no sustituye la clase ni supone que una herramienta mencionada se haya enseñado en profundidad.

## Publicación en GCP

Publicado el 15 de octubre: 18 archivos verificados por hash y 17 pantallas por HTTPS con validación TLS desde GCP. Las ocho clases con transcript existente tienen su resumen listo, generado con `openai:gpt-6-luna`. Se compararon clases, cursos, usuarios y movimientos con sus huellas previas: no cambiaron. Clave y configuración del servidor conservadas; base de datos y aplicación saludables. La verificación de páginas no hizo solicitudes adicionales de IA.

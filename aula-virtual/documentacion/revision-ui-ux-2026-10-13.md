**Revisión UI/UX de Cuadrilla, 13 de octubre de 2026.** El producto vigente busca refuerzo breve, sin culpa y desde el celular. La UI debe ayudar a elegir la próxima práctica, conservar el trabajo del alumno y convertir los datos del docente en acciones. La presente revisión identifica mejoras; no las implementa ni modifica reglas pedagógicas o de premios.

Se contrastaron los seis documentos de producto con el código actual y los recorridos de alumno/docente/administrador. Las 101 pruebas Python existentes pasaron. Se inspeccionaron visualmente en Chrome el login, Mis cursos, un curso y el primer reto con datos ficticios en una PostgreSQL aislada y sin llamadas a proveedores reales. Las pantallas docentes se revisaron mediante HTML renderizado y código. La revisión visual móvil no se completó por pérdida del acceso a Chrome; sus recomendaciones proceden del CSS y necesitan validación visual posterior.

**Fuentes de producto.**

- [Brief de producto](01_Brief_de_Producto.docx.pdf): usuario con poco tiempo, foco en repaso y práctica sin presión.
- [PRD](02_PRD.docx.pdf): módulos M1–M10, principios y prioridades.
- [Especificación funcional](03_Especificacion_Funcional.docx.pdf): pantallas A1–A8, D1–D8 y estados de borde.
- [Historias de usuario](04_User_Stories.docx.pdf): especialmente HU-14, HU-16, HU-24, HU-30 y HU-35.
- [AI behavior spec](05_AI_Behavior_Spec.docx.pdf): feedback breve, pistas graduales y pendiente sin penalidad.
- [EXP y Coins](06_Sistema_de_EXP_y_Coins.docx.pdf): fórmula de premios y confirmación de canje.

Prioridad sugerida: **P0** corrige información visual falsa o pérdida de trabajo; **P1** reduce fricción en el recorrido principal; **P2** mejora comprensión, accesibilidad y operación al crecer. Son prioridades de esta revisión, independientes de las P0/P1 del PRD.

| ID | Prioridad | Mejora | Evidencia |
|---|---|---|---|
| UX-01 | P0 | Corregir barras de progreso | Confirmado visualmente: Python dice 0 de 1 y muestra la barra llena |
| UX-02 | P0 | Conservar borradores al pedir pista, salir o volver | Confirmado: seleccionar una alternativa y pedir pista borra la selección |
| UX-03 | P1 | Hacer comprensible el acceso a repasos pendientes | Confirmado en Mis cursos y código: tres temas por repasar, CTA de reto semanal |
| UX-04 | P1 | Explicar las pistas antes de usarlas y alinear el texto con la fórmula de Coins | Confirmado: la advertencia aparece solo después de la primera pista |
| UX-05 | P1 | Unificar la siguiente acción y la presentación del puesto | Confirmado: Hacer quiz abre el curso; puesto vacío en tarjeta y #6 dentro con 0 EXP |
| UX-06 | P1 | Convertir Mi progreso en una guía de práctica | Plantilla: tabla de estados y fechas sin acción por tema |
| UX-07 | P1 | Agilizar validación docente y proteger ediciones | HTML/código: cuatro tarjetas extensas y recargas completas |
| UX-08 | P1 | Mejorar seguimiento de evaluaciones pendientes y reclamos | Plantillas: resultado pendiente y resumen sin acceso detallado al reto |
| UX-09 | P2 | Aumentar legibilidad y tamaño táctil | CSS: texto de navegación 10.5 px, botones pequeños 34 px, blanco/cian 2.23:1 |
| UX-10 | P2 | Completar la experiencia de canje y estados de Coins | Plantilla: confirmación previa existe; falta explicar uso posterior del descuento |
| UX-11 | P2 | Separar mensajes docentes de detalles de configuración | HTML: OPENAI_API_KEY y .env visibles en Subir clase |
| UX-12 | P2 | Escalar reportes, bandeja y seguimiento docente | Plantillas: listados extensos sin filtros/búsqueda/paginación y contacto binario |

**UX-01 — Barras de progreso.** En Mis cursos, Big Data (1/1) y Python (0/1) muestran barras igualmente llenas. La plantilla usa `style="width:...%"`, pero `main.py` envía `style-src 'self'`: los atributos de estilo quedan bloqueados. El span es un bloque sin ancho autorizado y ocupa el ancho completo. Otros estilos inline de separación, flex, anchura y ocultación visual pueden verse afectados. Cambiar las barras a un elemento nativo o a un mecanismo compatible con la CSP; trasladar estilos estáticos a clases. No hace falta debilitar la CSP para corregir la interfaz. Verificar visualmente 0%, valores intermedios y 100%, además de su texto accesible.

Referencias: `templates/student/courses.html:24`, `templates/student/progress.html`, `main.py:84`, `static/css/dmc.css:129`.

**UX-02 — Respuestas en borrador.** Reproducción: iniciar quiz de Python, seleccionar «Extraer (traer) los datos», pulsar Pedir pista. Se recarga el documento, todas las opciones quedan sin marcar y Enviar vuelve a estar deshabilitado. El formulario de pista no lleva la respuesta del formulario de envío. El mismo diseño pone en riesgo el texto de una respuesta abierta y no persiste borradores al salir. Conservar un borrador por usuario/quiz/item; distinguirlo de un intento evaluado. Considerar límites de privacidad y limpieza de datos también en borradores. Verificar alternativas y texto tras pista, navegación y recarga; no crear EXP, Coins ni intentos por guardar un borrador.

Referencias: `templates/student/reto.html:35`, `templates/student/_answer.html`, `web/student.py`, `static/js/quiz.js`.

**UX-03 — Repasos.** En la tarjeta Big Data, Lucía tiene tres temas por repasar y todos los quizzes completados; la acción principal es Hacer el reto semanal. `_siguiente(..., repasos)` recibe el número de repasos, pero no lo usa. La agenda se consume en el siguiente quiz de clase, no en una sesión independiente. Mostrar qué temas se repasarán y aclarar «Se incluirán en tu siguiente quiz» si esa continúa siendo la regla. Una sesión autónoma de repaso sería una decisión de producto que requiere definir su relación con el quiz fijo y los premios; no añadirla silenciosamente como cambio visual. Verificar el caso sin quizzes nuevos y evitar contar como acción inmediata algo que el alumno no puede iniciar.

Referencias: `services/cursos_alumno.py:30`, `templates/student/courses.html:30`, `services/quiz.py:_repaso`, HU-24.

**UX-04 — Pistas y premios.** Antes de la primera pista no se explica su efecto; después aparece «mitad de EXP y no cuenta para Coins». Colocar una explicación breve antes de usarla, con un tono que invite a aprender: «Puedes pedir ayuda; con pistas ganas la mitad del EXP de este reto». No añadir una confirmación modal en cada pista. Precisar la regla Coins: el código y el documento 06 calculan un promedio de verificables con puntaje reducido a la mitad con pistas. Por ejemplo, dos aciertos sin pistas y uno con pistas dan 83.33 y pueden alcanzar Coins. Las frases «sin pistas» o «no cuenta» se prestan a interpretar una exclusión absoluta, diferente de ese promedio. Alinear el texto y dar en el resumen una explicación del premio o de por qué no se obtuvo. No cambiar la fórmula para acomodar el copy.

Referencias: `templates/student/reto.html:45`, `templates/student/_feedback.html:20`, `templates/student/coins.html`, `rules/scoring.py:puntaje_quiz`, documento 06 §3.2.

**UX-05 — Siguiente acción y contexto.** La tarjeta dice Hacer el quiz de la clase 1, pero abre el curso, donde aún hay que pulsar Generar. Mantener el vocabulario exigido por la especificación, añadir «4 retos · sin cronómetro» y hacer coherente el destino con la promesa del botón; no iniciar un quiz con un GET que mute datos. También unificar la política de puesto con cero EXP: la tarjeta muestra —, mientras el curso muestra #6. Puede ser «Aún sin puesto» con una invitación a comenzar, o un puesto en ambas pantallas. Mantener una acción principal por contexto y reducir accesos duplicados en sidebar/tarjeta/bloque de accesos cuando dificulten elegir.

Referencias: `services/cursos_alumno.py:35`, `templates/student/courses.html:35`, `templates/student/course.html`, `services/ledger.py:puesto`.

**UX-06 — Progreso accionable.** Mi progreso presenta dominio, nivel y fecha, pero no conduce desde un tema a la práctica correspondiente. Abrir con una recomendación concreta («En tu próximo quiz repasarás X»), agrupar por Hoy / En progreso / Dominados / Sin datos y explicar «No visto» frente a «Sin datos». Ofrecer acción únicamente si existe una actividad que se puede iniciar; para lo demás, explicar disponibilidad. Preservar los requisitos de dominio y la ausencia de asistencia implícita. Verificar alumno nuevo, tema visto sin intentos, repasos vencidos y curso cerrado.

Referencia: `templates/student/progress.html`, `services/progress.py`, HU-35.

**UX-07 — Validación docente.** Los cuatro retos muestran fuente, error común, variantes, pistas y acciones en una página larga. Proponer un resumen «2 de 4 revisados», navegación entre retos, encabezado con tiempo/publicación que permanezca visible y comparación de versiones o cambios. Mantener el acceso a fuentes y a todas las versiones en el mismo panel. `teacher.js` recarga al vencer el plazo sin comprobar cambios sin guardar; `ui.js` recarga si el foco no está en un campo, aunque puedan existir datos modificados. Actualizar estados y contador de forma parcial, proteger borradores y comunicar claramente qué versión quedó publicada. Conservar publicación automática a una hora: cualquier suspensión del plazo sería un cambio funcional separado.

Referencias: `templates/teacher/class.html`, `templates/teacher/_version_form.html`, `static/js/teacher.js`, `static/js/ui.js:43`, HU-05/HU-06.

**UX-08 — Resultados y revisiones pendientes.** Los mensajes de pendiente ya dicen que no hay penalidad, pero el resumen final muestra filas de retos sin abrir el feedback individual. Un estado de evaluación o reclamo debería poder consultarse después: actividad, respuesta, estado y resultado corregido. Mostrar avisos internos cuando cambie el resultado y explicar deltas de EXP. Verificar fallo del proveedor, resultado tardío y reclamo resuelto sin repetir premios. Respetar que la respuesta no se penaliza por fallo del proveedor.

Referencias: `templates/student/_feedback.html`, `templates/student/final.html`, `templates/teacher/review.html`, `services/attempts.py`.

**UX-09 — Legibilidad y móvil.** El contraste calculado entre blanco y cian #00BFD7 es 2.23:1, usado en etiquetas pequeñas; usar texto oscuro o un fondo más oscuro. La navegación usa 10.5 px y `.btn-sm` permite 34 px de alto; ampliar texto importante y superficies táctiles, especialmente pista, salir y acciones docentes. Durante el quiz, mantener visible el camino de regreso sin dispersar con todas las secciones del producto; evaluar una presentación enfocada y conservar accesibilidad. El menú móvil cierra con Escape, pero no gestiona el foco al abrir ni lo limita al panel: revisar navegación con teclado. Validar posteriormente 360/390 px, zoom de texto, teclado móvil, lectores de pantalla y reducir movimiento; no afirmar que esas pruebas ya se realizaron.

Referencias: `static/css/dmc.css:50`, `:84`, `:117`, `:287`, `templates/base.html`, `static/js/ui.js`.

**UX-10 — Coins y canje.** Ya existe confirmación con descuento, coste y saldo restante; conservarla. Mostrar progreso hacia el primer canje, alternativas alcanzables y explicar cómo se utiliza un canje confirmado (referencia/estado/instrucción de administración), sin prometer integración comercial que no existe. La acción Canjear Coins preselecciona el mayor porcentaje alcanzable: preferir una elección explícita o destacar claramente la selección antes de confirmar. Verificar 599/600/890/1000 Coins, saldo residual y pantalla posterior. Ninguna revisión visual debe consumir Coins reales.

Referencia: `templates/student/coins.html`, `web/student.py`, documento 06 §4.

**UX-11 — Mensajes por rol.** La pantalla docente de carga expone nombres de variables y `.env`. Mostrar al docente «La IA no está disponible; avisa a administración. Puedes guardar la clase y procesarla después». Dejar los detalles técnicos en administración/diagnóstico. Añadir ayuda de acceso o contacto de soporte en login y, si se implementa, mostrar/ocultar contraseña. Mantener las cuentas demo claramente separadas de acceso real y no mostrar claves personales.

Referencias: `templates/teacher/upload.html`, `templates/auth/login.html`.

**UX-12 — Operación al crecer.** Añadir búsqueda por alumno/tema, filtros por estado y curso, orden por prioridad/antigüedad, contadores de pendientes y paginación en reportes y bandeja. Separar pendiente de atendido. «Contactado» registra una acción, pero un seguimiento útil puede necesitar nota y próxima acción; eso requiere campos/criterios definidos, no solo un botón nuevo. Presentar en el reporte primero el tema a reforzar, cuántos alumnos y la evidencia, preservando participación y mínimo de cinco alumnos con datos.

Referencias: `templates/teacher/students.html`, `class_report.html`, `review.html`, `risk.html`.

**Orden de trabajo propuesto.** Corregir UX-01/UX-02; resolver UX-03/UX-04/UX-05 para que el recorrido sea claro; continuar con progreso, validación y resultados pendientes; validar accesibilidad/móvil y completar canje/listados. Añadir pruebas de interacción en navegador para las barras, conservación de borradores y navegación de pistas: las 101 pruebas existentes no detectaron estos problemas visuales/interactivos.

# Revisión UI/UX · Aula virtual DMC · 15 de octubre de 2026

Se atendió la separación de módulos solicitada a partir de la captura de Mis Coins. La revisión combinó el código y pruebas en Chrome con cuentas ficticias y PostgreSQL aislada: Mis cursos, Mis Coins, quiz y pistas, reporte docente y acceso. Se revisaron también las plantillas administrativas. No se consumieron Coins ni se enviaron solicitudes reales a proveedores de IA.

## Cambios aplicados

| Hallazgo | Corrección | Verificación |
|---|---|---|
| Saldo e Historial estaban pegados | Separación común de 16 px entre módulos; clases de espaciado y contenedores grid/stack coherentes | Distancia medida: antes 0 px; después 16 px en escritorio y móvil |
| Los márgenes inline no se aplicaban por la CSP | Espaciado de módulos trasladado a CSS externo; regla compartida para módulos consecutivos, sin relajar la seguridad | CSP conserva `style-src 'self'`; no se añadió `unsafe-inline` |
| Porcentajes de canje con doble borde y texto demasiado desvanecido | Estilos limitados a la tarjeta de cada opción; se elimina la opacidad anidada y se conserva el texto legible | Antes: borde interior de 1,5 px y opacidad 0,5 en tarjeta y porcentaje; después: un solo borde y opacidad 1 |
| Selección de canje basada principalmente en color | Etiqueta «Seleccionado», borde y estado accesible; lista semántica con enlaces que conservan su función | Comprobación visual de 890 Coins, descuento 40 %, saldo posterior 90; sin confirmar |
| Barra llena que indicaba 0 de 1 quizzes | Barras nativas `progress`, con valor, máximo y nombre accesible | Antes: ancho del relleno igual al total con valor declarado 0; después: estados visuales 0, 25 y 100 % correctos |
| Dominio y distribución docente dependían de anchuras inline bloqueadas | Progreso nativo para dominio y SVG con geometría explícita para distribución | Gráficos reales del reporte docente: segmentos, colores y etiquetas; normalización visual de porcentajes redondeados que suman 99/101 |
| Botones pequeños en móvil | Alto mínimo de 44 px en `.btn-sm` hasta 800 px | Medición en pantalla del quiz: 44 px |
| Blanco sobre cian tenía contraste insuficiente | Texto oscuro en botones y etiquetas cian | Contraste calculado 8,40:1; texto de opciones no disponibles sobre fondo suave 5,51:1 |
| El ancho previsto del acceso también dependía de estilos inline | Clase de acceso centrada, con máximo 440 px y separación común | Renderizado de pantallas y revisión de la composición |
| Explicación de Coins simplificaba incorrectamente el efecto de las pistas | Texto de estado vacío aclara que reducen el puntaje del reto y que las abiertas no entran en el cálculo de Coins del quiz | Sin modificar reglas de EXP, Coins o canje |

La separación de 16 px es una decisión del sistema visual de la plataforma, no una medida impuesta por WCAG. Se conserva la jerarquía: espacio entre módulos, espacio interior de las tarjetas y agrupación de elementos relacionados. Las notificaciones siguen fuera del flujo del contenido.

Referencias de accesibilidad: [WCAG 2.2, contraste mínimo](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) y [tamaño mínimo de objetivos](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html). El mínimo AA para objetivos es de 24 × 24 px, con excepciones; se eligieron 44 px como objetivo práctico para botones móviles. El contraste del texto normal se contrasta con 4,5:1. Estas comprobaciones puntuales no sustituyen una revisión completa con tecnologías de asistencia.

## Otras mejoras identificadas y pendientes

| Prioridad | Mejora | Evidencia actual | Criterio de aceptación |
|---|---|---|---|
| P0 | Conservar la respuesta al pedir pista, salir y volver | Reproducido en Chrome: elegir «Extraer (traer) los datos» y pedir una pista deja 0 opciones marcadas y Enviar deshabilitado | Recuperar alternativa/texto del mismo reto, sin enviar ni calificar automáticamente; probar también respuestas largas y semanal |
| P1 | Explicar el efecto de las pistas antes de usarlas | En quiz la advertencia aparece después de la primera pista; persiste la simplificación «no cuenta para Coins» | Explicar antes de confirmar la primera pista, con lenguaje alineado a la fórmula real y sin perder el borrador |
| P1 | Llevar desde Mis cursos directamente a la práctica anunciada | El CTA «Hacer el quiz de la clase 1» abre la portada del curso y obliga a otro paso | Empezar o continuar el quiz indicado, conservando la posibilidad de volver al curso |
| P1 | Hacer accionables los repasos pendientes | Mis cursos anuncia temas por repasar; Mi progreso muestra estados y fechas, sin acceso por tema | Próxima acción clara según disponibilidad real de quizzes; no prometer una práctica inexistente |
| P1 | Alinear el puesto cuando no hay EXP | Sin actividad, tarjeta de curso muestra «—» y dentro del curso aparece un puesto numérico | Mismo criterio de «sin participación» en ambas vistas, sin cambiar el ranking |
| P2 | Facilitar búsqueda y revisión docente | Alumnos y bandeja muestran listados sin búsqueda/filtros/paginación propios | Búsqueda por nombre, filtros por pendiente/estado y orden de prioridad; conservar filtros al volver |
| P2 | Gestionar el foco del menú móvil | El JS abre/cierra el menú y permite Escape; no mueve ni contiene explícitamente el foco en el panel | Tabulación predecible, retorno al botón y contenido principal protegido mientras el menú funciona como panel superpuesto |
| P2 | Evitar vocabulario técnico para el docente | Subir clase todavía menciona la variable de API y `.env` cuando falta IA | Mensaje accionable para el docente; detalle técnico reservado a administración |
| P2 | Completar ayuda del canje | Ya se muestra coste/saldo y ahora selección textual; falta explicar uso posterior y estado del descuento | Referencia/estado e instrucciones reales de uso, sin prometer una integración comercial inexistente |
| P2 | Continuar migración de estilos inline restantes | Quedan atributos en detalles, formularios y otros elementos que la misma CSP bloquea | Clases semánticas para estilos estáticos y valores nativos/SVG para datos; sin ampliar permisos de la CSP |

P0/P1/P2 indican el orden propuesto de mejora de experiencia, no una modificación de las prioridades de los documentos originales de producto. P0 significa aquí posible pérdida de trabajo del alumno. Se actualizaron los hallazgos de la [revisión anterior](revision-ui-ux-2026-10-13.md): UX-01 queda corregido; UX-09 y UX-10 tienen avances parciales; los borradores siguen pendientes.

## Validación y despliegue

141 pruebas existentes aprobadas. Chrome en escritorio, 390 y 320 px: separación, legibilidad, selección de canje, barras y ausencia de desbordamiento horizontal en las pantallas revisadas. Casos de saldo 0, 599, 600, 890 y 1000 verificados sin POST de canje. Reporte docente con geometría SVG y separación de 16 px. Se mantuvieron las confirmaciones y notificaciones flotantes.

Actualización de 14 archivos de interfaz en la VM de GCP, con respaldo y control de salud, conservando configuración, base de datos y archivos existentes. Versión CSS `20261015-uiux`; JS sigue en `20261015-notificaciones`. Integridad de los 14 archivos y 11 pantallas afectadas verificada por HTTPS. Evidencia privada en `.local/deploy-gcp/uiux-verification.json`. La verificación pública usa HTTPS estricto desde GCP por el bloqueo local de `sslip.io` observado anteriormente.

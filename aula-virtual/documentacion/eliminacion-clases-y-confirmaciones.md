# Eliminación de clases y confirmaciones

Implementación solicitada por el usuario el 14 de octubre de 2026. Alcance confirmado expresamente: «Solo la base de datos y los archivos activos». Los respaldos históricos conservan su retención actual de 14 días.

## Uso

El docente entra a uno de sus cursos y elige **Eliminar** junto a una clase, o **Eliminar clase** dentro de ella. La pantalla previa identifica la clase y el curso, muestra las cantidades afectadas y explica los cambios de progreso y recompensas. Debe marcar la confirmación; al pulsar el botón final se abre un cuadro emergente con **Cancelar** y **Eliminar definitivamente**.

El administrador dispone de esta misma operación desde la vista docente de cualquier curso. El alumno no obtiene permisos de eliminación. Se mantiene el control de matrícula del docente, la sesión y el CSRF tanto para la vista previa como para el POST. GET nunca elimina información. Un envío sin confirmación se rechaza.

## Información activa eliminada

- Fila de la clase: transcript original y anonimizado, recursos, nombres de archivos, tarea y estados.
- Archivo fuente de la grabación/audio/transcript almacenado en la carpeta de cargas.
- Temas asociados a la clase, retos originales y reemplazos/variantes relacionados, versiones, explicaciones, soluciones y pistas.
- Quizzes de esa clase, sus respuestas y tareas marcadas; reportes, revisiones, auditorías y registros de IA vinculados.
- Retos semanales que usaron su material, con sus respuestas, versiones y recompensas. La tabla nueva `fuentes_semanal` registra las clases cuyo texto efectivamente entró al contexto de cada nuevo reto semanal. Para semanales antiguos sin ese registro se consideran posibles derivados los del mismo tema creados después de publicar la clase; la purga es conservadora para evitar conservar contenido de la clase borrada.
- EXP y Coins asociados a las actividades eliminadas y ajustes vinculados a sus revisiones.

Si un reto se reutilizó como repaso en el quiz de otra clase, se retiran ese ítem y su respuesta; se conservan los demás ítems y respuestas. Se ajustan el índice para continuar, el contador y los resúmenes del quiz. Sus premios existentes se limitan a lo que permite la actividad restante; la eliminación no crea premios nuevos.

El dominio, nivel guardado y agenda de los temas afectados se reconstruyen con la evidencia restante. El podio se calcula desde los movimientos vigentes. Las señales de riesgo y mensajes agregados se invalidan para recalcularlos al siguiente acceso. Se mantienen las cuentas, la malla, las matrículas y las demás clases. Se libera el número de la clase eliminada para poder volver a subirla.

## Integridad

La operación usa una transacción y el mismo control de trabajos del curso que la purga administrativa. Espera las solicitudes activas que tengan un bloqueo compartido del curso e impide borrar durante trabajos IA. Las publicaciones automáticas omiten temporalmente cursos bloqueados, con un orden de bloqueos compatible con la eliminación. Un trabajo encolado que encuentre sus filas ya borradas termina sin recrearlas.

Las Coins se comprueban bajo bloqueo de las cuentas afectadas. Si retirarlas dejaría saldo negativo por un canje anterior, se revierte todo y se pide al administrador corregir los canjes afectados. La eliminación no modifica canjes globales ni paga el podio.

Los archivos se mueven temporalmente dentro de la carpeta de cargas antes del commit: un fallo restaura los archivos y revierte los registros. Tras el commit se borran físicamente. Si la limpieza falla, la interfaz avisa de que quedan archivos pendientes; se vuelve a intentar al iniciar y en la tarea periódica. La recuperación distingue una interrupción anterior al commit y restaura el archivo cuando la clase todavía existe. Las rutas externas, enlaces simbólicos y archivos compartidos con otra clase bloquean la operación para evitar borrar contenido ajeno.

No se crea una papelera ni un historial adicional de la clase eliminada en la aplicación. La exclusión de respaldos fue elegida expresamente por el usuario.

## Cuadro emergente compartido

El diálogo HTML de `base.html`, gestionado por `static/js/ui.js`, se aplica a todas las acciones marcadas con `data-confirm` y a los formularios `data-delete` en cualquier perfil:

- Eliminar clases y eliminar cursos definitivamente.
- Quitar alumnos o docentes de un curso.
- Rechazar retos, también desde la bandeja de revisión.
- Las confirmaciones ya existentes de cierre de curso y devolución de Coins utilizan el mismo cuadro.

Se puede cancelar con el botón o con Escape. El foco inicial está en Cancelar y el navegador mantiene el foco dentro del diálogo. El texto se inserta como texto, sin interpretar HTML. Al confirmar se conserva el botón que originó la acción, incluidos su nombre y valor; el indicador de IA solo empieza después de confirmar el envío. Los formularios conservan su validación. La recarga automática espera mientras el cuadro está abierto. Hay respaldo con la confirmación nativa para navegadores que no admitan `dialog`.

## Verificación

Pruebas con PostgreSQL aislado y proveedor simulado: permisos, CSRF, clase publicada y con error, referencias de IA y sufijos, otros cursos y cuentas, repasos en quizzes completados/en curso, semanales y procedencia, recompensas canjeadas, trabajos IA activos, progreso reconstruido, rutas y archivos compartidos, rollback SQL/commit, recuperación de interrupciones y concurrencia con una tarea recién guardada y la publicación automática. La purga de cursos también se comprobó con la nueva tabla de fuentes.

Revisión en Chrome de escritorio y 390 px: diálogo visible y sin desbordamiento, foco en Cancelar, cancelación/Escape sin envío, validación previa, conservación de la acción enviada en un formulario de ensayo, confirmación de clases/cursos y retiro de matrículas. No se eliminaron datos públicos para comprobar la función ni se enviaron solicitudes reales a proveedores IA.

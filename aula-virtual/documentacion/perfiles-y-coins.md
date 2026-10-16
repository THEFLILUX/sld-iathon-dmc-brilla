# Perfil académico y profesional · 15 de octubre de 2026

El usuario solicitó perfiles con información aleatoria coherente para las cuentas existentes, vista bloqueada con edición explícita y recompensa de 0,5 DMC Coin por campo. Ante la ambigüedad de «pares», confirmó: **1 Coin por cada dos campos**.

## Vista y acceso

- **Mi perfil** se abre desde el avatar del encabezado, disponible en alumno, docente y administrador. El menú global del alumno conserva Mis cursos y Mis Coins.
- La vista inicial muestra valores en modo de consulta. **Editar perfil** abre el formulario; **Cancelar** descarta los cambios y **Guardar perfil** exige revisar y confirmar los datos.
- El docente dispone de **Ver perfil y experiencia** en la ficha de cada alumno de su curso. Administración → Usuarios incluye **Ver perfil** para todas las cuentas. Estos accesos son de consulta: solo el titular edita.
- Doce campos: edad; situación de estudio/trabajo; carrera; estado de estudios; ocupación; sector; años de experiencia; fecha de ingreso a DMC; cursos previos; herramientas conocidas; objetivo de aprendizaje; horas semanales disponibles.
- A partir de la fecha y la lista se muestran antigüedad en meses y cantidad de cursos declarados. Son valores derivados y no campos adicionales con recompensa.
- Los perfiles se presentan con textos neutros, sin etiquetas ni avisos sobre la procedencia de los datos, por solicitud posterior del usuario. No crean matrículas ni certificados ni sustituyen los datos de identidad. No se envían al proveedor de IA. Los nuevos usuarios creados desde administración reciben un perfil vacío para completarlo personalmente.

## Coins

- Se conserva la regla existente: las Coins corresponden a alumnos; docentes y administradores tienen perfil editable sin esa bonificación.
- Cada campo distinto confirmado reconoce 0,5 Coin. Se acredita **1 Coin por cada dos campos**, hasta **6 Coins por los doce campos**. Si hay un campo impar, su media Coin queda pendiente del siguiente campo nuevo.
- La precarga y la consulta no acreditan Coins. La recompensa ocurre al guardar la información revisada, nunca al registrar ejemplos.
- Cada campo se reconoce una sola vez. Cambiar sus valores o borrarlo y volverlo a completar no permite repetir la recompensa. Los movimientos se identifican de forma única por usuario y par.
- Las Coins se suman al saldo existente y al historial con origen **Perfil completado**, sin EXP ni cambios en podio, quizzes o recompensas anteriores.
- Si las Coins están pausadas, se permite guardar el perfil. Al reactivarlas, un nuevo guardado acredita los pares pendientes, sin duplicar los ya pagados.

## Implementación y datos

- Nueva tabla `perfiles_usuario`, FK al usuario, con datos JSON, campos reconocidos, marca de ejemplo, versión y fechas de confirmación/actualización.
- `services/profiles.py`: ejemplos estables por cuenta, validación de rangos y coherencia edad/experiencia/ingreso, edición y recompensa. Se verifica versión y se bloquea el usuario durante el guardado para impedir pérdidas de cambios y pagos duplicados.
- `web/profile.py`: `/perfil`, `/perfil/editar`, POST `/perfil`. Sesión, consentimiento del alumno y CSRF obligatorios; la identidad del destinatario se obtiene de la sesión. Lecturas docentes verifican curso y matrícula; lecturas administrativas exigen rol.
- Migración explícita e idempotente `db/upgrade_profile.py`: amplía el CHECK `movimiento_origen` con `perfil`, manteniendo cantidades enteras y el resto de restricciones. Se ejecuta con `python -m db.init` o al arrancar con `DB_AUTO_CREATE=true`. No modifica registros existentes.
- Los campos son opcionales. «Ninguno» permite declarar que no se han llevado cursos previos; cero años de experiencia es una respuesta válida. Los valores generados se escapan mediante Jinja.

## Verificación

161 pruebas aprobadas, incluidas once nuevas sobre precarga coherente, consulta/edición, pago único, campos impares, cero, eliminación/rellenado de valores, validación, CSRF, permisos, consentimiento, pausa de Coins, guardados concurrentes y migración de la restricción anterior sin alterar movimientos.

Chrome con datos ficticios: vista de consulta en escritorio y móvil; edición y cancelación sin persistir cambios; confirmación y acreditación de 6 Coins; formulario de doce campos en 320 px; sin desbordamiento horizontal, avatar de 44 px y navegación inferior conservada. El servidor aislado y la sesión de prueba se cerraron.

## Publicación en GCP

Publicada el 15 de octubre: 25 perfiles para las 25 cuentas existentes, cada uno con los doce campos ficticios completos y sin confirmar. 17 archivos verificados por hash y 18 pantallas/permisos por HTTPS con validación TLS desde GCP. Migración aplicada e idempotente. Huellas de usuarios, cursos, clases, intentos y movimientos iguales antes/después. La precarga y la verificación no acreditaron Coins ni hicieron llamadas de IA. Aplicación y base saludables; configuración y credenciales conservadas.

### Ajuste posterior de textos

El usuario pidió retirar cualquier indicación de datos de prueba de la interfaz. Se eliminaron las etiquetas y avisos del perfil, se unificó el progreso como «campos completos» y se mantuvo la indicación de revisar y guardar para obtener Coins. También se ajustaron los textos de acceso, contenido inicial y transcript disponible. La modificación afecta únicamente textos de interfaz.

Ajuste publicado y verificado en GCP: cinco archivos, 23 pruebas de perfiles/pantallas y 18 vistas por HTTPS; ausencia de los avisos retirados en las páginas verificadas. Los perfiles, identidades, cursos, clases, intentos y movimientos coinciden con sus huellas previas. Sin nuevas llamadas de IA ni acreditaciones de Coins durante esta actualización.

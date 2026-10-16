# Notificaciones flotantes · 15 de octubre de 2026

Los avisos de éxito, error, advertencia e información usan un componente compartido en los perfiles de alumno, docente y administrador, además del acceso y el consentimiento. Incluye el mensaje «La clase está publicada y tus alumnos ya ven el quiz.», errores de formularios, carga de malla, validación de quizzes, curso cerrado, mensajes al alumno y premios de Coins.

Cada aviso incluye una equis con el nombre accesible «Cerrar notificación». Se dibuja fuera de `main`, en una región fija que no ocupa espacio en el flujo del documento: arriba a la derecha en escritorio y abajo en móvil, por encima de la navegación inferior del alumno. La zona restante permite interactuar con la página; no hay fondo modal ni bloqueo del formulario. Al cerrar, las posiciones de los módulos no cambian.

Cuando coinciden varios avisos, solo uno queda visible. El contador y «Siguiente aviso» permiten recorrerlos sin descartarlos; cerrar uno muestra el siguiente. Permanecen hasta que se cierren o se navegue a otra página, sin temporizador. Las listas largas tienen altura acotada y desplazamiento por teclado. El cierre devuelve el foco al siguiente aviso o al contenido principal y elimina el parámetro `ok` del aviso cerrado para que no reaparezca al recargar.

Las instrucciones esenciales para confirmar una eliminación y el feedback pedagógico asociado a un reto permanecen dentro de sus módulos como contenido contextual. Las confirmaciones de eliminación conservan su diálogo con Cancelar/Confirmar y su validación; no son avisos informativos.

Implementación: macro `templates/_notifications.html`, región y bloque `notifications` en `base.html`, comportamiento en `static/js/ui.js` y estilos en `static/css/dmc.css`. Las pantallas específicas aportan sus avisos al mismo bloque. Los errores simples de todos los formularios se resuelven en la plantilla base. Caché de CSS/JS: `20261015-notificaciones`. No hay cambios de esquema, dependencias, claves ni reglas de negocio.

Verificación: 141 pruebas existentes aprobadas sobre PostgreSQL aislada y proveedores simulados. Inspección real en Chrome de escritorio y 390 × 844: cuatro tipos, cierre con ratón/teclado, cola, foco, lista larga desplazable, formulario utilizable, mensaje real de publicación y convivencia con el diálogo de confirmación. Se midieron las posiciones de los módulos antes y después: sin desplazamiento. Sin desbordamiento horizontal ni errores de consola.

Despliegue: actualización de 25 archivos en la VM existente de GCP con respaldo y control de salud; se conservaron base de datos, archivos y configuración. La verificación pública se realiza con TLS estricto desde GCP por el bloqueo Fortinet de `sslip.io` observado en la red local. Evidencia privada de integridad y pantallas en `.local/deploy-gcp/notifications-verification.json`; la comprobación no envía solicitudes de IA ni elimina cursos o clases.

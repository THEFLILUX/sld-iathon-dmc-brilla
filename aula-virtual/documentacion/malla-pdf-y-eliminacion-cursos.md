# Malla PDF y eliminación de cursos

Cambios solicitados el 14 de octubre de 2026.

## Malla en PDF

Administración → curso → Configurar → Cargar malla admite CSV/JSON (2 MB) y PDF (25 MB,
100 páginas y hasta 120 000 caracteres de texto). `pypdf` extrae todo el texto; el proveedor
generativo configurado organiza módulos, temas, subtemas y objetivos mediante un esquema
validado. No se guarda nada hasta que el administrador revisa la vista previa y confirma.
Si el PDF no trae un objetivo explícito, el modelo puede proponer uno, identificado en la
vista previa. Al confirmar se validan otra vez las filas y se conserva el upsert existente;
los temas anteriores y sus referencias no se borran.

Los PDF escaneados sin capa de texto requieren OCR previo; los protegidos con contraseña,
ilegibles, demasiado largos o sin malla reconocible reciben un error. No se añadió un servicio
OCR externo. CSV y JSON conservan el flujo anterior. Después de confirmar se solicita la
propuesta existente de niveles, fundamentales y rúbricas. Nueva función generativa:
`importador_malla`, adicional a las funciones de IA ya implementadas.

## Cierre y eliminación

Cerrar curso conserva datos y paga el podio final, como antes. Eliminar definitivamente está
disponible exclusivamente para el administrador en Configurar → Revisar eliminación. Muestra
el curso, ID, cantidades afectadas y recompensas. El POST exige CSRF, nombre exacto y confirmación.
Eliminar no paga el podio.

El borrado elimina matrículas, malla y brochure, clases/transcripts/recursos/tareas, retos y sus
versiones y auditoría, quizzes/items/respuestas, semanales, dominio/agenda, reportes, mensajes,
riesgo, revisiones, movimientos de EXP y Coins y registros de IA cuya referencia pertenece al
curso. Las cuentas, sesiones, demás cursos, ajustes globales y canjes de la cuenta se conservan.
Si retirar Coins produciría un saldo negativo por un canje, se rechaza el borrado hasta corregir
los canjes afectados. Esta purga explícita es una excepción al historial normal de movimientos,
que sigue siendo inmutable en las demás operaciones.

El curso se bloquea en PostgreSQL y los saldos se protegen con el mismo bloqueo de usuarios
usado para los canjes. No se borra durante trabajo de IA activo o generación pendiente. La
coordinación en memoria presupone la instancia y proceso únicos del despliegue actual.

Las grabaciones propias se apartan temporalmente dentro de la carpeta de cargas antes de
confirmar la transacción. Un fallo restaura archivos y datos; después del commit se borran
los archivos apartados. El inicio y la tarea periódica reconcilian una operación interrumpida
o reintentan una limpieza fallida. Nunca se siguen rutas fuera de uploads ni se borran
grabaciones compartidas con otros cursos. Los recursos y brochure se guardaban como texto,
no como archivos PDF adicionales. Los respaldos operativos existentes conservan su retención.

No se requieren migraciones ni nuevas dependencias. Verificación local: 117 pruebas aprobadas,
PostgreSQL aislada y proveedores simulados; nuevo esquema probado con los transportes HTTP
de OpenAI y Gemini. UI de vista previa y confirmación revisada en escritorio y móvil de 390 px.

# Demo del aula virtual de DMC en Google Cloud

Demo pública: **https://aulavirtualdmc.34.44.96.128.sslip.io**

La dirección anterior redirige a esta URL. Al cambiar de dominio, inicia sesión de nuevo con las
mismas credenciales.

Los accesos de los cinco participantes y los alumnos ficticios adicionales están en
[el archivo privado de credenciales](../../.local/deploy-gcp/accesos-demo.md). Las contraseñas y claves
no forman parte del repositorio ni de la imagen Docker.

## Recursos y arquitectura

| Recurso | Configuración |
|---|---|
| Proyecto | `project-ea6ff772-6759-45ec-925` |
| VM | `cuadrilla-demo`, zona `us-central1-a`, `e2-medium`, 4 GB RAM |
| Sistema | Debian 12, Docker Engine y Compose |
| Disco | 30 GB persistente, `pd-balanced` |
| IP reservada | `34.44.96.128` (`cuadrilla-demo-ip`) |
| Web | FastAPI, un proceso, detrás de Caddy con HTTPS automático |
| Base | PostgreSQL 16 en un volumen Docker; sin puerto público |
| Archivos | `/opt/cuadrilla/deploy/gcp/data/uploads` |
| Red | VPC `cuadrilla-demo`, subred `cuadrilla-demo-us-central1` |
| Acceso administrativo | SSH mediante IAP; puerto 22 restringido a IAP |
| Puertos públicos | 80 y 443; la app y PostgreSQL quedan dentro de la red Docker |
| IA | Gemini `gemini-3.5-flash-lite` mediante Vertex AI, texto y audio; OpenAI disponible desde Administración → IA y modelos |
| Identidad de IA | Cuenta de servicio `aula-virtual-ia`, rol Vertex AI User y credenciales temporales de la VM |
| Presupuesto | Alerta mensual de S/150, al 50%, 90% y 100%, antes de aplicar créditos |

Desde el 15 de octubre, **Administración → IA y modelos** permite probar y activar OpenAI o
Vertex AI sin reiniciar, además de editar sus modelos. La selección persistida tiene prioridad
sobre el proveedor inicial del entorno. Vertex utiliza el proyecto actual y la ubicación `global`;
OpenAI conserva su API key privada. El cambio no altera el contenido ni las calificaciones existentes.
Ver [configuración y verificación de Vertex AI](../../documentacion/vertex-ai-y-modelos.md).

Se copiaron los dos cursos, sus mallas y las nueve cuentas de la base local. La copia pública usa
contraseñas nuevas y excluye las sesiones locales. `DEMO_MODE=false` evita sembrar cuentas con
contraseña predeterminada. La clase 1 de Python usa el transcript MD autorizado porque la pista AAC
del MP4 original está dañada; el error de extracción se reprodujo también en el Mac.

Los trabajos de IA permanecen dentro del proceso. Mantener una instancia y un proceso; reiniciar
interrumpe los trabajos que estén ejecutándose y la app permite reintentarlos.

## Herramientas del Mac

Se instaló Google Cloud CLI mediante Homebrew, con su Python 3.14. La app conserva Python 3.12 y
las dependencias de `uv.lock`. Docker corre en la VM; no hace falta instalar Docker en el Mac para
administrar este despliegue.

La configuración de CLI se llama `cuadrilla-dmc`. Para conectarse:

```sh
gcloud compute ssh cuadrilla-demo \
  --configuration=cuadrilla-dmc \
  --project=project-ea6ff772-6759-45ec-925 \
  --zone=us-central1-a \
  --tunnel-through-iap
```

## Operación en la VM

```sh
cd /opt/cuadrilla/deploy/gcp
sudo docker compose --env-file runtime.env ps
sudo docker compose --env-file runtime.env logs --tail=50 app
```

Configuración y claves: `/opt/cuadrilla/deploy/gcp/runtime.env`, con permisos privados. Para cambiar
a Gemini, ajustar `LLM_PROVIDER`, `GOOGLE_API_KEY`, `LLM_MODEL` y, si corresponde,
`TRANSCRIPTION_PROVIDER` y `TRANSCRIPTION_MODEL`. Reiniciar la app cuando no esté procesando clases:

```sh
sudo docker compose --env-file runtime.env up -d app
```

Para una actualización de código, copiar el árbol actual del proyecto a `/opt/cuadrilla`, conservar
`runtime.env` y `data/uploads`, y construir de nuevo:

```sh
sudo docker compose --env-file runtime.env build app
sudo docker compose --env-file runtime.env up -d app
```

Antes de reiniciar, comprobar que no haya trabajo de IA activo, incluidos los registros con
`estado='generando'` de `resumenes_clase`. Esta tabla se crea al arrancar; los resúmenes
existentes no se vuelven a generar al abrir el curso. Un reinicio recupera sus trabajos interrumpidos.

Los volúmenes conservan la base y los certificados. Las tablas nuevas se crean al iniciar; cambiar
columnas de tablas existentes requiere una migración explícita. La actualización de perfiles añade
`perfiles_usuario` y amplía de forma idempotente el CHECK `movimiento_origen` con `perfil`; conserva los
movimientos existentes y sus importes enteros. Los perfiles de ejemplo no acreditan Coins al arrancar.

## Copias y cierre de la prueba

`/opt/cuadrilla/backup.sh` copia diariamente PostgreSQL y los archivos a `/opt/cuadrilla/backups`, a las
08:00 UTC (03:00 Lima). Conserva catorce días. Se verificó que `cron` está activo y se generó la primera
copia. Estas copias están en la misma VM; descargar una copia al Mac para conservar la actividad
antes de cerrar el proyecto o terminar la prueba.

La copia inicial de la base local está en `.local/deploy-gcp/local-database.dump`.
La copia del estado de GCP después de procesar la clase se descargó a
`.local/deploy-gcp/cloud-database.dump` y `.local/deploy-gcp/cloud-uploads.tar.gz`; ambos archivos
se verificaron y están excluidos de Git.

La prueba gratuita
indicada por la consola vence el **12 de enero de 2027**. La cuenta continúa en prueba gratuita; las
alertas de presupuesto no apagan recursos ni son un límite de gasto. OpenAI se factura fuera de GCP.

Para detener la VM:

```sh
gcloud compute instances stop cuadrilla-demo \
  --configuration=cuadrilla-dmc \
  --project=project-ea6ff772-6759-45ec-925 \
  --zone=us-central1-a
```

El disco y la IP reservada siguen existiendo al detenerla. Eliminar la VM con su disco elimina los
datos alojados en él; exportar la base y los archivos antes de desmontar la demo.

## Comprobaciones del despliegue

- Certificado HTTPS válido y `/health` con base conectada e IA configurada.
- Acceso de los cinco participantes, cookie Secure y restricciones por rol.
- Llamada real de chat con salida estructurada y transcripción real de audio sintético sin datos
  personales. Los diagnósticos se registran como `despliegue:*`, sin crear intentos de alumnos.
- Mapeo real y procesamiento del transcript autorizado: cuatro retos base, uno previo y trece
  versiones. La clase 1 quedó `por_validar`, disponible para revisar con el docente de Python.
- Calificación con feedback y propuesta de malla verificadas con llamadas reales. No se crearon
  intentos ni premios de alumnos durante esos diagnósticos.

# Acceso público para la presentación

El login incorpora **Probar DEMO**. Abre una selección con cinco participantes: dos alumnos, dos docentes y el administrador principales. Cada opción muestra únicamente el rol y el nombre vigente de la cuenta. Al seleccionarla se crea una sesión y se abre el acceso correspondiente, sin solicitar ni exponer contraseñas o DNI.

El selector utiliza una lista fija del servidor en `auth/demo.py`. No admite IDs, DNI ni roles enviados por el navegador como identidad de acceso; tampoco agrega otras cuentas aunque existan en la base. Si una cuenta está desactivada o ya no tiene el rol esperado, deja de estar disponible. Los participantes conservan los permisos de sus roles y comparten la información existente. No se crean cuentas ni se modifican sus contraseñas, perfiles, calificaciones o consentimiento al entrar.

El formulario normal de DNI y contraseña continúa disponible. Para cambiar de participante se usa **Salir**, luego **Probar DEMO**. Una sesión ya iniciada no puede cambiarse silenciosamente mediante el formulario público. Se conserva el aviso de consentimiento si el alumno todavía lo tiene pendiente.

## Configuración y controles

`PUBLIC_DEMO_LOGIN` está desactivado de forma predeterminada, incluso con `DEMO_MODE=true`. Se habilita explícitamente con `PUBLIC_DEMO_LOGIN=true` en el entorno local o en el `runtime.env` privado de GCP. Es independiente de `DEMO_MODE`, que controla la carga de contenido inicial. En GCP se conserva `DEMO_MODE=false`.

Para cerrar nuevas entradas públicas tras la presentación, establecer `PUBLIC_DEMO_LOGIN=false` y recrear el servicio cuando no haya trabajos de IA activos. Las sesiones ya abiertas conservan su vencimiento habitual y pueden cerrarse con **Salir**. Las credenciales normales no cambian.

Las rutas GET y POST rechazan el acceso cuando la opción está apagada. La selección utiliza un nonce en cookie HttpOnly, firma HMAC ligada al proceso y verificación de origen; la cookie dura diez minutos y se elimina al entrar. En HTTPS se marca Secure. Cada entrada crea una sesión aleatoria del mecanismo existente, con token almacenado como hash, cookie HttpOnly/SameSite y CSRF para las acciones posteriores. Se admiten hasta 30 entradas DEMO por IP en quince minutos; el contador es acotado e independiente del login habitual.

No hay contraseñas en las plantillas, JavaScript o enlaces de presentación. La apertura del selector y el inicio de sesión no realizan llamadas de IA. No se incorporan dependencias ni tablas nuevas.

## Verificación

198 pruebas aprobadas. Se cubren las cinco identidades, salida sin credenciales, configuración apagada, cuentas inactivas o con otro rol, participantes arbitrarios, CSRF/origen, límite de entradas, sesiones ya iniciadas, logout y consentimiento pendiente. Revisión en Chrome de escritorio y 320 px: cinco opciones, sin desbordamiento y botones de más de 74 px. Ingreso directo al docente y regreso al login comprobados en una base aislada.

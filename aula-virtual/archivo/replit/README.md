# Archivo de la plantilla Replit

Esta carpeta conserva el código de partida y los requisitos iniciales del desarrollo. Está separada
de la aplicación activa y queda excluida del contexto de construcción de Docker mediante `.dockerignore`.

| Ruta | Contenido conservado |
|---|---|
| `artifacts/api-server/` | Servidor Express de la plantilla original. |
| `artifacts/mockup-sandbox/` | Prototipo React/Vite y componentes visuales de la plantilla. |
| `lib/` | Clientes de API, esquemas y acceso a datos de la plantilla TypeScript. |
| `scripts/` | Scripts auxiliares del workspace original. |
| `package.json`, `pnpm-*.yaml`, `tsconfig*.json`, `.npmrc` | Configuración y dependencias del workspace original. |
| `artifacts/cuadrilla/package.json` | Antiguo adaptador de comandos pnpm a Python. |
| `attached_assets/` | Requisitos iniciales recibidos durante el desarrollo. Las grabaciones locales están excluidas de Git. |

Se conservan los archivos y sus rutas relativas dentro de la plantilla como referencia histórica.
Este conjunto no se mantiene como una aplicación instalable ni participa en el arranque, las pruebas
o la imagen de producción del aula virtual. La configuración de pnpm conserva sus controles originales
de instalación y dependencias.

Para trabajar en el producto vigente, usa la [guía de la web](../../README.md) y el
[mapa del repositorio](../../documentacion/estructura-del-repositorio.md).

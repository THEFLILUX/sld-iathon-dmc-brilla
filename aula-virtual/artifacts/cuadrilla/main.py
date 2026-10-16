import logging
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text, update
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.concurrency import run_in_threadpool

from auth.deps import Redirect, usuario_opcional
from config import APP_DIR, settings
from db.models import Clase, Intento, Reto, RetoSemanal
from db.seed import seed
from db.session import SessionLocal, get_db
from services.course_deletion import reconciliar_archivos_eliminados
from services.class_deletion import reconciliar_archivos_eliminados as reconciliar_archivos_clases
from web.admin import router as admin_router
from web.auth import router as auth_router
from web.student import router as student_router
from web.teacher import router as teacher_router
from web.profile import router as profile_router
from web.assistant import router as assistant_router
from web.ai_settings import router as ai_settings_router
from web.views import page

logger = logging.getLogger("aulavirtualdmc")
TICK_SEGUNDOS = 60


def tick() -> None:
    """Publish classes whose hour ended, approve expired replacements, retry pending gradings."""
    from services import attempts, summaries, validation
    from services.params import cargar

    reconciliar_archivos_eliminados()
    reconciliar_archivos_clases()
    with SessionLocal.begin() as db:
        validation.publicar_vencidas(db)
        params = cargar(db)
    attempts.reintentar_pendientes(params)
    summaries.completar_pendientes()


def _ciclo(parar: threading.Event) -> None:
    while not parar.wait(TICK_SEGUNDOS):
        try:
            tick()
        except Exception:
            logger.exception("Falló la tarea periódica")


@asynccontextmanager
async def lifespan(app):
    settings.SAMPLE_DIR.mkdir(exist_ok=True)
    settings.UPLOAD_DIR.mkdir(exist_ok=True)
    if settings.DB_AUTO_CREATE:
        # Creates missing tables and explicitly expands the ledger origin enum for profile rewards.
        from db.init import crear_tablas
        crear_tablas()
    seed()
    from services.profiles import preparar_existentes
    with SessionLocal.begin() as db:
        preparar_existentes(db)
    reconciliar_archivos_eliminados()
    reconciliar_archivos_clases()
    # A restart cannot resume in-memory jobs: say so instead of leaving work stuck.
    with SessionLocal.begin() as db:
        db.execute(update(Clase).where(Clase.estado == "procesando").values(
            estado="error", paso=None, error_mensaje="El servicio se reinició durante el procesamiento. Reintenta."))
        db.execute(update(Reto).where(Reto.estado == "generando").values(
            estado="error", error_mensaje="El servicio se reinició. Vuelve a generar este reto."))
        db.execute(update(RetoSemanal).where(RetoSemanal.estado == "generando").values(
            estado="error", error_mensaje="El servicio se reinició mientras se preparaba el reto semanal."))
        db.execute(update(Intento).where(Intento.estado == "evaluando").values(estado="pendiente"))
    from services.summaries import completar_pendientes
    completar_pendientes(reinicio=True)
    parar = threading.Event()
    hilo = threading.Thread(target=_ciclo, args=(parar,), name="aulavirtualdmc-tick", daemon=True)
    hilo.start()
    yield
    parar.set()


app = FastAPI(title="Aula virtual · DMC Institute", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount(f"{settings.BASE_PATH}/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
for router in (auth_router, student_router, teacher_router, admin_router, profile_router, assistant_router, ai_settings_router):
    app.include_router(router, prefix=settings.BASE_PATH)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    from ai import runtime
    with runtime.usar(await run_in_threadpool(runtime.cargar)):
        response = await call_next(request)
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
        "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'"
    )
    if "/static/" not in request.url.path:
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get(f"{settings.BASE_PATH}/", name="home")
def home(request: Request, usuario=Depends(usuario_opcional)):
    if usuario is None:
        return RedirectResponse(request.url_for("login"), status_code=303)
    destino = {"alumno": "student_home", "docente": "teacher_home", "admin": "admin_home"}[usuario.rol]
    return RedirectResponse(request.url_for(destino), status_code=303)


@app.get(f"{settings.BASE_PATH}/health", name="health")
def health(db=Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse({"status": "error", "database": "unavailable"}, status_code=503)
    return {"status": "ok", "database": "ok", "ai": "configurada" if settings.ai_enabled else "sin_clave"}


@app.exception_handler(Redirect)
async def redirect_handler(request: Request, exc: Redirect):
    return RedirectResponse(exc.url, status_code=303)


@app.exception_handler(StarletteHTTPException)
async def friendly_http_error(request: Request, exc: StarletteHTTPException):
    detalle = exc.detail if isinstance(exc.detail, str) else "No pudimos completar la solicitud."
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"detail": detalle}, status_code=exc.status_code)
    titulos = {403: "Sin permiso", 404: "No encontrado"}
    return page(request, "errors/error.html", {
        "page_title": titulos.get(exc.status_code, "No se pudo completar la solicitud"),
        "codigo": exc.status_code, "message": detalle,
    }, status_code=exc.status_code)


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError):
    # Never leak connection strings or query parameters.
    logger.error("Error de base de datos (%s)", type(exc).__name__)
    return page(request, "errors/error.html", {
        "page_title": "Servicio no disponible", "codigo": 503,
        "message": "No pudimos conectar con la base de datos. Intenta nuevamente en unos momentos.",
    }, status_code=503)

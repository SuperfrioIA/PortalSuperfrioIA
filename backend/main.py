import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.database import init_db
from backend.limiter import limiter
from backend.routers import admin, auth, portal
from backend.seed import seed_initial


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    seed_initial()
    yield


app = FastAPI(
    title="Hub SuperFrio & Icestar",
    description="Plataforma centralizadora de apps internos — POC",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# frame-src controla quais origens podem ser embutidas via <iframe> (apps tipo_acesso=iframe).
# Default seguro: 'self' + qualquer HTTPS. Em produção, restrinja às origens reais dos apps:
#   SUPERFRIO_FRAME_SRC="https://app1.interno https://app2.interno"
_FRAME_SRC = os.environ.get("SUPERFRIO_FRAME_SRC", "'self' https:")

_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    f"frame-src {_FRAME_SRC}; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

# CSP próprio da apresentação estática em /governanca/ (documento de TI, conteúdo
# confiável): permite os <script> inline da apresentação + Google Fonts, e deixa ela
# ser embutida no overlay do portal (frame-ancestors 'self'). NÃO afrouxa o resto do hub.
_CSP_GOVERNANCA = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'self'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    # A apresentação em /governanca/ tem CSP próprio (script inline) e pode ser embutida
    # same-origin no overlay do portal; o resto do hub mantém o CSP estrito e X-Frame DENY.
    if request.url.path.startswith("/governanca"):
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Content-Security-Policy"] = _CSP_GOVERNANCA
    else:
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Content-Security-Policy", _CSP)
    return response


app.include_router(auth.router)
app.include_router(portal.router)
app.include_router(admin.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

"""Local server: one Uvicorn worker, no autoreloader (background jobs live in this process)."""

import uvicorn

from config import settings

if __name__ == "__main__":
    print(f"Aula virtual DMC en http://{settings.HOST}:{settings.PORT}{settings.BASE_PATH or '/'}")
    uvicorn.run(
        "main:app", host=settings.HOST, port=settings.PORT, workers=1, reload=False,
        # Forwarded headers are trusted only from FORWARDED_ALLOW_IPS (a reverse proxy, if any).
        proxy_headers=True, forwarded_allow_ips=settings.FORWARDED_ALLOW_IPS,
        # Session cookies never appear in URLs, but keep access logs minimal anyway.
        access_log=False,
    )

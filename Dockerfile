FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SUPERFRIO_DB_PATH=/app/data/portal.db

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY alembic.ini .
COPY CHANGELOG.md ./
COPY entrypoint.sh /entrypoint.sh

RUN useradd -u 1000 -d /app -s /usr/sbin/nologin app \
    && mkdir -p /app/data \
    && chown -R app:app /app \
    && chmod +x /entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3); sys.exit(0)" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
# O ProxyHeadersMiddleware do uvicorn já vem ligado, mas por padrão só confia em
# 127.0.0.1 — atrás do ALB o peer é o balanceador, então os X-Forwarded-* eram
# ignorados. Três efeitos disso em produção (21/08/2026): redirect do StaticFiles
# saindo como http:// e barrado pelo CSP frame-src ao abrir app embutido; IP do
# ALB no lugar do IP real em todo log; e o rate limit de login virando coletivo,
# porque a chave do limiter é o IP do cliente.
# Contrapartida do curinga: quem alcançar a porta do container direto pode forjar
# o X-Forwarded-For. Mitigação correta = restringir a porta ao security group do ALB.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]

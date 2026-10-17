# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS apps
WORKDIR /build
COPY upstream.lock.json ./
COPY scripts/fetch_apps.py ./scripts/fetch_apps.py
RUN python scripts/fetch_apps.py --output /opt/artcraft

FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LIBERTY_DATA=/data LIBERTY_APPS=/opt/artcraft
WORKDIR /app
COPY requirements.lock ./
RUN pip install --require-hashes --no-cache-dir --disable-pip-version-check -r requirements.lock \
    && groupadd --gid 10001 liberty \
    && useradd --uid 10001 --gid liberty --no-create-home --shell /usr/sbin/nologin liberty \
    && mkdir -p /data && chown liberty:liberty /data && chmod 700 /data
COPY --from=apps /opt/artcraft /opt/artcraft
COPY . /app
RUN python scripts/package_source.py /opt/liberty-source.zip
USER 10001:10001
EXPOSE 8097
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request,os; from urllib.parse import urlsplit; h=urlsplit(os.environ.get('PUBLIC_ORIGIN','http://localhost:8097')).netloc; r=urllib.request.Request('http://127.0.0.1:8097/healthz',headers={'Host':h}); urllib.request.urlopen(r,timeout=3)"
CMD ["python", "-m", "uvicorn", "liberty.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8097", "--workers", "1", "--limit-concurrency", "80", "--timeout-keep-alive", "5", "--no-proxy-headers", "--no-access-log"]

# syntax=docker/dockerfile:1
ARG FIGCRAFT_BUNDLE_IMAGE=rust:1.95.0-bookworm@sha256:6258907abe69656e41cd992e0b705cdcfabcbbe3db374f92ed2d47121282d4a1
ARG GRIDCRAFT_BUNDLE_IMAGE=rust:1.95.0-bookworm@sha256:6258907abe69656e41cd992e0b705cdcfabcbbe3db374f92ed2d47121282d4a1
ARG WORDCRAFT_BUNDLE_IMAGE=rust:1.95.0-bookworm@sha256:6258907abe69656e41cd992e0b705cdcfabcbbe3db374f92ed2d47121282d4a1
FROM ${FIGCRAFT_BUNDLE_IMAGE} AS figcraft
WORKDIR /integration
COPY scripts/build_figcraft_web.sh scripts/patch_figcraft_web.py scripts/package_figcraft_web.py ./scripts/
COPY patches/figcraft-web ./patches/figcraft-web
# A trusted prebuilt bundle image needs a shell and /out. Both paths pass the
# exact compiled-file and patch/recipe hash checks in the installation stage.
RUN if [ ! -f /out/index.html ]; then bash scripts/build_figcraft_web.sh /build /out; fi

FROM ${GRIDCRAFT_BUNDLE_IMAGE} AS gridcraft
WORKDIR /integration
# Keep memory-intensive source builds sequential under BuildKit too.
COPY --from=figcraft /out/index.html /integration/figcraft-build-complete.html
COPY scripts/build_gridcraft_web.sh scripts/patch_gridcraft_web.py scripts/package_gridcraft_web.py ./scripts/
COPY patches/gridcraft-web ./patches/gridcraft-web
RUN if [ ! -f /out/index.html ]; then bash scripts/build_gridcraft_web.sh /build /out; fi

FROM ${WORDCRAFT_BUNDLE_IMAGE} AS wordcraft
WORKDIR /integration
COPY --from=gridcraft /out/index.html /integration/gridcraft-build-complete.html
COPY scripts/build_wordcraft_web.sh scripts/patch_wordcraft_web.py scripts/package_wordcraft_web.py ./scripts/
COPY patches/wordcraft-web ./patches/wordcraft-web
# Native UI tests use headless CPU Vulkan, never a host GPU or display server.
RUN if [ ! -f /out/index.html ]; then \
      apt-get update && apt-get install -y --no-install-recommends --no-upgrade \
        libvulkan1=1.3.239.0-1 mesa-vulkan-drivers=22.3.6-1+deb12u2 \
      && bash scripts/build_wordcraft_web.sh /build /out; fi

FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS apps
WORKDIR /build
COPY upstream.lock.json ./
COPY branding.lock.json ./
COPY assets/branding ./assets/branding
COPY figcraft-build.lock.json ./
COPY gridcraft-build.lock.json ./
COPY wordcraft-build.lock.json ./
COPY public-assets.lock.json ./
COPY liberty/__init__.py liberty/public_assets.py ./liberty/
COPY patches/figcraft-web ./patches/figcraft-web
COPY patches/gridcraft-web ./patches/gridcraft-web
COPY patches/wordcraft-web ./patches/wordcraft-web
COPY scripts/fetch_apps.py scripts/brand_apps.py scripts/install_source_web.py \
    scripts/build_figcraft_web.sh scripts/patch_figcraft_web.py scripts/package_figcraft_web.py \
    scripts/build_gridcraft_web.sh scripts/patch_gridcraft_web.py scripts/package_gridcraft_web.py \
    scripts/build_wordcraft_web.sh scripts/patch_wordcraft_web.py scripts/package_wordcraft_web.py \
    scripts/package_public_assets.py ./scripts/
COPY --from=figcraft /out ./figcraft-prepared
COPY --from=gridcraft /out ./gridcraft-prepared
COPY --from=wordcraft /out ./wordcraft-prepared
RUN python scripts/fetch_apps.py --output /opt/artcraft \
    && python scripts/install_source_web.py --bundle /build/figcraft-prepared --output /opt/artcraft --lock /build/figcraft-build.lock.json \
    && python scripts/install_source_web.py --bundle /build/gridcraft-prepared --output /opt/artcraft --lock /build/gridcraft-build.lock.json \
    && python scripts/install_source_web.py --bundle /build/wordcraft-prepared --output /opt/artcraft --lock /build/wordcraft-build.lock.json \
    && python scripts/package_public_assets.py /opt/artcraft /opt/liberty-public-assets

FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LIBERTY_DATA=/data LIBERTY_APPS=/opt/artcraft LIBERTY_PUBLIC_ASSETS=/opt/liberty-public-assets
WORKDIR /app
COPY requirements.lock ./
RUN pip install --require-hashes --no-cache-dir --disable-pip-version-check -r requirements.lock \
    && groupadd --gid 10001 liberty \
    && useradd --uid 10001 --gid liberty --no-create-home --shell /usr/sbin/nologin liberty \
    && mkdir -p /data && chown liberty:liberty /data && chmod 700 /data
COPY --from=apps /opt/artcraft /opt/artcraft
COPY --from=apps /opt/liberty-public-assets /opt/liberty-public-assets
COPY . /app
RUN python scripts/package_source.py /opt/liberty-source.zip
USER 10001:10001
EXPOSE 8097
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request,os; from urllib.parse import urlsplit; h=urlsplit(os.environ.get('PUBLIC_ORIGIN','http://localhost:8097')).netloc; r=urllib.request.Request('http://127.0.0.1:8097/healthz',headers={'Host':h}); urllib.request.urlopen(r,timeout=3)"
CMD ["python", "-m", "uvicorn", "liberty.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8097", "--workers", "1", "--limit-concurrency", "80", "--timeout-keep-alive", "5", "--no-proxy-headers", "--no-access-log"]

FROM julia:1.12.1 AS base

ENV DEBIAN_FRONTEND=noninteractive \
    JULIA_CONDAPKG_BACKEND=Null \
    JULIA_PYTHONCALL_EXE=/opt/venv/bin/python \
    JULIA_PYTHONCALL_LIB=/usr/lib/x86_64-linux-gnu/libpython3.13.so.1.0 \
    PYTHONUNBUFFERED=1 \
    SPARKBYTE_HOST=0.0.0.0 \
    SPARKBYTE_PORT=8081 \
    SPARKBYTE_LAUNCH_BROWSER=0 \
    SPARKBYTE_SKIP_PKG_INSTANTIATE=1 \
    SPARKBYTE_STATE_DIR=/app/runtime \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    libpython3.13 \
    python3 \
    python3-pip \
    python3-venv \
    python-is-python3 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv

COPY requirements.docker.txt ./requirements.docker.txt
RUN pip install --no-cache-dir -r requirements.docker.txt && \
    python -m playwright install --with-deps chromium

FROM base AS build

COPY . .

RUN julia --project=. -e 'using Pkg; Pkg.instantiate(); Pkg.precompile()'

FROM base AS runtime

COPY . .
COPY --from=build /root/.julia /root/.julia

RUN mkdir -p /app/runtime

EXPOSE 8081
EXPOSE 8082

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=4).read()"

CMD ["julia", "--project=.", "sparkbyte.jl"]

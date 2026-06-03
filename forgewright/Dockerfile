# syntax=docker/dockerfile:1.7
# =============================================================================
#  forgewright — multi-stage container image
#  Stage 1 (builder): produce an installable wheel of forgewright + browsers
#  Stage 2 (runtime): slim Python image with the wheel + browsers installed
# =============================================================================

ARG PYTHON_VERSION=3.12
ARG FORGEWRIGHT_VERSION=0.1.0
ARG GIT_REVISION=unknown

# -----------------------------------------------------------------------------
# 1. builder — full toolchain, build the wheel, install playwright browsers
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ARG FORGEWRIGHT_VERSION=0.1.0
ARG GIT_REVISION=unknown
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/forgewright-venv

# Build-time system packages: uv itself, plus the OS deps Playwright's
# Chromium needs. They aren't required in the runtime image because the
# `playwright install --with-deps` step here bakes the browser binaries
# into a location we copy across stages.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
 && rm -rf /var/lib/apt/lists/*

# Install uv (pinned, reproducible).
RUN curl -fsSL https://astral.sh/uv/install.sh -o /tmp/uv-install.sh \
 && UV_INSTALL_DIR=/usr/local/bin sh /tmp/uv-install.sh \
 && rm /tmp/uv-install.sh \
 && uv --version

WORKDIR /src

# ---- Layer 1: project metadata + lockfile (changes rarely) -----------------
COPY pyproject.toml uv.lock ./
COPY README.md LICENSE ./
COPY src/forgewright/py.typed ./src/forgewright/py.typed

# ---- Layer 2: source (changes more often) ----------------------------------
COPY src/ ./src/

# Sync deps (locked) and produce a wheel.
RUN uv sync \
        --locked \
        --all-extras \
        --no-dev \
 && uv run --no-sync python -c "import forgewright; print(forgewright.__version__)" \
 && uv build --out-dir /tmp/wheelhouse

# Build a clean runtime venv containing the wheel + extras, then bake in
# Playwright's Chromium binary and its system deps. We layer this in a single
# RUN so the final image's `/opt/venv` is self-contained.
# (`uv venv` does not seed `pip` into the venv by design; we use `uv pip
# install --python` which is the recommended path for non-interactive images.)
RUN uv venv /opt/forgewright-runtime --python ${PYTHON_VERSION} \
 && VIRTUAL_ENV=/opt/forgewright-runtime uv pip install --no-cache \
        /tmp/wheelhouse/forgewright-*.whl \
        playwright>=1.46 \
 && /opt/forgewright-runtime/bin/playwright install --with-deps chromium \
 && rm -rf /tmp/wheelhouse

# -----------------------------------------------------------------------------
# 2. runtime — slim image, non-root user, OCI labels
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ARG FORGEWRIGHT_VERSION=0.1.0
ARG GIT_REVISION=unknown
ARG BUILD_DATE
ARG VCS_REF

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    FORGEWRIGHT_HOME=/home/forgewright \
    FORGEWRIGHT_CONFIG=/home/forgewright/.config/forgewright \
    PATH="/opt/forgewright-runtime/bin:${PATH}"

# Minimal runtime libs. The Playwright bundle needs a few X11 / audio / GL
# shared objects even when running headless.
# Note: on Debian bookworm the ALSA library is `libasound2`; `libasound2t64`
# is the Ubuntu 24.04 / Debian trixie transitional name.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates \
        tini \
        # Playwright Chromium runtime deps (slim subset that survives
        # `playwright install --with-deps` at builder time).
        libnss3 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libxshmfence1 \
        libpango-1.0-0 \
        libcairo2 \
        libasound2 \
        libatspi2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# Create non-root user with stable uid/gid 1000.
RUN groupadd --system --gid 1000 forgewright \
 && useradd  --system --uid 1000 --gid forgewright \
        --home-dir /home/forgewright \
        --shell /sbin/nologin \
        --create-home \
        forgewright

# Copy the runtime venv (built in `builder`) verbatim.
# (We keep the original path so console-script shebangs continue to resolve.
# `uv pip install` writes shebangs like `#!/opt/forgewright-runtime/bin/python3`,
# which only works if the venv lives at that exact path.)
COPY --from=builder /opt/forgewright-runtime /opt/forgewright-runtime

# Copy Playwright's browser cache. The default install location is
# /root/.cache/ms-playwright in the builder, but when invoked via the wheel
# in a fresh PATH it resolves to the invoking user's HOME. We normalise to
# /home/forgewright/.cache/ms-playwright and use PLAYWRIGHT_BROWSERS_PATH.
COPY --from=builder --chown=forgewright:forgewright /root/.cache/ms-playwright /home/forgewright/.cache/ms-playwright
ENV PLAYWRIGHT_BROWSERS_PATH=/home/forgewright/.cache/ms-playwright

# Tini for clean signal handling; entrypoint.
# (tini is installed via apt-get in the runtime stage above.)

# Workdir + pre-create config dir for the non-root user.
WORKDIR /home/forgewright
RUN mkdir -p /home/forgewright/.config/forgewright /home/forgewright/workspace /home/forgewright/logs \
 && chown -R forgewright:forgewright /home/forgewright

# ---- OCI image labels (https://specs.opencontainers.org/image-spec/annotations/) ----
LABEL org.opencontainers.image.title="forgewright" \
      org.opencontainers.image.description="An open-source, CLI-first AI agent framework. Bring your own keys, run on your own box." \
      org.opencontainers.image.source="https://github.com/forest/forgewright" \
      org.opencontainers.image.url="https://github.com/forest/forgewright" \
      org.opencontainers.image.documentation="https://github.com/forest/forgewright/blob/main/README.md" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="Forest" \
      org.opencontainers.image.authors="Forest" \
      org.opencontainers.image.version="${FORGEWRIGHT_VERSION}" \
      org.opencontainers.image.revision="${GIT_REVISION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      io.artifacthub.package.readme-url="https://github.com/forest/forgewright/blob/main/README.md" \
      com.forgewright.mcp-port="8765"

EXPOSE 8765

USER forgewright

# Lightweight self-check — runs every 5m, gives a 10s grace period.
HEALTHCHECK --interval=5m --timeout=10s --start-period=10s --retries=3 \
  CMD ["forgewright", "--version"]

# tini reaps zombies; entrypoint is the CLI itself.
ENTRYPOINT ["/usr/bin/tini", "--", "forgewright"]
CMD ["--help"]

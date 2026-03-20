# Single multi-stage Dockerfile for all 3 browser modes.
# Build targets: headless, headful, headless-shell
#
#   docker build --target headless -t rc-headless .
#   docker build --target headful  -t rc-headful  .
#   docker build --target headless-shell -t rc-headless-shell .

# ---- Base: Python + common system deps + uv + Python deps ----
FROM python:3.12-slim-bookworm AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg2 ca-certificates \
    fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 \
    libcups2 libdbus-1-3 libdrm2 libgbm1 libnspr4 \
    libnss3 libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 \
    xdg-utils procps \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY collector/ ./collector/

ENTRYPOINT ["uv", "run", "python", "-m", "collector"]

# ---- Chrome: system Chrome + Playwright Chrome channel ----
FROM base AS chrome

RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | \
    gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] \
    http://dl.google.com/linux/chrome/deb/ stable main" > \
    /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && apt-get install -y --no-install-recommends google-chrome-stable && \
    rm -rf /var/lib/apt/lists/*

RUN uv run playwright install --with-deps chrome && \
    dpkg --purge --force-depends xvfb x11-utils 2>/dev/null || true && \
    rm -rf /var/lib/apt/lists/*

# ---- Headless: Chrome in --headless mode (no display needed) ----
FROM chrome AS headless

# ---- Headful: Chrome + Xvfb for GUI rendering ----
FROM chrome AS headful

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgtk-3-0 xvfb x11-utils \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.headful.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

# ---- Headless Shell: stripped headless-only binary (no system Chrome) ----
FROM base AS headless-shell

RUN uv run playwright install --with-deps chromium-headless-shell

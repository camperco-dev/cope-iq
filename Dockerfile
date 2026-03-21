FROM python:3.11-slim

# Install system dependencies for Playwright Chromium + Xvfb virtual display.
# Xvfb is required because qPublic's Cloudflare protection blocks headless Chromium;
# running Chromium with a virtual display bypasses the bot fingerprinting check.
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright's Chromium browser.
RUN playwright install chromium

COPY . .

EXPOSE 8080

# Start Xvfb virtual display before launching the app.
# DISPLAY=:99 is used by Playwright's non-headless Chromium launch.
CMD Xvfb :99 -screen 0 1280x800x24 -ac +extension GLX +render -noreset & \
    export DISPLAY=:99 && \
    uvicorn main:app --host 0.0.0.0 --port 8080

# TRUE REAL Exness MT5 via Wine + MT5 terminal for Render free
# Based on xm-exness-mt5-linux - Docker with Wine MT5 + REST API for REAL trading
FROM python:3.11-slim

# Install Wine, Xvfb, and dependencies for MT5
RUN dpkg --add-architecture i386 && \
    apt-get update && \
    apt-get install -y \
    wget \
    curl \
    xvfb \
    wine64 \
    wine32 \
    winbind \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

# Set Wine environment
ENV WINEPREFIX=/root/.wine
ENV WINEARCH=win64
ENV DISPLAY=:99

# Create Wine prefix
RUN winecfg /v 2>&1 | head -20 || true

# Install Python dependencies
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir mt5linux || echo "mt5linux optional, will use MetaTrader5 if available"

# Try to install MetaTrader5 (only works on Windows, but try)
RUN pip install --no-cache-dir MetaTrader5 || echo "MetaTrader5 not available on Linux, using mt5linux + Wine"

# Copy app files
COPY . .

# Download MT5 terminal from MetaQuotes (for Exness)
# Exness MT5 download: https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe
# Or Exness specific: https://download.mql5.com/cdn/web/exness.technology/mt5/exness5setup.exe
RUN mkdir -p /tmp/mt5 && \
    cd /tmp/mt5 && \
    wget -q https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe -O mt5setup.exe || \
    wget -q https://download.mql5.com/cdn/web/exness.technology/mt5/exness5setup.exe -O mt5setup.exe || \
    echo "MT5 download failed, will try alternative" && \
    ls -lh

# Create startup script that runs Xvfb + Wine MT5 + FastAPI
RUN cat > /app/start.sh << 'START'
#!/bin/bash
set -e

echo "=== Starting TRUE REAL Exness MT5 via Wine ==="

# Start Xvfb for Wine GUI
echo "Starting Xvfb on :99..."
Xvfb :99 -screen 0 1024x768x24 > /tmp/xvfb.log 2>&1 &
XVFB_PID=$!
sleep 2

# Try to run MT5 terminal via Wine if exists
if [ -f "/tmp/mt5/mt5setup.exe" ]; then
    echo "Installing MT5 via Wine..."
    timeout 30 wine /tmp/mt5/mt5setup.exe /auto 2>&1 | head -20 || echo "MT5 setup timeout or failed, continuing"
fi

# Try to find and run MT5 terminal
MT5_PATHS=(
    "/root/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"
    "/root/.wine/drive_c/Program Files/MetaTrader 5/terminal.exe"
    "/root/.wine/drive_c/Program Files (x86)/MetaTrader 5/terminal64.exe"
)

for mt5_path in "${MT5_PATHS[@]}"; do
    if [ -f "$mt5_path" ]; then
        echo "Found MT5 at $mt5_path, starting via Wine..."
        wine "$mt5_path" /portable > /tmp/mt5.log 2>&1 &
        MT5_PID=$!
        echo "MT5 started PID $MT5_PID"
        sleep 5
        break
    fi
done

# If no MT5 found, try to use mt5linux container approach
echo "Checking for mt5linux..."
if python -c "import mt5linux" 2>/dev/null; then
    echo "mt5linux available - will use for REAL Exness if MT5 terminal running"
else
    echo "mt5linux not available, using fallback - Deriv REAL via WebSocket works without MT5"
fi

echo "=== Starting ASTRA6 FastAPI (REAL trading) ==="
echo "Exness REAL via MT5 Direct (if Wine MT5 running) + Deriv REAL via WebSocket (works free)"
echo "User gives login/server/password in BOT tab → auto-trading"

# Start FastAPI
exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1

START
RUN chmod +x /app/start.sh

# Expose port
EXPOSE 10000

# Use start.sh
CMD ["/app/start.sh"]

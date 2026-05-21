#!/bin/bash
echo "============================================"
echo "  TrueWeight Scale Bridge"
echo "  Ohaus Ranger Count 3000"
echo "============================================"
echo ""

# Move to script directory so relative paths work
cd "$(dirname "$0")"

# Optional: read COM port override from config file
COM_PORT=""
if [ -f "bridge-config.txt" ]; then
    COM_PORT=$(cat "bridge-config.txt" | tr -d '[:space:]')
fi

# Auto-install if venv doesn't exist
if [ ! -f "venv/bin/python3" ]; then
    echo "First run - setting up environment..."
    echo ""

    if ! command -v python3 &>/dev/null; then
        echo "[ERROR] Python 3 is not installed."
        echo ""
        echo "Install it with Homebrew:"
        echo "  brew install python"
        echo ""
        echo "Or download from: https://www.python.org/downloads/"
        read -p "Press Enter to close..."
        exit 1
    fi

    echo "Creating virtual environment..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to create virtual environment."
        read -p "Press Enter to close..."
        exit 1
    fi

    echo "Installing dependencies..."
    venv/bin/pip install "pyserial>=3.5" "websockets>=12.0" --quiet
    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to install dependencies."
        read -p "Press Enter to close..."
        exit 1
    fi

    echo ""
    echo "[OK] Setup complete!"
    echo ""
fi

if [ -n "$COM_PORT" ]; then
    echo "Scale port: $COM_PORT (from bridge-config.txt)"
else
    echo "Scale port: AUTO-DETECT"
fi
echo "To force a specific port, edit bridge-config.txt"
echo "  (e.g., /dev/tty.usbserial-1420)"
echo ""

# Kill any stale bridge processes holding port 8765
echo "Checking for stale bridge processes..."
PIDS=$(lsof -ti tcp:8765 2>/dev/null)
if [ -n "$PIDS" ]; then
    echo "Killing stale process(es) on port 8765: $PIDS"
    kill -9 $PIDS 2>/dev/null
    sleep 1
fi

echo "Starting bridge... (press Ctrl+C to stop)"
echo "Once connected, open https://trueweight.io"
echo ""
echo "============================================"
echo ""

if [ -n "$COM_PORT" ]; then
    venv/bin/python3 run.py --serial "$COM_PORT" --baud 9600 --verbose
else
    venv/bin/python3 run.py --baud 9600 --verbose
fi

echo ""
echo "Bridge stopped."
read -p "Press Enter to close..."

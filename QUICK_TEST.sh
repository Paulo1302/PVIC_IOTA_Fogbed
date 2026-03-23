#!/bin/bash

# 🚀 IOTA Automatic Transfer - Quick Test Script
# Usage: bash QUICK_TEST.sh

set -e

echo "=========================================="
echo "🚀 IOTA NETWORK - QUICK TEST"
echo "=========================================="
echo ""

REPO_DIR="/home/paulo/Documentos/PVIC_IOTA_Fogbed"
PYTHON_BIN="/opt/fogbed/venv/bin/python3"

# Check prerequisites
echo "📋 Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    echo "❌ Docker not found. Please install Docker."
    exit 1
fi
echo "  ✅ Docker found"

if ! command -v sudo &> /dev/null; then
    echo "❌ Sudo not found. Please install sudo."
    exit 1
fi
echo "  ✅ Sudo available"

if [ ! -d "$REPO_DIR" ]; then
    echo "❌ Repository not found at $REPO_DIR"
    exit 1
fi
echo "  ✅ Repository found"

if ! docker images | grep -q "iota-dev"; then
    echo "❌ Docker image 'iota-dev:latest' not found"
    echo "   Run: docker build -f docker/Dockerfile.local -t iota-dev:latest ."
    exit 1
fi
echo "  ✅ Docker image found"

if [ ! -f "$PYTHON_BIN" ]; then
    echo "⚠️  Fogbed Python not found at $PYTHON_BIN"
    echo "   Will use system Python3 instead"
    PYTHON_BIN="python3"
fi
echo "  ✅ Python found ($PYTHON_BIN)"

echo ""
echo "✅ All prerequisites satisfied!"
echo ""

# Cleanup
echo "🧹 Cleaning up previous runs..."
sudo mn -c 2>/dev/null || true
docker rm -f $(docker ps -aq --filter "name=mn.") 2>/dev/null || true
sleep 1
echo "  ✅ Cleanup completed"

echo ""
echo "🚀 Starting IOTA Network with Automatic Transfers..."
echo "   (This may take 30-60 seconds)"
echo ""

cd "$REPO_DIR"

# Run the example
sudo PYTHONPATH="$(pwd)" "$PYTHON_BIN" examples/04_auto_transfer_network.py

echo ""
echo "=========================================="
echo "✅ Test completed!"
echo "=========================================="

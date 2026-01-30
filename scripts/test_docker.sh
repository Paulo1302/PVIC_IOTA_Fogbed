#!/bin/bash
set -e

IMAGE_NAME="${1:-iota-dev}"

echo "🧪 Testing Docker image: ${IMAGE_NAME}"
echo ""

echo "1️⃣ Testing iota binary..."
docker run --rm ${IMAGE_NAME}:latest iota --version

echo ""
echo "2️⃣ Testing iota-node binary..."
docker run --rm ${IMAGE_NAME}:latest iota-node --version

echo ""
echo "3️⃣ Testing network tools..."
docker run --rm ${IMAGE_NAME}:latest ip addr show

echo ""
echo "4️⃣ Testing directory structure..."
docker run --rm ${IMAGE_NAME}:latest ls -la /app

echo ""
echo "✅ All tests passed!"

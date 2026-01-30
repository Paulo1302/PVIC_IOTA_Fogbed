#!/bin/bash
set -e

VERSION="${1:-v1.15.0}"
IMAGE_NAME="${2:-iota-dev}"

echo "🐳 Building IOTA Docker images for Fogbed..."
echo "   IOTA Version: ${VERSION}"
echo "   Image Name: ${IMAGE_NAME}"
echo ""

# Build produção
echo "📦 Building production image..."
docker build \
    --build-arg IOTA_VERSION="${VERSION}" \
    -t "${IMAGE_NAME}:latest" \
    -t "${IMAGE_NAME}:${VERSION}" \
    -f docker/Dockerfile \
    .

echo ""
echo "📦 Building development image..."
docker build \
    -t "${IMAGE_NAME}:dev" \
    -f docker/Dockerfile.dev \
    .

echo ""
echo "✅ Build completed!"
echo ""
echo "📋 Available images:"
docker images | grep "${IMAGE_NAME}"
echo ""
echo "🚀 Test with:"
echo "   docker run --rm ${IMAGE_NAME}:latest iota --version"

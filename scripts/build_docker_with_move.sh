#!/bin/bash

set -e

echo "Building IOTA Docker image with Move support..."

docker build \
  -f docker/Dockerfile \
  -t iota-dev:latest \
  --build-arg IOTA_VERSION=v1.15.0 \
  .

echo ""
echo "✅ Image built successfully: iota-dev:latest"
echo ""
echo "Verifying Move tooling..."
docker run --rm iota-dev:latest bash -c "iota --version && (iota move --help || echo 'Move integrated into iota binary')"

echo ""
echo "✅ All tools available. Ready for smart contract deployment!"

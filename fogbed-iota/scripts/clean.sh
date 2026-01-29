#!/bin/bash

echo "🧹 Cleaning project artifacts..."

# Python artifacts
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
find . -type f -name "*.pyo" -delete 2>/dev/null || true
find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true

# Build artifacts
rm -rf build/ dist/ .eggs/

# Test artifacts
rm -rf .pytest_cache/ .coverage htmlcov/ .tox/

# Docker artifacts
docker system prune -f

echo "✅ Cleanup completed!"

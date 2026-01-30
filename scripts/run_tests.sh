#!/bin/bash
set -e

echo "🧪 Running tests..."

# Unit tests
echo "Running unit tests..."
pytest tests/unit/ -v

# Integration tests
echo "Running integration tests..."
pytest tests/integration/ -v

# Coverage report
echo "Generating coverage report..."
pytest --cov=fogbed_iota --cov-report=html --cov-report=term

echo "✅ Tests completed!"
echo "   Coverage report: htmlcov/index.html"

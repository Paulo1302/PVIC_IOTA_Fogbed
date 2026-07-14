#!/bin/bash
set -e

echo "🧪 Running full test suite..."

# Run all tests and generate coverage report in a single pass
pytest tests/unit/ tests/integration/ -v --cov=fogbed_iota --cov-report=html --cov-report=term

echo ""
echo "✅ Tests completed successfully!"
echo "   Coverage report: htmlcov/index.html"

#!/bin/bash
set -e

echo "🔧 Setting up development environment..."

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements-dev.txt

# Install package in editable mode
pip install -e .

# Install pre-commit hooks
pre-commit install

echo "✅ Development environment ready!"
echo "   Activate with: source venv/bin/activate"

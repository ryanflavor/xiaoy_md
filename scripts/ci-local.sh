#!/bin/bash
set -e  # Exit on first failure

echo "🔍 Running local CI checks..."
echo "================================"

echo "📦 Installing dependencies..."
uv sync --frozen

echo ""
echo "🎨 Checking code format..."
uv run black --check src/ tests/ scripts/

echo ""
echo "🔤 Running type checks..."
uv run mypy src scripts tests

echo ""
echo "🏗️ Validating architecture..."
if [ -f scripts/check_architecture.py ]; then
    uv run python scripts/check_architecture.py
else
    echo "⚠️ Architecture validation script not found, skipping..."
fi

echo ""
echo "🧪 Running test suite..."
uv run pytest tests/ -v --tb=short --cov=src --cov-report=term-missing

echo ""
echo "================================"
echo "✅ All CI checks passed successfully!"
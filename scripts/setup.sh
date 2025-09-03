#!/bin/bash
set -e

echo "🔍 Detecting environment..."

# Detect OS
OS=$(uname -s)
ARCH=$(uname -m)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}📦 Setting up development environment for $OS/$ARCH${NC}"
echo "=================================================="

# Check Python version
echo -e "\n${YELLOW}Checking Python version...${NC}"
PYTHON_VERSION=$(python3 --version 2>&1 | grep -Po '(?<=Python )\d+\.\d+')
REQUIRED_VERSION="3.13"

if [ "$PYTHON_VERSION" != "$REQUIRED_VERSION" ]; then
    echo -e "${RED}❌ Python $REQUIRED_VERSION required, found $PYTHON_VERSION${NC}"
    echo "Please install Python 3.13:"
    echo "  Ubuntu/Debian: sudo apt install python3.13"
    echo "  macOS: brew install python@3.13"
    echo "  Or use pyenv: pyenv install 3.13.0"
    exit 1
fi
echo -e "${GREEN}✅ Python $PYTHON_VERSION found${NC}"

# Install uv if not present
echo -e "\n${YELLOW}Checking uv package manager...${NC}"
if ! command -v uv &> /dev/null; then
    echo "📥 Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
    echo -e "${GREEN}✅ uv installed successfully${NC}"
else
    echo -e "${GREEN}✅ uv is already installed${NC}"
fi

# Platform-specific configurations
case "$OS" in
    Darwin)
        echo -e "\n${YELLOW}🍎 Configuring for macOS...${NC}"
        # Check for Homebrew
        if ! command -v brew &> /dev/null; then
            echo "Homebrew not found. Some dependencies may need manual installation."
        fi
        ;;
    Linux)
        echo -e "\n${YELLOW}🐧 Configuring for Linux...${NC}"
        # Check for required packages
        if command -v apt &> /dev/null; then
            echo "Debian/Ubuntu detected"
        elif command -v yum &> /dev/null; then
            echo "RedHat/CentOS detected"
        fi
        ;;
esac

# Create project structure
echo -e "\n${YELLOW}📁 Verifying project structure...${NC}"
DIRS=("src/adapters" "src/domain" "src/application" "tests/unit" "tests/integration" "scripts")
for dir in "${DIRS[@]}"; do
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir"
        echo "  Created: $dir"
    else
        echo "  Exists: $dir"
    fi
done
echo -e "${GREEN}✅ Project structure verified${NC}"

# Install dependencies
echo -e "\n${YELLOW}📚 Installing dependencies...${NC}"
uv sync
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Dependencies installed successfully${NC}"
else
    echo -e "${RED}❌ Failed to install dependencies${NC}"
    exit 1
fi

# Run architecture validation
echo -e "\n${YELLOW}🏗️  Validating architecture...${NC}"
python3 scripts/check_architecture.py
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Architecture validation passed${NC}"
else
    echo -e "${YELLOW}⚠️  Architecture validation has warnings (expected for initial setup)${NC}"
fi

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo -e "\n${YELLOW}📝 Creating .env file...${NC}"
    cat > .env << 'EOF'
# Application
APP_NAME=market-data-service
ENVIRONMENT=development
DEBUG=true

# Server
HOST=0.0.0.0
PORT=8000

# NATS
NATS_URL=nats://localhost:4222
NATS_CLUSTER_ID=market-data-cluster

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
EOF
    echo -e "${GREEN}✅ .env file created${NC}"
else
    echo -e "\n${GREEN}✅ .env file already exists${NC}"
fi

# Display next steps
echo -e "\n${GREEN}=================================================="
echo -e "✨ Environment setup complete!${NC}"
echo -e "\n${YELLOW}Next steps:${NC}"
echo "1. Activate the virtual environment:"
echo "   source .venv/bin/activate"
echo ""
echo "2. Run the application:"
echo "   uv run python -m src"
echo ""
echo "3. Run tests:"
echo "   uv run pytest"
echo ""
echo "4. Check code formatting:"
echo "   uv run black --check src tests"
echo ""
echo "5. Run type checking:"
echo "   uv run mypy src"
echo ""
echo -e "${GREEN}Happy coding! 🚀${NC}"
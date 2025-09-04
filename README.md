# Market Data Service

![CI Status](https://github.com/yourorg/market-data-service/workflows/Code%20Quality%20CI/badge.svg)

A high-performance market data service built with Python 3.13 using hexagonal architecture principles.

## Features

- **Hexagonal Architecture**: Clean separation of business logic from infrastructure
- **High Performance**: Asynchronous processing with Python 3.13's improved async capabilities
- **NATS Integration**: Real-time message streaming and pub/sub patterns
- **Type Safety**: Strict type checking with Mypy and Pydantic models
- **Test-Driven Development**: Comprehensive test suite with pytest
- **Docker Support**: Containerized deployment for consistency

## Prerequisites

- **Python 3.13**: Required (exact version)
- **uv**: Package manager (will be installed if not present)
- **Git**: Version control
- **Docker** (optional): For containerized development

## Quick Start

### 1. Install uv (if not already installed)

```bash
# Linux/macOS
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
irm https://astral.sh/uv/install.ps1 | iex
```

After installation, restart your terminal or add uv to your PATH:
```bash
export PATH="$HOME/.cargo/bin:$PATH"  # Linux/macOS
```

### 2. Clone the Repository

```bash
git clone https://github.com/yourorg/market-data-service.git
cd market-data-service
```

### 3. Set Up the Development Environment

```bash
# Install dependencies and create virtual environment
uv sync

# Activate the virtual environment (optional, uv handles this automatically)
source .venv/bin/activate  # Linux/macOS
# or
.venv\Scripts\activate  # Windows
```

### 4. Run the Onboarding Wizard (Recommended)

```bash
python scripts/onboard.py
```

This will verify your environment and guide you through the setup process.

## Development Workflow

### Running the Application

```bash
# Using uv (recommended)
uv run python -m src

# Or with activated venv
python -m src
```

### Code Formatting

```bash
# Format code with Black
uv run black src tests

# Check formatting without making changes
uv run black --check src tests
```

### Type Checking

```bash
# Run type checking with Mypy
uv run mypy src

# Type check with strict settings (default in our config)
uv run mypy --strict src
```

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src

# Run specific test categories
uv run pytest -m unit        # Unit tests only
uv run pytest -m integration # Integration tests only
```

### Architecture Validation

```bash
# Check hexagonal architecture boundaries
python scripts/check_architecture.py

# Generate dependency graph
python scripts/visualize_architecture.py
```

### Running CI Checks Locally

To run the same checks that CI performs before pushing code:

```bash
# Run all CI checks in sequence
uv sync --frozen                              # Install exact dependencies
uv run black --check src/ tests/ scripts/     # Check code formatting
uv run mypy src scripts                       # Type checking (excludes tests per config)
uv run python scripts/check_architecture.py   # Architecture validation
uv run pytest tests/ -v --cov=src             # Run test suite with coverage

# Or create a local CI script
echo '#!/bin/bash
set -e  # Exit on first failure
echo "Installing dependencies..."
uv sync --frozen
echo "Checking code format..."
uv run black --check src/ tests/ scripts/
echo "Running type checks..."
uv run mypy src/ tests/ scripts/
echo "Validating architecture..."
uv run python scripts/check_architecture.py
echo "Running tests..."
uv run pytest tests/ -v --cov=src
echo "✅ All CI checks passed!"
' > scripts/ci-local.sh
chmod +x scripts/ci-local.sh

# Then run with:
./scripts/ci-local.sh
```

## Project Structure

```
market-data-service/
├── .github/              # GitHub Actions workflows
├── docs/                 # Documentation
├── scripts/              # Development and deployment scripts
│   ├── check_architecture.py
│   ├── onboard.py
│   └── setup.sh
├── src/                  # Source code
│   ├── adapters/         # External interfaces (DB, API, Message Queue)
│   ├── application/      # Use cases and application services
│   ├── domain/           # Business logic and entities
│   ├── config.py         # Configuration management
│   └── __main__.py       # Application entry point
├── tests/                # Test suite
│   ├── integration/      # Integration tests
│   └── unit/            # Unit tests
├── .gitignore           # Git ignore patterns
├── .pre-commit-config.yaml  # Pre-commit hooks
├── docker-compose.yml    # Docker services configuration
├── Dockerfile           # Container definition
├── pyproject.toml       # Project configuration and dependencies
└── README.md            # This file
```

## Architecture

This project follows **Hexagonal Architecture** (Ports and Adapters) principles:

- **Domain Layer**: Pure business logic with no external dependencies
- **Application Layer**: Use cases that orchestrate domain logic
- **Adapters Layer**: Implementations of external interfaces

### Key Principles

1. **Dependency Rule**: Dependencies only point inward (adapters → application → domain)
2. **Immutable Domain Objects**: Core business entities are immutable
3. **Port Interfaces**: All external dependencies are abstracted behind interfaces
4. **Test-Driven Development**: Write tests first, then implementation

## Configuration

The application uses environment variables for configuration. Create a `.env` file:

```env
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
```

## Docker Development

### Using Docker Compose

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

### Building the Docker Image

```bash
# Build development image
docker build -f Dockerfile.dev -t market-data-service:dev .

# Build production image
docker build -t market-data-service:latest .
```

## Dependency Management

### Adding Dependencies

```bash
# Add a production dependency
uv add package-name

# Add a development dependency
uv add --dev package-name

# Add with version constraint
uv add "package-name>=1.0.0,<2.0.0"
```

### Updating Dependencies

```bash
# Update all dependencies
uv sync --upgrade

# Update specific package
uv add package-name@latest
```

### Lock File

The `uv.lock` file ensures reproducible builds. Always commit this file:

```bash
# Regenerate lock file
uv pip compile pyproject.toml -o uv.lock

# Install from lock file
uv sync --frozen
```

## Troubleshooting

### Common Issues

#### Python Version Mismatch
```bash
# Error: Python 3.13 required
# Solution: Install Python 3.13
sudo apt update && sudo apt install python3.13  # Ubuntu/Debian
# Or use pyenv:
pyenv install 3.13.0
pyenv local 3.13.0
```

#### uv Command Not Found
```bash
# Add uv to PATH
export PATH="$HOME/.cargo/bin:$PATH"
# Add to ~/.bashrc or ~/.zshrc for persistence
```

#### Import Errors After Setup
```bash
# Clear cache and reinstall
uv cache clean
uv sync --refresh
```

#### Architecture Validation Failures
```bash
# Check for layer violations
python scripts/check_architecture.py
# Fix imports according to hexagonal architecture rules
```

## Contributing

1. Create a feature branch from `main`
2. Follow TDD: Write tests first
3. Ensure all tests pass: `uv run pytest`
4. Format code: `uv run black src tests`
5. Type check: `uv run mypy src`
6. Validate architecture: `python scripts/check_architecture.py`
7. Create a pull request

## Pre-commit Hooks

Install pre-commit hooks to ensure code quality:

```bash
# Install pre-commit
uv add --dev pre-commit

# Set up hooks
uv run pre-commit install

# Run hooks manually
uv run pre-commit run --all-files
```

## Performance Considerations

- Python 3.13 provides ~15-20% better async performance
- Use `asyncio.TaskGroup` for concurrent operations
- Leverage Pydantic's validation for data integrity
- NATS JetStream for persistent messaging

## Documentation

- Architecture details: `docs/architecture/`
- API documentation: Run `uv run mkdocs serve`
- PRD: `docs/prd.md`
- QA assessments: `docs/qa/`

## Support

- Issues: [GitHub Issues](https://github.com/yourorg/market-data-service/issues)
- Wiki: `docs/wiki/`
- Slack: #market-data-team

## License

MIT License - see LICENSE file for details

## Acknowledgments

- Built with Python 3.13 and uv
- Follows hexagonal architecture principles
- Inspired by Domain-Driven Design
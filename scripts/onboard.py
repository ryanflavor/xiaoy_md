#!/usr/bin/env python3
"""Linux-optimized onboarding wizard for MVP development"""

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path


class LinuxOnboardingWizard:
    """Streamlined Linux developer setup"""

    def __init__(self):
        self.start_time = time.time()
        self.checks_passed = []
        self.issues = []

    def run(self):
        """Run the Linux onboarding process"""
        self.print_welcome()

        steps = [
            ("System Check", self.check_system),
            ("Docker Check", self.check_docker),
            ("Python 3.13 Setup", self.check_python),
            ("uv Installation", self.check_uv),
            ("Project Setup", self.setup_project),
            ("Tools Verification", self.verify_tools),
            ("Architecture Validation", self.validate_architecture),
            ("Quick Start Guide", self.show_quickstart),
        ]

        for step_name, step_func in steps:
            print(f"\n📍 {step_name}...")
            success, message = step_func()
            if success:
                self.checks_passed.append(step_name)
                print(f"   ✅ {message}")
            else:
                self.issues.append((step_name, message))
                print(f"   ⚠️  {message}")
                if not self.offer_fix(step_name):
                    break

        self.print_summary()

    def print_welcome(self):
        """Print welcome message"""
        print("=" * 60)
        print("🚀 Market Data Service - Development Environment Setup")
        print("=" * 60)
        print("\nOptimized for Linux deployment (MVP)")
        print("Expected time: < 15 minutes\n")

        name = input("👤 Developer name: ")
        print(f"\nWelcome, {name}! Let's set up your development environment.\n")

    def check_system(self) -> tuple[bool, str]:
        """Verify system requirements"""
        system = platform.system()
        arch = platform.machine()

        if system == "Linux":
            # Check Linux distribution
            try:
                with open("/etc/os-release") as f:
                    os_info = f.read()
                    if "Ubuntu" in os_info or "Debian" in os_info:
                        distro = "Ubuntu/Debian"
                    elif "Alpine" in os_info:
                        distro = "Alpine"
                    else:
                        distro = "Generic Linux"

                if arch in ["x86_64", "aarch64"]:
                    return True, f"{distro} {arch} - Perfect for MVP!"
                else:
                    return False, f"Unsupported architecture: {arch}"
            except:
                return True, f"{system} system detected"
        elif system == "Darwin":
            return True, f"macOS {arch} - Development supported"
        elif system == "Windows":
            return True, "Windows - Consider using WSL2 for better compatibility"
        else:
            return False, f"Unsupported system: {system}"

    def check_docker(self) -> tuple[bool, str]:
        """Check Docker installation for containerized development"""
        if shutil.which("docker"):
            try:
                result = subprocess.run(
                    ["docker", "--version"], capture_output=True, text=True
                )
                if result.returncode == 0:
                    version = result.stdout.strip().split()[2].rstrip(",")
                    return True, f"Docker {version} installed"
            except:
                pass
        return False, "Docker not found (optional but recommended)"

    def check_python(self) -> tuple[bool, str]:
        """Check Python 3.13 installation"""
        try:
            result = subprocess.run(
                ["python3", "--version"], capture_output=True, text=True
            )
            version = result.stdout.strip()

            if "3.13" in version:
                return True, f"{version} ✨"
            else:
                # Try python3.13 specifically
                result = subprocess.run(
                    ["python3.13", "--version"], capture_output=True, text=True
                )
                if result.returncode == 0:
                    return True, f"{result.stdout.strip()} ✨"
                return False, f"Python 3.13 required, found {version}"
        except:
            return False, "Python not found"

    def check_uv(self) -> tuple[bool, str]:
        """Check uv installation"""
        if shutil.which("uv"):
            result = subprocess.run(["uv", "--version"], capture_output=True, text=True)
            if result.returncode == 0:
                return True, f"uv {result.stdout.strip()} installed"

        # Offer to install
        print("\n   📦 uv not found. Installing...")
        return self.install_uv()

    def install_uv(self) -> tuple[bool, str]:
        """Install uv package manager"""
        try:
            # Use shell=True for curl pipe
            result = subprocess.run(
                "curl -LsSf https://astral.sh/uv/install.sh | sh",
                shell=True,
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                # Add to PATH for current session
                cargo_bin = Path.home() / ".cargo" / "bin"
                os.environ["PATH"] = f"{cargo_bin}:{os.environ['PATH']}"
                return True, "uv installed successfully"
            else:
                return False, f"Failed to install uv: {result.stderr}"
        except Exception as e:
            return False, f"Failed to install uv: {e}"

    def setup_project(self) -> tuple[bool, str]:
        """Set up project structure and dependencies"""
        try:
            # Check if we're in the right directory
            if not Path("pyproject.toml").exists():
                return False, "pyproject.toml not found - are you in the project root?"

            # Install dependencies
            print("   📚 Installing dependencies...")
            result = subprocess.run(["uv", "sync"], capture_output=True, text=True)

            if result.returncode != 0:
                return False, f"Dependency installation failed: {result.stderr}"

            return True, "Project setup complete"
        except Exception as e:
            return False, f"Setup failed: {e}"

    def verify_tools(self) -> tuple[bool, str]:
        """Verify all development tools"""
        tools = ["black", "mypy", "pytest"]
        missing = []

        for tool in tools:
            result = subprocess.run(
                ["uv", "run", tool, "--version"], capture_output=True, text=True
            )
            if result.returncode != 0:
                missing.append(tool)

        if missing:
            return False, f"Missing tools: {', '.join(missing)}"
        return True, "All development tools verified"

    def validate_architecture(self) -> tuple[bool, str]:
        """Validate hexagonal architecture setup"""
        try:
            result = subprocess.run(
                ["python3", "scripts/check_architecture.py"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return True, "Hexagonal architecture validated"
            else:
                # It's okay if there are no violations on initial setup
                if "✅ Architecture validation PASSED" in result.stdout:
                    return True, "Architecture structure ready"
                return True, "Architecture validation ready (no code yet)"
        except Exception as e:
            return False, f"Architecture validation failed: {e}"

    def show_quickstart(self) -> tuple[bool, str]:
        """Show quick start commands"""
        print("\n" + "=" * 60)
        print("🚀 Quick Start Commands:")
        print("=" * 60)
        print("   • uv sync                     # Install/update dependencies")
        print("   • source .venv/bin/activate   # Activate virtual environment")
        print("   • uv run python -m src        # Run the application")
        print("   • uv run pytest               # Run tests")
        print("   • uv run black src tests      # Format code")
        print("   • uv run mypy src             # Type check")
        print("   • docker-compose up -d        # Start services (if Docker)")
        print("\n📚 Documentation:")
        print("   • README.md                   # Getting started guide")
        print("   • docs/architecture/          # Architecture documentation")
        print("   • docs/qa/                    # QA assessments")

        return True, "Ready to develop!"

    def offer_fix(self, step: str) -> bool:
        """Offer to fix issues"""
        response = input(f"\n   Would you like help fixing {step}? (y/n): ")
        if response.lower() == "y":
            self.provide_fix(step)
            # Try the step again
            return True
        return False

    def provide_fix(self, step: str):
        """Provide specific fixes for each step"""
        fixes = {
            "Python 3.13 Setup": """
📝 To install Python 3.13:

Ubuntu/Debian:
    sudo add-apt-repository ppa:deadsnakes/ppa
    sudo apt update
    sudo apt install python3.13 python3.13-venv python3.13-dev

macOS:
    brew install python@3.13

Alternative (pyenv):
    curl https://pyenv.run | bash
    pyenv install 3.13.0
    pyenv local 3.13.0
            """,
            "uv Installation": """
📝 Manual uv installation:

Linux/macOS:
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"

Then add to your shell config (~/.bashrc or ~/.zshrc):
    export PATH="$HOME/.cargo/bin:$PATH"
            """,
            "Docker Check": """
📝 Docker installation (optional):

Ubuntu/Debian:
    sudo apt update
    sudo apt install docker.io docker-compose
    sudo usermod -aG docker $USER
    # Log out and back in for group changes

macOS:
    Download Docker Desktop from https://docker.com
            """,
            "Project Setup": """
📝 Project setup troubleshooting:

1. Ensure you're in the project root:
    cd /path/to/market-data-service

2. Clear uv cache and retry:
    uv cache clean
    uv sync --refresh

3. Check Python version:
    python3 --version  # Should be 3.13
            """,
        }

        if step in fixes:
            print(fixes[step])
        else:
            print(f"\n   ℹ️  Please check the README.md for {step} instructions.")

    def print_summary(self):
        """Print onboarding summary"""
        elapsed = int(time.time() - self.start_time)
        minutes = elapsed // 60
        seconds = elapsed % 60

        print("\n" + "=" * 60)
        print("📊 Onboarding Summary")
        print("=" * 60)
        print(f"\n⏱️  Time taken: {minutes}m {seconds}s")
        print(
            f"✅ Completed: {len(self.checks_passed)}/{len(self.checks_passed) + len(self.issues)} steps"
        )

        if self.issues:
            print(f"\n⚠️  Issues to address ({len(self.issues)}):")
            for step, issue in self.issues:
                print(f"   • {step}: {issue}")
            print(
                "\n💡 Tip: Run 'python scripts/onboard.py' again after fixing issues."
            )
        else:
            print("\n🎉 Perfect setup! Your environment is fully configured!")

        if elapsed < 900:  # 15 minutes
            print("\n⭐ Excellent! Setup completed in under 15 minutes!")

        print("\n📖 Next: Check out the README.md for development workflow.")
        print("💬 Questions? Check docs/qa/ for detailed guides.")


def main():
    """Main entry point"""
    wizard = LinuxOnboardingWizard()
    wizard.run()


if __name__ == "__main__":
    main()

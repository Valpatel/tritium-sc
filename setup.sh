#!/bin/bash
#
# TRITIUM-SC Setup Script
# Security Camera Intelligence Platform
#
# Usage: ./setup.sh [command]
#   install     - Full installation (Python venv, deps, database)
#   deps        - Install Python dependencies only
#   db          - Initialize database only
#   ml          - Install ML dependencies (YOLO, PyTorch)
#   dev         - Start development server
#   docker      - Build and start Docker containers
#   test        - Run tests
#   clean       - Clean up temporary files
#   sync        - Run NVR sync script (original functionality)
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
export PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

# Colors
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${CYAN}[TRITIUM-SC]${NC} $*"; }
success() { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*"; exit 1; }

# Check Python version
check_python() {
    if ! command -v python3 &> /dev/null; then
        error "Python 3 is required but not installed"
    fi

    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    log "Python version: $PYTHON_VERSION"
}

# Create virtual environment
create_venv() {
    if [[ ! -d ".venv" ]]; then
        log "Creating virtual environment..."
        python3 -m venv .venv
        success "Virtual environment created"
    else
        log "Virtual environment already exists"
    fi
}

# Install base dependencies
install_deps() {
    log "Installing Python dependencies..."
    source .venv/bin/activate
    pip install --upgrade pip -q
    pip install -r requirements.txt -q
    success "Base dependencies installed"
}

# Install ML dependencies (YOLO, PyTorch, etc.)
install_ml() {
    log "Installing ML dependencies (this may take a while)..."
    source .venv/bin/activate

    # Check for CUDA
    if command -v nvidia-smi &> /dev/null; then
        log "NVIDIA GPU detected, installing CUDA-enabled PyTorch..."
        pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121 -q
    else
        log "No NVIDIA GPU detected, installing CPU-only PyTorch..."
        pip install torch torchvision -q
    fi

    pip install ultralytics opencv-python-headless numpy supervision -q
    success "ML dependencies installed"

    # Download YOLO model
    log "Downloading YOLOv8 model..."
    python3 -c "from ultralytics import YOLO; YOLO('yolov8n.pt')" 2>/dev/null
    success "YOLOv8 model downloaded"
}

# Initialize database
init_db() {
    log "Initializing database..."
    source .venv/bin/activate
    python3 -c "
import asyncio
from app.database import init_db
asyncio.run(init_db())
print('Database initialized')
"
    success "Database initialized"
}

# Start development server
start_dev() {
    log "Starting development server..."
    source .venv/bin/activate
    python run.py --reload
}

# Start production server
start_prod() {
    log "Starting production server..."
    source .venv/bin/activate
    python run.py --workers 4
}

# Docker commands
docker_build() {
    log "Building Docker image..."
    docker-compose build
    success "Docker image built"
}

docker_up() {
    log "Starting Docker containers..."
    docker-compose up -d
    success "Containers started"
}

docker_down() {
    log "Stopping Docker containers..."
    docker-compose down
    success "Containers stopped"
}

# Run tests
run_tests() {
    log "Running tests..."
    source .venv/bin/activate
    pip install pytest pytest-asyncio -q
    pytest tests/ -v
}

# Run NVR sync
run_sync() {
    log "Running NVR sync..."
    if [[ -f "$SCRIPT_DIR/sync-cameras.sh" ]]; then
        "$SCRIPT_DIR/sync-cameras.sh"
    else
        error "sync-cameras.sh not found"
    fi
}

# Clean up
clean() {
    log "Cleaning up..."
    rm -rf __pycache__ .pytest_cache
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    success "Cleanup complete"
}

# Full installation
full_install() {
    log "Starting full installation..."
    echo ""
    echo "  ████████╗██████╗ ██╗████████╗██╗██╗   ██╗███╗   ███╗"
    echo "  ╚══██╔══╝██╔══██╗██║╚══██╔══╝██║██║   ██║████╗ ████║"
    echo "     ██║   ██████╔╝██║   ██║   ██║██║   ██║██╔████╔██║"
    echo "     ██║   ██╔══██╗██║   ██║   ██║██║   ██║██║╚██╔╝██║"
    echo "     ██║   ██║  ██║██║   ██║   ██║╚██████╔╝██║ ╚═╝ ██║"
    echo "     ╚═╝   ╚═╝  ╚═╝╚═╝   ╚═╝   ╚═╝ ╚═════╝ ╚═╝     ╚═╝-SC"
    echo ""

    check_python
    create_venv
    install_deps
    install_ml
    init_db

    echo ""
    success "Installation complete!"
    echo ""
    log "To start the server:"
    echo "    ./setup.sh dev     # Development mode with auto-reload"
    echo "    ./setup.sh prod    # Production mode"
    echo ""
    log "Or manually:"
    echo "    source .venv/bin/activate"
    echo "    python run.py"
    echo ""
}

# Show help
show_help() {
    echo "TRITIUM-SC Setup Script"
    echo "Security Camera Intelligence Platform"
    echo ""
    echo "Usage: ./setup.sh [command]"
    echo ""
    echo "Commands:"
    echo "  install     Full installation (venv, deps, ML, database)"
    echo "  deps        Install Python dependencies only"
    echo "  ml          Install ML dependencies (YOLO, PyTorch)"
    echo "  db          Initialize database only"
    echo "  dev         Start development server (with auto-reload)"
    echo "  prod        Start production server"
    echo "  docker      Build and start Docker containers"
    echo "  docker-down Stop Docker containers"
    echo "  sync        Run NVR sync script"
    echo "  test        Run tests"
    echo "  clean       Clean up temporary files"
    echo "  help        Show this help message"
    echo ""
}

# Main
case "${1:-help}" in
    install)    full_install ;;
    deps)       create_venv && install_deps ;;
    ml)         install_ml ;;
    db)         init_db ;;
    dev)        start_dev ;;
    prod)       start_prod ;;
    docker)     docker_build && docker_up ;;
    docker-down) docker_down ;;
    sync)       run_sync ;;
    test)       run_tests ;;
    clean)      clean ;;
    help|--help|-h) show_help ;;
    *)          error "Unknown command: $1. Use './setup.sh help' for usage." ;;
esac

#!/bin/bash
# =============================================================
# deploy.sh — Redeploy script for crypto-screener on VPS
#
# Usage:
#   ./deploy.sh              → git pull + docker compose up (default)
#   ./deploy.sh --install    → git pull + pip install + docker compose up
#   ./deploy.sh --build      → git pull + docker compose up --build (force rebuild)
#   ./deploy.sh --full       → git pull + pip install + docker compose up --build
#   ./deploy.sh --local      → pip install only (no git, no docker)
# =============================================================

set -e  # Exit immediately on error

# ── Colors ────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ── Helpers ───────────────────────────────────────────────────
log()     { echo -e "${BLUE}[deploy]${NC} $1"; }
success() { echo -e "${GREEN}[✓]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }
error()   { echo -e "${RED}[✗]${NC} $1"; exit 1; }

# ── Parse flags ───────────────────────────────────────────────
DO_GIT=true
DO_INSTALL=false
DO_BUILD=false

case "$1" in
  --install)
    DO_GIT=true
    DO_INSTALL=true
    DO_BUILD=false
    ;;
  --build)
    DO_GIT=true
    DO_INSTALL=false
    DO_BUILD=true
    ;;
  --full)
    DO_GIT=true
    DO_INSTALL=true
    DO_BUILD=true
    ;;
  --local)
    DO_GIT=false
    DO_INSTALL=true
    DO_BUILD=false
    ;;
  "")
    # default: git + docker up (no rebuild)
    ;;
  *)
    echo "Usage: $0 [--install | --build | --full | --local]"
    echo ""
    echo "  (no flag)   git pull + docker compose up -d"
    echo "  --install   git pull + pip install + docker compose up -d"
    echo "  --build     git pull + docker compose up -d --build"
    echo "  --full      git pull + pip install + docker compose up -d --build"
    echo "  --local     pip install only (no git, no docker)"
    exit 1
    ;;
esac

# ── Working directory ─────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
log "Working directory: $SCRIPT_DIR"

# ── Step 1: Git ───────────────────────────────────────────────
if [ "$DO_GIT" = true ]; then
  log "Fetching latest changes from remote..."
  git fetch origin
  success "git fetch done"

  log "Pulling origin main..."
  git pull origin main
  success "git pull done"
fi

# ── Step 2: pip install ───────────────────────────────────────
if [ "$DO_INSTALL" = true ]; then
  log "Installing Python dependencies..."

  if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
    success "requirements.txt installed"
  else
    warn "requirements.txt not found — skipping"
  fi

  if [ -f "requirements-dev.txt" ]; then
    read -p "  Install dev dependencies? (requirements-dev.txt) [y/N]: " install_dev
    if [[ "$install_dev" =~ ^[Yy]$ ]]; then
      pip install -r requirements-dev.txt
      success "requirements-dev.txt installed"
    fi
  fi
fi

# ── Step 3: Docker ────────────────────────────────────────────
if [ "$DO_GIT" = true ] || [ "$DO_BUILD" = true ]; then
  # Check if docker compose is available
  if ! command -v docker &> /dev/null; then
    error "docker not found. Please install Docker first."
  fi

  # Support both 'docker compose' (v2) and 'docker-compose' (v1)
  if docker compose version &> /dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
  elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
  else
    error "Neither 'docker compose' nor 'docker-compose' found."
  fi

  log "Stopping existing containers..."
  $COMPOSE_CMD down
  success "Containers stopped"

  if [ "$DO_BUILD" = true ]; then
    log "Building and starting containers (--build)..."
    $COMPOSE_CMD up -d --build
  else
    log "Starting containers..."
    $COMPOSE_CMD up -d
  fi

  success "Containers started"

  # ── Health check ──────────────────────────────────────────
  log "Waiting for API to be healthy..."
  RETRIES=10
  for i in $(seq 1 $RETRIES); do
    sleep 3
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/health 2>/dev/null || echo "000")
    if [ "$HTTP_STATUS" = "200" ]; then
      success "API is healthy (HTTP 200)"
      break
    fi
    if [ "$i" = "$RETRIES" ]; then
      warn "API health check timed out after ${RETRIES} retries — check logs with: docker logs crypto-screener-api"
    else
      warn "Attempt $i/$RETRIES: HTTP $HTTP_STATUS — retrying..."
    fi
  done

  # ── Show logs ─────────────────────────────────────────────
  echo ""
  log "Last 20 lines of container logs:"
  echo "────────────────────────────────"
  $COMPOSE_CMD logs --tail=20
fi

echo ""
success "Deploy complete!"

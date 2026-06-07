#!/usr/bin/env bash
# install_vps.sh — Instalação idempotente do EVE Autônomo em VPS limpa.
#
# Requerimentos: Ubuntu 22.04 / Debian 12. Deve rodar como root ou com sudo.
# Uso:
#   sudo bash scripts/install_vps.sh [--repo URL] [--dir PATH] [--skip-docker]
#
# Idempotência: cada passo verifica se já está feito antes de executar.
# Shellcheck: deve passar sem erros (SC2086 suprimido onde necessário).

set -euo pipefail

# ---------------------------------------------------------------------------
# Variáveis configuráveis
# ---------------------------------------------------------------------------

REPO_URL="${REPO_URL:-https://github.com/engsathiago/EVE_Autonomo.git}"
INSTALL_DIR="${INSTALL_DIR:-/opt/eve}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
AGENT_USER="${AGENT_USER:-eve}"
WEB_TOKEN_FILE="${WEB_TOKEN_FILE:-/etc/eve/web_token}"
LOG_FILE="/var/log/install_vps.sh.log"

# ---------------------------------------------------------------------------
# Cores e helpers
# ---------------------------------------------------------------------------

_red()    { printf '\033[31m%s\033[0m\n' "$*"; }
_green()  { printf '\033[32m%s\033[0m\n' "$*"; }
_yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
_info()   { _green  "[INFO]  $*" | tee -a "$LOG_FILE"; }
_warn()   { _yellow "[WARN]  $*" | tee -a "$LOG_FILE"; }
_err()    { _red    "[ERROR] $*" | tee -a "$LOG_FILE"; exit 1; }
_step()   { echo    ""           | tee -a "$LOG_FILE"; _green "==> $*" | tee -a "$LOG_FILE"; }

_require_root() {
    if [[ $EUID -ne 0 ]]; then
        _err "Este script requer root. Use: sudo bash $0"
    fi
}

_cmd_exists() { command -v "$1" &>/dev/null; }

# ---------------------------------------------------------------------------
# Argparse mínimo
# ---------------------------------------------------------------------------

SKIP_DOCKER=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)     REPO_URL="$2";    shift 2 ;;
        --dir)      INSTALL_DIR="$2"; shift 2 ;;
        --skip-docker) SKIP_DOCKER=1; shift ;;
        *) _warn "Argumento desconhecido: $1"; shift ;;
    esac
done

# ---------------------------------------------------------------------------
# Passo 0: pré-flight
# ---------------------------------------------------------------------------

_require_root

mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"

_info "EVE Autônomo — install_vps.sh"
_info "Repo:    $REPO_URL"
_info "Dir:     $INSTALL_DIR"
_info "Compose: $COMPOSE_FILE"
_info "Log:     $LOG_FILE"

# Detecta distro
if [[ -f /etc/os-release ]]; then
    # shellcheck source=/dev/null
    source /etc/os-release
    _info "Distro: ${PRETTY_NAME:-desconhecida}"
else
    _warn "Não foi possível detectar distro — assumindo Ubuntu/Debian."
fi

# ---------------------------------------------------------------------------
# Passo 1: Dependências de sistema
# ---------------------------------------------------------------------------

_step "1. Dependências de sistema (git, curl, ca-certificates)"

apt-get update -qq

PKGS_NEEDED=()
for pkg in git curl ca-certificates gnupg lsb-release ufw; do
    if ! dpkg -l "$pkg" 2>/dev/null | grep -q '^ii'; then
        PKGS_NEEDED+=("$pkg")
    fi
done

if [[ ${#PKGS_NEEDED[@]} -gt 0 ]]; then
    _info "Instalando: ${PKGS_NEEDED[*]}"
    apt-get install -y -q "${PKGS_NEEDED[@]}"
else
    _info "Dependências já instaladas."
fi

# ---------------------------------------------------------------------------
# Passo 2: Docker Engine
# ---------------------------------------------------------------------------

_step "2. Docker Engine + Compose plugin"

if [[ $SKIP_DOCKER -eq 1 ]]; then
    _info "--skip-docker: pulando instalação do Docker."
elif _cmd_exists docker && docker compose version &>/dev/null; then
    _info "Docker e Compose plugin já instalados: $(docker --version)"
else
    _info "Instalando Docker Engine..."

    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL "https://download.docker.com/linux/${ID:-ubuntu}/gpg" \
        -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc

    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/${ID:-ubuntu} \
$(lsb_release -cs) stable" \
        > /etc/apt/sources.list.d/docker.list

    apt-get update -qq
    apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin

    systemctl enable --now docker
    _info "Docker instalado: $(docker --version)"
fi

# ---------------------------------------------------------------------------
# Passo 3: Clonar ou atualizar repositório
# ---------------------------------------------------------------------------

_step "3. Repositório em $INSTALL_DIR"

if [[ -d "$INSTALL_DIR/.git" ]]; then
    _info "Repositório já existe — atualizando..."
    git -C "$INSTALL_DIR" pull --ff-only
else
    _info "Clonando $REPO_URL em $INSTALL_DIR..."
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

# ---------------------------------------------------------------------------
# Passo 4: Configurar .env
# ---------------------------------------------------------------------------

_step "4. Arquivo .env"

ENV_FILE="$INSTALL_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
    _info ".env já existe — mantendo sem sobrescrever."
else
    cp "$INSTALL_DIR/.env.example" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    _warn ".env criado a partir de .env.example."
    _warn "Edite $ENV_FILE antes de continuar:"
    _warn "  ANTHROPIC_API_KEY, POSTGRES_PASSWORD, (TELEGRAM_BOT_TOKEN)"
    echo ""
    read -r -p "Pressione ENTER após editar .env ou Ctrl+C para abortar... "
fi

# Valida que POSTGRES_PASSWORD não é vazio
if ! grep -qE "^POSTGRES_PASSWORD=.+" "$ENV_FILE"; then
    _err "POSTGRES_PASSWORD está vazio em $ENV_FILE. Configure antes de continuar."
fi

# ---------------------------------------------------------------------------
# Passo 5: Firewall (UFW)
# ---------------------------------------------------------------------------

_step "5. Firewall (UFW)"

if _cmd_exists ufw; then
    ufw --force reset    &>/dev/null || true
    ufw default deny incoming &>/dev/null
    ufw default allow outgoing &>/dev/null

    ufw allow ssh        comment "SSH"           &>/dev/null
    ufw allow 80/tcp     comment "HTTP"          &>/dev/null
    ufw allow 443/tcp    comment "HTTPS"         &>/dev/null
    # Gateway e core acessíveis apenas localmente
    ufw allow from 127.0.0.1 to any port 3000 comment "Gateway (local)" &>/dev/null
    ufw allow from 127.0.0.1 to any port 8000 comment "Core API (local)" &>/dev/null
    ufw allow from 127.0.0.1 to any port 8080 comment "Web UI (local)"  &>/dev/null

    ufw --force enable &>/dev/null
    _info "UFW configurado: $(ufw status | head -1)"
else
    _warn "UFW não disponível — firewall não configurado."
fi

# ---------------------------------------------------------------------------
# Passo 6: Token da Web UI
# ---------------------------------------------------------------------------

_step "6. Token da Web UI"

mkdir -p "$(dirname "$WEB_TOKEN_FILE")"
chmod 700 "$(dirname "$WEB_TOKEN_FILE")"

if [[ -f "$WEB_TOKEN_FILE" ]]; then
    _info "Token já existe em $WEB_TOKEN_FILE."
else
    TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    echo "$TOKEN" > "$WEB_TOKEN_FILE"
    chmod 600 "$WEB_TOKEN_FILE"
    _info "Token gerado em $WEB_TOKEN_FILE"
    # Injeta AGENT_WEB_TOKEN no .env se não estiver lá
    if ! grep -qE "^AGENT_WEB_TOKEN=.+" "$ENV_FILE"; then
        echo "AGENT_WEB_TOKEN=$TOKEN" >> "$ENV_FILE"
        _info "AGENT_WEB_TOKEN adicionado ao .env"
    fi
fi

# ---------------------------------------------------------------------------
# Passo 7: Logrotate
# ---------------------------------------------------------------------------

_step "7. Logrotate"

LOGROTATE_SRC="$INSTALL_DIR/core/src/agent/deploy/templates/logrotate.conf"
LOGROTATE_DST="/etc/logrotate.d/eve-agent"

if [[ -f "$LOGROTATE_DST" ]]; then
    _info "logrotate já configurado em $LOGROTATE_DST."
elif [[ -f "$LOGROTATE_SRC" ]]; then
    cp "$LOGROTATE_SRC" "$LOGROTATE_DST"
    _info "logrotate instalado em $LOGROTATE_DST."
else
    _warn "Template de logrotate não encontrado em $LOGROTATE_SRC — pulando."
fi

# ---------------------------------------------------------------------------
# Passo 8: Cron de backup diário
# ---------------------------------------------------------------------------

_step "8. Cron de backup diário"

CRON_ENTRY="0 3 * * * root docker compose -f $INSTALL_DIR/$COMPOSE_FILE exec -T core agent deploy backup >> /var/log/eve-backup.log 2>&1"
CRON_FILE="/etc/cron.d/eve-backup"

if [[ -f "$CRON_FILE" ]]; then
    _info "Cron de backup já existe em $CRON_FILE."
else
    echo "$CRON_ENTRY" > "$CRON_FILE"
    chmod 644 "$CRON_FILE"
    _info "Cron de backup diário configurado (3h da manhã)."
fi

# ---------------------------------------------------------------------------
# Passo 9: Docker Compose up
# ---------------------------------------------------------------------------

_step "9. docker compose up -d"

cd "$INSTALL_DIR"

if [[ $SKIP_DOCKER -eq 0 ]]; then
    _info "Iniciando serviços..."
    docker compose -f "$COMPOSE_FILE" pull --quiet
    docker compose -f "$COMPOSE_FILE" up -d

    _info "Aguardando boot (30s)..."
    sleep 30

    _info "Status dos serviços:"
    docker compose -f "$COMPOSE_FILE" ps
else
    _info "--skip-docker: docker compose up pulado."
fi

# ---------------------------------------------------------------------------
# Passo 10: Verificação de saúde
# ---------------------------------------------------------------------------

_step "10. Verificação de saúde"

HEALTH_FAIL=0

if [[ $SKIP_DOCKER -eq 0 ]]; then
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        _info "Core API: ✓ healthy (localhost:8000)"
    else
        _warn "Core API: não respondeu em localhost:8000"
        HEALTH_FAIL=1
    fi

    if curl -sf http://localhost:3000/health > /dev/null 2>&1; then
        _info "Gateway:  ✓ healthy (localhost:3000)"
    else
        _warn "Gateway: não respondeu em localhost:3000 (pode ser normal se Telegram não configurado)"
    fi
fi

# ---------------------------------------------------------------------------
# Sumário
# ---------------------------------------------------------------------------

echo ""
_green "==========================================="
_green "  EVE Autônomo — instalação concluída"
_green "==========================================="
_info "Diretório: $INSTALL_DIR"
_info "Log:       $LOG_FILE"
_info "Token UI:  $WEB_TOKEN_FILE"
echo ""

if [[ $HEALTH_FAIL -eq 1 ]]; then
    _warn "Core não respondeu ao healthcheck. Verifique:"
    _warn "  docker compose -f $INSTALL_DIR/$COMPOSE_FILE logs core --tail=50"
else
    _info "Para acessar a Web UI:"
    _info "  http://<ip_da_vps>:8080/?token=\$(cat $WEB_TOKEN_FILE)"
fi

_info "Para monitorar:"
_info "  docker compose -f $INSTALL_DIR/$COMPOSE_FILE logs -f"

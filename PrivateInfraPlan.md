# LocalChat — Private Infrastructure Deployment Plan

> Analogue of `IaCplan.md` for a self-hosted server that is reachable from the internet.
> No cloud provider is required. All components run on your own hardware via Docker Compose.

---

## Stack Summary

| Layer | Technology |
|---|---|
| Application | Flask 3.x + Gunicorn (Python 3.12) |
| Database | PostgreSQL 16 + pgvector (`pgvector/pgvector:pg16`) |
| LLM inference | Ollama (`ollama/ollama:latest`) — requires NVIDIA GPU |
| Container runtime | Docker CE + Docker Compose plugin |
| Reverse proxy / TLS | Nginx + Certbot (Let's Encrypt) |
| Container registry | GitHub Container Registry (`ghcr.io`) — free |
| Secrets | Docker `.env` file (owner-only permissions) |
| Configuration mgmt | Bash setup script (`setup-server.sh`) |
| CI/CD | GitHub Actions — SSH deploy key |

---

## Architecture

```
GitHub (push to main)
        │
        ▼
GitHub Actions CI/CD
        │
        ├─── docker build + push ──────────────► ghcr.io/jwvanderstam/localchat
        │
        └─── SSH → docker compose pull + up ──► Private Server (your hardware)
                                                        │
                                          ┌─────────────┼──────────────┐
                                          ▼             ▼              ▼
                                       app           postgres       ollama
                                    (Flask:5000)   (pg:5432)     (API:11434)
                                          │
                                          ▼
                                       Nginx
                               (reverse proxy + TLS)
                                          │
                         ┌────────────────┴────────────────┐
                         ▼                                 ▼
                  TCP 443 (HTTPS)                  TCP 80 (HTTP→redirect)
                  internet-facing                  internet-facing
```

---

## Network Port Map

This is the complete list of TCP connections required. Configure your router/firewall
and OS firewall (UFW) according to this table.

### Inbound — from the internet to the server

| Port | Protocol | Direction | Purpose | Expose publicly |
|------|----------|-----------|---------|-----------------|
| `80` | TCP | Internet → Nginx | HTTP — redirects to HTTPS | **Yes** |
| `443` | TCP | Internet → Nginx | HTTPS — terminates TLS, proxies to Flask on 5000 | **Yes** |
| `22` | TCP | Admin IP → server | SSH management | **Restrict to your IP(s)** |

> **Ports 5000, 5432 and 11434 must NOT be exposed to the internet.**
> They are bound to the internal Docker bridge network only.

### Internal — Docker bridge network (`localchat_net`, `172.20.0.0/24`)

| Port | Service | Who connects | Notes |
|------|---------|-------------|-------|
| `5000` | `app` (Flask/Gunicorn) | Nginx only | App listens on `0.0.0.0:5000` inside the container |
| `5432` | `postgres` | `app` only | Never published to the host; DNS name `postgres` inside Docker network |
| `11434` | `ollama` | `app` only | Never published to the host; DNS name `ollama` inside Docker network |

### Outbound — from the server to the internet

| Destination | Port | Purpose |
|-------------|------|---------|
| `ghcr.io`, `registry-1.docker.io` | `443` | Pull Docker images |
| `registry.ollama.ai` | `443` | Pull Ollama models |
| `acme-v02.api.letsencrypt.org` | `80` + `443` | Certbot ACME challenge |
| `github.com` | `443` | GitHub Actions SSH callback |
| `*.ubuntu.com` | `80` + `443` | `apt` package updates |

### Router / port-forward rules (if server is behind NAT)

| Router WAN port | Forward to | Server LAN port | Notes |
|-----------------|-----------|-----------------|-------|
| `80` | `<server-LAN-IP>` | `80` | Required for ACME HTTP-01 challenge |
| `443` | `<server-LAN-IP>` | `443` | HTTPS traffic |
| `22` | `<server-LAN-IP>` | `22` | SSH — restrict source IP in router ACL |

---

## Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| GPU | NVIDIA GTX 1080 (8 GB VRAM) | RTX 3090 / RTX 4090 (24 GB VRAM) |
| CPU | 4 cores | 8+ cores |
| RAM | 16 GB | 32 GB |
| Storage | 200 GB SSD | 500 GB NVMe SSD |
| OS | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |
| CUDA driver | ≥ 535 | latest stable |

> **Model VRAM requirements:**
> - `llama3.2` (3B): ~3 GB VRAM
> - `llama3.2` (8B): ~6 GB VRAM
> - `nomic-embed-text`: ~274 MB VRAM
> A 8 GB GPU can run both simultaneously. 24 GB covers larger models (llama3.1:70b requires ~40 GB).

---

## Repository file layout

```
LocalChat/
├── docker-compose.yml              ← full app stack (app + postgres + ollama)
├── Dockerfile                      ← already exists (multi-stage, non-root)
├── nginx/
│   ├── localchat.conf              ← Nginx server block (HTTP + HTTPS)
│   └── options-ssl-nginx.conf      ← Mozilla-recommended TLS settings
├── setup-server.sh                 ← one-time server bootstrap script
├── deploy.sh                       ← pull + rolling restart (called by CI/CD)
└── .github/
    └── workflows/
        └── deploy.yml              ← build → push → deploy pipeline
```

---

## File: `docker-compose.yml`

```yaml
version: '3.9'

services:

  app:
    image: ghcr.io/jwvanderstam/localchat:${TAG:-latest}
    build:
      context: .
      dockerfile: Dockerfile
    # NOT published to host — Nginx connects via Docker network
    expose:
      - "5000"
    env_file: /opt/localchat/.env
    environment:
      PG_HOST: postgres
      PG_PORT: "5432"
      OLLAMA_BASE_URL: "http://ollama:11434"
      SERVER_HOST: "0.0.0.0"
      SERVER_PORT: "5000"
      APP_ENV: production
      LOG_FORMAT: json
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - uploads:/app/uploads
      - logs:/app/logs
    restart: unless-stopped
    networks: [net]

  postgres:
    image: pgvector/pgvector:pg16
    # NOT published to host
    expose:
      - "5432"
    environment:
      POSTGRES_USER: ${PG_USER:-postgres}
      POSTGRES_PASSWORD: ${PG_PASSWORD}
      POSTGRES_DB: ${PG_DB:-rag_db}
    volumes:
      - pgdata:/var/lib/postgresql/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${PG_USER:-postgres} -d ${PG_DB:-rag_db}"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks: [net]

  ollama:
    image: ollama/ollama:latest
    # NOT published to host
    expose:
      - "11434"
    volumes:
      - ollama_models:/root/.ollama
    restart: unless-stopped
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    networks: [net]

  nginx:
    image: nginx:1.27-alpine
    ports:
      - "80:80"     # ← internet-facing
      - "443:443"   # ← internet-facing
    volumes:
      - ./nginx/localchat.conf:/etc/nginx/conf.d/localchat.conf:ro
      - ./nginx/options-ssl-nginx.conf:/etc/nginx/options-ssl-nginx.conf:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro   # TLS certificates
      - /var/www/certbot:/var/www/certbot:ro   # ACME webroot
    depends_on:
      - app
    restart: unless-stopped
    networks: [net]

volumes:
  pgdata:
  uploads:
  logs:
  ollama_models:

networks:
  net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/24
```

---

## File: `nginx/localchat.conf`

```nginx
# HTTP — ACME challenge only; everything else → HTTPS
server {
    listen 80;
    server_name your.domain.com;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

# HTTPS — TLS termination + reverse proxy to Flask
server {
    listen 443 ssl;
    server_name your.domain.com;

    ssl_certificate     /etc/letsencrypt/live/your.domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your.domain.com/privkey.pem;
    include             /etc/nginx/options-ssl-nginx.conf;

    # Increase body size for document uploads
    client_max_body_size 50M;

    # Long timeout for streaming RAG responses
    proxy_read_timeout 120s;
    proxy_send_timeout 120s;

    location / {
        proxy_pass         http://app:5000;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;

        # Required for SSE / streaming chat responses
        proxy_buffering    off;
        proxy_cache        off;
    }
}
```

---

## File: `nginx/options-ssl-nginx.conf`

```nginx
# Mozilla Intermediate TLS configuration
ssl_protocols       TLSv1.2 TLSv1.3;
ssl_ciphers         ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
ssl_prefer_server_ciphers off;
ssl_session_cache   shared:SSL:10m;
ssl_session_timeout 1d;
ssl_session_tickets off;
add_header          Strict-Transport-Security "max-age=63072000" always;
```

---

## File: `setup-server.sh`

Run once on a fresh Ubuntu 22.04 server as `root` or with `sudo`.

```bash
#!/usr/bin/env bash
# One-time server bootstrap.
# Usage: sudo bash setup-server.sh <deploy-username>
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

DEPLOY_USER="${1:-deploy}"

# ── System update ─────────────────────────────────────────────────────────────
apt-get update && apt-get upgrade -y

# ── Create non-root deploy user ───────────────────────────────────────────────
id "$DEPLOY_USER" &>/dev/null || useradd -m -s /bin/bash "$DEPLOY_USER"
usermod -aG docker "$DEPLOY_USER" 2>/dev/null || true

# ── Docker CE ─────────────────────────────────────────────────────────────────
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
usermod -aG docker "$DEPLOY_USER"

# ── NVIDIA driver ─────────────────────────────────────────────────────────────
apt-get install -y --no-install-recommends ubuntu-drivers-common
ubuntu-drivers install
# Reboot required after this step — handled at end of script.

# ── NVIDIA container toolkit ──────────────────────────────────────────────────
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | gpg --dearmor -o /usr/share/keyrings/nvidia-ct-keyring.gpg

curl -sL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-ct-keyring.gpg] https://#g' \
  | tee /etc/apt/sources.list.d/nvidia-ct.list

apt-get update && apt-get install -y --no-install-recommends nvidia-container-toolkit
nvidia-ctk runtime configure --runtime=docker
# docker restart happens after reboot

# ── Certbot (Let's Encrypt) ───────────────────────────────────────────────────
apt-get install -y certbot

# ── UFW firewall ──────────────────────────────────────────────────────────────
ufw default deny incoming
ufw default allow outgoing
ufw allow 80/tcp    comment 'HTTP (ACME + redirect)'
ufw allow 443/tcp   comment 'HTTPS'
# Replace <your-admin-ip> with your actual IP or CIDR block
ufw allow from <your-admin-ip> to any port 22 proto tcp comment 'SSH admin'
ufw --force enable

# ── fail2ban (SSH brute-force protection) ─────────────────────────────────────
apt-get install -y fail2ban
systemctl enable --now fail2ban

# ── App directory ─────────────────────────────────────────────────────────────
mkdir -p /opt/localchat
chown "$DEPLOY_USER":"$DEPLOY_USER" /opt/localchat

# ── SSH deploy key (paste GitHub Actions public key) ─────────────────────────
mkdir -p /home/"$DEPLOY_USER"/.ssh
chmod 700 /home/"$DEPLOY_USER"/.ssh
touch /home/"$DEPLOY_USER"/.ssh/authorized_keys
chmod 600 /home/"$DEPLOY_USER"/.ssh/authorized_keys
chown -R "$DEPLOY_USER":"$DEPLOY_USER" /home/"$DEPLOY_USER"/.ssh

# ── Systemd service — auto-start stack on reboot ─────────────────────────────
cat > /etc/systemd/system/localchat.service << UNIT
[Unit]
Description=LocalChat Docker Compose Stack
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/localchat
ExecStart=/usr/libexec/docker/cli-plugins/docker-compose up -d --remove-orphans
ExecStop=/usr/libexec/docker/cli-plugins/docker-compose down
TimeoutStartSec=300
User=${DEPLOY_USER}
EnvironmentFile=/opt/localchat/.env

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable localchat.service

echo ""
echo "=== Setup complete. Reboot now to load NVIDIA drivers ==="
echo "    sudo reboot"
```

---

## File: `deploy.sh`

Copied to `/opt/localchat/deploy.sh` on the server. Called by GitHub Actions over SSH.

```bash
#!/usr/bin/env bash
# Rolling deploy — pull new app image, restart app container only.
# postgres and ollama are NOT restarted (preserves data + loaded models).
set -euo pipefail

cd /opt/localchat

# Authenticate to GitHub Container Registry using a read-only token
echo "${GHCR_TOKEN}" | docker login ghcr.io -u "${GHCR_USER}" --password-stdin

# Pull only the app image
TAG="${1:-latest}"
export TAG
docker compose pull app

# Restart app container with zero downtime (postgres + ollama keep running)
docker compose up -d --no-deps --remove-orphans app

echo "Deploy complete: localchat:${TAG}"
```

---

## File: `.github/workflows/deploy.yml`

```yaml
name: Build & Deploy

on:
  push:
    branches: [main]
  workflow_dispatch:

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: jwvanderstam/localchat

jobs:

  # ── 1. Build & push Docker image ────────────────────────────────────────────
  build:
    name: Docker — build & push
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write     # required for ghcr.io push

    steps:
      - uses: actions/checkout@v4

      - name: Log in to GitHub Container Registry
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build & push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: |
            ghcr.io/${{ env.IMAGE_NAME }}:${{ github.sha }}
            ghcr.io/${{ env.IMAGE_NAME }}:latest
          cache-from: type=registry,ref=ghcr.io/${{ env.IMAGE_NAME }}:latest
          cache-to:   type=inline

  # ── 2. Deploy to private server ─────────────────────────────────────────────
  deploy:
    name: Deploy — rolling update on private server
    needs: build
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Write SSH private key
        run: |
          echo "${{ secrets.SERVER_SSH_PRIVATE_KEY }}" > /tmp/deploy_key
          chmod 600 /tmp/deploy_key

      - name: Copy docker-compose.yml + deploy.sh to server
        run: |
          scp -o StrictHostKeyChecking=no -i /tmp/deploy_key \
            docker-compose.yml \
            deploy.sh \
            nginx/localchat.conf \
            nginx/options-ssl-nginx.conf \
            ${{ secrets.SERVER_DEPLOY_USER }}@${{ secrets.SERVER_HOST }}:/opt/localchat/

      - name: Run rolling deploy
        run: |
          ssh -o StrictHostKeyChecking=no -i /tmp/deploy_key \
            ${{ secrets.SERVER_DEPLOY_USER }}@${{ secrets.SERVER_HOST }} \
            "GHCR_TOKEN='${{ secrets.GITHUB_TOKEN }}' \
             GHCR_USER='${{ github.actor }}' \
             bash /opt/localchat/deploy.sh ${{ github.sha }}"
```

---

## GitHub Secrets required

| Secret | Description |
|---|---|
| `SERVER_HOST` | Public IP or hostname of your server (e.g. `203.0.113.10` or `localchat.example.com`) |
| `SERVER_DEPLOY_USER` | OS username on the server (e.g. `deploy`) |
| `SERVER_SSH_PRIVATE_KEY` | Private key whose public half is in `~deploy/.ssh/authorized_keys` |

> `GITHUB_TOKEN` is provided automatically by GitHub Actions — no secret needed for `ghcr.io` push.

---

## One-time setup commands

```bash
# ── 0. Point DNS to your server ───────────────────────────────────────────────
# In your DNS provider, add an A record:
#   your.domain.com  →  <your-server-public-ip>
# TTL: 300 seconds. Wait for propagation before running certbot.

# ── 1. Generate SSH key pair for GitHub Actions ───────────────────────────────
ssh-keygen -t ed25519 -f ~/.ssh/localchat_deploy -N "" -C "github-actions-deploy"
# Public key  → paste into /home/deploy/.ssh/authorized_keys on the server
# Private key → add as GitHub Secret SERVER_SSH_PRIVATE_KEY

# ── 2. Run server bootstrap ───────────────────────────────────────────────────
scp setup-server.sh root@<server-ip>:/tmp/
ssh root@<server-ip> "bash /tmp/setup-server.sh deploy"
ssh root@<server-ip> "cat /home/deploy/.ssh/authorized_keys"
# Append your localchat_deploy.pub output here, then:
ssh root@<server-ip> "reboot"

# ── 3. Obtain TLS certificate (after DNS is propagated + server is rebooted) ──
ssh deploy@<server-ip>
sudo certbot certonly --webroot \
  -w /var/www/certbot \
  -d your.domain.com \
  --email admin@your.domain.com \
  --agree-tos \
  --non-interactive
# Certificates written to: /etc/letsencrypt/live/your.domain.com/

# ── 4. Set up automatic certificate renewal ───────────────────────────────────
sudo crontab -e
# Add this line:
# 0 3 * * * certbot renew --quiet --deploy-hook "docker exec localchat-nginx-1 nginx -s reload"

# ── 5. Write the .env file on the server (never committed to git) ──────────────
cat > /opt/localchat/.env << 'ENV'
PG_USER=postgres
PG_PASSWORD=<strong-random-password>
PG_DB=rag_db
SECRET_KEY=<python -c "import secrets; print(secrets.token_hex(32))">
JWT_SECRET_KEY=<python -c "import secrets; print(secrets.token_hex(32))">
REGISTRY=ghcr.io
TAG=latest
ENV
chmod 600 /opt/localchat/.env

# ── 6. First deploy ────────────────────────────────────────────────────────────
cd /opt/localchat
docker compose up -d
docker compose logs -f app   # watch startup

# ── 7. Pull Ollama models once (cached in ollama_models Docker volume) ─────────
docker exec $(docker ps -qf name=ollama) ollama pull llama3.2
docker exec $(docker ps -qf name=ollama) ollama pull nomic-embed-text

# All future deploys: git push origin main  ← triggers GitHub Actions
```

---

## PostgreSQL backup

```bash
# /opt/localchat/backup.sh  — run via cron
#!/usr/bin/env bash
set -euo pipefail
BACKUP_DIR="/opt/localchat/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"

docker exec $(docker ps -qf name=postgres) \
  pg_dump -U postgres rag_db \
  | gzip > "$BACKUP_DIR/rag_db_${TIMESTAMP}.sql.gz"

# Keep last 7 daily backups
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +7 -delete
```

```bash
# Add to deploy user crontab  (crontab -e)
0 2 * * * bash /opt/localchat/backup.sh >> /opt/localchat/logs/backup.log 2>&1
```

---

## Firewall rules summary (UFW)

```bash
# Verify the ruleset after setup-server.sh has run:
sudo ufw status verbose

# Expected output:
# Status: active
# Default: deny (incoming), allow (outgoing)
#
# To                         Action      From
# --                         ------      ----
# 80/tcp                     ALLOW IN    Anywhere          # HTTP (ACME + redirect)
# 443/tcp                    ALLOW IN    Anywhere          # HTTPS
# 22/tcp                     ALLOW IN    <your-admin-ip>   # SSH admin
```

> Ports `5000`, `5432`, and `11434` are **not listed** — they are never published
> to the host network. Traffic to those services flows exclusively over the internal
> Docker bridge (`172.20.0.0/24`).

---

## Maintenance runbook

```bash
# Check application health
curl -s https://your.domain.com/api/health | python3 -m json.tool

# View live logs
ssh deploy@<server-ip> "cd /opt/localchat && docker compose logs -f app"

# Restart only the app (postgres + ollama unaffected)
ssh deploy@<server-ip> "cd /opt/localchat && docker compose restart app"

# Reload Nginx config (e.g. after cert renewal)
ssh deploy@<server-ip> "docker compose exec nginx nginx -s reload"

# Pull a new Ollama model
ssh deploy@<server-ip> \
  "docker exec \$(docker ps -qf name=ollama) ollama pull <model-name>"

# Full stack restart (causes ~5 s downtime)
ssh deploy@<server-ip> "cd /opt/localchat && docker compose down && docker compose up -d"

# Restore database from backup
ssh deploy@<server-ip>
zcat /opt/localchat/backups/rag_db_<timestamp>.sql.gz \
  | docker exec -i $(docker ps -qf name=postgres) psql -U postgres rag_db
```

---

## Comparison with IaCplan.md (Azure)

| Concern | Azure (IaCplan.md) | Private server (this plan) |
|---|---|---|
| Infrastructure provisioning | Bicep (declarative) | `setup-server.sh` (imperative) |
| Container registry | Azure Container Registry | GitHub Container Registry (`ghcr.io`) |
| Secret storage | Azure Key Vault | `/opt/localchat/.env` (chmod 600) |
| Authentication to registry | Managed Identity | `GITHUB_TOKEN` (scoped to repo) |
| TLS termination | Azure load balancer / App Gateway | Nginx + Certbot |
| Inbound ports open | NSG rules in Bicep | UFW rules in `setup-server.sh` |
| Cost | ~$415/month (GPU VM + managed services) | Hardware cost only (electricity) |
| GPU | Azure `Standard_NC4as_T4_v3` (T4) | Your NVIDIA card |
| Backup | Azure-managed (optional) | `backup.sh` + cron |

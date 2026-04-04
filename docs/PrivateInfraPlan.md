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

### Deployment tiers

Three tiers are defined. Pick the one that fits your workload. All tiers run the
identical Docker Compose stack — only the hardware changes.

| Tier | Use case | Concurrent users |
|------|----------|-----------------|
| **Dev / home lab** | Personal use, evaluation | 1–2 |
| **Small team** | Small office, team of ≤ 10 | 5–10 |
| **Production** | Departmental / public-facing | 20+ |

---

### CPU

The application itself (Flask + RAG pipeline) is CPU-bound during document
chunking and BM25 scoring. PostgreSQL pgvector ANN search benefits from
multiple cores for parallel index scans.

| Tier | Minimum | Recommended | Notes |
|------|---------|-------------|-------|
| Dev | 4 cores / 4 threads | 6 cores | Any modern x86-64 |
| Small team | 6 cores / 12 threads | 8 cores / 16 threads | Hyperthreading helps |
| Production | 8 cores / 16 threads | 16 cores / 32 threads | Server-class preferred |

**Specific validated CPUs:**

| Tier | Intel | AMD |
|------|-------|-----|
| Dev | Core i5-12400 | Ryzen 5 5600 |
| Small team | Core i7-13700 | Ryzen 7 7700X |
| Production | Xeon Silver 4314 | EPYC 7282 |

**PCIe lanes:** The GPU must sit in a PCIe x16 (Gen 3 or Gen 4) slot.
Bandwidth to system RAM is only relevant for CPU-offloaded layers — ensure your
CPU provides at least 16 PCIe lanes direct to the GPU.

---

### GPU (NVIDIA only — required for Ollama)

Ollama uses CUDA for inference. AMD ROCm is supported by Ollama but is not
covered by this plan. A CUDA-capable NVIDIA GPU is **mandatory**.

#### VRAM requirements per model

| Model | VRAM needed | Notes |
|-------|------------|-------|
| `nomic-embed-text` | 274 MB | Embedding only — always loaded |
| `llama3.2:3b` | ~2.5 GB | Default chat model |
| `llama3.2:8b` | ~5.5 GB | Better quality, same family |
| `mistral:7b` | ~5.0 GB | Alternative 7B |
| `llama3.1:8b` | ~6.0 GB | Context-window optimised |
| `llama3.1:70b` | ~40 GB | Requires A100 / multi-GPU |
| `deepseek-r1:7b` | ~5.5 GB | Reasoning model |
| `deepseek-r1:32b` | ~22 GB | High-quality reasoning |

> **Rule of thumb:** VRAM needed = model parameter count × 2 bytes (FP16)
> + ~500 MB overhead. A single model is always kept loaded in VRAM
> between requests — plan for the largest model you intend to run.

#### GPU selection by tier

| Tier | Card | VRAM | TDP | PCIe | Validated CUDA |
|------|------|------|-----|------|----------------|
| Dev | NVIDIA RTX 3060 | 12 GB | 170 W | x16 Gen 4 | ✅ CUDA 12.x |
| Dev | NVIDIA RTX 3070 | 8 GB | 220 W | x16 Gen 4 | ✅ CUDA 12.x |
| Small team | NVIDIA RTX 3090 | 24 GB | 350 W | x16 Gen 4 | ✅ CUDA 12.x |
| Small team | NVIDIA RTX 4070 Ti | 12 GB | 285 W | x16 Gen 4 | ✅ CUDA 12.x |
| Production | NVIDIA RTX 4090 | 24 GB | 450 W | x16 Gen 4 | ✅ CUDA 12.x |
| Production | NVIDIA A10G (server) | 24 GB | 150 W | x16 Gen 4 | ✅ CUDA 12.x |
| Production | NVIDIA A100 SXM | 80 GB | 400 W | SXM4 | ✅ CUDA 12.x |

> Minimum supported CUDA compute capability: **7.5** (Turing architecture, e.g. RTX 2060).
> Older Pascal (compute 6.x) cards are **not** supported by current Ollama builds.

---

### System RAM

RAM is consumed by: Python/Flask workers, PostgreSQL shared buffers,
pgvector index caching, and Docker overhead.

| Tier | Minimum | Recommended | Notes |
|------|---------|-------------|-------|
| Dev | 16 GB | 32 GB | DDR4-3200 or better |
| Small team | 32 GB | 64 GB | Dual-channel mandatory |
| Production | 64 GB | 128 GB | ECC recommended for server boards |

**PostgreSQL shared_buffers guideline:** allocate 25% of total RAM.
With 32 GB RAM → set `shared_buffers = 8GB` in `postgresql.conf`
(passed via `POSTGRES_SHARED_BUFFERS` env var in docker-compose).

---

### Storage

Storage is split across three logical purposes with different I/O profiles:

| Volume | Path in Docker | I/O profile | Minimum size | Recommended |
|--------|---------------|-------------|-------------|-------------|
| OS + Docker images | host `/` | Sequential read/write | 80 GB | 120 GB |
| PostgreSQL data (`pgdata`) | `/var/lib/postgresql/data` | **Random 4K IOPS** — critical | 100 GB | 500 GB NVMe |
| Uploaded documents (`uploads`) | `/app/uploads` | Sequential write | 20 GB | 100 GB |
| Ollama models (`ollama_models`) | `/root/.ollama` | Large sequential read | 50 GB | 200 GB |
| Application logs (`logs`) | `/app/logs` | Sequential write | 5 GB | 20 GB |

**Disk type requirements:**

| Volume | Type | Minimum IOPS | Rationale |
|--------|------|-------------|-----------|
| PostgreSQL | NVMe SSD | 10 000 random 4K read | pgvector ANN index scans are I/O intensive |
| Ollama models | SATA SSD or NVMe | 500 sequential read | Models are memory-mapped; cold load only |
| OS | SATA SSD | 500 | Standard boot + Docker layer pulls |
| Uploads / logs | HDD or SATA SSD | 100 | Low I/O |

**Validated storage configurations:**

| Tier | Config |
|------|--------|
| Dev | 1× 1 TB NVMe (all volumes on one drive) |
| Small team | 1× 500 GB NVMe for PostgreSQL + 1× 1 TB SATA SSD for models + OS |
| Production | 1× 1 TB NVMe RAID-1 for PostgreSQL + 2× 2 TB NVMe for models + 240 GB SSD OS |

---

### Network interface

| Tier | Minimum | Recommended |
|------|---------|-------------|
| Dev / home lab | 100 Mbit/s | 1 Gbit/s |
| Small team | 1 Gbit/s | 1 Gbit/s |
| Production | 1 Gbit/s | 10 Gbit/s |

**Internet uplink requirements:**

| Scenario | Required bandwidth | Notes |
|----------|--------------------|-------|
| 1 concurrent streaming chat | ~50 Kbit/s downstream to client | SSE token stream |
| Document upload (10 MB PDF) | 10 MB / upload time | Depends on user's uplink |
| Ollama model pull (llama3.2:8b ~5 GB) | Any — one-time | Done at setup only |
| 10 concurrent users | ~5 Mbit/s sustained | Typical office DSL is sufficient |

---

### Power supply

| Tier | PSU capacity needed | Example card + PSU |
|------|--------------------|--------------------|
| Dev | 550 W | RTX 3060 (170 W) + 65 W CPU → 550 W PSU |
| Small team | 750 W | RTX 3090 (350 W) + 125 W CPU → 750 W PSU |
| Production | 1000 W | RTX 4090 (450 W) + 150 W CPU → 1000 W PSU |

> Add 20% headroom above peak draw. 80+ Gold certification or better is
> recommended for efficiency and stability under sustained GPU load.

---

### UPS (recommended for production)

PostgreSQL write-ahead log (WAL) can be corrupted by sudden power loss.

| Tier | UPS capacity | Hold-up time |
|------|-------------|-------------|
| Dev | Not required | — |
| Small team | 650 VA / 400 W | ≥ 5 min (time to `docker compose stop` cleanly) |
| Production | 1500 VA / 900 W | ≥ 10 min + automatic `shutdown` hook |

---

### Cooling

| Component | Requirement |
|-----------|------------|
| GPU | Case must accommodate the GPU length (RTX 4090: up to 336 mm). Minimum 2 case fans. |
| Ambient temp | ≤ 25 °C intake for sustained full-GPU workloads |
| Server room | Active airflow recommended for production; do not run in enclosed cabinet without ventilation |

---

## Software Requirements

### Operating system

| Requirement | Value |
|-------------|-------|
| **OS** | Ubuntu Server **22.04 LTS** (Jammy Jellyfish) |
| Kernel | ≥ 5.15 (ships with Ubuntu 22.04; do not downgrade) |
| Architecture | x86-64 (amd64) only — ARM64 is not supported by all NVIDIA drivers |
| Init system | systemd (required for `localchat.service`) |
| Shell | bash 5.x |

> Ubuntu 20.04 (Focal) is **not** recommended — NVIDIA driver packages for
> the toolkit may lag behind the 22.04 versions.
> Ubuntu 24.04 (Noble) works but is not yet validated against all NVIDIA driver
> versions as of this writing.

---

### NVIDIA software stack

All three layers must be compatible with each other. Use the version matrix below.

| Component | Minimum version | Recommended | Install method |
|-----------|----------------|-------------|----------------|
| NVIDIA GPU driver | **535.x** | latest 560.x | `ubuntu-drivers install` |
| CUDA runtime (in container) | **12.1** | 12.4 | bundled in Ollama image |
| NVIDIA Container Toolkit | **1.14.0** | latest 1.16.x | `apt` from NVIDIA repo |
| `nvidia-ctk` CLI | same as toolkit | same | same package |

**Version compatibility check (run after install):**
```bash
# NVIDIA driver
nvidia-smi

# Expected output includes:
# Driver Version: 560.xx   CUDA Version: 12.x

# Container toolkit
nvidia-ctk --version

# Docker can see the GPU
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

**CUDA compute capability verification:**
```bash
# Must be ≥ 7.5
nvidia-smi --query-gpu=compute_cap --format=csv,noheader
```

---

### Docker

| Component | Minimum version | Recommended | Notes |
|-----------|----------------|-------------|-------|
| Docker Engine (CE) | **24.0** | latest 27.x | Install via `get.docker.com` script |
| Docker Compose plugin | **2.20** | latest 2.29.x | Bundled with Docker CE ≥ 24 |
| Docker daemon config | — | See below | Must enable NVIDIA runtime |

**Required `/etc/docker/daemon.json` after `nvidia-ctk runtime configure`:**
```json
{
  "runtimes": {
    "nvidia": {
      "path": "nvidia-container-runtime",
      "runtimeArgs": []
    }
  },
  "default-runtime": "nvidia"
}
```

**Version check:**
```bash
docker --version          # Docker version 27.x.x
docker compose version    # Docker Compose version v2.29.x
```

---

### Nginx

| Property | Value |
|----------|-------|
| Version | **1.27.x** (Alpine-based Docker image `nginx:1.27-alpine`) |
| Modules needed | `ngx_http_proxy_module`, `ngx_http_ssl_module`, `ngx_http_rewrite_module` — all included in the official image |
| TLS | TLSv1.2 + TLSv1.3 (TLSv1.0 and TLSv1.1 disabled) |
| Streaming | `proxy_buffering off` required for Gunicorn SSE responses |

---

### Certbot / Let's Encrypt

| Property | Value |
|----------|-------|
| Version | ≥ **2.6.0** (`apt install certbot`) |
| Challenge type | HTTP-01 webroot (port 80 must be reachable) |
| Certificate renewal | Automatic via cron — runs `certbot renew` + Nginx reload |
| Certificate validity | 90 days (auto-renewed at 30 days remaining) |
| Wildcard certificates | Supported via DNS-01 challenge (requires DNS provider plugin) |

---

### Python (inside Docker container — no host install needed)

The application runs entirely inside the Docker image. No Python installation
is required on the host OS.

| Property | Value |
|----------|-------|
| Python version | **3.12.x** (pinned in `Dockerfile` `FROM python:3.12-slim`) |
| Key packages | Flask 3.1, Gunicorn 23.0, psycopg[binary] ≥ 3.3, pydantic 2.12 |
| Virtual environment | `/opt/venv` inside container (multi-stage build) |
| WSGI workers | `2 × CPU_count + 1` (default), overridable via `GUNICORN_WORKERS` |

---

### PostgreSQL + pgvector

| Property | Value |
|----------|-------|
| PostgreSQL version | **16** (`pgvector/pgvector:pg16` Docker image) |
| pgvector extension | **0.7.x** (bundled in the image) |
| Vector dimensions | 768 (nomic-embed-text output — stored in `VECTOR(768)` columns) |
| Index type | HNSW (default in pgvector 0.5+) — requires `CREATE INDEX USING hnsw` |
| Connection pooling | psycopg-pool (min 2, max 10 — configurable via env vars) |

---

### Ollama

| Property | Value |
|----------|-------|
| Image | `ollama/ollama:latest` |
| Minimum Ollama version | **0.3.0** (first stable release with HNSW model offloading) |
| API port | `11434` (internal Docker network only) |
| GPU offload | Controlled via `OLLAMA_NUM_GPU` env var (`-1` = all layers on GPU) |
| Model storage | Docker named volume `ollama_models` mounted at `/root/.ollama` |

---

### Host OS packages (installed by `setup-server.sh`)

| Package | Version | Purpose |
|---------|---------|---------|
| `ubuntu-drivers-common` | distro default | Auto-detect + install NVIDIA driver |
| `nvidia-container-toolkit` | ≥ 1.14 | Docker → GPU passthrough |
| `certbot` | ≥ 2.6 | Let's Encrypt TLS certificates |
| `ufw` | distro default (0.36) | Host firewall |
| `fail2ban` | distro default (0.11) | SSH brute-force protection |
| `openssh-server` | ≥ 8.9 | SSH access + CI/CD deploy |
| `curl`, `gnupg`, `apt-transport-https` | distro default | Package bootstrapping |

---

### Internet access requirements (outbound from server)

All of the following must be reachable from the server over HTTPS (TCP 443)
for initial setup and ongoing operation.

| Endpoint | Required for | Frequency |
|----------|-------------|-----------|
| `get.docker.com` | Docker CE install | Once |
| `download.docker.com` | Docker APT repo | On `apt upgrade` |
| `nvidia.github.io` | NVIDIA Container Toolkit APT repo | Once + on upgrade |
| `ghcr.io` | Pull app Docker image | Every deploy |
| `registry-1.docker.io` | Pull `postgres`, `ollama`, `nginx` images | First deploy + upgrades |
| `registry.ollama.ai` | Pull LLM/embedding models | Once per model |
| `acme-v02.api.letsencrypt.org` | TLS certificate issuance | Every 90 days |
| `github.com` | CI/CD SSH callback | Every deploy |
| `*.ubuntu.com`, `security.ubuntu.com` | `apt` updates | Weekly (recommended) |

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

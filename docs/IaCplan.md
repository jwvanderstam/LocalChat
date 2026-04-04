# LocalChat — Infrastructure as Code Deployment Plan

## Stack Summary

| Layer | Technology |
|---|---|
| Application | Flask 3.x + Gunicorn (Python 3.12) |
| Database | PostgreSQL 16 + pgvector (`pgvector/pgvector:pg16`) |
| LLM inference | Ollama (`ollama/ollama:latest`) — requires NVIDIA GPU |
| Container runtime | Docker CE + Docker Compose plugin |
| Container registry | Azure Container Registry (Basic SKU) |
| Infrastructure | Azure VM `Standard_NC4as_T4_v3` (4 vCPU · 28 GB RAM · 1× NVIDIA T4) |
| Secrets | Azure Key Vault (RBAC mode) |
| IaC language | Bicep |
| CI/CD | GitHub Actions (OIDC — no long-lived credentials) |

---

## Architecture

```
GitHub (push to main)
        │
        ▼
GitHub Actions CI/CD
        │
        ├─── az deployment group create ──► Bicep (idempotent provision)
        │                                         │
        │                                         ├─ VNet + NSG (ports 22, 5000)
        │                                         ├─ Azure Container Registry
        │                                         ├─ Key Vault
        │                                         └─ GPU VM (Ubuntu 22.04)
        │                                              └─ cloud-init.sh
        │                                                  ├─ Docker CE
        │                                                  ├─ NVIDIA driver
        │                                                  └─ nvidia-container-toolkit
        │
        ├─── docker build + push ──────────────► ACR
        │
        └─── SSH → docker compose pull + up ──► VM
                                                  │
                                          ┌───────┼───────────┐
                                          ▼       ▼           ▼
                                        app    postgres    ollama
                                      (Flask)  (pgvector)  (T4 GPU)
```

> **Why GPU VM + Docker Compose instead of AKS or Container Apps?**
> Ollama requires direct NVIDIA GPU access. ACA and AKS GPU support exists but
> adds significant cost and operational complexity for a single-node workload.
> A single `Standard_NC4as_T4_v3` at ~$0.53/hr running Docker Compose is
> the most practical and cost-effective fit for this stack.

---

## Repository file layout

```
LocalChat/
├── docker-compose.yml          ← full app stack (app + postgres + ollama)
├── Dockerfile                  ← already exists (multi-stage, non-root)
├── infra/
│   ├── main.bicep              ← all Azure resources in one file
│   ├── main.bicepparam         ← parameter values (secrets via env vars)
│   └── cloud-init.sh           ← VM bootstrap script (Docker + NVIDIA)
└── .github/
    └── workflows/
        └── deploy.yml          ← build → provision → deploy pipeline
```

---

## File: `docker-compose.yml`

```yaml
version: '3.9'

services:

  app:
    image: ${REGISTRY}/localchat:${TAG:-latest}
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "5000:5000"
    env_file: .env          # written on the VM at deploy time
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

volumes:
  pgdata:
  uploads:
  logs:
  ollama_models:

networks:
  net:
    driver: bridge
```

---

## File: `infra/main.bicep`

```bicep
// infra/main.bicep
// Scope: resource group (pre-create the RG or use subscription scope)
//
// Deploy:
//   az group create -n rg-localchat-prod -l eastus
//   az deployment group create -g rg-localchat-prod \
//     -f infra/main.bicep -p @infra/main.bicepparam

@description('Azure region')
param location string = resourceGroup().location

@description('Short prefix for all resource names')
param prefix string = 'localchat'

@description('VM admin username')
param adminUsername string = 'localchat'

@description('SSH public key content (the full ssh-rsa ... string)')
@secure()
param adminSshPublicKey string

@description('PostgreSQL password')
@secure()
param pgPassword string

@description('Flask SECRET_KEY')
@secure()
param secretKey string

@description('Flask JWT_SECRET_KEY')
@secure()
param jwtSecretKey string

// ── Unique suffix so names don't collide across subscriptions ─────────────────
var suffix = uniqueString(resourceGroup().id)

// ── Key Vault ─────────────────────────────────────────────────────────────────
resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${prefix}-kv-${take(suffix, 8)}'
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    softDeleteRetentionInDays: 7
    enabledForDeployment: true
  }
}

resource kvPg 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'pg-password'
  properties: { value: pgPassword }
}

resource kvSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'secret-key'
  properties: { value: secretKey }
}

resource kvJwt 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'jwt-secret-key'
  properties: { value: jwtSecretKey }
}

// ── Azure Container Registry ──────────────────────────────────────────────────
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: replace('${prefix}acr${take(suffix, 8)}', '-', '')
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }   // managed identity only — no admin creds
}

// ── Networking ────────────────────────────────────────────────────────────────
resource nsg 'Microsoft.Network/networkSecurityGroups@2023-09-01' = {
  name: '${prefix}-nsg'
  location: location
  properties: {
    securityRules: [
      {
        name: 'allow-ssh'
        properties: {
          priority: 100
          protocol: 'Tcp'
          access: 'Allow'
          direction: 'Inbound'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '22'
        }
      }
      {
        name: 'allow-app'
        properties: {
          priority: 110
          protocol: 'Tcp'
          access: 'Allow'
          direction: 'Inbound'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '5000'
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-09-01' = {
  name: '${prefix}-vnet'
  location: location
  properties: {
    addressSpace: { addressPrefixes: ['10.0.0.0/16'] }
    subnets: [
      {
        name: 'default'
        properties: {
          addressPrefix: '10.0.1.0/24'
          networkSecurityGroup: { id: nsg.id }
        }
      }
    ]
  }
}

resource pip 'Microsoft.Network/publicIPAddresses@2023-09-01' = {
  name: '${prefix}-pip'
  location: location
  sku: { name: 'Standard' }
  properties: {
    publicIPAllocationMethod: 'Static'
    dnsSettings: { domainNameLabel: '${prefix}-${take(suffix, 8)}' }
  }
}

resource nic 'Microsoft.Network/networkInterfaces@2023-09-01' = {
  name: '${prefix}-nic'
  location: location
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          subnet: { id: vnet.properties.subnets[0].id }
          publicIPAddress: { id: pip.id }
          privateIPAllocationMethod: 'Dynamic'
        }
      }
    ]
  }
}

// ── GPU VM (Standard_NC4as_T4_v3: 4 vCPU · 28 GB RAM · 1× NVIDIA T4) ─────────
resource vm 'Microsoft.Compute/virtualMachines@2023-09-01' = {
  name: '${prefix}-vm'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    hardwareProfile: { vmSize: 'Standard_NC4as_T4_v3' }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: '0001-com-ubuntu-server-jammy'
        sku: '22_04-lts-gen2'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        diskSizeGB: 128
        managedDisk: { storageAccountType: 'Premium_LRS' }
      }
    }
    osProfile: {
      computerName: '${prefix}-vm'
      adminUsername: adminUsername
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: {
          publicKeys: [
            {
              path: '/home/${adminUsername}/.ssh/authorized_keys'
              keyData: adminSshPublicKey
            }
          ]
        }
      }
    }
    networkProfile: {
      networkInterfaces: [{ id: nic.id }]
    }
  }
}

// ── RBAC: VM managed identity → Key Vault Secrets User ────────────────────────
resource kvRbac 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, vm.id, '4633458b-17de-408a-b874-0445c86b69e6')
  scope: kv
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6'  // Key Vault Secrets User
    )
    principalId: vm.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ── RBAC: VM managed identity → AcrPull ──────────────────────────────────────
resource acrRbac 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, vm.id, '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '7f951dda-4ed3-4680-a7ca-43fe172d538d'  // AcrPull
    )
    principalId: vm.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ── VM Bootstrap: install Docker + NVIDIA toolkit ────────────────────────────
resource bootstrap 'Microsoft.Compute/virtualMachines/extensions@2023-09-01' = {
  parent: vm
  name: 'bootstrap'
  location: location
  properties: {
    publisher: 'Microsoft.Azure.Extensions'
    type: 'CustomScript'
    typeHandlerVersion: '2.1'
    autoUpgradeMinorVersion: true
    settings: {
      fileUris: []
      commandToExecute: loadTextContent('cloud-init.sh')
    }
  }
}

// ── Outputs ───────────────────────────────────────────────────────────────────
output vmPublicIp string = pip.properties.ipAddress
output appUrl string = 'http://${pip.properties.dnsSettings.fqdn}:5000'
output acrLoginServer string = acr.properties.loginServer
output keyVaultName string = kv.name
output vmPrincipalId string = vm.identity.principalId
```

---

## File: `infra/main.bicepparam`

```bicep
using './main.bicep'

param prefix          = 'localchat'
param location        = 'eastus'
param adminUsername   = 'localchat'

// Actual secret values are injected by GitHub Actions — never commit them.
param adminSshPublicKey = readEnvironmentVariable('BICEP_SSH_PUBLIC_KEY')
param pgPassword        = readEnvironmentVariable('BICEP_PG_PASSWORD')
param secretKey         = readEnvironmentVariable('BICEP_SECRET_KEY')
param jwtSecretKey      = readEnvironmentVariable('BICEP_JWT_SECRET_KEY')
```

---

## File: `infra/cloud-init.sh`

```bash
#!/usr/bin/env bash
# VM bootstrap — runs once via CustomScript extension.
# Installs: Docker CE, Docker Compose plugin, NVIDIA driver + container toolkit,
# Azure CLI, and registers a systemd service that manages the app stack.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# ── Docker CE ─────────────────────────────────────────────────────────────────
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
usermod -aG docker localchat

# ── NVIDIA driver + container toolkit ────────────────────────────────────────
apt-get install -y --no-install-recommends ubuntu-drivers-common
ubuntu-drivers install

curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | gpg --dearmor -o /usr/share/keyrings/nvidia-ct-keyring.gpg

curl -sL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-ct-keyring.gpg] https://#g' \
  | tee /etc/apt/sources.list.d/nvidia-ct.list

apt-get update && apt-get install -y --no-install-recommends nvidia-container-toolkit
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker

# ── Azure CLI (used on VM to read Key Vault secrets at deploy time) ───────────
curl -sL https://aka.ms/InstallAzureCLIDeb | bash

# ── App directory ─────────────────────────────────────────────────────────────
mkdir -p /app && chown localchat:localchat /app

# ── Systemd service — docker compose up on every reboot ──────────────────────
cat > /etc/systemd/system/localchat.service << 'UNIT'
[Unit]
Description=LocalChat Docker Compose Stack
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/app
ExecStart=/usr/libexec/docker/cli-plugins/docker-compose up -d --remove-orphans
ExecStop=/usr/libexec/docker/cli-plugins/docker-compose down
TimeoutStartSec=300
User=localchat
EnvironmentFile=/app/.env

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable localchat.service
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
  IMAGE_NAME: localchat
  RESOURCE_GROUP: rg-localchat-prod

jobs:

  # ── 1. Provision infrastructure (idempotent Bicep deploy) ───────────────────
  provision:
    name: Bicep — provision infrastructure
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    outputs:
      acr_server: ${{ steps.deploy.outputs.acrLoginServer }}
      vm_ip:      ${{ steps.deploy.outputs.vmPublicIp }}
      kv_name:    ${{ steps.deploy.outputs.keyVaultName }}

    steps:
      - uses: actions/checkout@v4

      - name: Azure login (OIDC — no stored passwords)
        uses: azure/login@v2
        with:
          client-id:       ${{ secrets.AZURE_CLIENT_ID }}
          tenant-id:       ${{ secrets.AZURE_TENANT_ID }}
          subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}

      - name: Deploy Bicep
        id: deploy
        env:
          BICEP_SSH_PUBLIC_KEY: ${{ secrets.VM_SSH_PUBLIC_KEY }}
          BICEP_PG_PASSWORD:    ${{ secrets.PG_PASSWORD }}
          BICEP_SECRET_KEY:     ${{ secrets.SECRET_KEY }}
          BICEP_JWT_SECRET_KEY: ${{ secrets.JWT_SECRET_KEY }}
        run: |
          az group create -n $RESOURCE_GROUP -l eastus --query id -o tsv

          OUT=$(az deployment group create \
            -g $RESOURCE_GROUP \
            -f infra/main.bicep \
            -p @infra/main.bicepparam \
            --query properties.outputs \
            -o json)

          echo "acrLoginServer=$(echo $OUT | jq -r .acrLoginServer.value)" >> $GITHUB_OUTPUT
          echo "vmPublicIp=$(echo $OUT     | jq -r .vmPublicIp.value)"     >> $GITHUB_OUTPUT
          echo "keyVaultName=$(echo $OUT   | jq -r .keyVaultName.value)"   >> $GITHUB_OUTPUT

  # ── 2. Build & push Docker image ────────────────────────────────────────────
  build:
    name: Docker — build & push
    needs: provision
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read

    steps:
      - uses: actions/checkout@v4

      - name: Azure login (OIDC)
        uses: azure/login@v2
        with:
          client-id:       ${{ secrets.AZURE_CLIENT_ID }}
          tenant-id:       ${{ secrets.AZURE_TENANT_ID }}
          subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}

      - name: ACR login
        run: az acr login --name ${{ secrets.ACR_NAME }}

      - name: Build & push
        run: |
          REGISTRY=${{ needs.provision.outputs.acr_server }}
          docker build \
            -t $REGISTRY/$IMAGE_NAME:${{ github.sha }} \
            -t $REGISTRY/$IMAGE_NAME:latest \
            .
          docker push $REGISTRY/$IMAGE_NAME:${{ github.sha }}
          docker push $REGISTRY/$IMAGE_NAME:latest

  # ── 3. Rolling deploy to VM ──────────────────────────────────────────────────
  deploy:
    name: Deploy — rolling update on VM
    needs: [provision, build]
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read

    steps:
      - uses: actions/checkout@v4

      - name: Azure login (OIDC)
        uses: azure/login@v2
        with:
          client-id:       ${{ secrets.AZURE_CLIENT_ID }}
          tenant-id:       ${{ secrets.AZURE_TENANT_ID }}
          subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}

      - name: Write SSH private key
        run: |
          echo "${{ secrets.VM_SSH_PRIVATE_KEY }}" > /tmp/vm_key
          chmod 600 /tmp/vm_key

      - name: Copy compose file to VM
        run: |
          scp -o StrictHostKeyChecking=no -i /tmp/vm_key \
            docker-compose.yml \
            localchat@${{ needs.provision.outputs.vm_ip }}:/app/docker-compose.yml

      - name: Rolling deploy (pull app image only — postgres & ollama untouched)
        run: |
          ssh -o StrictHostKeyChecking=no -i /tmp/vm_key \
            localchat@${{ needs.provision.outputs.vm_ip }} << 'REMOTE'
              set -euo pipefail

              KV_NAME=$(cat /app/.kv_name)

              # Fetch secrets from Key Vault using VM managed identity
              export PG_PASSWORD=$(az keyvault secret show \
                --vault-name $KV_NAME --name pg-password --query value -o tsv)
              export SECRET_KEY=$(az keyvault secret show \
                --vault-name $KV_NAME --name secret-key --query value -o tsv)
              export JWT_SECRET_KEY=$(az keyvault secret show \
                --vault-name $KV_NAME --name jwt-secret-key --query value -o tsv)
              export PG_USER=postgres
              export PG_DB=rag_db
              export REGISTRY=${{ needs.provision.outputs.acr_server }}
              export TAG=${{ github.sha }}

              # Write .env (contains no long-lived credentials — only transient secrets)
              printf "PG_PASSWORD=%s\nSECRET_KEY=%s\nJWT_SECRET_KEY=%s\nPG_USER=%s\nPG_DB=%s\nREGISTRY=%s\nTAG=%s\n" \
                "$PG_PASSWORD" "$SECRET_KEY" "$JWT_SECRET_KEY" \
                "$PG_USER" "$PG_DB" "$REGISTRY" "$TAG" > /app/.env

              az acr login --name ${{ secrets.ACR_NAME }}

              cd /app
              docker compose pull app
              docker compose up -d --no-deps --remove-orphans app
          REMOTE
```

---

## GitHub Secrets required

| Secret | Description |
|---|---|
| `AZURE_CLIENT_ID` | Federated identity / service principal client ID |
| `AZURE_TENANT_ID` | Azure AD tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription ID |
| `ACR_NAME` | ACR resource name (without `.azurecr.io`) |
| `VM_SSH_PUBLIC_KEY` | Full contents of `~/.ssh/id_rsa.pub` |
| `VM_SSH_PRIVATE_KEY` | Full contents of `~/.ssh/id_rsa` |
| `PG_PASSWORD` | PostgreSQL password |
| `SECRET_KEY` | Flask `SECRET_KEY` |
| `JWT_SECRET_KEY` | Flask `JWT_SECRET_KEY` |

---

## One-time setup commands

```bash
# 1. Generate an SSH key pair for the VM (if you don't have one)
ssh-keygen -t rsa -b 4096 -f ~/.ssh/localchat_vm -N ""
# Add ~/.ssh/localchat_vm.pub as VM_SSH_PUBLIC_KEY in GitHub Secrets
# Add ~/.ssh/localchat_vm     as VM_SSH_PRIVATE_KEY in GitHub Secrets

# 2. Create a service principal with federated OIDC (no password stored in GitHub)
az ad app create --display-name localchat-deploy
# In Azure Portal → App Registration → Federated credentials:
#   Issuer:  https://token.actions.githubusercontent.com
#   Subject: repo:jwvanderstam/LocalChat:ref:refs/heads/main

# 3. First infrastructure deploy (cloud-init runs — takes ~10 min for NVIDIA driver)
az group create -n rg-localchat-prod -l eastus
BICEP_SSH_PUBLIC_KEY="$(cat ~/.ssh/localchat_vm.pub)" \
BICEP_PG_PASSWORD="<your-pg-password>" \
BICEP_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')" \
BICEP_JWT_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')" \
  az deployment group create \
    -g rg-localchat-prod \
    -f infra/main.bicep \
    -p @infra/main.bicepparam

# 4. After cloud-init finishes — store the Key Vault name on the VM
VM_IP=$(az vm show -g rg-localchat-prod -n localchat-vm --show-details --query publicIps -o tsv)
KV_NAME=$(az deployment group show -g rg-localchat-prod -n main \
  --query properties.outputs.keyVaultName.value -o tsv)
ssh -i ~/.ssh/localchat_vm localchat@$VM_IP "echo $KV_NAME > /app/.kv_name"

# 5. Pull Ollama models once (they are cached in the ollama_models Docker volume)
ssh -i ~/.ssh/localchat_vm localchat@$VM_IP \
  "docker exec \$(docker ps -qf name=ollama) ollama pull llama3.2 && \
   docker exec \$(docker ps -qf name=ollama) ollama pull nomic-embed-text"

# All future deploys: git push origin main  ← triggers the GitHub Actions workflow
```

---

## Cost estimate (East US, pay-as-you-go)

| Resource | SKU | Est. monthly cost |
|---|---|---|
| GPU VM `Standard_NC4as_T4_v3` | 1× NVIDIA T4, 4 vCPU, 28 GB | ~$385 (730 hrs) |
| Premium SSD OS disk 128 GB | `Premium_LRS` | ~$20 |
| Azure Container Registry | Basic | ~$5 |
| Key Vault | Standard (< 10k ops/mo) | ~$0.03 |
| Public IP (Static Standard) | — | ~$4 |
| Outbound bandwidth | First 100 GB free | ~$0–10 |
| **Total** | | **~$415/month** |

> **Cost reduction options:**
> - Shut down the VM overnight with `az vm deallocate` (saves ~70%)
> - Use a spot/low-priority VM (`--priority Spot`) for non-production
> - Switch to `Standard_NC4as_T4_v3` Reserved Instance (1-yr) for ~40% savings

---

## Maintenance runbook

```bash
# Check app health
curl http://<VM_IP>:5000/api/health

# View live logs
ssh localchat@<VM_IP> "cd /app && docker compose logs -f app"

# Restart a single service
ssh localchat@<VM_IP> "cd /app && docker compose restart app"

# Pull a new Ollama model
ssh localchat@<VM_IP> \
  "docker exec \$(docker ps -qf name=ollama) ollama pull <model-name>"

# Tear down everything (data volumes preserved)
ssh localchat@<VM_IP> "cd /app && docker compose down"

# Destroy all Azure resources
az group delete -n rg-localchat-prod --yes --no-wait
```

# LocalChat — Production Deployment (Helm)

> The raw `k8s/*.yaml` manifests have been superseded by the Helm chart at `helm/localchat/`.

## Prerequisites

- Kubernetes 1.25+
- Helm 3.10+
- `kubectl` configured for the target cluster
- A built and pushed Docker image (or use `image.pullPolicy: IfNotPresent` with a local image for dev)

## Quick start

```bash
# 1. Lint the chart
helm lint helm/localchat/

# 2. Dry-run to check rendered manifests
helm template localchat helm/localchat/ \
  --set postgresql.auth.password=changeme | kubectl apply --dry-run=client -f -

# 3. Install
helm install localchat helm/localchat/ \
  --namespace localchat --create-namespace \
  --set postgresql.auth.password=changeme \
  --set "env.SECRET_KEY=<random-32-char-string>"
```

## Values overview

| Key | Default | Description |
|-----|---------|-------------|
| `replicaCount` | `2` | App pod replicas (ignored when autoscaling enabled) |
| `image.repository` | `localchat` | Container image |
| `image.tag` | `latest` | Image tag |
| `postgresql.enabled` | `true` | Deploy bundled PostgreSQL StatefulSet |
| `postgresql.auth.password` | `""` | **Must be set** |
| `redis.enabled` | `true` | Deploy bundled Redis StatefulSet |
| `ingress.enabled` | `false` | Create Nginx Ingress resource |
| `ingress.host` | `localchat.example.com` | Public hostname |
| `autoscaling.enabled` | `true` | Enable HPA (2–6 replicas) |
| `mcp.localDocs.enabled` | `true` | Deploy local-docs MCP server |
| `mcp.webSearch.enabled` | `true` | Deploy web-search MCP server |
| `mcp.cloudConnectors.enabled` | `false` | Deploy cloud-connectors MCP server |

## Using an external database

```bash
helm install localchat helm/localchat/ \
  --set postgresql.enabled=false \
  --set postgresql.external.host=my-postgres.example.com \
  --set postgresql.auth.password=<db-password>
```

## Production values override

Create a `values.prod.yaml`:

```yaml
replicaCount: 4
image:
  repository: registry.example.com/localchat
  tag: 1.0.2
  pullPolicy: Always

ingress:
  enabled: true
  host: chat.example.com
  tls: true
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod

postgresql:
  auth:
    password: "<strong-password>"
  persistence:
    size: 50Gi
    storageClass: premium-ssd

redis:
  auth:
    password: "<strong-password>"

mcp:
  cloudConnectors:
    enabled: true
```

Install with:

```bash
helm install localchat helm/localchat/ -f values.prod.yaml --namespace localchat
```

## Upgrade

```bash
helm upgrade localchat helm/localchat/ -f values.prod.yaml --namespace localchat
```

Deployments use `RollingUpdate` strategy; the app stays available during upgrades.

## Rollback

```bash
# List revisions
helm history localchat -n localchat

# Roll back to previous
helm rollback localchat -n localchat
```

## Secrets management

The chart creates a `Secret` resource from `values.yaml`. For production, use an
external secrets manager (e.g. Vault, AWS Secrets Manager with ESO) and patch or
replace the Secret rather than storing passwords in values files.

Required secret keys:

| Key | Purpose |
|-----|---------|
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `REDIS_PASSWORD` | Redis password (optional) |
| `SECRET_KEY` | Flask session signing key |
| `ADMIN_PASSWORD` | Initial admin user password |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for OAuth token encryption (base64url, 32 bytes) |
| `MICROSOFT_CLIENT_ID` | Azure AD app client ID (SharePoint/OneDrive) |
| `MICROSOFT_CLIENT_SECRET` | Azure AD app client secret |

Generate a Fernet key:

```python
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

## Uninstall

```bash
helm uninstall localchat -n localchat
# PVCs are retained by default — delete manually if no longer needed:
kubectl delete pvc -n localchat -l app.kubernetes.io/instance=localchat
```

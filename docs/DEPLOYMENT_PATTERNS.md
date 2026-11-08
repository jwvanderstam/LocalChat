# Deployment patterns

> **Status: proposed, not a validated recipe.** This library is being proposed in
> [Initiative 14](ROADMAP.md). Existing guides
> remain the source of operational steps until each pattern is reconciled and tested.

The goal is to describe deployment approaches in one consistent format and distinguish
verified steps from assumptions. A deployment is a tested pattern only when an operator
can reproduce its checks in the stated environment.

## Pattern record

Each entry should cover:

- Intended environment and prerequisites
- Service topology and configuration
- Persistent application and model state
- Model/artifact acquisition and network requirements
- Security boundaries, including proxy and certificate requirements
- Startup, upgrade, recreation, and recovery procedures
- Exact validation steps and which results are measured, inferred, or still unknown

Do not include organization names, internal hostnames, addresses, credentials, customer
identifiers, or workstation inventory in a public pattern.

## Candidate: managed development workstation

**Status:** user-reported; not independently reproduced or validated.

**Shape:** Windows host with WSL2 and Docker Desktop, LocalChat services in containers, and
an available GPU. This describes a deployment class, not a specific organization's
equipment or network.

**Problem to validate:** model acquisition from inside the runtime may fail under managed
network, proxy, or certificate policy. The report does not yet establish which layer is
responsible, so hardware changes and model-size tuning are not the first diagnostic steps.

**Design question:** can model acquisition use an environment-approved path separate from
runtime startup, with artifacts stored persistently for Ollama? Candidates to test include
a host-side pull, pre-populated persistent storage, offline import, an approved internal
artifact source, or correctly configured proxy and certificate trust. The permitted path
depends on the target environment; do not bypass TLS or network controls.

**Validation gates:**

1. Identify the failing layer in the host, WSL2, container, network/proxy, and Ollama path.
2. Acquire one known-good model through the approved path and confirm it is stored
   persistently.
3. Recreate the containers and confirm the model remains available and loads through
   LocalChat without requiring a download during normal startup.
4. Only then verify GPU inference and record the result separately from model acquisition.

## Patterns to catalog

Initiative 14 proposes bringing the existing Docker Compose and Scaleway guides, plus the
privately owned development workstation pattern, under this format. It then evaluates
whether the managed workstation candidate meets the evidence and reproducibility bar for
publication.

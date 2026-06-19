---
name: disconnected-score
description: >
  Score a repository's readiness for disconnected / air-gapped OpenShift deployments.
  Scans for image manifest completeness, digest enforcement, runtime egress, and
  Python dependency validation. Use when asked to check disconnected readiness,
  air-gap compliance, or image mirroring coverage for an RHOAI component repo.
user-invocable: true
allowed-tools: Read, Bash, Glob, Grep
---

# disconnected-readiness-scorer

Score a repository's readiness for deployment in disconnected / air-gapped OpenShift environments.

## What it does

Scans a repository for common patterns that break disconnected deployments:

1. **Image manifest completeness** — every container image referenced in code must be accounted for in the disconnected image contract. Supports two patterns automatically: `RELATED_IMAGE_*` env vars (used by the opendatahub-operator) and static CSV `relatedImages` lists.
2. **Operator manifest parser** — extracts the authoritative image manifest from the opendatahub-operator source (100+ `RELATED_IMAGE_*` env vars across 18 components). This is the source of truth for what images must be mirrorable.
3. **Digest enforcement** — image references must use `@sha256:` digests, not mutable tags.
4. **Runtime egress detection** — flags code that makes outbound HTTP calls at runtime (as opposed to build time).
5. **Python dependency validation** — ensures pip/import targets are available from bundled mirrors, not PyPI/GitHub.

All rules exclude test files (`*_test.go`, `test/`, `testdata/`), CI config (`.github/`, `.tekton/`), and linting rules (`semgrep.yaml`) from blocker-level findings.

## Prerequisites

- Python 3.12+
- arch-analyzer binary (install with `make install-arch-analyzer` in the repo root)

The scorer uses arch-analyzer to extract production code scope and kustomize overlay mappings. This replaces fragile Dockerfile parsing and provides accurate production vs non-production file classification.

## Usage

```bash
claude plugin install disconnected-readiness-scorer@opendatahub-skills
```

Then from the root of any RHOAI component repo:

```bash
/disconnected-score
```

### Options

- `--rules all` (default) — run all rules
- `--rules csv,tags` — run only specified rules
- `--fix` — attempt auto-remediation for supported rules (e.g., replace image tags with digests)
- `--report markdown` — output a markdown report (default)
- `--report json` — output machine-readable JSON

## Output

```text
Disconnected Readiness Score: NOT READY

  FAIL     image-manifest-complete   2 blocker(s)
  PASS     no-image-tags             All checks passed
  PASS     no-runtime-egress         All checks passed
  PASS     python-imports-bundled    All checks passed

Blockers: 2 | Passed: 3
```

### Score levels

| Score         | Meaning                              |
|---------------|--------------------------------------|
| **READY**     | All rules pass — no blocker findings |
| **NOT READY** | One or more blocker-level findings   |

## Rules

### image-manifest-complete

Parses Dockerfiles, Helm charts, kustomize overlays, Go/Python source, and YAML manifests for container image references. Compares against:

- `spec.relatedImages` in the ClusterServiceVersion (CSV)
- The disconnected-helper image manifest (if present)

Any image found in code but missing from both lists is a **blocker**.

### no-image-tags

Scans all image references for tag-based refs (`:latest`, `:v1.2.3`). Tags cannot be reliably mirrored — only digest refs (`@sha256:...`) are guaranteed to resolve in a disconnected registry.

Production manifests with tags: **blocker**. Test/dev manifests with tags: **warning**.

### no-runtime-egress

Scans Go, Python, and TypeScript source for patterns indicating outbound network calls:

- Go: `http.Get`, `http.Post`, `http.NewRequest`, `net.Dial`
- Python: `requests.get`, `urllib.request`, `httpx`, `aiohttp`
- TypeScript: `fetch(`, `axios`, `http.request`
- Shell: `curl`, `wget` in scripts executed at runtime

Build-time usage (Dockerfiles, Makefiles, CI scripts) is excluded. Runtime usage where the URL is configurable/mirrorable is **info**; hardcoded external URLs are a **blocker**.

### python-imports-bundled

For Python projects, checks:

- `requirements.txt`, `setup.py`, `pyproject.toml` for packages not in the known-mirrors catalog
- Runtime `pip install` or `subprocess` calls that fetch from PyPI/GitHub
- `git+https://` dependencies in any requirements file

Unbundled runtime dependencies: **blocker**. Unbundled dev/test dependencies: **warning**.

## Configuration

### Central config (`config/config.yaml`)

Exception rules applied to all scanned repos.

```yaml
exceptions:
  - rule: "*"
    paths:
      - "**/test/**"
    reason: "Test directory — not deployed in production"

  - rule: no-runtime-egress
    repo: opendatahub-io/odh-dashboard
    paths:
      - "frontend/src/utilities/fetch.ts"
    reason: "Uses cluster-internal API proxy, not external egress"

  - rule: "*"
    images:
      - "*/REPLACE_IMAGE:*"
      - "*:replace"
    reason: "Kustomize/template placeholder images"
```

### Per-repo config (`.disconnected-readiness/config.yaml`)

Optional config in the target repo for repo-specific exclusions.

```yaml
exceptions:
  - rule: no-runtime-egress
    paths:
      - "internal/client.go"
    reason: "Calls cluster-internal Kubernetes API"
```

## Integration

- **CI**: Add as a GitHub Action or GitLab CI job. Fails the pipeline on blocker-level findings.
- **Org Pulse**: Scores are reported to the dashboard alongside Agent Ready scores.
- **Agent Ready synergy**: Shares the same rule-engine architecture. A repo can run both Agent Ready and Disconnected Readiness as part of the same CI step.

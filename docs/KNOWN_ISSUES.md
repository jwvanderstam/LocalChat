# Known Issues

## pdfminer.six cannot be upgraded past 20251230

**Status:** Blocked on upstream  
**Affected:** `requirements.txt` — `pdfminer.six` and `pdfplumber`

`pdfplumber==0.11.9` (latest as of 2026-04-18) hard-pins `pdfminer.six==20251230`. Dependabot PR #25 attempted to bump `pdfminer.six` to `20260107`, but pip rejects the combination as irresolvable.

**Resolution:** Keep `pdfminer.six==20251230` until `pdfplumber` releases a version that loosens its pin. Dependabot will reopen the PR automatically when that happens.

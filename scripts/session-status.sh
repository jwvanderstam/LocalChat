#!/usr/bin/env bash
# session-status: end-of-session safety check (tool-agnostic).
# Surfaces orphaned commits, open PRs, and sync drift so work pushed to an
# already-merged branch (which lands nowhere without an open PR) gets caught.
set -e
git fetch -q --all 2>/dev/null || true

echo "=== branches with commits NOT in main ==="
found=0
for b in $(git for-each-ref --format='%(refname:short)' refs/heads/); do
  [ "$b" = "main" ] && continue
  n=$(git log "main..$b" --oneline 2>/dev/null | wc -l | tr -d ' ')
  if [ "$n" -gt 0 ]; then
    echo "  $b: $n commit(s) not in main — check before deleting: git log main..$b"
    found=1
  fi
done
[ "$found" -eq 0 ] && echo "  (none — all local branches merged into main)"

echo "=== sync: main vs origin/main (left=local-ahead right=remote-ahead) ==="
git rev-list --left-right --count main...origin/main 2>/dev/null || echo "  (no upstream)"

if command -v gh >/dev/null 2>&1; then
  echo "=== open PRs ==="
  gh pr list --state open 2>/dev/null || echo "  (gh unavailable)"
fi
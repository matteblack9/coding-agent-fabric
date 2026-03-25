#!/bin/bash
# Cleanup script to run after migration is complete and integration tests pass.
# The .tasks/ directory itself is preserved (used as a task log).
# Only legacy communication files are deleted.
set -euo pipefail

BASE="${1:-.tasks}"
echo "=== Identifying legacy communication files ==="

# poll.sh
[ -f "$BASE/poll.sh" ] && echo "[DELETE] $BASE/poll.sh" || echo "[SKIP] poll.sh"

# Legacy communication files inside date-stamped subdirectories (REQUEST.md, PROCESSING.md, SUCCESS.md, FAILED.md)
find "$BASE" -maxdepth 3 -name "REQUEST.md" -o -name "PROCESSING.md" \
  -o -name "SUCCESS.md" -o -name "FAILED.md" 2>/dev/null | while read f; do
  echo "[DELETE] $f"
done

echo ""
echo "Review the list above, then run: $0 <base_dir> --execute"
if [ "${2:-}" = "--execute" ]; then
  rm -f "$BASE/poll.sh"
  find "$BASE" -maxdepth 3 \( -name "REQUEST.md" -o -name "PROCESSING.md" \
    -o -name "SUCCESS.md" -o -name "FAILED.md" \) -delete
  echo "Legacy communication files removed (.tasks/ directory retained)"
fi

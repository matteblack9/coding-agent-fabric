#!/bin/bash
# 마이그레이션 완료 + 통합 테스트 통과 후 실행할 정리 스크립트
# .tasks/ 디렉토리 자체는 유지 (작업 로그 용도)
# 기존 통신용 파일만 삭제
set -euo pipefail

BASE="${1:-.tasks}"
echo "=== 기존 통신용 파일 식별 ==="

# poll.sh
[ -f "$BASE/poll.sh" ] && echo "[DELETE] $BASE/poll.sh" || echo "[SKIP] poll.sh"

# 기존 날짜 폴더 내부의 통신용 파일 (REQUEST.md, PROCESSING.md, SUCCESS.md, FAILED.md)
find "$BASE" -maxdepth 3 -name "REQUEST.md" -o -name "PROCESSING.md" \
  -o -name "SUCCESS.md" -o -name "FAILED.md" 2>/dev/null | while read f; do
  echo "[DELETE] $f"
done

echo ""
echo "확인 후 실행: $0 <base_dir> --execute"
if [ "${2:-}" = "--execute" ]; then
  rm -f "$BASE/poll.sh"
  find "$BASE" -maxdepth 3 \( -name "REQUEST.md" -o -name "PROCESSING.md" \
    -o -name "SUCCESS.md" -o -name "FAILED.md" \) -delete
  echo "통신용 파일 정리 완료 (.tasks/ 디렉토리는 유지)"
fi

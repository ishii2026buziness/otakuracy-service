#!/usr/bin/env bash
# infra/ サブモジュール内に uncommitted changes がないか確認する
# pre-commit hook または CI から呼ぶ

set -euo pipefail

DIRTY=$(git -C "$(git rev-parse --show-toplevel)/infra" status --porcelain 2>/dev/null || true)
if [ -n "$DIRTY" ]; then
  echo "ERROR: infra/ に uncommitted な変更があります。"
  echo "infra/ は k12-network-notes の submodule です。変更は k12-network-notes で行ってください。"
  echo "  正本: ~/repos/github.com/ishii2025buziness/k12-network-notes"
  echo ""
  echo "変更を破棄するには: git -C infra/ checkout ."
  exit 1
fi
echo "OK: infra/ に uncommitted な変更はありません。"

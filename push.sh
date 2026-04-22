#!/bin/bash
# push.sh — 一键推送 petintable 到 GitHub
# 用法: ./push.sh YOUR_GITHUB_USERNAME

set -e

USERNAME="${1:-}"
if [ -z "$USERNAME" ]; then
  echo "Usage: ./push.sh YOUR_GITHUB_USERNAME"
  exit 1
fi

cd "$(dirname "$0")"

echo "→ Adding remote..."
git remote add origin "https://github.com/${USERNAME}/petintable.git" 2>/dev/null || git remote set-url origin "https://github.com/${USERNAME}/petintable.git"

echo "→ Pushing main branch..."
git branch -M main
git push -u origin main

echo "→ Pushing tag v0.1.0 (triggers CI build)..."
git tag -f v0.1.0
git push -f origin v0.1.0

echo "✓ Done. Check https://github.com/${USERNAME}/petintable/actions"

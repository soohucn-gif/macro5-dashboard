#!/bin/bash
# 一次性引导：给 gh token 加上 workflow scope，然后把 Actions 定时任务推上去。
# GitHub 规定 OAuth token 没有 workflow scope 就不能创建/修改 .github/workflows/ 下的文件。
set -e
cd "$(dirname "$0")"
if ! gh auth status 2>&1 | grep -q "workflow"; then
  echo "→ 需要授权 workflow scope，浏览器会打开 github.com/login/device"
  gh auth refresh -h github.com -s workflow
fi
git add .github/workflows/update.yml
git commit -m "ci: 每日/每月自动更新 workflow"
git push
echo "✅ 已推送。Actions 页：https://github.com/soohucn-gif/macro5-dashboard/actions"
echo "→ 可以立刻手动跑一次验证：gh workflow run '数据更新' --repo soohucn-gif/macro5-dashboard"

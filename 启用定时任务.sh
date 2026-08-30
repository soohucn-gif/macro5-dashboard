#!/bin/bash
# 一次性引导：给 gh token 加上 workflow scope，再把 Actions 定时任务推上去。
#
# 为什么需要这一步：GitHub 规定 OAuth token 没有 workflow scope 就不能创建或修改
# .github/workflows/ 下的文件 —— git push / Contents API / Git Data API / deploy key
# 四条路都按这个路径拦，所以只能由你本人授权一次。授权后这个脚本会自动完成剩下的事。
set -euo pipefail
cd "$(dirname "$0")"

REPO=soohucn-gif/macro5-dashboard
WF=.github/workflows/update.yml

echo "▸ 仓库：$(pwd)"

if [ ! -f "$WF" ]; then
  echo "✗ 找不到 $WF —— 这个文件应该在本地工作区里，请确认没被误删。" >&2
  exit 1
fi

# ── 1. 授权 ────────────────────────────────────────────────────────────────
if gh auth status 2>&1 | grep -q "workflow"; then
  echo "▸ workflow scope 已具备，跳过授权。"
else
  echo "▸ 需要授权 workflow scope。"
  echo "  接下来终端会给你一个一次性代码，浏览器会打开 github.com/login/device："
  echo "  把代码粘进去、点 Authorize，然后回到这里等它自己继续。"
  echo
  gh auth refresh -h github.com -s workflow
  echo
  if ! gh auth status 2>&1 | grep -q "workflow"; then
    echo "✗ 授权没完成（可能超时了）。重新跑一次这个脚本即可。" >&2
    exit 1
  fi
  echo "▸ 授权成功。"
fi

# ── 2. 推 workflow ─────────────────────────────────────────────────────────
git pull --ff-only --quiet origin main || true
if git ls-files --error-unmatch "$WF" >/dev/null 2>&1 && git diff --quiet HEAD -- "$WF"; then
  echo "▸ workflow 已在仓库里且无改动，跳过提交。"
else
  git add "$WF"
  if git diff --cached --quiet; then
    echo "▸ 没有待提交的改动。"
  else
    git -c user.email=soohucn@gmail.com -c user.name=henryhu \
        commit -q -m "ci: 每日/每月自动更新 workflow"
    git push
    echo "▸ 已推送。"
  fi
fi

# ── 3. 验证 ────────────────────────────────────────────────────────────────
if gh api "repos/$REPO/contents/$WF" >/dev/null 2>&1; then
  echo "✓ 仓库里已存在 $WF"
else
  echo "✗ 推上去了但仓库里查不到，请检查 https://github.com/$REPO/actions" >&2
  exit 1
fi

# ── 4. 立刻跑一次，别等到明早才发现有问题 ──────────────────────────────────
echo "▸ 手动触发一次，验证整条管道……"
gh workflow run "数据更新" --repo "$REPO" >/dev/null
sleep 8
gh run list --repo "$REPO" --workflow "数据更新" --limit 1

cat <<EOF

✅ 完成。之后的节奏：
   · 每日 23:37 UTC（北京 07:37）自动抓数 → 重建看板 → 推送
   · 每月 2 号额外生成上月月度快照
   · 北京 08:09 由 Claude 定时任务把当日数值推到你手机

   Actions： https://github.com/$REPO/actions
   看板：    https://soohucn-gif.github.io/macro5-dashboard/
EOF

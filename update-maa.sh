#!/bin/sh
# 更新 maa-cli 自身 + MaaCore + 游戏资源
#
# 镜像为瘦身排除了 MaaResource/.git，所以常规 `maa update` 会报
#   could not find repository at '.../MaaResource'
# 这里检测到没有 .git 时自动降级为 `maa install --force`，并带失败回滚。
#
# 坑：判断命令成败必须看它自己的退出码，不能 `cmd | tail`（拿到的是 tail 的 0）。
LOG="${MAA_LOG:-/maa/data/run.log}"
DATA="${XDG_DATA_HOME:-/root/.local/share}/maa"
RES="$DATA/MaaResource"
OUT=/tmp/maa-update.out
MAA=/usr/local/bin/maa

show() { tail -"${1:-30}" "$OUT" 2>/dev/null | sed 's/^/[maa]   /'; }

echo "[maa] $(date '+%F %T') ===== 开始更新 MAA ====="
echo "[maa] 更新前版本："
"$MAA" --version 2>&1 | sed 's/^/[maa]   /'

echo "[maa] --- maa self update（maa-cli 本体）---"
if "$MAA" self update > "$OUT" 2>&1; then
  show 20
else
  show 20
  echo "[maa]   （self update 未生效，继续后面的步骤）"
fi

if [ -d "$RES/.git" ]; then
  echo "[maa] --- maa update（增量更新 MaaCore + 资源）---"
  if "$MAA" update > "$OUT" 2>&1; then
    show 30
  else
    show 40
    echo "[maa] !! maa update 失败"
  fi
else
  echo "[maa] --- 资源目录没有 .git，改用 maa install --force 重新拉取 ---"
  if [ -d "$RES" ]; then
    rm -rf "${RES}.bak"
    mv "$RES" "${RES}.bak"
  fi
  if "$MAA" install --force > "$OUT" 2>&1; then
    show 30
    rm -rf "${RES}.bak"
    echo "[maa] 资源重新安装完成"
  else
    show 40
    echo "[maa] !! 重新安装失败，回滚旧资源"
    if [ -d "${RES}.bak" ]; then
      rm -rf "$RES"
      mv "${RES}.bak" "$RES"
    fi
  fi
fi
rm -f "$OUT"

echo "[maa] 更新后版本："
"$MAA" --version 2>&1 | sed 's/^/[maa]   /'
echo "[maa] $(date '+%F %T') ===== 更新结束 ====="

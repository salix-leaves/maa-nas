#!/bin/bash
# 准备 Docker 构建上下文：把 maa-cli / MaaCore / adb 下载到本地目录
set -e
BASE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$BASE/bin" "$BASE/data"
export MAA_INSTALL_DIR="$BASE/bin"
export XDG_DATA_HOME="$BASE/data"
export HOME="${HOME:-/root}"

echo "==> 安装 maa-cli"
if [ ! -x "$BASE/bin/maa" ]; then
  curl -fsSL https://raw.githubusercontent.com/MaaAssistantArknights/maa-cli/main/install.sh | bash
else
  echo "    已存在，跳过"
fi

echo "==> 安装 MaaCore 及资源"
"$BASE/bin/maa" install

echo "==> 下载 adb (Google platform-tools)"
if [ ! -x "$BASE/platform-tools/adb" ]; then
  tmp="$(mktemp -d)"
  curl -fsSL -o "$tmp/pt.zip" https://dl.google.com/android/repository/platform-tools-latest-linux.zip
  unzip -q -o "$tmp/pt.zip" -d "$BASE/"
  rm -rf "$tmp"
else
  echo "    已存在，跳过"
fi

echo
echo "==> 完成"
"$BASE/bin/maa" --version
"$BASE/platform-tools/adb" version | head -1
echo "现在可以: docker compose up -d --build"

#!/bin/sh
# 日志轮转：每次运行前把 run.log 轮转成 run.log.1，只保留最近 N 份（默认 5）
# 必须在「打开日志文件句柄之前」调用，否则写入会跟着 rename 走丢
LOG="${MAA_LOG:-/maa/data/run.log}"
KEEP="${MAA_LOG_KEEP:-5}"

[ -s "$LOG" ] || exit 0

i="$KEEP"
while [ "$i" -gt 1 ]; do
  prev=$((i - 1))
  [ -f "${LOG}.${prev}" ] && mv -f "${LOG}.${prev}" "${LOG}.${i}"
  i="$prev"
done
mv -f "$LOG" "${LOG}.1"

# 清掉超出保留份数的旧文件
j=$((KEEP + 1))
while [ -f "${LOG}.${j}" ]; do
  rm -f "${LOG}.${j}"
  j=$((j + 1))
done
exit 0

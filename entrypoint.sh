#!/bin/sh
# 有参数 -> 直接透传给 maa
if [ "$#" -gt 0 ]; then
  exec /usr/local/bin/maa "$@"
fi

# 一次性模式（命令行手动触发，等价于网页上的「开始日常」）
if [ "${MAA_ONESHOT:-0}" = "1" ]; then
  exec /usr/local/bin/run-daily.sh
fi

# 首次运行：把镜像里烤好的资源播种到持久卷 /maa/data（之后「更新 MAA」的结果才能保留，重建不丢）
if [ ! -d /maa/data/maa ] && [ -d /opt/maa-seed ]; then
  echo "[maa] 首次运行：初始化资源到持久卷 /maa/data（约 1 分钟）..."
  cp -a /opt/maa-seed/. /maa/data/
  echo "[maa] 资源初始化完成"
fi

echo "[maa] Web 手动开关：http://<NAS-IP>:${MAA_WEB_PORT:-5599}"
python3 /usr/local/bin/webctl.py &

AT="${MAA_CRON_TIME:-}"
TASK="${MAA_TASK:-daily}"

# 定时关闭（MAA_CRON_TIME 为空或 off）——只保留手动开关
if [ -z "$AT" ] || [ "$AT" = "off" ]; then
  echo "[maa] 定时执行：已关闭（仅手动触发）"
  while true; do sleep 3600; done
fi

echo "[maa] 定时执行：每天 ${AT} 运行 '${TASK}'"
while true; do
  if [ "$(date +%H:%M)" = "$AT" ]; then
    /usr/local/bin/rotate-log.sh
    /usr/local/bin/run-daily.sh >> "${MAA_LOG:-/maa/data/run.log}" 2>&1
    sleep 60
  fi
  sleep 20
done

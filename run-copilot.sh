#!/bin/sh
# 自动抄作业：按关卡找作业 → 下载 → 生成任务 → 运行（复用 run-daily.sh 的 PC 唤醒/游戏启动预检）
#
# 环境变量：
#   MAA_COPILOT_STAGE     关卡（必填）。单关如 YW-8；批量填活动名如 昨日海（跑该活动全部关卡）
#   MAA_COPILOT_BAN       屏蔽干员（逗号分隔），默认 号角,阿斯卡纶,娜仁图雅,娜仁图亚
#   MAA_COPILOT_LIMIT     每关最多取多少份作业参与筛选，默认 50
#   MAA_COPILOT_IGNORE_REQ  自动编队是否忽略练度要求（true/false），默认 true
STAGE="${MAA_COPILOT_STAGE:?请设置 MAA_COPILOT_STAGE，例如 YW-8 或 昨日海}"
BAN="${MAA_COPILOT_BAN:-号角,阿斯卡纶,娜仁图雅,娜仁图亚}"
LIMIT="${MAA_COPILOT_LIMIT:-50}"
IGNORE_REQ="${MAA_COPILOT_IGNORE_REQ:-true}"

echo "[copilot] $(date '+%F %T') ===== 开始抄作业：$STAGE（屏蔽：$BAN）====="

TASK=/maa/config/tasks/_copilot.toml
rm -f "$TASK"
FTMP=/tmp/copilot-find.log

# 1) 找作业 + 下载 + 生成任务
python3 /usr/local/bin/copilot.py "$STAGE" --ban "$BAN" --limit "$LIMIT" \
  --task "$TASK" --ignore-req "$IGNORE_REQ" > "$FTMP" 2>&1
rc=$?
cat "$FTMP"
rm -f "$FTMP"

if [ $rc -eq 2 ]; then
  echo "[copilot] 网络错误，请稍后重试（作业站 DNS/网络可能抖动）"
  exit 2
elif [ $rc -ne 0 ] || [ ! -f "$TASK" ]; then
  echo "[copilot] 没有可用作业：该关卡可能没有作业，或都被屏蔽干员过滤了"
  exit 1
fi

echo "[copilot] 开始运行（唤醒 PC → 启动游戏 → 自动编队 → 战斗）"

# 2) 复用 run-daily.sh 的完整预检流程
MAA_TASK=_copilot /usr/local/bin/run-daily.sh

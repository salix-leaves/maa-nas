#!/bin/sh
# 自动抄作业：按关卡找作业 → 下载 → 生成任务 → 运行（复用 run-daily.sh 的 PC 唤醒/游戏启动预检）
#
# 环境变量：
#   MAA_COPILOT_STAGE     关卡（必填），如 YW-8 / YW-6 / 鳞的记忆 / act52side_08
#   MAA_COPILOT_BAN       屏蔽干员（逗号分隔），默认 号角,阿斯卡纶,娜仁图雅,娜仁图亚
#   MAA_COPILOT_LIMIT     每关最多取多少份作业参与筛选，默认 50
#   MAA_COPILOT_IGNORE_REQ  自动编队是否忽略练度要求（true/false），默认 true
STAGE="${MAA_COPILOT_STAGE:?请设置 MAA_COPILOT_STAGE，例如 YW-8}"
BAN="${MAA_COPILOT_BAN:-号角,阿斯卡纶,娜仁图雅,娜仁图亚}"
LIMIT="${MAA_COPILOT_LIMIT:-50}"
IGNORE_REQ="${MAA_COPILOT_IGNORE_REQ:-true}"

echo "[copilot] $(date '+%F %T') ===== 开始抄作业：$STAGE（屏蔽：$BAN）====="

# 1) 找作业 + 下载（输出存临时文件，既保留日志又拿到路径）
FTMP=/tmp/copilot-find.log
if ! python3 /usr/local/bin/copilot.py "$STAGE" --ban "$BAN" --limit "$LIMIT" > "$FTMP" 2>&1; then
  cat "$FTMP"
  rm -f "$FTMP"
  echo "[copilot] 找不到符合条件的作业，终止"
  exit 1
fi
cat "$FTMP"
OUT=$(grep '^OUT=' "$FTMP" | head -1 | cut -d= -f2-)
rm -f "$FTMP"
if [ -z "$OUT" ] || [ ! -f "$OUT" ]; then
  echo "[copilot] 作业文件无效，终止"
  exit 1
fi

# 2) 生成动态任务（下划线前缀，网页菜单里不显示）
TASK=/maa/config/tasks/_copilot.toml
cat > "$TASK" <<EOF
# @name 自动抄作业
# @desc 动态生成，由 run-copilot.sh 写入，请勿手动编辑

[[tasks]]
name = "开始唤醒"
type = "StartUp"
params = { client_type = "Official", start_game_enabled = true }

[[tasks]]
name = "自动抄作业"
type = "Copilot"
params = { filename = "$OUT", formation = true, add_trust = true, ignore_requirements = $IGNORE_REQ, support_unit_usage = 1 }

[[tasks]]
name = "关闭游戏"
type = "CloseDown"
params = { client_type = "Official" }
EOF

echo "[copilot] 作业文件：$OUT"
echo "[copilot] 开始运行（唤醒 PC → 启动游戏 → 自动编队 → 战斗）"

# 3) 复用 run-daily.sh 的完整预检流程
MAA_TASK=_copilot /usr/local/bin/run-daily.sh

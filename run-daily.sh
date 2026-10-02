#!/bin/sh
# 日常执行体：确保模拟器在跑 -> 确保游戏在跑 -> maa run
# 模拟器没启动时，通过 SSH 触发 PC 上的计划任务（跑在交互会话里，才能拉起 MuMu 图形主程序）
LOCK=/tmp/maa-run.lock
if [ -e "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  echo "[maa] 已有任务在运行 (pid $(cat "$LOCK"))，跳过"
  exit 1
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT INT TERM

TASK="${MAA_TASK:-daily}"
ADB_ADDR="${MAA_ADB_ADDRESS:-192.168.2.150:16384}"
PKG="${MAA_GAME_PKG:-com.hypergryph.arknights}"
PC_SSH="${MAA_PC_SSH:-leaves@192.168.2.150}"
PC_TASK="${MAA_PC_TASK:-MAA-StartMuMu}"
MUMU_MGR="${MAA_MUMU_MANAGER:-D:\\mumu\\MuMuPlayer-12.0\\nx_main\\MuMuManager.exe}"
MUMU_INDEX="${MAA_MUMU_INDEX:-0}"
WAIT_SECS="${MAA_WAIT_SECS:-180}"

adb_ready() { timeout 6 adb -s "$ADB_ADDR" get-state >/dev/null 2>&1; }

# 首次运行时按环境变量生成 MaaCore 连接配置（之后可自行编辑该文件）
PROFILE=/maa/config/profiles/default.toml
if [ ! -f "$PROFILE" ]; then
  mkdir -p "$(dirname "$PROFILE")"
  cat > "$PROFILE" <<TOML
[connection]
adb_path = "adb"
address  = "${ADB_ADDR}"
config   = "CompatPOSIXShell"

[instance_options]
touch_mode = "MaaTouch"
kill_adb_on_exit = false
TOML
  echo "[maa] 已生成连接配置 ${PROFILE}"
fi

wake_pc() {
  if ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "$PC_SSH" \
       "schtasks /run /tn ${PC_TASK}" >/dev/null 2>&1; then
    echo "[maa] 已触发计划任务 ${PC_TASK}（在 PC 的登录会话中启动 MuMu）"
  else
    echo "[maa] 计划任务不可用，回退直接调用 MuMuManager ..."
    ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "$PC_SSH" \
        "\"${MUMU_MGR}\" control -v ${MUMU_INDEX} launch -pkg ${PKG}" 2>&1 | tail -2
  fi
}

echo "[maa] $(date '+%F %T') 连接模拟器 ${ADB_ADDR} ..."
timeout 10 adb connect "$ADB_ADDR" >/dev/null 2>&1

if ! adb_ready; then
  echo "[maa] 模拟器没在运行，远程启动 MuMu ..."
  wake_pc
  echo "[maa] 等待模拟器 + 安卓启动（最多 ${WAIT_SECS} 秒）..."
fi

ok=0
deadline=$(( $(date +%s) + WAIT_SECS ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  timeout 6 adb connect "$ADB_ADDR" >/dev/null 2>&1
  if adb_ready; then ok=1; break; fi
  sleep 5
done

if [ "$ok" != "1" ]; then
  echo "[maa] !! 模拟器始终不可达：${ADB_ADDR}"
  echo "[maa]    排查："
  echo "[maa]      1) PC 是否开机（关机的话需要 WoL）"
  echo "[maa]      2) PC 上 SSH 是否可用：ssh ${PC_SSH} hostname"
  echo "[maa]      3) 计划任务是否存在：ssh ${PC_SSH} schtasks /query /tn ${PC_TASK}"
  adb kill-server >/dev/null 2>&1
  exit 2
fi
echo "[maa] 模拟器就绪"

# 模拟器刚起来时游戏可能还没启动，补一次
if ! timeout 8 adb -s "$ADB_ADDR" shell pidof "$PKG" >/dev/null 2>&1; then
  echo "[maa] 游戏未运行，启动 ${PKG}"
  timeout 20 adb -s "$ADB_ADDR" shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
  sleep 25
fi

echo "[maa] $(date '+%F %T') ===== 开始日常 ====="
/usr/local/bin/maa run "$TASK"
rc=$?
echo "[maa] $(date '+%F %T') ===== 日常结束(退出码 ${rc}) ====="
exit $rc

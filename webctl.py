#!/usr/bin/env python3
"""MAA 控制台：功能选单 + 任务参数编辑 + 实时日志。

认证：HTTP Basic，或「记住我」Cookie。
首次用  http://<IP>:<PORT>/?k=<密码>  打开一次，写入 1 年有效期的 Cookie，之后免密。

页面：
  /                功能选单（扫 $MAA_TASKS_DIR/*.toml 生成按钮）
  /task/<id>       该任务参数编辑页（改完保存回 .toml，无需重启/重建镜像）
  /api/state       运行状态 JSON

任务文件约定：
  文件名（去 .toml）= 任务 ID；文件头 `# @name 显示名` / `# @desc 说明` 用作按钮文字。
"""
import base64, hashlib, html, json, os, re, subprocess, time, tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote, unquote

PORT = int(os.environ.get("MAA_WEB_PORT", "5599"))
USER = os.environ.get("MAA_WEB_USER", "maa")
PASSWORD = os.environ.get("MAA_WEB_PASSWORD", "")
LOG = os.environ.get("MAA_LOG", "/maa/data/run.log")
RUNNER = "/usr/local/bin/run-daily.sh"
TASKS_DIR = os.environ.get("MAA_TASKS_DIR", "/maa/config/tasks")
DEFAULT_TASK = os.environ.get("MAA_TASK", "daily")
STATE = "/tmp/maa-current-task"

COOKIE = "maatoken"
TOKEN = hashlib.sha256(("%s:%s" % (USER, PASSWORD)).encode()).hexdigest() if PASSWORD else ""

# ---------------------------------------------------------------- 参数知识库
# type -> { 参数名: (说明, 默认值, 类型) }
# 类型: text / int / float / bool / list / 或一个候选值列表(下拉)
KNOWN = {
    "StartUp": {
        "client_type": ("客户端", "Official",
                        ["Official", "Bilibili", "txwy", "YoStarEN", "YoStarJP", "YoStarKR"]),
        "start_game_enabled": ("自动启动客户端", True, "bool"),
        "account_name": ("切换账号（留空不切）", "", "text"),
    },
    "CloseDown": {
        "client_type": ("客户端", "Official",
                        ["Official", "Bilibili", "txwy", "YoStarEN", "YoStarJP", "YoStarKR"]),
    },
    "Fight": {
        "stage": ("关卡（如 1-7 / CE-6 / Annihilation）", "1-7", "text"),
        "medicine": ("最多吃几个理智药", 0, "int"),
        "medicine_expire_days": ("用多少天内过期的药", 0, "int"),
        "stone": ("最多吃几个源石", 0, "int"),
        "times": ("打几把", 6, "int"),
        "series": ("代理倍率 -1~10（0=自动最大）", 0, "int"),
        "report_to_penguin": ("汇报企鹅物流", False, "bool"),
        "DrGrandet": ("节省理智碎石模式", False, "bool"),
        "client_type": ("客户端（崩了自动重连用）", "", "text"),
    },
    "Recruit": {
        "refresh": ("刷新三星 Tag", False, "bool"),
        "select": ("点击的 Tag 等级", [4, 5], "list"),
        "confirm": ("确认的 Tag 等级", [3, 4, 5], "list"),
        "times": ("招募几次", 4, "int"),
        "expedite": ("使用加急许可", False, "bool"),
        "level3_recruitment_permit_reserve": ("保留 3 星许可数", 0, "int"),
        "extra_tags_mode": ("多选 Tag：0默认 1选3个 2更多高星", 0, "int"),
        "set_time": ("设置招募时限", True, "bool"),
    },
    "Infrast": {
        "mode": ("模式：0默认 / 10000自定义 / 20000轮换", 0, "int"),
        "facility": ("要换班的设施", ["Mfg", "Trade", "Power", "Control", "Reception", "Office", "Dorm"], "list"),
        "drones": ("无人机用途", "Money",
                   ["_NotUse", "Money", "SyntheticJade", "CombatRecord", "PureGold", "OriginStone", "Chip"]),
        "threshold": ("工作心情阈值 0~1", 0.3, "float"),
        "dorm_notstationed_enabled": ("宿舍启用「未进驻」", False, "bool"),
        "dorm_trust_enabled": ("宿舍填信赖未满干员", False, "bool"),
        "reception_message_board": ("领取会客室信息板信用", True, "bool"),
        "reception_clue_exchange": ("进行线索交流", True, "bool"),
        "reception_send_clue": ("赠送线索", True, "bool"),
        "continue_training": ("继续未完成的专精训练", False, "bool"),
    },
    "Mall": {
        "visit_friends": ("访问好友基建", True, "bool"),
        "shopping": ("购物", True, "bool"),
        "buy_first": ("优先购买（商品名）", ["招聘许可", "龙门币"], "list"),
        "blacklist": ("购物黑名单（商品名）", ["碳", "家具零件", "加急许可"], "list"),
        "only_buy_discount": ("只买折扣物品", False, "bool"),
        "reserve_max_credit": ("信用低于 300 停止购买", False, "bool"),
        "force_shopping_if_credit_full": ("信用溢出时无视黑名单", False, "bool"),
    },
    "Award": {
        "award": ("每日/每周任务奖励", True, "bool"),
        "mail": ("所有邮件奖励", True, "bool"),
        "recruit": ("限定池每日免费单抽", True, "bool"),
        "orundum": ("幸运墙合成玉", True, "bool"),
        "mining": ("限时开采许可合成玉", True, "bool"),
        "specialaccess": ("五周年月卡奖励", False, "bool"),
        "signinevent": ("限时签到活动", True, "bool"),
    },
    "Roguelike": {
        "theme": ("主题", "Sarkaz",
                  ["Phantom", "Mizuki", "Sami", "Sarkaz", "JieGarden"]),
        "mode": ("策略：0刷等级 / 1刷源石锭 / 2刷开局 / 4刷坍缩范式", 0, "int"),
        "squad": ("分队（如 指挥分队/后勤分队）", "Default", "text"),
        "roles": ("职业组（如 近卫方舟/高台突破）", "Default", "text"),
        "core_char": ("指定核心干员", "", "text"),
        "use_support": ("使用助战干员", False, "bool"),
        "use_nonfriend_support": ("使用非好友助战", False, "bool"),
        "starts_count": ("开始探索次数（打多少把）", 9999999, "int"),
        "difficulty": ("难度（0=默认）", 0, "int"),
        "investment_enabled": ("存源石锭", True, "bool"),
        "investments_count": ("最多投资几次", 999, "int"),
        "stop_when_investment_full": ("投资满了就停止任务", False, "bool"),
        "expected_collapse": ("预期坍缩值（刷坍缩模式）", 0, "int"),
        "start_with_elite_two": ("开局精二（刷开局模式）", False, "bool"),
    },
}


def tasks_dir():
    return TASKS_DIR


def _read_head(path):
    """读文件头注释里的 @name / @desc。"""
    name, desc = "", ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                p = line.split(None, 2)
                if len(p) == 3 and p[0] == "#":
                    if p[1] == "@name":
                        name = p[2].strip()
                    elif p[1] == "@desc":
                        desc = p[2].strip()
    except OSError:
        pass
    return name, desc


def list_tasks():
    out = []
    try:
        files = sorted(f for f in os.listdir(tasks_dir()) if f.endswith(".toml"))
    except OSError:
        return out
    for fn in files:
        tid = fn[:-5]
        name, desc = _read_head(os.path.join(tasks_dir(), fn))
        out.append({"id": tid, "name": name or tid, "desc": desc})
    return out


def task_path(tid):
    return os.path.join(tasks_dir(), tid + ".toml")


def read_blocks(tid):
    """返回 [{'name','type','params'}]，与文件里 [[tasks]] 的顺序一致。"""
    p = task_path(tid)
    try:
        with open(p, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return []
    out = []
    for t in data.get("tasks", []):
        out.append({"name": t.get("name", ""), "type": t.get("type", ""),
                    "params": dict(t.get("params", {}))})
    return out


def toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_params(params):
    return "params = { " + ", ".join("%s = %s" % (k, toml_value(v)) for k, v in params.items()) + " }"


def save_blocks(tid, blocks):
    """把每个 [[tasks]] 块的 params 写回文件，其余内容（注释等）原样保留。"""
    p = task_path(tid)
    with open(p, encoding="utf-8") as f:
        lines = f.read().splitlines()
    out, idx, i, n = [], 0, 0, len(lines)
    while i < n:
        line = lines[i]
        if line.strip() == "[[tasks]]":
            blk = blocks[idx] if idx < len(blocks) else None
            idx += 1
            out.append(line)
            j = i + 1
            body = []
            while j < n and lines[j].strip() != "[[tasks]]":
                body.append(lines[j])
                j += 1
            params = (blk or {}).get("params") or {}
            wrote = False
            for k, bl in enumerate(body):
                if bl.strip().startswith("params"):
                    if params:
                        body[k] = render_params(params)
                    else:
                        body[k] = ""
                    wrote = True
                    break
            if not wrote and params:
                pos = 0
                for k, bl in enumerate(body):
                    if bl.strip().startswith("type"):
                        pos = k + 1
                        break
                body.insert(pos, render_params(params))
            out.extend(body)
            i = j
        else:
            out.append(line)
            i += 1
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    if not text.endswith("\n"):
        text += "\n"
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def parse_value(raw, kind):
    raw = (raw or "").strip()
    if kind == "bool":
        return raw.lower() in ("true", "1", "yes", "on", "是")
    if kind == "int":
        try:
            return int(float(raw))
        except ValueError:
            return 0
    if kind == "float":
        try:
            return float(raw)
        except ValueError:
            return 0.0
    if kind == "list":
        s = raw.strip()
        if s.startswith("[") and s.endswith("]"):
            s = s[1:-1]
        items = [x.strip().strip('"').strip("'") for x in s.split(",")] if s else []
        out = []
        for x in items:
            if not x:
                continue
            try:
                out.append(int(x))
            except ValueError:
                out.append(x)
        return out
    return raw


def fmt_value(v, kind):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return "[" + ", ".join(str(x) for x in v) + "]"
    return str(v)


def is_running():
    return subprocess.run(["pgrep", "-f", RUNNER],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def current_task():
    try:
        with open(STATE) as f:
            return f.read().strip()
    except OSError:
        return ""


def log_tail(n=150):
    try:
        with open(LOG, "r", errors="replace") as f:
            return "".join(f.readlines()[-n:]) or "(暂无内容)"
    except OSError:
        return "(还没有运行记录)"


def start_run(task):
    if is_running():
        return False
    env = dict(os.environ)
    env["MAA_TASK"] = task
    fh = open(LOG, "a")
    subprocess.Popen(["setsid", RUNNER], stdout=fh, stderr=subprocess.STDOUT, env=env)
    try:
        with open(STATE, "w") as f:
            f.write(task)
    except OSError:
        pass
    return True


def stop_run():
    for sig in ("-TERM", "-KILL"):
        for pat in (RUNNER, "/usr/local/bin/maa run", "adb connect"):
            subprocess.run(["pkill", sig, "-f", pat],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
    subprocess.run(["pkill", "-KILL", "-f", "adb -L tcp:5037"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


STYLE = """
 body{font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
      background:#12151c;color:#e6e8ee;margin:0;padding:22px}
 .card{max-width:940px;margin:0 auto;background:#1b1f2a;border-radius:14px;padding:24px;
       box-shadow:0 6px 24px rgba(0,0,0,.35)}
 h1{font-size:20px;margin:0 0 4px}
 h2{font-size:17px;margin:0 0 14px}
 .sub{color:#8b93a7;font-size:13px;margin-bottom:18px}
 .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;vertical-align:middle}
 .on{background:#3ddc84;box-shadow:0 0 8px #3ddc84}
 .off{background:#5a6272}
 .row{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(215px,1fr));gap:10px;margin:0 0 4px}
 button{font-size:15px;padding:11px 16px;border:0;border-radius:9px;cursor:pointer;
        font-weight:600;transition:filter .15s}
 button:hover:not(:disabled){filter:brightness(1.15)}
 .go{background:#2b3446;color:#dfe6f5;width:100%}
 .primary{background:#3ddc84;color:#08240f}
 .stop{background:#ff5c5c;color:#2a0505}
 button:disabled{opacity:.35;cursor:not-allowed}
 .tcard{background:#20263a;border-radius:11px;padding:10px}
 .tfoot{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:6px}
 .d{color:#7d869b;font-size:11.5px;line-height:1.35}
 a.cfg{color:#8b93a7;text-decoration:none;font-size:15px;padding:2px 6px;border-radius:6px}
 a.cfg:hover{background:#2b3446;color:#dfe6f5}
 pre{background:#0d1016;border-radius:9px;padding:14px;height:42vh;overflow:auto;
     font-size:12.5px;line-height:1.5;white-space:pre-wrap;word-break:break-all;color:#b9c2d4}
 h3{font-size:13px;color:#8b93a7;margin:22px 0 8px;font-weight:500}
 .blk{background:#20263a;border-radius:11px;padding:14px 16px;margin-bottom:12px}
 .bh{font-size:14px;margin-bottom:10px;color:#cfd6e6}
 .bh code{color:#8b93a7;font-size:12.5px;margin-left:6px}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th{text-align:left;color:#7d869b;font-weight:500;font-size:12px;padding:2px 6px}
 td{padding:3px 6px;vertical-align:middle}
 td.k code{color:#a9b6cf;font-size:12.5px}
 td.hint{color:#6f788c;font-size:11.5px}
 input[type=text],select{background:#0d1016;border:1px solid #2b3446;border-radius:7px;
        color:#e6e8ee;padding:6px 9px;font-size:13px;width:100%;box-sizing:border-box}
 input[type=text]:focus,select:focus{outline:0;border-color:#3ddc84}
 input[type=checkbox]{width:16px;height:16px;accent-color:#3ddc84}
 .actions{display:flex;gap:12px;align-items:center;margin-top:6px}
 .back{color:#8b93a7;text-decoration:none;font-size:13px}
 .back:hover{color:#dfe6f5}
 .empty{color:#7d869b;font-size:13px}
"""

MENU_PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MAA 控制台</title>
<style>__STYLE__</style></head><body><div class="card">
<h1>明日方舟 · MAA 控制台</h1>
<div class="sub">NAS → ADB → PC 上 MuMu 模拟器里的游戏</div>
<div class="row">
  <div id="st" style="font-size:15px">__STATUS__</div>
  <div><form method="post" action="/stop" style="margin:0">
    <button id="sp" class="stop" style="width:auto;padding:11px 26px"__STOPDIS__>■ 停止</button>
  </form></div>
</div>
<h3>功能选单（点按钮执行，点 ⚙ 调参数）</h3>
<div class="grid" id="tasks">__TASKS__</div>
<h3>运行日志（每 5 秒自动刷新）</h3>
<pre id="log">__LOG__</pre>
</div>
<script>
async function tick(){
  try{
    const r = await fetch('/api/state', {cache:'no-store'});
    const j = await r.json();
    document.getElementById('st').innerHTML = j.running
      ? '<span class="dot on"></span>运行中' + (j.taskName ? '：' + j.taskName : '')
      : '<span class="dot off"></span>空闲';
    document.querySelectorAll('#tasks button').forEach(function(b){ b.disabled = j.running; });
    document.getElementById('sp').disabled = !j.running;
    const el = document.getElementById('log');
    if (el.textContent !== j.log) { el.textContent = j.log; el.scrollTop = el.scrollHeight; }
  }catch(e){}
}
setInterval(tick, 5000);
</script>
</body></html>"""

TASK_PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ · 设置</title>
<style>__STYLE__</style></head><body><div class="card">
<form method="post" action="/task/__ID__">
<h2>⚙ __TITLE__ <span class="d">— __DESC__</span></h2>
<div class="sub">改完点保存，直接写回 <code>config/tasks/__ID__.toml</code>，下次执行即生效（无需重启）</div>
__BLOCKS__
<div class="actions">
  <button class="go primary" type="submit" style="width:auto;padding:11px 26px">💾 保存</button>
  <a class="back" href="/">← 返回功能选单</a>
</div>
</form>
</div></body></html>"""


def esc(v, quote_attr=False):
    return html.escape(str(v), quote=quote_attr)


def value_input(field, value, kind, checked):
    """渲染一个参数的输入控件。"""
    v = fmt_value(value, kind)
    if isinstance(kind, list):  # 下拉候选
        opts = "".join('<option value="%s"%s>%s</option>'
                       % (esc(o, True), " selected" if str(o) == v else "", esc(o)) for o in kind)
        if v not in [str(o) for o in kind]:
            opts += '<option value="%s" selected>%s</option>' % (esc(v, True), esc(v))
        ctl = '<select name="%s">%s</select>' % (esc(field, True), opts)
    elif kind == "bool":
        ctl = ('<select name="%s"><option value="true"%s>true（启用）</option>'
               '<option value="false"%s>false（关闭）</option></select>'
               % (esc(field, True), " selected" if str(v) == "true" else "",
                  " selected" if str(v) == "false" else ""))
    else:
        ctl = '<input type="text" name="%s" value="%s">' % (esc(field, True), esc(v, True))
    return ctl


def render_task_page(tid, blocks):
    rows_html = []
    for i, b in enumerate(blocks):
        ttype = b.get("type", "")
        known = KNOWN.get(ttype, {})
        cur = b.get("params", {})
        rows = []
        # 1) 已知参数
        for key, meta in known.items():
            label, default, kind = meta
            present = key in cur
            val = cur[key] if present else default
            rows.append(
                '<tr><td><input type="checkbox" name="on.%d.%s" value="1"%s></td>'
                '<td class="k"><code>%s</code></td>'
                '<td>%s</td><td class="hint">%s</td></tr>'
                % (i, esc(key, True), " checked" if present else "",
                   esc(key), value_input("p.%d.%s" % (i, key), val, kind, present),
                   esc(label)))
        # 2) 文件里有、但不在知识库里的参数（原样保留，可删）
        for key, val in cur.items():
            if key in known:
                continue
            rows.append(
                '<tr><td><input type="checkbox" name="on.%d.%s" value="1" checked></td>'
                '<td class="k"><code>%s</code></td>'
                '<td><input type="text" name="p.%d.%s" value="%s"></td>'
                '<td class="hint">（自定义参数）</td></tr>'
                % (i, esc(key, True), esc(key), i, esc(key, True), esc(fmt_value(val, ""), True)))
        rows_html.append(
            '<div class="blk">'
            '<div class="bh"><b>%s</b><code>%s</code></div>'
            '<table><tr><th style="width:44px">启用</th><th style="width:180px">参数</th>'
            '<th style="width:230px">值</th><th>说明</th></tr>%s</table>'
            '</div>'
            % (esc(b.get("name") or ttype), esc(ttype), "".join(rows)))
    if not rows_html:
        rows_html.append('<p class="empty">这个文件里没有 [[tasks]] 块</p>')
    return "".join(rows_html)


def task_cards(running):
    items = list_tasks()
    if not items:
        return '<p class="empty">config/tasks/ 下没有 .toml 任务文件</p>'
    cards = []
    for t in items:
        cls = "go primary" if t["id"] == DEFAULT_TASK else "go"
        dis = " disabled" if running else ""
        cards.append(
            '<div class="tcard">'
            '<form method="post" action="/start" style="margin:0">'
            '<input type="hidden" name="task" value="' + esc(t["id"], True) + '">'
            '<button class="' + cls + '"' + dis + '>' + esc(t["name"]) + '</button>'
            '</form>'
            '<div class="tfoot"><span class="d">' + esc(t["desc"] or t["id"]) + '</span>'
            '<a class="cfg" href="/task/' + quote(t["id"]) + '" title="调整参数">⚙</a>'
            '</div></div>')
    return "\n".join(cards)


class H(BaseHTTPRequestHandler):
    def _authorized(self):
        if not PASSWORD:
            return True
        if TOKEN and (COOKIE + "=" + TOKEN) in self.headers.get("Cookie", ""):
            return True
        want = "Basic " + base64.b64encode(("%s:%s" % (USER, PASSWORD)).encode()).decode()
        return self.headers.get("Authorization") == want

    def _deny(self):
        body = ("<h3>需要登录。想免密就用 http://&lt;IP&gt;:%d/?k=&lt;密码&gt; 打开一次。</h3>"
                % PORT).encode()
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="MAA"')
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send(self, code, data, ctype="text/html; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _task_name(self, tid):
        for t in list_tasks():
            if t["id"] == tid:
                return t["name"]
        return tid

    def do_GET(self):
        path = urlparse(self.path).path
        if PASSWORD:
            q = parse_qs(urlparse(self.path).query)
            if q.get("k") and q["k"][0] == PASSWORD:
                self._send(303, b"", extra={"Set-Cookie":
                    "%s=%s; Path=/; Max-Age=31536000; SameSite=Lax" % (COOKIE, TOKEN),
                    "Location": "/"})
                return
        if not self._authorized():
            return self._deny()

        if path == "/api/state":
            run = is_running()
            cur = current_task()
            data = json.dumps({"running": run, "task": cur,
                               "taskName": self._task_name(cur) if cur else "",
                               "log": log_tail()}).encode()
            return self._send(200, data, "application/json; charset=utf-8")

        if path.startswith("/task/"):
            tid = unquote(path[len("/task/"):]).strip("/")
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", tid or ""):
                return self._send(404, "任务名不合法".encode())
            if not os.path.isfile(task_path(tid)):
                return self._send(404, "找不到该任务".encode())
            meta = next((t for t in list_tasks() if t["id"] == tid),
                        {"name": tid, "desc": ""})
            body = (TASK_PAGE
                    .replace("__STYLE__", STYLE)
                    .replace("__TITLE__", esc(meta["name"]))
                    .replace("__DESC__", esc(meta["desc"] or tid))
                    .replace("__ID__", esc(tid, True))
                    .replace("__BLOCKS__", render_task_page(tid, read_blocks(tid)))).encode()
            return self._send(200, body)

        run = is_running()
        cur = current_task()
        if run:
            status = ('<span class="dot on"></span>运行中'
                      + ("　<b>" + esc(self._task_name(cur)) + "</b>" if cur else ""))
        else:
            status = '<span class="dot off"></span>空闲'
        body = (MENU_PAGE
                .replace("__STYLE__", STYLE)
                .replace("__STATUS__", status)
                .replace("__STOPDIS__", "" if run else " disabled")
                .replace("__TASKS__", task_cards(run))
                .replace("__LOG__", html.escape(log_tail()))).encode()
        self._send(200, body)

    def do_POST(self):
        if not self._authorized():
            return self._deny()
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""

        if path.startswith("/task/"):
            tid = unquote(path[len("/task/"):]).strip("/")
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", tid or ""):
                return self._send(404, "任务名不合法".encode())
            form = parse_qs(raw, keep_blank_values=True)
            blocks = read_blocks(tid)
            if not blocks:
                # 解析不出 [[tasks]] 就拒绝保存，避免把原文件写坏
                return self._send(400, "任务文件解析失败，已拒绝保存".encode())
            new_params = [dict() for _ in blocks]
            for field, vals in form.items():
                if not field.startswith("p."):
                    continue
                parts = field.split(".", 2)
                if len(parts) != 3:
                    continue
                try:
                    idx = int(parts[1])
                except ValueError:
                    continue
                if not (0 <= idx < len(blocks)):
                    continue
                key = parts[2]
                if ("on.%d.%s" % (idx, key)) not in form:
                    continue  # 未勾选启用
                kind = KNOWN.get(blocks[idx].get("type", ""), {}).get(key, ("", "", "text"))[2]
                new_params[idx][key] = parse_value(vals[0] if vals else "", kind)
            for i, b in enumerate(blocks):
                b["params"] = new_params[i]
            save_blocks(tid, blocks)
            return self._send(303, b"", extra={"Location": "/task/" + quote(tid) + "?saved=1"})

        if path == "/start":
            task = (parse_qs(raw).get("task") or [DEFAULT_TASK])[0]
            if task not in [t["id"] for t in list_tasks()]:
                task = DEFAULT_TASK
            start_run(task)
        elif path == "/stop":
            stop_run()
        self._send(303, b"", extra={"Location": "/"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("[webctl] listening on 0.0.0.0:%d (user=%s, cookie=%s, tasks=%s)"
          % (PORT, USER, "on" if TOKEN else "off", len(list_tasks())), flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()

#!/usr/bin/env python3
"""MAA 控制台：网页上选功能一键执行 + 实时日志。

认证：HTTP Basic，或「记住我」Cookie。
首次用  http://<IP>:<PORT>/?k=<密码>  打开一次，写入 1 年有效期的 Cookie，之后免密。

功能选单来自 $MAA_TASKS_DIR（默认 /maa/config/tasks）里的 *.toml：
  - 文件名（去掉 .toml）= 任务 ID
  - 文件头注释 `# @name 显示名` / `# @desc 说明` 用作按钮文字

执行时把 MAA_TASK=<任务ID> 传给 run-daily.sh。
"""
import base64, hashlib, html, json, os, subprocess, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

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


def is_running():
    return subprocess.run(["pgrep", "-f", RUNNER],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def current_task():
    try:
        with open(STATE) as f:
            return f.read().strip()
    except OSError:
        return ""


def list_tasks():
    """扫描任务目录，返回 [{'id','name','desc'}]，按文件名排序。"""
    out = []
    try:
        files = sorted(f for f in os.listdir(TASKS_DIR) if f.endswith(".toml"))
    except OSError:
        return out
    for fn in files:
        tid = fn[:-5]
        name, desc = tid, ""
        try:
            with open(os.path.join(TASKS_DIR, fn), encoding="utf-8", errors="replace") as f:
                for line in f:
                    p = line.split(None, 2)
                    if len(p) == 3 and p[0] == "#":
                        if p[1] == "@name":
                            name = p[2].strip()
                        elif p[1] == "@desc":
                            desc = p[2].strip()
        except OSError:
            pass
        out.append({"id": tid, "name": name, "desc": desc})
    return out


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
    """先 TERM 再 KILL，并一并清掉卡住的 adb connect。"""
    for sig in ("-TERM", "-KILL"):
        for pat in (RUNNER, "/usr/local/bin/maa run", "adb connect"):
            subprocess.run(["pkill", sig, "-f", pat],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
    subprocess.run(["pkill", "-KILL", "-f", "adb -L tcp:5037"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def task_cards(running):
    items = list_tasks()
    if not items:
        return '<p class="empty">config/tasks/ 下没有 .toml 任务文件</p>'
    cards = []
    for t in items:
        cls = "go primary" if t["id"] == DEFAULT_TASK else "go"
        dis = " disabled" if running else ""
        cards.append(
            '<form method="post" action="/start">'
            '<input type="hidden" name="task" value="' + html.escape(t["id"], quote=True) + '">'
            '<button class="' + cls + '"' + dis + '>' + html.escape(t["name"]) + '</button>'
            '<span class="d">' + html.escape(t["desc"] or t["id"]) + '</span>'
            '</form>')
    return "\n".join(cards)


PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MAA 控制台</title>
<style>
 body{font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
      background:#12151c;color:#e6e8ee;margin:0;padding:22px}
 .card{max-width:940px;margin:0 auto;background:#1b1f2a;border-radius:14px;padding:24px;
       box-shadow:0 6px 24px rgba(0,0,0,.35)}
 h1{font-size:20px;margin:0 0 4px}
 .sub{color:#8b93a7;font-size:13px;margin-bottom:18px}
 .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;vertical-align:middle}
 .on{background:#3ddc84;box-shadow:0 0 8px #3ddc84}
 .off{background:#5a6272}
 .row{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(215px,1fr));gap:10px;margin:0 0 4px}
 .grid form{display:flex;flex-direction:column;gap:5px;margin:0}
 button{font-size:15px;padding:11px 16px;border:0;border-radius:9px;cursor:pointer;
        font-weight:600;width:100%;transition:filter .15s}
 button:hover:not(:disabled){filter:brightness(1.15)}
 .go{background:#2b3446;color:#dfe6f5}
 .primary{background:#3ddc84;color:#08240f}
 .stop{background:#ff5c5c;color:#2a0505}
 button:disabled{opacity:.35;cursor:not-allowed}
 .d{color:#7d869b;font-size:11.5px;text-align:center;line-height:1.35}
 .empty{color:#7d869b;font-size:13px}
 pre{background:#0d1016;border-radius:9px;padding:14px;height:44vh;overflow:auto;
     font-size:12.5px;line-height:1.5;white-space:pre-wrap;word-break:break-all;color:#b9c2d4}
 h3{font-size:13px;color:#8b93a7;margin:22px 0 8px;font-weight:500}
</style></head><body><div class="card">
<h1>明日方舟 · MAA 控制台</h1>
<div class="sub">NAS → ADB → PC 上 MuMu 模拟器里的游戏</div>
<div class="row">
  <div id="st" style="font-size:15px">__STATUS__</div>
  <div><form method="post" action="/stop" style="margin:0">
    <button id="sp" class="stop" style="width:auto;padding:11px 26px"__STOPDIS__>■ 停止</button>
  </form></div>
</div>
<h3>功能选单（点击即执行）</h3>
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

    def do_GET(self):
        # 免密令牌入口： /?k=<密码>
        if PASSWORD:
            q = parse_qs(urlparse(self.path).query)
            if q.get("k") and q["k"][0] == PASSWORD:
                self._send(303, b"", extra={"Set-Cookie":
                    "%s=%s; Path=/; Max-Age=31536000; SameSite=Lax" % (COOKIE, TOKEN),
                    "Location": "/"})
                return
        if not self._authorized():
            return self._deny()

        if urlparse(self.path).path == "/api/state":
            run = is_running()
            cur = current_task()
            name = ""
            for t in list_tasks():
                if t["id"] == cur:
                    name = t["name"]
                    break
            data = json.dumps({"running": run, "task": cur, "taskName": name,
                               "log": log_tail()}).encode()
            return self._send(200, data, "application/json; charset=utf-8")

        run = is_running()
        cur = current_task()
        cur_name = ""
        for t in list_tasks():
            if t["id"] == cur:
                cur_name = t["name"]
                break
        if run:
            status = ('<span class="dot on"></span>运行中'
                      + ("　<b>" + html.escape(cur_name or cur) + "</b>" if cur else ""))
        else:
            status = '<span class="dot off"></span>空闲'

        body = (PAGE
                .replace("__STATUS__", status)
                .replace("__STOPDIS__", "" if run else " disabled")
                .replace("__TASKS__", task_cards(run))
                .replace("__LOG__", html.escape(log_tail()))).encode()
        self._send(200, body)

    def do_POST(self):
        if not self._authorized():
            return self._deny()
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        if urlparse(self.path).path == "/start":
            task = (parse_qs(raw).get("task") or [DEFAULT_TASK])[0]
            if task not in [t["id"] for t in list_tasks()]:
                task = DEFAULT_TASK
            start_run(task)
        elif urlparse(self.path).path == "/stop":
            stop_run()
        self._send(303, b"", extra={"Location": "/"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("[webctl] listening on 0.0.0.0:%d (user=%s, cookie=%s, tasks=%s)"
          % (PORT, USER, "on" if TOKEN else "off", len(list_tasks())), flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()

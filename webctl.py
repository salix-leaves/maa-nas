#!/usr/bin/env python3
"""MAA 手动开关：网页开始/停止日常 + 实时日志。

认证：HTTP Basic，或「记住我」Cookie。
首次用  http://<IP>:5599/?k=<密码>  打开一次，写入 1 年有效期的 Cookie，之后免密。
"""
import base64, hashlib, html, json, os, subprocess, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("MAA_WEB_PORT", "5599"))
USER = os.environ.get("MAA_WEB_USER", "maa")
PASSWORD = os.environ.get("MAA_WEB_PASSWORD", "")
LOG = os.environ.get("MAA_LOG", "/maa/data/run.log")
RUNNER = "/usr/local/bin/run-daily.sh"
TASK = os.environ.get("MAA_TASK", "daily")

COOKIE = "maatoken"
TOKEN = hashlib.sha256(("%s:%s" % (USER, PASSWORD)).encode()).hexdigest() if PASSWORD else ""

def is_running():
    return subprocess.run(["pgrep", "-f", RUNNER],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0

def log_tail(n=150):
    try:
        with open(LOG, "r", errors="replace") as f:
            return "".join(f.readlines()[-n:]) or "(暂无内容)"
    except OSError:
        return "(还没有运行记录)"

def start_run():
    if is_running():
        return
    fh = open(LOG, "a")
    subprocess.Popen(["setsid", RUNNER], stdout=fh, stderr=subprocess.STDOUT)

def stop_run():
    """先 TERM 再 KILL，并一并清掉卡住的 adb connect。"""
    for sig in ("-TERM", "-KILL"):
        for pat in (RUNNER, "/usr/local/bin/maa run", "adb connect"):
            subprocess.run(["pkill", sig, "-f", pat],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
    subprocess.run(["pkill", "-KILL", "-f", "adb -L tcp:5037"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MAA 手动开关</title>
<style>
 body{{font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
      background:#12151c;color:#e6e8ee;margin:0;padding:22px}}
 .card{{max-width:940px;margin:0 auto;background:#1b1f2a;border-radius:14px;padding:24px;
       box-shadow:0 6px 24px rgba(0,0,0,.35)}}
 h1{{font-size:20px;margin:0 0 4px}}
 .sub{{color:#8b93a7;font-size:13px;margin-bottom:20px}}
 .dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;vertical-align:middle}}
 .on{{background:#3ddc84;box-shadow:0 0 8px #3ddc84}}
 .off{{background:#5a6272}}
 form{{display:inline}}
 button{{font-size:15px;padding:11px 26px;border:0;border-radius:9px;cursor:pointer;
        margin-left:10px;font-weight:600}}
 .go{{background:#3ddc84;color:#08240f}}
 .stop{{background:#ff5c5c;color:#2a0505}}
 button:disabled{{opacity:.35;cursor:not-allowed}}
 pre{{background:#0d1016;border-radius:9px;padding:14px;height:46vh;overflow:auto;
     font-size:12.5px;line-height:1.5;white-space:pre-wrap;word-break:break-all;color:#b9c2d4}}
 .row{{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}}
 h3{{font-size:13px;color:#8b93a7;margin:22px 0 8px;font-weight:500}}
</style></head><body><div class="card">
<h1>明日方舟 · MAA 手动开关</h1>
<div class="sub">NAS → ADB → PC 上 MuMu 里的游戏 &nbsp;·&nbsp; 任务清单：{task}</div>
<div class="row">
  <div id="st" style="font-size:15px">{status}</div>
  <div>
    <form method="post" action="/start"><button id="go" class="go" {gos}>{gol}</button></form>
    <form method="post" action="/stop"><button id="sp" class="stop" {stos}>{stol}</button></form>
  </div>
</div>
<h3>运行日志（每 5 秒自动刷新）</h3>
<pre id="log">{log}</pre>
</div>
<script>
async function tick(){{
  try{{
    const r = await fetch('/api/state', {{cache:'no-store'}});
    const j = await r.json();
    document.getElementById('st').innerHTML = j.running
      ? '<span class="dot on"></span>运行中'
      : '<span class="dot off"></span>空闲';
    document.getElementById('go').disabled = j.running;
    document.getElementById('sp').disabled = !j.running;
    const el = document.getElementById('log');
    if (el.textContent !== j.log) {{ el.textContent = j.log; el.scrollTop = el.scrollHeight; }}
  }}catch(e){{}}
}}
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
        body = ("<h3>需要登录。想免密就用 http://&lt;IP&gt;:%d/?k=&lt;密码&gt; 打开一次。</h3>" % PORT).encode()
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
            data = json.dumps({"running": is_running(), "log": log_tail()}).encode()
            return self._send(200, data, "application/json; charset=utf-8")

        run = is_running()
        body = PAGE.format(
            task=html.escape(TASK),
            status=('<span class="dot on"></span>运行中' if run else '<span class="dot off"></span>空闲'),
            gos="disabled" if run else "", gol="▶ 开始日常",
            stos="" if run else "disabled", stol="■ 停止",
            log=html.escape(log_tail()),
        ).encode()
        self._send(200, body)

    def do_POST(self):
        if not self._authorized():
            return self._deny()
        if self.path == "/start":
            start_run()
        elif self.path == "/stop":
            stop_run()
        self._send(303, b"", extra={"Location": "/"})

    def log_message(self, *a):
        pass

if __name__ == "__main__":
    print("[webctl] listening on 0.0.0.0:%d (user=%s, cookie=%s)"
          % (PORT, USER, "on" if TOKEN else "off"), flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()

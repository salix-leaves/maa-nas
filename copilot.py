#!/usr/bin/env python3
"""MAA 作业（Copilot）自动查找 + 下载 + 批量任务生成。

从作业站 prts.maa.plus 按关卡精确搜索作业，解析每份作业里的干员名单，
过滤掉使用了「屏蔽干员」的作业，按热度选出最优，下载保存，并可生成
「多作业模式」任务（copilot_list）一次连续打完多个关卡。

用法：
  python3 copilot.py <关卡> [--ban 干员1,干员2] [--limit N] [--task 输出.toml] [--ignore-req true]

  <关卡> 支持：
    - 单关：YW-8 / act52side_08 / 鳞的记忆
    - 批量：昨日海（活动名，匹配该活动全部关卡，逐个找最优作业）

  加 --task 时会生成一份 Copilot 任务 TOML（多关卡用 copilot_list 连续战斗）。

环境变量：
  MAA_COPILOT_API   作业站 API 域名，默认 https://prts.maa.plus
  MAA_COPILOT_DIR   作业保存目录，默认 /maa/config/copilot
  MAA_COPILOT_BAN   默认屏蔽干员（逗号分隔）

退出码：0 成功；1 找不到匹配作业；2 网络/解析错误。
"""
import json
import os
import sys
import urllib.parse
import urllib.request

API = os.environ.get("MAA_COPILOT_API", "https://prts.maa.plus")
COPILOT_DIR = os.environ.get("MAA_COPILOT_DIR", "/maa/config/copilot")
DEFAULT_BAN = os.environ.get("MAA_COPILOT_BAN", "号角,阿斯卡纶,娜仁图雅,娜仁图亚")
LEVEL_CACHE = os.path.join(COPILOT_DIR, ".level-list.json")


def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "maa-nas-copilot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_levels(force=False):
    if not force and os.path.exists(LEVEL_CACHE):
        try:
            with open(LEVEL_CACHE, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    data = http_get(API + "/arknights/level/v2?lite=true")
    levels = data.get("data", {}).get("levels", [])
    try:
        os.makedirs(COPILOT_DIR, exist_ok=True)
        with open(LEVEL_CACHE, "w", encoding="utf-8") as f:
            json.dump(levels, f, ensure_ascii=False)
    except OSError:
        pass
    return levels


def resolve_stages(levels, query):
    """把用户给的关卡写法解析成 stage_id 列表（可能匹配多个关卡）。

    批量首通场景：跳过突袭变体（stage_id 带 #f#）和教学关（代码含 -TR），
    并按显示代码（cat_three）去重。
    """
    q = query.strip()
    exact = []
    fuzzy = []
    for lv in levels:
        sid = lv.get("stage_id", "")
        if "#f#" in sid:
            continue  # 突袭变体，批量首通用普通难度
        cat3 = lv.get("cat_three", "")
        if "-TR" in cat3:
            continue  # 教学关，跳过
        cat2 = lv.get("cat_two", "")
        name = lv.get("name", "")
        if q in (sid, cat3, name, cat2):
            exact.append(lv)
        elif q.lower() in (sid.lower(), cat3.lower(), name.lower(), cat2.lower()):
            fuzzy.append(lv)
    seen = set()
    out = []
    for lv in exact + fuzzy:
        key = lv.get("cat_three") or lv.get("stage_id")
        if key and key not in seen:
            seen.add(key)
            out.append(lv)
    return out


def copilot_operators(content_json):
    names = set()
    try:
        data = json.loads(content_json) if isinstance(content_json, str) else content_json
    except (json.JSONDecodeError, TypeError):
        return names
    for op in data.get("opers", []) or []:
        if op.get("name"):
            names.add(op["name"])
    for grp in data.get("groups", []) or []:
        for op in grp.get("opers", []) or []:
            if op.get("name"):
                names.add(op["name"])
    for act in data.get("actions", []) or []:
        if isinstance(act, dict) and act.get("name"):
            names.add(act["name"])
    return names


def hits_ban(content_json, banned):
    return bool(copilot_operators(content_json) & banned)


def query_copilots(stage_id, limit=50):
    url = "%s/copilot/query?%s" % (API, urllib.parse.urlencode(
        {"levelKeyword": stage_id, "page": 1, "limit": limit}))
    return http_get(url).get("data", {}).get("data", [])


def pick_best(cops, banned):
    ok = []
    for c in cops:
        if not c.get("available", True):
            continue
        if c.get("status") not in (None, "PUBLIC"):
            continue
        if c.get("type") != "PRTS":
            continue
        if hits_ban(c.get("content", ""), banned):
            continue
        ok.append(c)
    ok.sort(key=lambda c: (
        float(c.get("hot_score") or 0),
        int(c.get("like") or 0),
        int(c.get("rating_level") or 0),
        int(c.get("views") or 0),
    ), reverse=True)
    return ok


def summarize(c):
    content = c.get("content", "")
    try:
        doc = json.loads(content).get("doc", {}) or {}
        title = doc.get("title") or "(无标题)"
    except (json.JSONDecodeError, TypeError):
        title = "(无标题)"
    return {
        "id": c.get("id"),
        "author": c.get("uploader"),
        "title": title,
        "hot_score": c.get("hot_score"),
        "like": c.get("like"),
        "views": c.get("views"),
        "operators": sorted(copilot_operators(content)),
    }


def save_copilot(cop, stage):
    """把作业 JSON 落盘，返回 (绝对路径, 导航名)。"""
    safe = (stage.get("cat_three") or stage.get("stage_id")).replace("/", "_")
    path = os.path.join(COPILOT_DIR, safe + ".json")
    os.makedirs(COPILOT_DIR, exist_ok=True)
    content = cop.get("content", "")
    try:
        parsed = json.loads(content)
        text = json.dumps(parsed, ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, TypeError):
        text = content
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    nav = stage.get("cat_three") or stage.get("stage_id")
    return path, nav


def write_task(entries, task_path, ignore_req):
    """entries: [{'filename','nav_name'}]，写 Copilot 任务 TOML（多作业模式）。"""
    items = ", ".join('{ filename = "%s", nav_name_override = "%s" }'
                      % (e["filename"], e["nav_name"]) for e in entries)
    params = ("copilot_list = [" + items + "], formation = true, add_trust = true, "
              "ignore_requirements = " + ("true" if ignore_req else "false")
              + ", support_unit_usage = 1")
    lines = [
        "# @name 自动抄作业",
        "# @desc 动态生成，由 copilot.py 写入，请勿手动编辑",
        "",
        "[[tasks]]",
        'name = "开始唤醒"',
        'type = "StartUp"',
        'params = { client_type = "Official", start_game_enabled = true }',
        "",
        "[[tasks]]",
        'name = "自动抄作业"',
        'type = "Copilot"',
        "params = { " + params + " }",
        "",
        "[[tasks]]",
        'name = "关闭游戏"',
        'type = "CloseDown"',
        'params = { client_type = "Official" }',
        "",
    ]
    os.makedirs(os.path.dirname(task_path) or ".", exist_ok=True)
    with open(task_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    stage_query = args[0]
    banned = set(x.strip() for x in DEFAULT_BAN.split(",") if x.strip())
    limit = 50
    task_path = None
    ignore_req = True
    i = 1
    while i < len(args):
        a = args[i]
        if a == "--ban" and i + 1 < len(args):
            banned = set(x.strip() for x in args[i + 1].split(",") if x.strip())
            i += 2
        elif a == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif a == "--task" and i + 1 < len(args):
            task_path = args[i + 1]
            i += 2
        elif a == "--ignore-req" and i + 1 < len(args):
            ignore_req = args[i + 1].lower() not in ("false", "0", "no")
            i += 2
        else:
            i += 1

    print("[copilot] 加载关卡列表…")
    levels = fetch_levels()
    matches = resolve_stages(levels, stage_query)
    if not matches:
        print("[copilot] 找不到关卡：%s" % stage_query)
        return 1
    print("[copilot] 匹配到 %d 个关卡：%s"
          % (len(matches), "、".join("%s(%s)" % (m.get("cat_three"), m.get("name")) for m in matches)))

    entries = []
    for m in matches:
        sid = m["stage_id"]
        cops = query_copilots(sid, limit)
        ok = pick_best(cops, banned)
        label = "%s(%s)" % (m.get("cat_three"), m.get("name"))
        if not ok:
            print("[copilot] %s 无符合条件的作业，跳过（共 %d 份）" % (label, len(cops)))
            continue
        best = ok[0]
        info = summarize(best)
        path, nav = save_copilot(best, m)
        entries.append({"filename": path, "nav_name": nav})
        print("[copilot] ✓ %s 选「%s」作者 %s（热度 %.1f，%d 份候选）"
              % (label, info["title"], info["author"], info["hot_score"], len(ok)))

    if not entries:
        print("[copilot] 没有任何关卡找到符合条件的作业")
        return 1

    print("[copilot] 共 %d 份作业就绪" % len(entries))
    if task_path:
        write_task(entries, task_path, ignore_req)
        print("[copilot] 任务已生成: %s" % task_path)
    elif len(entries) == 1:
        print("OUT=%s" % entries[0]["filename"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

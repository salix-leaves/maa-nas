#!/usr/bin/env python3
"""MAA 作业（Copilot）自动查找 + 下载。

从作业站 prts.maa.plus 按关卡精确搜索作业，解析每份作业里的干员名单，
过滤掉使用了「屏蔽干员」的作业，按热度选出最优一份，下载保存为 JSON。

用法：
  python3 copilot.py <关卡> [--ban 干员1,干员2,...] [--out /path/x.json] [--limit 50]

  <关卡> 支持多种写法：YW-8（活动关卡代码）、act52side_08（stage_id）、
  「鳞的记忆」（关卡名）、「昨日海」（活动名，会列出所有该活动关卡）。

环境变量：
  MAA_COPILOT_API   作业站 API 域名，默认 https://prts.maa.plus
  MAA_COPILOT_DIR   作业保存目录，默认 /maa/config/copilot
  MAA_COPILOT_BAN   默认屏蔽干员（逗号分隔），CLI --ban 优先

退出码：0 成功；1 找不到匹配作业；2 网络/解析错误。
"""
import json
import os
import sys
import time
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
    """拉取关卡列表（lite），带缓存。"""
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
    """把用户给的关卡写法解析成 stage_id 列表（可能匹配多个关卡）。"""
    q = query.strip()
    exact = []
    fuzzy = []
    for lv in levels:
        sid = lv.get("stage_id", "")
        cat2 = lv.get("cat_two", "")
        cat3 = lv.get("cat_three", "")
        name = lv.get("name", "")
        if q in (sid, cat3, name, cat2):
            exact.append(lv)
        elif q.lower() in (sid.lower(), cat3.lower(), name.lower(), cat2.lower()):
            fuzzy.append(lv)
    # 去重（按 stage_id），优先精确匹配
    seen = set()
    out = []
    for lv in exact + fuzzy:
        sid = lv.get("stage_id")
        if sid and sid not in seen:
            seen.add(sid)
            out.append(lv)
    return out


def copilot_operators(content_json):
    """提取作业 JSON 里用到的全部干员名（opers + groups + actions 的 name）。"""
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
    names = copilot_operators(content_json)
    return bool(names & banned)


def query_copilots(stage_id, limit=50):
    url = "%s/copilot/query?%s" % (API, urllib.parse.urlencode(
        {"levelKeyword": stage_id, "page": 1, "limit": limit}))
    data = http_get(url)
    return data.get("data", {}).get("data", [])


def pick_best(cops, banned):
    """过滤屏蔽干员 + 不可用，按热度排序。"""
    ok = []
    for c in cops:
        if not c.get("available", True):
            continue
        if c.get("status") not in (None, "PUBLIC"):
            continue
        if c.get("type") != "PRTS":
            continue
        content = c.get("content", "")
        if hits_ban(content, banned):
            continue
        ok.append(c)
    # 热度优先，点赞/评分/浏览次之
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


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    stage_query = args[0]
    banned = set(x.strip() for x in DEFAULT_BAN.split(",") if x.strip())
    limit = 50
    out_path = None
    i = 1
    while i < len(args):
        if args[i] == "--ban" and i + 1 < len(args):
            banned = set(x.strip() for x in args[i + 1].split(",") if x.strip())
            i += 2
        elif args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif args[i] == "--out" and i + 1 < len(args):
            out_path = args[i + 1]
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
          % (len(matches), ", ".join("%s(%s)" % (m.get("cat_three"), m.get("name")) for m in matches)))

    all_ok = []
    for m in matches:
        sid = m["stage_id"]
        cops = query_copilots(sid, limit)
        ok = pick_best(cops, banned)
        print("[copilot] %s(%s) 共 %d 份作业，排除屏蔽后剩 %d 份"
              % (m.get("cat_three"), m.get("name"), len(cops), len(ok)))
        for c in ok:
            c["_stage"] = m
        all_ok.extend(ok)

    if not all_ok:
        print("[copilot] 没有符合条件（不含屏蔽干员）的作业")
        return 1

    best = all_ok[0]
    info = summarize(best)
    print("[copilot] 最优作业：")
    print("  作者: %s" % info["author"])
    print("  标题: %s" % info["title"])
    print("  热度: %.2f  点赞: %s  浏览: %s" % (info["hot_score"], info["like"], info["views"]))
    print("  用到干员: %s" % "、".join(info["operators"]))

    stage = best["_stage"]
    safe = (stage.get("cat_three") or stage.get("stage_id")).replace("/", "_")
    if not out_path:
        out_path = os.path.join(COPILOT_DIR, safe + ".json")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    # content 是 JSON 字符串，落盘成格式化 JSON
    content = best.get("content", "")
    try:
        parsed = json.loads(content)
        text = json.dumps(parsed, ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, TypeError):
        text = content
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    print("[copilot] 已保存: %s" % out_path)
    # 输出路径供上层脚本取用
    print("OUT=%s" % out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

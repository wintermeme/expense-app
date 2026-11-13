"""读写数据：优先用 GitHub 私有仓库里的 JSON；没配置密钥时退回本地文件（仅测试用）。"""
import base64
import copy
import json
import os
import time

import requests
import streamlit as st

DEFAULT = {
    "orders": [], "bills": [], "income": [], "drafts": [],
    "item_settings": {},
    "categories": {
        "食材": {"kind": "daily"}, "日用品": {"kind": "daily"},
        "零食饮料（超市）": {"kind": "daily"},
        "外卖堂食": {"kind": "casual"}, "奶茶小吃": {"kind": "casual"},
        "交通": {"kind": "casual"}, "娱乐": {"kind": "casual"},
        "穿": {"kind": "casual", "thr": True},
        "家具家电厨具": {"kind": "big"}, "医疗数码旅行": {"kind": "big"},
        "其他": {"kind": "casual", "thr": True},
    },
    "bill_types": {"房租": "amortize", "物业": "amortize", "网费": "amortize", "话费": "amortize"},
    "budget": {"monthly": 0},
    "settings": {"font": "B", "alert_pct": 15, "big_threshold": 200, "tz": "Asia/Shanghai"},
}
LOCAL_FILE = "expenses_local.json"


class Conflict(Exception):
    pass


def github_conf():
    try:
        return st.secrets["GITHUB_TOKEN"], st.secrets["DATA_REPO"], st.secrets.get("DATA_PATH", "expenses.json")
    except Exception:
        return None


OLD_CATS = {"买菜": "食材", "肉蛋奶": "食材"}


def _migrate(d):
    """把旧分类「买菜」「肉蛋奶」合并成「食材」，历史记录一并改过来。"""
    for o in d.get("orders", []):
        for i in o.get("items", []):
            if i.get("category") in OLD_CATS:
                i["category"] = OLD_CATS[i["category"]]
    cats = d.get("categories", {})
    if any(k in cats for k in OLD_CATS):
        for k in OLD_CATS:
            cats.pop(k, None)
        if "食材" not in cats:
            d["categories"] = {"食材": {"kind": "daily"}, **cats}
    return d


def _fill(d):
    if not isinstance(d, dict):
        d = {}
    for k, v in DEFAULT.items():
        if k not in d:
            d[k] = copy.deepcopy(v)
        elif isinstance(v, dict) and k in ("settings", "budget"):
            for kk, vv in v.items():
                d[k].setdefault(kk, vv)
    return _migrate(d)


def _url(repo, path):
    return f"https://api.github.com/repos/{repo}/contents/{path}"


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def load():
    g = github_conf()
    if not g:
        if os.path.exists(LOCAL_FILE):
            with open(LOCAL_FILE, encoding="utf-8") as f:
                return _fill(json.load(f)), None
        return _fill({}), None
    token, repo, path = g
    r = requests.get(_url(repo, path), headers=_headers(token), timeout=20)
    if r.status_code == 404:
        return _fill({}), None
    r.raise_for_status()
    j = r.json()
    if j.get("content"):
        text = base64.b64decode(j["content"]).decode("utf-8")
    elif j.get("size", 0) > 0:
        # 文件超过 1MB 时 GitHub 不在这里返回内容，改用原始内容接口读取（上限约 100MB）
        r2 = requests.get(_url(repo, path), headers={**_headers(token), "Accept": "application/vnd.github.raw+json"}, timeout=60)
        r2.raise_for_status()
        text = r2.text
        if not text.strip():
            raise RuntimeError("数据文件很大但读取失败，为避免覆盖已停止，请稍后重试")
    else:
        text = ""
    return _fill(json.loads(text) if text.strip() else {}), j["sha"]


def _save(data, sha, msg):
    g = github_conf()
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if not g:
        with open(LOCAL_FILE, "w", encoding="utf-8") as f:
            f.write(text)
        return None
    token, repo, path = g
    body = {"message": msg, "content": base64.b64encode(text.encode("utf-8")).decode()}
    if sha:
        body["sha"] = sha
    r = requests.put(_url(repo, path), headers=_headers(token), json=body, timeout=20)
    if r.status_code in (409, 422):
        raise Conflict()
    r.raise_for_status()
    return r.json()["content"]["sha"]


def update(mutator, msg="update"):
    """先拉最新数据，再套用修改，再写回；遇到冲突自动重试，所以手机电脑同时记账不会互相覆盖。"""
    for _ in range(4):
        data, sha = load()
        mutator(data)
        try:
            sha = _save(data, sha, msg)
        except Conflict:
            time.sleep(0.6)
            continue
        st.session_state["data"] = data
        st.session_state["sha"] = sha
        return data
    raise RuntimeError("同步冲突多次重试仍失败，请稍后再试")

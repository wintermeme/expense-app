"""价格统计、涨价预警、生活费用摊销、月报与建议。"""
import calendar
import datetime as dt

from calc import LABEL, unit_price

DEFAULT_MONTHS = {"房租": 3, "物业": 3, "网费": 1, "话费": 1}
KIND_NAME = {"daily": "日常消耗", "casual": "随手消费", "big": "偶发大件"}


def D(s):
    return dt.date.fromisoformat(s)


def ym_of(d):
    return d.strftime("%Y-%m")


def ym_add(ym, n):
    y, m = map(int, ym.split("-"))
    t = y * 12 + m - 1 + n
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def ym_days(ym):
    y, m = map(int, ym.split("-"))
    return calendar.monthrange(y, m)[1]


def add_months(d, n):
    t = d.year * 12 + d.month - 1 + n
    y, m = t // 12, t % 12 + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def item_setting(data, item):
    s = {"strategy": "随便买", "brand": ""}
    s.update(data["item_settings"].get(item, {}))
    return s


def kind_of(data, it):
    if it.get("big"):
        return "big"
    c = data["categories"].get(it["category"], {"kind": "casual"})
    if c.get("thr") and it["amount"] > data["settings"]["big_threshold"]:
        return "big"
    return c.get("kind", "casual")


def records(data):
    """把所有订单拆成一件件物品，运费/优惠按金额比例摊到每件上，得到“实付”。"""
    out = []
    for o in data["orders"]:
        items = o.get("items", [])
        tot = sum(i["amount"] for i in items)
        ex = sum(e["amount"] for e in o.get("extras", []))
        for i in items:
            paid = i["amount"] + (ex * i["amount"] / tot if tot else 0)
            dim, up = unit_price(i["amount"], i.get("qty"), i.get("unit"))
            _, upp = unit_price(paid, i.get("qty"), i.get("unit"))
            out.append({"date": o["date"], "store": o.get("store", ""), "order": o["id"], "id": i["id"],
                        "item": i["item"], "brand": i.get("brand", ""), "category": i["category"],
                        "qty": i.get("qty"), "unit": i.get("unit"), "amount": i["amount"], "paid": paid,
                        "dim": dim, "up": up, "upp": upp, "kind": kind_of(data, i)})
    return out


def item_records(recs, item, key):
    rs = [r for r in recs if r["item"] == item and r[key] is not None]
    if not rs:
        return []
    dims = [r["dim"] for r in rs]
    main = max(set(dims), key=dims.count)
    return [r for r in rs if r["dim"] == main]


def price_stats(rs, key):
    if not rs:
        return None
    last = max(rs, key=lambda r: r["date"])
    return {"lo": min(rs, key=lambda r: r[key]), "hi": max(rs, key=lambda r: r[key]),
            "avg": sum(r[key] for r in rs) / len(rs), "last": last, "n": len(rs)}


def brand_table(rs, key):
    g = {}
    for r in rs:
        g.setdefault(r["brand"] or "（无品牌）", []).append(r[key])
    rows = [{"品牌": b, "平均": sum(v) / len(v), "最低": min(v), "最高": max(v), "次数": len(v)} for b, v in g.items()]
    return sorted(rows, key=lambda x: x["平均"])


def loyal_trend(data, recs, item, today):
    s = item_setting(data, item)
    rs = [r for r in item_records(recs, item, "upp")
          if (not s["brand"] or r["brand"] == s["brand"]) and (today - D(r["date"])).days <= 90]
    if len(rs) < 2:
        return None
    rs.sort(key=lambda r: r["date"])
    a, b = rs[0]["upp"], rs[-1]["upp"]
    return {"first": a, "last": b, "pct": (b - a) / a * 100, "dim": rs[0]["dim"], "n": len(rs)}


# ---------- 生活费用 ----------
def bill_kind(data, name):
    return data["bill_types"].get(name, "cash")


def bills_of(data, name):
    return sorted([b for b in data["bills"] if b["name"] == name], key=lambda b: b["date"])


def spans(data):
    """房租、物业这类：每笔从缴费日起往后覆盖，到下一笔缴费日为止；最新一笔先按历史间隔或默认周期预估。"""
    out = []
    for name in sorted({b["name"] for b in data["bills"] if bill_kind(data, b["name"]) == "amortize"}):
        bs = bills_of(data, name)
        gaps = [(D(bs[i + 1]["date"]) - D(bs[i]["date"])).days for i in range(len(bs) - 1)]
        for i, b in enumerate(bs):
            s = D(b["date"])
            if i + 1 < len(bs):
                e, est = D(bs[i + 1]["date"]), False
            else:
                e = s + dt.timedelta(days=round(sum(gaps) / len(gaps))) if gaps else add_months(s, DEFAULT_MONTHS.get(name, 1))
                est = True
            if e <= s:
                e = s + dt.timedelta(days=1)
            out.append((name, s, e, b["amount"], est))
    return out


def spread(s, e, amount):
    total = (e - s).days
    res, ym = {}, ym_of(s)
    while True:
        ms = dt.date(int(ym[:4]), int(ym[5:]), 1)
        nms = dt.date(int(ym_add(ym, 1)[:4]), int(ym_add(ym, 1)[5:]), 1)
        ov = (min(e, nms) - max(s, ms)).days
        if ov > 0:
            res[ym] = amount * ov / total
        if nms >= e:
            break
        ym = ym_add(ym, 1)
    return res


def cash_avg(bs):
    """水电气：除最新一笔外的总额 ÷ 第一笔到最新一笔的天数 × 30.4。"""
    if len(bs) < 2:
        return None
    span = (D(bs[-1]["date"]) - D(bs[0]["date"])).days
    if span <= 30:
        return None
    return sum(b["amount"] for b in bs[:-1]) / span * 30.4


def living(data, ym, mode, today):
    rows, total = [], 0.0
    if mode == "cash":
        for name in sorted({b["name"] for b in data["bills"]}):
            v = sum(b["amount"] for b in bills_of(data, name) if b["date"][:7] == ym)
            if v:
                rows.append((name, v, "实缴"))
                total += v
        return total, rows
    for name, s, e, amt, est in spans(data):
        v = spread(s, e, amt).get(ym, 0)
        if v > 0.005:
            rows.append((name, v, "预估" if est else "摊销"))
            total += v
    for name in sorted({b["name"] for b in data["bills"] if bill_kind(data, b["name"]) == "cash"}):
        bs = bills_of(data, name)
        actual = sum(b["amount"] for b in bs if b["date"][:7] == ym)
        avg = cash_avg(bs)
        if avg is not None and bs[0]["date"][:7] <= ym <= ym_of(today):
            rows.append((name, avg, f"月均参考（本月实缴 {actual:.0f}）"))
            total += avg
        elif actual:
            rows.append((name, actual, "实缴"))
            total += actual
    return total, rows


def bill_status(data, today):
    out = []
    for name in sorted({b["name"] for b in data["bills"]}):
        bs = bills_of(data, name)
        if bill_kind(data, name) == "amortize":
            sp = [x for x in spans(data) if x[0] == name][-1]
            left = (sp[2] - today).days
            out.append(f"{name}已付到 {sp[2]}，还剩约 {left} 天" if left >= 0
                       else f"{name}预计已到期 {-left} 天，注意续缴")
        elif len(bs) >= 3:
            gaps = [(D(bs[i + 1]["date"]) - D(bs[i]["date"])).days for i in range(len(bs) - 1)]
            since = (today - D(bs[-1]["date"])).days
            if since > max(gaps):
                out.append(f"{name}已 {since} 天没缴，超过你以往最长间隔 {max(gaps)} 天，注意余额")
    return out


# ---------- 月报 ----------
def cat_sums(data, recs, ym):
    c = {}
    for r in recs:
        if r["date"][:7] == ym and r["kind"] != "big":
            c[r["category"]] = c.get(r["category"], 0) + r["amount"]
    return c


def month_report(data, ym, mode, today):
    cur = ym == ym_of(today)
    dim = ym_days(ym)
    days = today.day if cur else dim
    allr = records(data)
    recs = [r for r in allr if r["date"][:7] == ym]
    kinds = {"daily": 0.0, "casual": 0.0, "big": 0.0}
    for r in recs:
        kinds[r["kind"]] += r["amount"]
    extras = sum(e["amount"] for o in data["orders"] if o["date"][:7] == ym for e in o.get("extras", []))
    liv, liv_rows = living(data, ym, mode, today)
    income = sum(x["amount"] for x in data["income"] if x["date"][:7] == ym)
    run = kinds["daily"] + kinds["casual"] + extras
    spend = run + kinds["big"] + liv
    rep = {"ym": ym, "cur": cur, "days": days, "daily": kinds["daily"], "casual": kinds["casual"],
           "big": kinds["big"], "extras": extras, "living": liv, "living_rows": liv_rows, "income": income,
           "run": run, "spend": spend, "balance": income - spend, "day_avg": run / days if days else 0,
           "cats": cat_sums(data, allr, ym), "bigs": [r for r in recs if r["kind"] == "big"]}
    rep["advice"] = advice(data, rep, allr, today)
    return rep


def advice(data, rep, allr, today):
    ym, out = rep["ym"], []
    first = min([r["date"] for r in allr] + [b["date"] for b in data["bills"]] or ["9999"])
    if first[:7] == ym:
        out.append("这是你记账的第一个月，数据不完整，下面的对比和结论仅供参考。")
    bud = data["budget"].get("monthly") or 0
    if bud:
        pct = rep["run"] / bud * 100
        msg = f"本月日常开销已用预算 {pct:.0f}%（{rep['run']:.0f} / {bud:.0f} 元，不含偶发大件和生活成本）"
        if rep["cur"] and rep["days"] >= 5:
            proj = rep["run"] / rep["days"] * ym_days(ym)
            if proj > bud:
                msg += f"；按目前速度月底约 {proj:.0f} 元，会超支约 {proj - bud:.0f} 元"
        out.append(msg)
    prev = ym_add(ym, -1)
    pc = cat_sums(data, allr, prev)
    for c, v in rep["cats"].items():
        p = pc.get(c, 0)
        if p > 0:
            a, b = v / rep["days"], p / ym_days(prev)
            if a > b * 1.25 and (a - b) * ym_days(ym) >= 30:
                out.append(f"{c}日均 {a:.1f} 元，比上月日均（{b:.1f} 元）多 {(a / b - 1) * 100:.0f}%")
    thr = data["settings"]["alert_pct"]
    mrecs = [r for r in allr if r["date"][:7] == ym and r["kind"] == "daily" and r["upp"] is not None]
    for item in sorted({r["item"] for r in mrecs}):
        s = item_setting(data, item)
        if s["strategy"] != "随便买":
            continue
        rs = item_records(allr, item, "upp")
        hist = [r["upp"] for r in rs if r["date"][:7] < ym]
        cur_v = [r["upp"] for r in rs if r["date"][:7] == ym]
        if len(hist) >= 3 and cur_v:
            h, c = sum(hist) / len(hist), sum(cur_v) / len(cur_v)
            if c > h * (1 + thr / 100):
                out.append(f"{item}本月均价 {c:.2f} {LABEL[rs[0]['dim']]}，比历史均价 {h:.2f} 高 {(c / h - 1) * 100:.0f}%，近期偏贵")
        brands = {}
        for r in rs:
            if r["brand"] and (today - D(r["date"])).days <= 90:
                brands.setdefault(r["brand"], []).append(r["upp"])
        if len(brands) >= 2:
            avg = {b: sum(v) / len(v) for b, v in brands.items()}
            best = min(avg, key=avg.get)
            for r in [x for x in rs if x["date"][:7] == ym and x["brand"] and x["brand"] != best]:
                if avg[r["brand"]] > avg[best] * 1.1:
                    out.append(f"{item}：{best}近 3 个月均价最低（{avg[best]:.2f}），本月你买了{r['brand']}（{avg[r['brand']]:.2f}）")
                    break
    for item, s in data["item_settings"].items():
        if s.get("strategy") == "认品牌":
            t = loyal_trend(data, allr, item, today)
            if t and t["pct"] >= thr:
                out.append(f"你认的「{item}」近 3 个月涨了 {t['pct']:.0f}%（{t['first']:.2f} → {t['last']:.2f} {LABEL[t['dim']]}），要不要重新考虑")
    if rep["bigs"]:
        tot12 = sum(r["amount"] for r in allr if r["kind"] == "big" and ym_add(ym, -11) <= r["date"][:7] <= ym)
        out.append(f"本月偶发大件 {rep['big']:.0f} 元，已排除在日均和预算之外；近 12 个月大件共 {tot12:.0f} 元")
    if rep["cur"]:
        out += bill_status(data, today)
    return out

"""价格统计、涨价预警、生活费用摊销、月报与建议。"""
import calendar
import datetime as dt

from calc import LABEL, unit_info, unit_price

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
            refund = min(float(i.get("refund") or 0), i["amount"])
            dim, up = unit_price(i["amount"], i.get("qty"), i.get("unit"))
            _, upp = unit_price(paid, i.get("qty"), i.get("unit"))
            if refund > 0 and refund >= i["amount"] - 1e-9:   # 全额退款：不算一次真实购买，不进价格统计
                dim, up, upp = None, None, None
            out.append({"date": o["date"], "store": o.get("store", ""), "order": o["id"], "id": i["id"],
                        "item": i["item"], "brand": i.get("brand", ""), "category": i["category"],
                        "qty": i.get("qty"), "unit": i.get("unit"), "amount": i["amount"], "refund": refund, "net": i["amount"] - refund, "paid": paid,
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


def iter_months(start, end):
    ym, last = ym_of(start), ym_of(end)
    while ym <= last:
        y, m = int(ym[:4]), int(ym[5:])
        yield ym, dt.date(y, m, 1), dt.date(y, m, ym_days(ym))
        ym = ym_add(ym, 1)


def overlap_days(a, b, c, d):
    """闭区间 [a,b] 与 [c,d] 重叠的天数。"""
    return max(0, (min(b, d) - max(a, c)).days + 1)


def living_range(data, start, end, mode, today):
    """生活成本：摊销类按天分摊，水电气按月均参考；现金口径按缴费日。适用于任意起止日期。"""
    acc = {}
    eom = dt.date(today.year, today.month, ym_days(ym_of(today)))   # 当月月底：和摊销一样，当月整月都按月均计入

    def add(name, v, note):
        acc[(name, note)] = acc.get((name, note), 0) + v

    if mode == "cash":
        for b in data["bills"]:
            if start <= D(b["date"]) <= end:
                add(b["name"], b["amount"], "实缴")
    else:
        one = dt.timedelta(days=1)
        for name, s, e, amt, est in spans(data):
            ov = overlap_days(s, e - one, start, end)
            if ov:
                add(name, amt * ov / (e - s).days, "预估" if est else "摊销")
        for name in sorted({b["name"] for b in data["bills"] if bill_kind(data, b["name"]) == "cash"}):
            bs = bills_of(data, name)
            actual = sum(b["amount"] for b in bs if start <= D(b["date"]) <= end)
            avg = cash_avg(bs)
            v = 0.0
            if avg is not None:
                first = D(bs[0]["date"]).replace(day=1)
                for ym, ms, me in iter_months(start, end):
                    v += avg * overlap_days(max(start, ms), min(end, me), first, eom) / ym_days(ym)
            if v > 0.005:
                add(name, v, f"月均参考（期内实缴 {actual:.0f}）")
            elif actual:
                add(name, actual, "实缴")
    rows = [(n, v, note) for (n, note), v in sorted(acc.items())]
    return sum(v for _, v, _ in rows), rows


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


# ---------- 用量追踪 ----------
def _avg(xs):
    return sum(xs) / len(xs) if xs else None


def tracker_rows(data, today):
    rows = []
    for t in data.get("trackers", []):
        s = D(t["start"])
        e = D(t["end"]) if t.get("end") else None
        days = max(1, (e - s).days) if e else (today - s).days
        info = unit_info(t.get("unit"))
        base = t["qty"] * info[1] if (t.get("qty") and info) else None
        rows.append({**t, "done": e is not None, "days": days, "dim": info[0] if info else None, "base": base,
                     "rate": base / days if (e and base) else None, "cost_day": t["amount"] / days if e else None})
    return rows


def tracker_expect(rows, t):
    """同一物品以往用完的记录，估计这一件大概能用多少天；没有以往记录返回 None。"""
    prev = [r for r in rows if r["done"] and r["item"] == t["item"] and r["id"] != t["id"]]
    if not prev:
        return None
    rates = [r["rate"] for r in prev if r["rate"] and r["dim"] == t["dim"]]
    if t["base"] and rates:
        return t["base"] / _avg(rates)
    return _avg([r["days"] for r in prev])


def tracker_notes(data, today, start=None, end=None):
    """温馨提示：新用完的和以往比快了还是慢了；使用中的快用完了或比平时久。"""
    rows, out = tracker_rows(data, today), []
    fin = [r for r in rows if r["done"]]
    for t in sorted(fin, key=lambda r: r["end"]):
        if start and not (str(start) <= t["end"] <= str(end)):
            continue
        prev = [r for r in fin if r["item"] == t["item"] and r["end"] < t["end"]]
        if not prev:
            continue
        rates = [r["rate"] for r in prev if r["rate"] and r["dim"] == t["dim"]]
        avgd = _avg([r["days"] for r in prev])
        if t["rate"] and rates:
            ratio, basis = t["rate"] / _avg(rates), "（按每天用量算）"
        else:
            ratio, basis = avgd / t["days"], ""
        if ratio >= 1.25:
            out.append(f"「{t['item']}」这次用了 {t['days']} 天，比以往（平均约 {avgd:.0f} 天）用得快约 {(ratio - 1) * 100:.0f}%{basis}，是不是用量变大了？")
        elif ratio <= 0.8:
            out.append(f"「{t['item']}」这次用了 {t['days']} 天，比以往（平均约 {avgd:.0f} 天）用得慢约 {(1 - ratio) * 100:.0f}%{basis}，用量变少了，留意保质期或是不是买多了。")
    if start is None or start <= today <= end:
        for t in [r for r in rows if not r["done"]]:
            exp = tracker_expect(rows, t)
            if not exp:
                continue
            if t["days"] >= exp * 1.2:
                out.append(f"「{t['item']}」已经用了 {t['days']} 天，比以往（约 {exp:.0f} 天）久，可能用得比平时慢；用完了记得点「已用完」。")
            elif t["days"] >= exp * 0.85:
                out.append(f"「{t['item']}」按以往的速度快用完了（约 {exp:.0f} 天），留意补货。")
    return out


# ---------- 时间段报告（周 / 月 / 季度 / 半年 / 年 / 自定义） ----------
def cat_sums_range(recs, start, end):
    S, E, c = str(start), str(end), {}
    for r in recs:
        if S <= r["date"] <= E and r["kind"] != "big":
            c[r["category"]] = c.get(r["category"], 0) + r["net"]
    return c


def period_report(data, start, end, mode, today, title=""):
    total_days = (end - start).days + 1
    cur = start <= today <= end
    days = max(1, (min(end, today) - start).days + 1) if start <= today else total_days
    allr = records(data)
    S, E = str(start), str(end)
    recs = [r for r in allr if S <= r["date"] <= E]
    kinds = {"daily": 0.0, "casual": 0.0, "big": 0.0}
    for r in recs:
        kinds[r["kind"]] += r["net"]
    extras = sum(e["amount"] for o in data["orders"] if S <= o["date"] <= E for e in o.get("extras", []))
    liv, liv_rows = living_range(data, start, end, mode, today)
    income = sum(x["amount"] for x in data["income"] if S <= x["date"] <= E)
    run = kinds["daily"] + kinds["casual"] + extras
    spend = run + kinds["big"] + liv
    bud = data["budget"].get("monthly") or 0
    bud_total = sum(bud * overlap_days(max(start, ms), min(end, me), ms, me) / ym_days(ym)
                    for ym, ms, me in iter_months(start, end)) if bud else 0
    tr = {}
    for r in recs:
        if r["category"] == "交通" and r["kind"] != "big":
            t = tr.setdefault(r["item"], [0, 0.0])
            t[0] += 1
            t[1] += r["net"]
    rep = {"title": title or f"{start} ~ {end}", "start": start, "end": end, "ym": S[:7], "cur": cur, "days": days,
           "total_days": total_days, "daily": kinds["daily"], "casual": kinds["casual"], "big": kinds["big"],
           "extras": extras, "living": liv, "living_rows": liv_rows, "income": income, "run": run, "spend": spend,
           "balance": income - spend, "day_avg": run / days if days else 0, "budget_total": bud_total,
           "cats": cat_sums_range(allr, start, end),
           "bigs": [r for r in recs if r["kind"] == "big" and r["net"] > 0],
           "transport": sorted([{"item": k, "n": v[0], "amount": v[1]} for k, v in tr.items()], key=lambda x: -x["amount"])}
    rep["advice"] = advice(data, rep, allr, today)
    return rep


def month_report(data, ym, mode, today):
    y, m = int(ym[:4]), int(ym[5:])
    return period_report(data, dt.date(y, m, 1), dt.date(y, m, ym_days(ym)), mode, today, title=f"{y}年{m}月")


def trend(data, rep, mode, today):
    """走势：时间段不超过 31 天按天，否则按月；每格拆成日常 / 随手 / 附加 / 大件（按月时再加生活成本）。"""
    start, end = rep["start"], rep["end"]
    daily = rep["total_days"] <= 31
    S, E = str(start), str(end)
    key = (lambda s: s[5:]) if daily else (lambda s: s[:7])
    order = []
    if daily:
        d = start
        while d <= end:
            order.append((str(d)[5:], d, d))
            d += dt.timedelta(days=1)
    else:
        order = [(ym, max(start, ms), min(end, me)) for ym, ms, me in iter_months(start, end)]
    agg = {k: {"日常消耗": 0.0, "随手消费": 0.0, "附加费用": 0.0, "偶发大件": 0.0} for k, _, _ in order}
    name = {"daily": "日常消耗", "casual": "随手消费", "big": "偶发大件"}
    for r in records(data):
        if S <= r["date"] <= E:
            agg[key(r["date"])][name[r["kind"]]] += r["net"]
    for o in data["orders"]:
        if S <= o["date"] <= E:
            agg[key(o["date"])]["附加费用"] += sum(e["amount"] for e in o.get("extras", []))
    rows = []
    for k, a, b in order:
        row = {"期间": k, **agg[k]}
        if not daily:
            row["生活成本"] = living_range(data, a, b, mode, today)[0]
        rows.append(row)
    return rows


def advice(data, rep, allr, today):
    start, end, out = rep["start"], rep["end"], []
    S, E = str(start), str(end)
    ref = min(end, today)
    dates = [r["date"] for r in allr] + [b["date"] for b in data["bills"]]
    if dates and D(min(dates)) > start:
        out.append(f"你的记账从 {min(dates)} 开始，这段时间的数据不完整，下面的对比和结论仅供参考。")
    bt = rep["budget_total"]
    if bt:
        msg = f"这段时间日常开销已用预算 {rep['run'] / bt * 100:.0f}%（{rep['run']:.0f} / {bt:.0f} 元，不含偶发大件和生活成本）"
        if rep["cur"] and end > today and rep["days"] >= 5:
            proj = rep["run"] / rep["days"] * rep["total_days"]
            if proj > bt:
                msg += f"；按目前速度到期末约 {proj:.0f} 元，会超支约 {proj - bt:.0f} 元"
        out.append(msg)
    n = rep["total_days"]
    pe = start - dt.timedelta(days=1)
    pc = cat_sums_range(allr, pe - dt.timedelta(days=n - 1), pe)
    for c, v in rep["cats"].items():
        p = pc.get(c, 0)
        if p > 0:
            a, b = v / rep["days"], p / n
            if a > b * 1.25 and (a - b) * n >= 30:
                out.append(f"{c}日均 {a:.1f} 元，比上一个同样长度的时间段（{b:.1f} 元）多 {(a / b - 1) * 100:.0f}%")
    thr = data["settings"]["alert_pct"]
    mrecs = [r for r in allr if S <= r["date"] <= E and r["kind"] == "daily" and r["upp"] is not None]
    for item in sorted({r["item"] for r in mrecs}):
        if item_setting(data, item)["strategy"] != "随便买":
            continue
        rs = item_records(allr, item, "upp")
        hist = [r["upp"] for r in rs if r["date"] < S]
        cur_v = [r["upp"] for r in rs if S <= r["date"] <= E]
        if len(hist) >= 3 and cur_v:
            h, c = sum(hist) / len(hist), sum(cur_v) / len(cur_v)
            if c > h * (1 + thr / 100):
                out.append(f"{item}这段时间均价 {c:.2f} {LABEL[rs[0]['dim']]}，比历史均价 {h:.2f} 高 {(c / h - 1) * 100:.0f}%，近期偏贵")
        brands = {}
        for r in rs:
            if r["brand"] and 0 <= (ref - D(r["date"])).days <= 90:
                brands.setdefault(r["brand"], []).append(r["upp"])
        if len(brands) >= 2:
            avg = {b: sum(v) / len(v) for b, v in brands.items()}
            best = min(avg, key=avg.get)
            for r in [x for x in rs if S <= x["date"] <= E and x["brand"] and x["brand"] != best]:
                if avg[r["brand"]] > avg[best] * 1.1:
                    out.append(f"{item}：{best}近 3 个月均价最低（{avg[best]:.2f}），这段时间你买了{r['brand']}（{avg[r['brand']]:.2f}）")
                    break
    for item, s in data["item_settings"].items():
        if s.get("strategy") == "认品牌":
            t = loyal_trend(data, allr, item, ref)
            if t and t["pct"] >= thr:
                out.append(f"你认的「{item}」近 3 个月涨了 {t['pct']:.0f}%（{t['first']:.2f} → {t['last']:.2f} {LABEL[t['dim']]}），要不要重新考虑")
    if rep["bigs"]:
        tot12 = sum(r["net"] for r in allr if r["kind"] == "big" and ref - dt.timedelta(days=365) < D(r["date"]) <= ref)
        out.append(f"这段时间偶发大件 {rep['big']:.0f} 元，已排除在日均和预算之外；近 12 个月大件共 {tot12:.0f} 元")
    out += tracker_notes(data, today, start, end)
    if rep["cur"]:
        out += bill_status(data, today)
    return out

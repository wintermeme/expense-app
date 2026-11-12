"""小票排版：32 字符宽，中文按 2 个宽度计算。"""
import datetime as dt
import unicodedata

W = 32
SEP = "-" * W
DSEP = "=" * W
WEEK = "一二三四五六日"


def dw(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def cut(s, w):
    out, n = "", 0
    for c in s:
        cw = dw(c)
        if n + cw > w:
            break
        out += c
        n += cw
    return out


def center(s):
    return " " * max(0, (W - dw(s)) // 2) + s


def line(left, right):
    right = str(right)
    left = cut(left, W - dw(right) - 1)
    return left + " " * (W - dw(left) - dw(right)) + right


def money(x):
    return f"{x:.2f}"


def wrap_pairs(pairs):
    lines, cur = [], ""
    for p in pairs:
        t = p if not cur else cur + " | " + p
        if dw(t) > W and cur:
            lines.append(cur)
            cur = p
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


def render_day(data, day):
    from calc import LABEL, unit_price
    d = dt.date.fromisoformat(day)
    out = [DSEP, center("每 日 消 费 小 票"), DSEP,
           f"日期：{day}   周{WEEK[d.weekday()]}", SEP]
    total, n, cats = 0.0, 0, {}
    for o in [o for o in data["orders"] if o["date"] == day]:
        if o.get("store"):
            out.append(f"[{o['store']}]")
        for it in o["items"]:
            n += 1
            name = it["item"] + (f"·{it['brand']}" if it.get("brand") else "")
            out.append(line(f"{n:02d} {name}", money(it["amount"])))
            dim, up = unit_price(it["amount"], it.get("qty"), it.get("unit"))
            if up is not None:
                out.append(cut(f"   {it['qty']:g}{it['unit']} x {up:.2f}{LABEL[dim]}", W))
            total += it["amount"]
            cats[it["category"]] = cats.get(it["category"], 0) + it["amount"]
        for e in o.get("extras", []):
            out.append(line("   " + e["name"], money(e["amount"])))
            total += e["amount"]
            cats["附加费用"] = cats.get("附加费用", 0) + e["amount"]
    if n == 0:
        out.append(center("（今天还没有记录）"))
    out += [SEP, f"共 {n} 笔", line("合计", "¥" + money(total))]
    if cats:
        out.append(SEP)
        out += wrap_pairs([f"{k} {money(v)}" for k, v in cats.items()])
    bills = [b for b in data["bills"] if b["date"] == day]
    if bills:
        out += [SEP, "生活缴费（不计入合计）"]
        out += [line("  " + b["name"], money(b["amount"])) for b in bills]
    out += [DSEP, center("谢谢惠顾 · 明天继续记账"), DSEP]
    return "\n".join(out)


def render_month(rep):
    out = [DSEP, center(f"{rep['ym']} 月 度 小 票"), DSEP]
    out.append(line("收入", money(rep["income"])))
    out.append(SEP)
    out.append(line("日常消耗", money(rep["daily"])))
    out.append(line("随手消费", money(rep["casual"])))
    out.append(line("附加费用", money(rep["extras"])))
    out.append(line("偶发大件", money(rep["big"])))
    out.append(line("生活成本", money(rep["living"])))
    out += [SEP, line("总支出", money(rep["spend"])), line("结余", money(rep["balance"])), SEP,
            line("日均消费(不含大件)", money(rep["day_avg"]))]
    if rep["cats"]:
        out.append(SEP)
        out += wrap_pairs([f"{k} {money(v)}" for k, v in sorted(rep["cats"].items(), key=lambda x: -x[1])])
    out += [DSEP]
    return "\n".join(out)

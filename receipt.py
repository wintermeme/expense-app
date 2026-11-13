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


def pad(s, w):
    return s + " " * max(0, w - dw(s))


def rpad(s, w):
    return " " * max(0, w - dw(s)) + s


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


def day_groups(data, day):
    """同一天同一店铺的多张订单合并成一组；没填店铺的放最前面，不加店名。"""
    order, g = [], {}
    for o in data["orders"]:
        if o["date"] != day:
            continue
        k = o.get("store") or ""
        if k not in g:
            g[k] = {"items": [], "extras": {}}
            order.append(k)
        g[k]["items"] += o["items"]
        for e in o.get("extras", []):
            g[k]["extras"][e["name"]] = g[k]["extras"].get(e["name"], 0) + e["amount"]
    order.sort(key=lambda k: k != "")
    return [(k, g[k]["items"], {n: v for n, v in g[k]["extras"].items() if v}) for k in order]


def item_row(it):
    """返回 (名称, 数量文字, 单价文字, 金额)。"""
    from calc import LABEL, unit_price
    name = it["item"] + (f"·{it['brand']}" if it.get("brand") else "")
    dim, up = unit_price(it["amount"], it.get("qty"), it.get("unit"))
    qty = f"{it['qty']:g}{it['unit']}" if up is not None else ""
    price = f"{up:.2f}{LABEL[dim][1:]}" if up is not None else ""
    return name, qty, price, it["amount"]


def day_summary(data, day):
    groups = day_groups(data, day)
    n = sum(len(its) for _, its, _ in groups)
    total, cats = 0.0, {}
    for _, its, ex in groups:
        for it in its:
            net = it["amount"] - (it.get("refund") or 0)
            total += net
            cats[it["category"]] = cats.get(it["category"], 0) + net
        for v in ex.values():
            total += v
            cats["附加费用"] = cats.get("附加费用", 0) + v
    cats = {k: v for k, v in cats.items() if abs(v) > 0.004}
    return groups, n, total, cats


def wrap_name(s, w):
    out, cur = [], ""
    for c in s:
        if dw(cur + c) > w:
            out.append(cur)
            cur = c
        else:
            cur += c
    return out + [cur]


def render_day(data, day):
    """文字版（用于复制、下载）：每件两行，第一行名称和金额，第二行数量 × 单价。"""
    d = dt.date.fromisoformat(day)
    groups, n, total, cats = day_summary(data, day)
    out = [DSEP, center("每 日 消 费 小 票"), DSEP, f"日期：{day}   周{WEEK[d.weekday()]}", SEP,
           line("物品 / 数量 × 单价", "金额"), SEP]
    if n == 0:
        out.append(center("（今天还没有记录）"))
    for store, its, ex in groups:
        if store:
            out.append(f"[{store}]")
        for it in its:
            name, qty, price, amt = item_row(it)
            parts = wrap_name(name, W - 10)
            out.append(line(parts[0], money(amt)))
            out += ["  " + x for x in parts[1:]]
            if qty:
                out.append(cut(f"  {qty} × {price}", W))
            if it.get("refund"):
                out.append(line("  退款", "-" + money(it["refund"])))
        for k, v in ex.items():
            out.append(line("  " + k, money(v)))
        if store and (len(its) + len(ex) > 1):
            out.append(line("  小计", money(sum(i["amount"] - (i.get("refund") or 0) for i in its) + sum(ex.values()))))
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


def render_day_html(data, day):
    """页面上显示的小票：真正的表格，列对齐由页面保证，不受手机字体影响。"""
    from html import escape as e
    d = dt.date.fromisoformat(day)
    groups, n, total, cats = day_summary(data, day)
    h = ['<div class="rc"><div class="rc-title">每 日 消 费 小 票</div>',
         f'<div class="rc-sub">{day}　周{WEEK[d.weekday()]}</div>',
         '<table><thead><tr><th>物品</th><th>数量</th><th>单价</th><th>金额</th></tr></thead><tbody>']
    if n == 0:
        h.append('<tr><td colspan="4" class="rc-empty">今天还没有记录</td></tr>')
    for store, its, ex in groups:
        if store:
            h.append(f'<tr class="rc-store"><td colspan="4">{e(store)}</td></tr>')
        for it in its:
            name, qty, price, amt = item_row(it)
            h.append(f'<tr><td>{e(name)}</td><td>{e(qty)}</td><td>{e(price)}</td><td>{money(amt)}</td></tr>')
            if it.get("refund"):
                h.append(f'<tr class="rc-refund"><td colspan="3">　退款</td><td>-{money(it["refund"])}</td></tr>')
        for k, v in ex.items():
            h.append(f'<tr class="rc-ex"><td colspan="3">{e(k)}</td><td>{money(v)}</td></tr>')
        if store and (len(its) + len(ex) > 1):
            sub = sum(i["amount"] - (i.get("refund") or 0) for i in its) + sum(ex.values())
            h.append(f'<tr class="rc-sub2"><td colspan="3">小计</td><td>{money(sub)}</td></tr>')
    h.append('</tbody></table>')
    h.append(f'<div class="rc-total"><span>共 {n} 笔</span><span>合计　¥{money(total)}</span></div>')
    if cats:
        h.append('<div class="rc-cats">' + "　|　".join(f"{e(k)} {money(v)}" for k, v in cats.items()) + '</div>')
    bills = [b for b in data["bills"] if b["date"] == day]
    if bills:
        h.append('<div class="rc-cats">生活缴费（不计入合计）：' + "　".join(f"{e(b['name'])} {money(b['amount'])}" for b in bills) + '</div>')
    h.append('</div>')
    return "".join(h)


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

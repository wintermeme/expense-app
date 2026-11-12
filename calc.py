"""单位换算、运费摊分、比价。"""

UNITS = {}
for _u, _f in {"g": 0.002, "克": 0.002, "kg": 2, "公斤": 2, "千克": 2, "斤": 1, "两": 0.1}.items():
    UNITS[_u] = ("w", _f)
for _u, _f in {"ml": 0.001, "毫升": 0.001, "l": 1, "升": 1}.items():
    UNITS[_u] = ("v", _f)
for _u in ["个", "瓶", "包", "盒", "袋", "支", "片", "卷", "只", "条", "颗", "罐", "件"]:
    UNITS[_u] = ("c", 1)

UNIT_LIST = ["g", "kg", "斤", "两", "ml", "L", "个", "瓶", "包", "盒", "袋", "支", "片", "卷"]
LABEL = {"w": "元/斤", "v": "元/升", "c": "元/个"}


def unit_info(unit):
    if not unit:
        return None
    u = str(unit).strip()
    return UNITS.get(u) or UNITS.get(u.lower())


def unit_price(amount, qty, unit):
    """返回 (类型, 单价)；算不出时返回 (None, None)。"""
    info = unit_info(unit)
    try:
        qty = float(qty)
    except (TypeError, ValueError):
        return None, None
    if not info or qty <= 0 or amount is None:
        return None, None
    dim, factor = info
    return dim, float(amount) / (qty * factor)


def compare(options):
    """options: [{brand, price, qty, unit}]。返回 (行列表, 错误信息)。"""
    rows = []
    for o in options:
        dim, up = unit_price(o.get("price"), o.get("qty"), o.get("unit"))
        if up is None:
            continue
        rows.append({"brand": o.get("brand") or "（未填品牌）", "price": o["price"],
                     "qty": o["qty"], "unit": o["unit"], "dim": dim, "up": up})
    if len(rows) < 2:
        return [], "至少填写两个选项（价格、数量、单位都要填）"
    if len({r["dim"] for r in rows}) > 1:
        return [], "这些选项的单位类型不同（比如克和毫升），没法直接比较"
    rows.sort(key=lambda r: r["up"])
    worst = rows[-1]["up"]
    for r in rows:
        r["label"] = LABEL[r["dim"]]
        r["save_pct"] = (worst - r["up"]) / worst * 100 if worst else 0
    return rows, None

import datetime as dt
import hmac
import json
import uuid
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import analysis as an
import calc
import receipt
import storage

st.set_page_config(page_title="记账小票", page_icon="🧾", layout="centered")

FONTS = {
    "B": ("Nunito + 系统黑体（默认）", '"Nunito","PingFang SC","Microsoft YaHei","Noto Sans SC",sans-serif',
          "https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700&display=swap"),
    "A": ("系统圆体", 'ui-rounded,"SF Pro Rounded","Yuanti SC","YouYuan","PingFang SC","Microsoft YaHei",sans-serif', None),
    "C": ("霞鹜文楷", '"LXGW WenKai","Nunito",serif', "https://cdn.jsdelivr.net/npm/lxgw-wenkai-webfont@1.7.0/style.css"),
    "D": ("站酷快乐体", '"ZCOOL KuaiLe","Nunito",sans-serif',
          "https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700&family=ZCOOL+KuaiLe&display=swap"),
}
KIND_LABEL = {"daily": "日常消耗", "casual": "随手消费", "big": "偶发大件"}
KIND_KEY = {v: k for k, v in KIND_LABEL.items()}
BILL_LABEL = {"amortize": "摊销（房租物业类）", "cash": "按缴费计入（水电气类）"}
BILL_KEY = {v: k for k, v in BILL_LABEL.items()}


def inject_css(font_key):
    _, family, url = FONTS.get(font_key, FONTS["B"])
    imp = f"@import url('{url}');" if url else ""
    st.markdown(f"""<style>
{imp}
html, body, .stApp, .stApp p, .stApp label, .stApp li, .stApp h1, .stApp h2, .stApp h3, .stApp h4,
.stApp button, .stApp input, .stApp textarea, .stApp [data-baseweb="select"] *, .stApp table,
.stApp [data-testid="stMetricValue"], .stApp [data-testid="stCaptionContainer"] {{ font-family: {family} !important; }}
.stApp code, .stApp pre, .stApp pre * {{ font-family: "SFMono-Regular", Menlo, Consolas, "Sarasa Mono SC", "Noto Sans Mono CJK SC", monospace !important; }}
.stApp .stButton > button, .stApp .stDownloadButton > button {{ border-radius: 999px; }}
.stApp [data-baseweb="tab-list"] {{ gap: 4px; overflow-x: auto; }}
.block-container {{ padding-top: 4.5rem; max-width: 760px; }}
@media (max-width: 640px) {{
  .stApp [data-baseweb="tab-list"] {{ position: fixed; bottom: 0; left: 0; right: 0; z-index: 999;
    padding: 6px 8px calc(6px + env(safe-area-inset-bottom)); border-top: 0.5px solid rgba(128,128,160,.35); background: #EFF0F7; }}
  .block-container {{ padding-bottom: 6rem; }}
}}
@media (max-width: 640px) and (prefers-color-scheme: dark) {{ .stApp [data-baseweb="tab-list"] {{ background: #171923; }} }}
</style>""", unsafe_allow_html=True)


def uid():
    return dt.datetime.now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:6]


def num(x):
    try:
        if x is None or pd.isna(x):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def write(mutator, msg="update"):
    try:
        storage.update(mutator, msg)
        return True
    except Exception as e:
        st.error(f"保存失败：{e}")
        return False


def gate():
    conf = storage.github_conf()
    try:
        pw = st.secrets.get("APP_PASSWORD")
    except Exception:
        pw = None
    if conf and not pw:
        st.error("已连接 GitHub 数据仓库，但 Secrets 里没有设置 APP_PASSWORD。为了保护账本，应用已停止，请先设置密码。")
        st.stop()
    if not pw or st.session_state.get("ok"):
        return
    st.title("🧾 记账小票")
    x = st.text_input("访问密码", type="password")
    if x:
        if hmac.compare_digest(x, str(pw)):
            st.session_state["ok"] = True
            st.rerun()
        else:
            st.error("密码不对")
    st.stop()


def mk_item(item, brand, cat, qty, unit, amount, big):
    qty = num(qty)
    it = {"id": uid(), "item": (item or "").strip() or cat, "brand": (brand or "").strip(),
          "category": cat, "amount": round(float(amount), 2), "big": bool(big)}
    if qty and qty > 0 and calc.unit_info(unit):
        it["qty"], it["unit"] = qty, unit
    return it


gate()
if "data" not in st.session_state:
    try:
        st.session_state["data"], st.session_state["sha"] = storage.load()
    except Exception as e:
        st.error(f"读取数据失败：{e}")
        st.stop()
data = st.session_state["data"]
S = data["settings"]
inject_css(S.get("font", "B"))
try:
    today = dt.datetime.now(ZoneInfo(S.get("tz", "Asia/Shanghai"))).date()
except Exception:
    today = dt.date.today()
if st.session_state.get("flash"):
    st.toast(st.session_state.pop("flash"))
st.session_state.setdefault("n", 0)
n = st.session_state["n"]
cats = list(data["categories"])
recs = an.records(data)

t_add, t_rc, t_cmp, t_price, t_rep, t_life, t_set = st.tabs(["记账", "小票", "比价", "价格", "月报", "生活", "设置"])

# ---------------- 记账 ----------------
with t_add:
    mode = st.radio("方式", ["快速记一笔", "记订单（多件 / 有运费）"], horizontal=True, label_visibility="collapsed")
    c1, c2 = st.columns(2)
    day = c1.date_input("日期", value=today, key="add_date")
    store = c2.text_input("店铺（可不填）", key="add_store")
    items = []
    if mode == "快速记一笔":
        amount = st.number_input("金额（元）", min_value=0.0, value=None, step=0.5, format="%.2f",
                                 placeholder="0.00", key=f"amt{n}")
        cat = st.pills("分类", cats, selection_mode="single", default=cats[0], key=f"cat{n}") or cats[0]
        names = sorted({i["item"] for o in data["orders"] for i in o["items"]})
        item = st.selectbox("物品", names, index=None, accept_new_options=True,
                            placeholder="选择，或直接输入新物品", key=f"item{n}")
        brand = st.text_input("品牌（可不填）", key=f"brand{n}")
        q1, q2 = st.columns(2)
        qty = q1.number_input("数量（买菜、日用品建议填）", min_value=0.0, value=None, step=1.0, key=f"qty{n}")
        unit = q2.selectbox("单位", calc.UNIT_LIST, key=f"unit{n}")
        big = st.checkbox("这笔是偶发大件，不计入日均", key=f"big{n}")
        if amount:
            items.append(mk_item(item, brand, cat, qty, unit, amount, big))
    else:
        st.caption("每行一件物品；分类、单位可点选。运费、优惠在下方填写，会按金额比例摊到每件上。")
        base = pd.DataFrame({"物品": [""] * 3, "品牌": [""] * 3, "分类": [cats[0]] * 3,
                             "数量": pd.Series([None] * 3, dtype="float"), "单位": ["g"] * 3,
                             "金额": pd.Series([None] * 3, dtype="float"), "大件": [False] * 3})
        ed = st.data_editor(base, num_rows="dynamic", width="stretch", key=f"oe{n}", column_config={
            "分类": st.column_config.SelectboxColumn(options=cats, required=True),
            "单位": st.column_config.SelectboxColumn(options=calc.UNIT_LIST),
            "数量": st.column_config.NumberColumn(min_value=0.0),
            "金额": st.column_config.NumberColumn(min_value=0.0, format="%.2f"),
            "大件": st.column_config.CheckboxColumn()})
        for r in ed.to_dict("records"):
            if num(r["金额"]):
                items.append(mk_item(r["物品"], r["品牌"], r["分类"] or cats[0], r["数量"], r["单位"], r["金额"], r["大件"]))
    with st.expander("附加费用（运费、杂费、优惠）"):
        f1, f2, f3 = st.columns(3)
        ship = f1.number_input("运费", min_value=0.0, value=0.0, step=1.0, key=f"ship{n}")
        other = f2.number_input("打包等杂费", min_value=0.0, value=0.0, step=1.0, key=f"oth{n}")
        disc = f3.number_input("优惠减免", min_value=0.0, value=0.0, step=1.0, key=f"disc{n}")
    if st.button("记一笔", type="primary", width="stretch"):
        if not items:
            st.warning("请先填写金额")
        else:
            extras = [{"name": k, "amount": v} for k, v in (("运费", ship), ("杂费", other), ("优惠", -disc)) if v]
            order = {"id": uid(), "date": str(day), "store": store.strip(), "extras": extras, "items": items}
            if write(lambda d: d["orders"].append(order), "add order"):
                st.session_state["n"] += 1
                st.session_state["flash"] = "已记录 ✓"
                st.rerun()
    today_total = sum(r["amount"] for r in recs if r["date"] == str(today))
    st.caption(f"今天已记 ¥{today_total:.2f}")

# ---------------- 小票 ----------------
with t_rc:
    rday = st.date_input("日期", value=today, key="rday")
    txt = receipt.render_day(data, str(rday))
    st.code(txt, language=None)
    st.download_button("下载 .txt", txt, file_name=f"小票-{rday}.txt", width="stretch")
    drs = [r for r in recs if r["date"] == str(rday)]
    with st.expander("修改 / 删除当天记录"):
        if not drs:
            st.caption("这一天没有记录。")
        else:
            df = pd.DataFrame([{"id": r["id"], "物品": r["item"], "品牌": r["brand"], "分类": r["category"],
                                "数量": r["qty"], "单位": r["unit"], "金额": r["amount"],
                                "大件": r["kind"] == "big", "删除": False} for r in drs])
            df["数量"] = df["数量"].astype("float")
            ed = st.data_editor(df, key=f"mg{rday}", width="stretch", hide_index=True, column_config={
                "id": None,
                "分类": st.column_config.SelectboxColumn(options=cats),
                "单位": st.column_config.SelectboxColumn(options=calc.UNIT_LIST),
                "金额": st.column_config.NumberColumn(min_value=0.0, format="%.2f")})
            st.caption("「大件」只在你手动标记时保存；按金额自动转大件的不用管。")
            if st.button("保存修改", key="mgsave"):
                chg = {r["id"]: r for r in ed.to_dict("records")}

                def mut(d):
                    for o in d["orders"]:
                        keep = []
                        for it in o["items"]:
                            r = chg.get(it["id"])
                            if r is None:
                                keep.append(it)
                                continue
                            if r["删除"]:
                                continue
                            nm = mk_item(r["物品"], r["品牌"], r["分类"], r["数量"], r["单位"], r["金额"], False)
                            it.update(item=nm["item"], brand=nm["brand"], category=nm["category"], amount=nm["amount"])
                            it.pop("qty", None)
                            it.pop("unit", None)
                            if "qty" in nm:
                                it["qty"], it["unit"] = nm["qty"], nm["unit"]
                            keep.append(it)
                        o["items"] = keep
                    d["orders"] = [o for o in d["orders"] if o["items"]]

                if write(mut, "edit items"):
                    st.session_state["flash"] = "已保存"
                    st.rerun()

# ---------------- 比价 ----------------
with t_cmp:
    st.caption("输入同一种东西的几个选项，自动换算成同一单位，选出最划算的。")
    base = pd.DataFrame({"品牌": ["", ""], "价格": pd.Series([None, None], dtype="float"),
                         "数量": pd.Series([None, None], dtype="float"), "单位": ["g", "g"]})
    ed = st.data_editor(base, num_rows="dynamic", width="stretch", key="cmp", column_config={
        "价格": st.column_config.NumberColumn(min_value=0.0, format="%.2f"),
        "数量": st.column_config.NumberColumn(min_value=0.0),
        "单位": st.column_config.SelectboxColumn(options=calc.UNIT_LIST)})
    opts = [{"brand": r["品牌"], "price": num(r["价格"]), "qty": num(r["数量"]), "unit": r["单位"]}
            for r in ed.to_dict("records")]
    rows, err = calc.compare(opts)
    if err:
        st.info(err)
    else:
        b = rows[0]
        st.success(f"最划算：{b['brand']}，{b['up']:.2f} {b['label']}，比最贵的省 {b['save_pct']:.0f}%")
        st.dataframe(pd.DataFrame([{"品牌": r["brand"], "价格": r["price"], "数量": f"{r['qty']:g}{r['unit']}",
                                    "单价": f"{r['up']:.2f} {r['label']}", "比最贵省": f"{r['save_pct']:.0f}%"}
                                   for r in rows]), hide_index=True, width="stretch")

# ---------------- 价格 ----------------
with t_price:
    names = sorted({r["item"] for r in recs if r["up"] is not None})
    if not names:
        st.info("记账时填了数量和单位，这里才会出现价格记录。")
    else:
        item = st.selectbox("物品", names, key="pq_item")
        basis = st.radio("单价口径", ["实付（含运费分摊）", "商品价"], horizontal=True)
        key = "upp" if basis.startswith("实付") else "up"
        rs = an.item_records(recs, item, key)
        lab = calc.LABEL[rs[0]["dim"]]
        sts = an.price_stats(rs, key)
        m1, m2 = st.columns(2)
        m1.metric("最低价", f"{sts['lo'][key]:.2f}", help=lab)
        m1.caption(f"{sts['lo']['date']} {sts['lo']['brand']} {sts['lo']['store']}")
        m2.metric("最高价", f"{sts['hi'][key]:.2f}", help=lab)
        m2.caption(f"{sts['hi']['date']} {sts['hi']['brand']} {sts['hi']['store']}")
        m3, m4 = st.columns(2)
        m3.metric("平均价", f"{sts['avg']:.2f}", help=lab)
        m4.metric("最近一次", f"{sts['last'][key]:.2f}", help=lab)
        m4.caption(f"{sts['last']['date']} {sts['last']['brand']}")
        st.caption(f"单位：{lab}，共 {sts['n']} 次记录" + ("；记录不足 3 次，波动判断仅供参考" if sts["n"] < 3 else ""))
        cdf = pd.DataFrame({"日期": pd.to_datetime([r["date"] for r in rs]), "单价": [r[key] for r in rs]})
        st.line_chart(cdf.sort_values("日期").set_index("日期"))
        tbl = pd.DataFrame([{"日期": r["date"], "品牌": r["brand"], "店铺": r["store"],
                             "数量": f"{r['qty']:g}{r['unit']}", "金额": r["amount"], "单价": round(r[key], 2),
                             "标记": "▼最低" if r["id"] == sts["lo"]["id"] else ("▲最高" if r["id"] == sts["hi"]["id"] else "")}
                            for r in sorted(rs, key=lambda r: r["date"], reverse=True)])
        st.dataframe(tbl, hide_index=True, width="stretch")
        cur = an.item_setting(data, item)
        STR = ["随便买", "认品牌", "认品类"]
        with st.expander(f"购买策略：{cur['strategy']}"):
            st.caption("随便买：谁便宜买谁，参与跨品牌建议。认品牌 / 认品类：不管价格就要这个，不参与跨品牌建议；认品牌会提示涨价。")
            sv = st.selectbox("策略", STR, index=STR.index(cur["strategy"]), key=f"str_{item}")
            bv = st.text_input("认的品牌或品类（可不填）", value=cur["brand"], key=f"sb_{item}")
            if st.button("保存策略", key=f"ss_{item}"):
                if write(lambda d: d["item_settings"].__setitem__(item, {"strategy": sv, "brand": bv.strip()}), "set strategy"):
                    st.rerun()
        if cur["strategy"] == "认品牌":
            tr = an.loyal_trend(data, recs, item, today)
            if tr:
                msg = f"近 3 个月 {tr['first']:.2f} → {tr['last']:.2f} {calc.LABEL[tr['dim']]}，变化 {tr['pct']:+.0f}%"
                (st.warning if tr["pct"] >= S["alert_pct"] else st.info)(msg)
            else:
                st.caption("近 3 个月这个品牌记录不足 2 次，暂时看不出涨跌。")
        else:
            bt = an.brand_table(rs, key)
            if len(bt) >= 2:
                st.write("各品牌对比（按平均单价从低到高）")
                st.dataframe(pd.DataFrame(bt).round(2), hide_index=True, width="stretch")

# ---------------- 月报 ----------------
with t_rep:
    months = sorted({r["date"][:7] for r in recs} | {b["date"][:7] for b in data["bills"]}
                    | {x["date"][:7] for x in data["income"]} | {an.ym_of(today)}, reverse=True)
    ym = st.selectbox("月份", months)
    mode_lab = st.radio("口径", ["摊销（默认）", "现金"], horizontal=True,
                        help="摊销：房租按天分摊、水电气用月均；现金：缴费当月算当月支出")
    rep = an.month_report(data, ym, "cash" if mode_lab == "现金" else "amort", today)
    a, b = st.columns(2)
    a.metric("收入", f"{rep['income']:.2f}")
    b.metric("总支出", f"{rep['spend']:.2f}")
    a.metric("结余", f"{rep['balance']:.2f}")
    b.metric("日均消费", f"{rep['day_avg']:.2f}", help="日常消耗 + 随手消费 + 附加费用，不含偶发大件和生活成本")
    st.dataframe(pd.DataFrame([
        {"项目": "日常消耗", "金额": rep["daily"]}, {"项目": "随手消费", "金额": rep["casual"]},
        {"项目": "附加费用（运费等）", "金额": rep["extras"]}, {"项目": "偶发大件", "金额": rep["big"]},
        {"项目": "生活成本", "金额": rep["living"]}]).round(2), hide_index=True, width="stretch")
    if rep["cats"]:
        st.write("日常和随手消费分类")
        cdf = pd.DataFrame([{"分类": k, "金额": v, "占比": f"{v / rep['run'] * 100:.0f}%" if rep["run"] else ""}
                            for k, v in sorted(rep["cats"].items(), key=lambda x: -x[1])])
        st.dataframe(cdf.round(2), hide_index=True, width="stretch")
    if rep["bigs"]:
        st.write("偶发大件明细")
        st.dataframe(pd.DataFrame([{"日期": r["date"], "物品": r["item"], "金额": r["amount"]} for r in rep["bigs"]]),
                     hide_index=True, width="stretch")
    if rep["living_rows"]:
        st.write("生活成本明细")
        st.dataframe(pd.DataFrame([{"名称": n_, "金额": round(v, 2), "说明": nt} for n_, v, nt in rep["living_rows"]]),
                     hide_index=True, width="stretch")
    st.write("建议")
    if rep["advice"]:
        for t in rep["advice"]:
            st.markdown(f"- {t}")
    else:
        st.caption("暂时没有需要提醒的，数据多了会更准。")
    mtxt = receipt.render_month(rep)
    with st.expander("月度小票（可复制）"):
        st.code(mtxt, language=None)
        st.download_button("下载 .txt", mtxt, file_name=f"月度小票-{ym}.txt", key="mdl")

# ---------------- 生活 ----------------
with t_life:
    st.write("缴费记录")
    bn = sorted({b["name"] for b in data["bills"]} | {"房租", "物业", "电费", "水费", "燃气", "网费", "话费"})
    l1, l2, l3 = st.columns(3)
    bname = l1.selectbox("名称", bn, index=None, accept_new_options=True, placeholder="选择或输入", key=f"bn{n}")
    bdate = l2.date_input("缴费日期", value=today, key=f"bd{n}")
    bamt = l3.number_input("金额", min_value=0.0, value=None, step=10.0, key=f"ba{n}")
    if st.button("记缴费", width="stretch"):
        if not bname or not bamt:
            st.warning("请填写名称和金额")
        else:
            rec = {"id": uid(), "name": bname.strip(), "date": str(bdate), "amount": float(bamt)}
            if write(lambda d: d["bills"].append(rec), "add bill"):
                st.session_state["n"] += 1
                st.rerun()
    for t in an.bill_status(data, today):
        st.info(t)
    if data["bills"]:
        df = pd.DataFrame([{"id": b["id"], "日期": b["date"], "名称": b["name"], "金额": b["amount"], "删除": False}
                           for b in sorted(data["bills"], key=lambda b: b["date"], reverse=True)])
        ed = st.data_editor(df, hide_index=True, width="stretch", key=f"bl{len(df)}",
                            disabled=["id", "日期", "名称", "金额"], column_config={"id": None})
        if st.button("删除勾选的缴费", key="bldel"):
            ids = {r["id"] for r in ed.to_dict("records") if r["删除"]}
            if ids and write(lambda d: d.__setitem__("bills", [b for b in d["bills"] if b["id"] not in ids]), "del bills"):
                st.rerun()
    st.divider()
    st.write("收入记录")
    i1, i2, i3 = st.columns(3)
    isrc = i1.text_input("来源", placeholder="工资", key=f"is{n}")
    idate = i2.date_input("日期", value=today, key=f"id{n}")
    iamt = i3.number_input("金额", min_value=0.0, value=None, step=100.0, key=f"ia{n}")
    if st.button("记收入", width="stretch"):
        if not iamt:
            st.warning("请填写金额")
        else:
            rec = {"id": uid(), "source": isrc.strip() or "收入", "date": str(idate), "amount": float(iamt)}
            if write(lambda d: d["income"].append(rec), "add income"):
                st.session_state["n"] += 1
                st.rerun()
    if data["income"]:
        df = pd.DataFrame([{"id": x["id"], "日期": x["date"], "来源": x["source"], "金额": x["amount"], "删除": False}
                           for x in sorted(data["income"], key=lambda x: x["date"], reverse=True)])
        ed = st.data_editor(df, hide_index=True, width="stretch", key=f"il{len(df)}",
                            disabled=["id", "日期", "来源", "金额"], column_config={"id": None})
        if st.button("删除勾选的收入", key="idel"):
            ids = {r["id"] for r in ed.to_dict("records") if r["删除"]}
            if ids and write(lambda d: d.__setitem__("income", [x for x in d["income"] if x["id"] not in ids]), "del income"):
                st.rerun()

# ---------------- 设置 ----------------
with t_set:
    fk = st.selectbox("字体", list(FONTS), index=list(FONTS).index(S.get("font", "B")),
                      format_func=lambda k: FONTS[k][0])
    s1, s2 = st.columns(2)
    bud = s1.number_input("月预算（元，0 为不设）", min_value=0.0, value=float(data["budget"].get("monthly") or 0), step=100.0)
    thr = s2.number_input("单笔超过多少算大件（仅「穿」「其他」）", min_value=0.0, value=float(S["big_threshold"]), step=50.0)
    al = s1.number_input("涨价提醒阈值（%）", min_value=1.0, value=float(S["alert_pct"]), step=1.0)
    TZS = ["Asia/Shanghai", "Asia/Hong_Kong", "Asia/Tokyo", "America/Los_Angeles", "America/New_York", "Europe/London", "UTC"]
    tz = s2.selectbox("时区", TZS, index=TZS.index(S["tz"]) if S["tz"] in TZS else 0)
    st.write("分类设置")
    cdf = pd.DataFrame([{"分类": k, "性质": KIND_LABEL[v.get("kind", "casual")], "超阈值转大件": bool(v.get("thr"))}
                        for k, v in data["categories"].items()])
    ced = st.data_editor(cdf, num_rows="dynamic", hide_index=True, width="stretch", key="cats",
                         column_config={"性质": st.column_config.SelectboxColumn(options=list(KIND_KEY), required=True)})
    st.write("生活费用类型")
    st.caption("摊销：房租物业这类，付一次覆盖一段时间；按缴费计入：水电气，缴费当月算，另给月均参考。没列出的名称默认按缴费计入。")
    names_b = sorted(set(data["bill_types"]) | {b["name"] for b in data["bills"]})
    bdf = pd.DataFrame([{"名称": nm, "类型": BILL_LABEL[an.bill_kind(data, nm)]} for nm in names_b])
    bed = st.data_editor(bdf, hide_index=True, width="stretch", key="btypes", disabled=["名称"],
                         column_config={"类型": st.column_config.SelectboxColumn(options=list(BILL_KEY), required=True)})
    if st.button("保存设置", type="primary", width="stretch"):
        newc = {}
        for r in ced.to_dict("records"):
            if r["分类"] and str(r["分类"]).strip():
                newc[str(r["分类"]).strip()] = {"kind": KIND_KEY[r["性质"] or "随手消费"], **({"thr": True} if r["超阈值转大件"] else {})}
        newb = {r["名称"]: BILL_KEY[r["类型"]] for r in bed.to_dict("records")}

        def mut(d):
            d["settings"].update(font=fk, big_threshold=thr, alert_pct=al, tz=tz)
            d["budget"]["monthly"] = bud
            if newc:
                d["categories"] = newc
            d["bill_types"].update(newb)

        if write(mut, "settings"):
            st.session_state["flash"] = "设置已保存"
            st.rerun()
    st.divider()
    r1, r2 = st.columns(2)
    if r1.button("重新同步数据", width="stretch"):
        st.session_state.pop("data", None)
        st.rerun()
    r2.download_button("备份 JSON", json.dumps(data, ensure_ascii=False, indent=1),
                       file_name="expenses-backup.json", width="stretch")
    st.caption("数据存放位置：" + ("GitHub 私有仓库" if storage.github_conf() else "本地测试文件（还没连接 GitHub）"))

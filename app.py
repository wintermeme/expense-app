import datetime as dt
import hmac
import json
import uuid
from collections import Counter
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
.rc {{ border: 1px dashed rgba(128,128,160,.55); border-radius: 14px; padding: 16px 14px; background: rgba(128,128,160,.07); }}
.rc-title {{ text-align: center; font-size: 1.15rem; font-weight: 600; letter-spacing: .15em; }}
.rc-sub {{ text-align: center; opacity: .7; font-size: .85rem; margin: 2px 0 10px; }}
.rc table {{ width: 100%; border-collapse: collapse; font-size: .92rem; font-variant-numeric: tabular-nums; }}
.rc th {{ text-align: left; font-weight: 600; opacity: .75; padding: 6px 4px; border-top: 1px dashed rgba(128,128,160,.55); border-bottom: 1px dashed rgba(128,128,160,.55); }}
.rc td {{ padding: 5px 4px; vertical-align: top; }}
.rc th:nth-child(n+2), .rc td:nth-child(n+2) {{ text-align: right; white-space: nowrap; }}
.rc td:first-child {{ word-break: break-all; }}
.rc tr.rc-store td {{ font-weight: 600; padding-top: 10px; text-align: left; opacity: .9; }}
.rc tr.rc-ex td, .rc tr.rc-sub2 td {{ opacity: .75; }}
.rc tr.rc-sub2 td {{ border-top: 1px dotted rgba(128,128,160,.45); }}
.rc .rc-empty {{ text-align: center !important; opacity: .6; padding: 14px; }}
.rc-total {{ display: flex; justify-content: space-between; font-weight: 600; font-size: 1.05rem; border-top: 1px dashed rgba(128,128,160,.55); margin-top: 8px; padding-top: 8px; }}
.rc-cats {{ margin-top: 8px; font-size: .82rem; opacity: .75; }}
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


def txt(x):
    return "" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x).strip()


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
    it = {"id": uid(), "item": txt(item) or cat, "brand": txt(brand), "category": cat,
          "amount": round(float(amount), 2), "big": bool(big)}
    if qty and qty > 0 and calc.unit_info(unit):
        it["qty"], it["unit"] = qty, unit
    return it


def parse_qty(s):
    s = txt(s)
    if not s:
        return None, None
    try:
        v = float(s)
    except ValueError:
        return None, "数量要填数字"
    return (v if v > 0 else None), None


# ---------- 历史记忆：店铺、品牌、物品、数量都从已有记录里统计，不用另外存 ----------
def hist(d):
    sc, bc, ic = Counter(), Counter(), Counter()
    last, qtys, ibr = {}, {}, {}
    for o in sorted(d["orders"], key=lambda o: o["date"]):
        if o.get("store"):
            sc[o["store"]] += 1
        for i in o["items"]:
            if i["category"] == "交通":
                continue
            ic[i["item"]] += 1
            last[i["item"]] = {"brand": i.get("brand", ""), "category": i["category"], "unit": i.get("unit")}
            if i.get("brand"):
                bc[i["brand"]] += 1
                ibr.setdefault(i["item"], Counter())[i["brand"]] += 1
            if i.get("qty"):
                qtys.setdefault(i["item"], []).append(f"{i['qty']:g}")
    return {"stores": [k for k, _ in sc.most_common()], "brands": [k for k, _ in bc.most_common()],
            "items": [k for k, _ in ic.most_common()], "last": last,
            "ibrands": {k: [b for b, _ in v.most_common()] for k, v in ibr.items()},
            "qtys": {k: list(dict.fromkeys(reversed(v)))[:6] for k, v in qtys.items()}}


TRANSPORT = ["地铁", "公交", "打车", "共享单车", "高铁火车", "飞机", "其他"]


def transport_hist(d):
    cnt, last = Counter(), {}
    for o in sorted(d["orders"], key=lambda o: o["date"]):
        for i in o["items"]:
            if i["category"] == "交通":
                cnt[i["item"]] += 1
                last[i["item"]] = i["amount"]
    tools = [k for k, _ in cnt.most_common()]
    return tools + [t for t in TRANSPORT if t not in tools], last


def opts(base, cur):
    base = list(base)
    return base + ([cur] if cur and cur not in base else [])


def item_fields(p, init, d):
    """竖着排的一件商品表单。p 是控件 key 前缀。选了物品后，品牌、分类、单位自动带出上次的值。"""
    ss, H, cats = st.session_state, hist(d), list(d["categories"])
    ss.setdefault(p + "item", init.get("item") or None)
    ss.setdefault(p + "brand", init.get("brand") or None)
    ss.setdefault(p + "cat", init.get("cat") if init.get("cat") in cats else cats[0])
    ss.setdefault(p + "qty", init.get("qty") or None)
    ss.setdefault(p + "unit", init.get("unit") or "g")
    ss.setdefault(p + "big", bool(init.get("big")))
    ss.setdefault(p + "last", init.get("item") or None)
    if init.get("amount") is not None:
        ss.setdefault(p + "amount", float(init["amount"]))
    st.selectbox("物品", opts(H["items"], ss[p + "item"]), index=None, accept_new_options=True,
                 placeholder="选择历史，或直接输入新的", key=p + "item")
    cur = ss[p + "item"]
    if cur != ss[p + "last"]:
        ss[p + "last"] = cur
        lp = H["last"].get(cur)
        if lp:
            ss[p + "brand"] = lp["brand"] or None
            if lp["category"] in cats:
                ss[p + "cat"] = lp["category"]
            if lp["unit"]:
                ss[p + "unit"] = lp["unit"]
    ib = H["ibrands"].get(cur, [])
    st.selectbox("品牌（可不填）", opts(ib + [b for b in H["brands"] if b not in ib], ss[p + "brand"]), index=None,
                 accept_new_options=True, placeholder="选择历史，或直接输入", key=p + "brand")
    st.selectbox("分类", cats, key=p + "cat")
    st.selectbox("数量（可不填）", opts(H["qtys"].get(cur, []), ss[p + "qty"]), index=None, accept_new_options=True,
                 placeholder="选择历史，或直接输入数字", key=p + "qty")
    st.selectbox("单位", calc.UNIT_LIST, key=p + "unit")
    st.number_input("金额（元）", min_value=0.0, value=None, step=0.5, format="%.2f", placeholder="0.00", key=p + "amount")
    st.checkbox("偶发大件，不计入日均", key=p + "big")


def read_item(p, cats):
    ss = st.session_state
    if not ss.get(p + "amount"):
        return None, "请先填写金额"
    q, err = parse_qty(ss.get(p + "qty"))
    if err:
        return None, err
    return mk_item(ss.get(p + "item"), ss.get(p + "brand"), ss.get(p + "cat") or cats[0], q,
                   ss.get(p + "unit"), ss[p + "amount"], ss.get(p + "big")), None


def commit_order(day, store, items, extras, draft_id=None):
    order = {"id": uid(), "date": str(day), "store": txt(store), "extras": extras, "items": items}

    def mut(d):
        d["orders"].append(order)
        if draft_id:
            d["drafts"] = [x for x in d["drafts"] if x["id"] != draft_id]
    return write(mut, "add order")


def save_draft(kind, form, draft_id):
    rec = {"id": draft_id, "kind": kind, "updated": dt.datetime.now().strftime("%m-%d %H:%M"), "form": form}
    return write(lambda d: d.__setitem__("drafts", [x for x in d["drafts"] if x["id"] != draft_id] + [rec]), "save draft")


def extras_of(ship, other, disc):
    return [{"name": k, "amount": v} for k, v in (("运费", ship), ("杂费", other), ("优惠", -(disc or 0))) if v]


def frag_rerun():
    """弹窗内只刷新弹窗本身；万一不在弹窗里，退回整页刷新。"""
    try:
        st.rerun(scope="fragment")
    except st.errors.StreamlitAPIException:
        st.rerun()


def clear_dlg():
    for k in [k for k in st.session_state if k.startswith("dlg_")]:
        del st.session_state[k]


# ---------- 弹窗 ----------
@st.dialog("记一件")
def dlg_one():
    ss, d = st.session_state, st.session_state["data"]
    init, H, cats = ss.get("dlg_init", {}), hist(d), list(d["categories"])
    ss.setdefault("dlg_o_date", dt.date.fromisoformat(init["date"]) if init.get("date") else ss["today"])
    ss.setdefault("dlg_o_store", init.get("store") or None)
    st.date_input("日期", key="dlg_o_date")
    st.selectbox("店铺（可不填）", opts(H["stores"], ss["dlg_o_store"]), index=None, accept_new_options=True,
                 placeholder="选择历史，或直接输入", key="dlg_o_store")
    item_fields("dlg_o_", init, d)
    with st.expander("附加费用（运费、杂费、优惠）"):
        ss.setdefault("dlg_o_ship", init.get("ship") or 0.0)
        ss.setdefault("dlg_o_other", init.get("other") or 0.0)
        ss.setdefault("dlg_o_disc", init.get("disc") or 0.0)
        st.number_input("运费", min_value=0.0, step=1.0, key="dlg_o_ship")
        st.number_input("打包等杂费", min_value=0.0, step=1.0, key="dlg_o_other")
        st.number_input("优惠减免", min_value=0.0, step=1.0, key="dlg_o_disc")
    c1, c2 = st.columns(2)
    if c1.button("保存", type="primary", width="stretch"):
        it, err = read_item("dlg_o_", cats)
        if err:
            st.warning(err)
        elif commit_order(ss["dlg_o_date"], ss["dlg_o_store"], [it],
                          extras_of(ss["dlg_o_ship"], ss["dlg_o_other"], ss["dlg_o_disc"]), ss.get("dlg_draft")):
            ss["flash"] = "已记录 ✓"
            st.rerun()
    if c2.button("存草稿", width="stretch"):
        ss["dlg_draft"] = ss.get("dlg_draft") or uid()
        p = "dlg_o_"
        form = {"date": str(ss[p + "date"]), "store": ss[p + "store"], "item": ss[p + "item"], "brand": ss[p + "brand"],
                "cat": ss[p + "cat"], "qty": ss[p + "qty"], "unit": ss[p + "unit"], "amount": ss.get(p + "amount"),
                "big": ss[p + "big"], "ship": ss[p + "ship"], "other": ss[p + "other"], "disc": ss[p + "disc"]}
        if save_draft("one", form, ss["dlg_draft"]):
            ss["flash"] = "已存入草稿箱"
            st.rerun()


@st.dialog("记多件")
def dlg_multi():
    ss, d = st.session_state, st.session_state["data"]
    init, H, cats = ss.get("dlg_init", {}), hist(d), list(d["categories"])
    ss.setdefault("dlg_m_date", dt.date.fromisoformat(init["date"]) if init.get("date") else ss["today"])
    ss.setdefault("dlg_m_store", init.get("store") or None)
    st.date_input("日期", key="dlg_m_date")
    st.selectbox("店铺（填一次，整单共用）", opts(H["stores"], ss["dlg_m_store"]), index=None, accept_new_options=True,
                 placeholder="选择历史，或直接输入", key="dlg_m_store")
    items = ss["dlg_m_items"]

    def autosave():
        ss["dlg_draft"] = ss.get("dlg_draft") or uid()
        form = {"date": str(ss["dlg_m_date"]), "store": ss["dlg_m_store"], "items": ss["dlg_m_items"],
                "ship": ss.get("dlg_m_ship", 0.0), "other": ss.get("dlg_m_other", 0.0), "disc": ss.get("dlg_m_disc", 0.0)}
        return save_draft("multi", form, ss["dlg_draft"])

    if items:
        st.markdown(f"**已加入 {len(items)} 件，商品合计 ¥{sum(i['amount'] for i in items):.2f}**")
        for it in items:
            a, b = st.columns([6, 1])
            a.write(f"{it['item']}{'·' + it['brand'] if it['brand'] else ''}　¥{it['amount']:.2f}")
            if b.button("✕", key="dlg_mdel_" + it["id"]):
                ss["dlg_m_items"] = [x for x in items if x["id"] != it["id"]]
                autosave()
                frag_rerun()
    st.divider()
    st.markdown("**添加一件商品**")
    p = f"dlg_m{ss['dlg_m_c']}_"
    item_fields(p, {}, d)
    if st.button("加入这一件", width="stretch"):
        it, err = read_item(p, cats)
        if err:
            st.warning(err)
        else:
            ss["dlg_m_items"] = items + [it]
            ss["dlg_m_c"] += 1
            autosave()
            frag_rerun()
    st.divider()
    st.markdown("**整单的附加费用**")
    st.caption("会按每件商品的金额比例分摊到每一件上")
    ss.setdefault("dlg_m_ship", init.get("ship") or 0.0)
    ss.setdefault("dlg_m_other", init.get("other") or 0.0)
    ss.setdefault("dlg_m_disc", init.get("disc") or 0.0)
    st.number_input("运费", min_value=0.0, step=1.0, key="dlg_m_ship")
    st.number_input("打包等杂费", min_value=0.0, step=1.0, key="dlg_m_other")
    st.number_input("优惠减免", min_value=0.0, step=1.0, key="dlg_m_disc")
    c1, c2 = st.columns(2)
    if c1.button("提交订单", type="primary", width="stretch"):
        if not items:
            st.warning("还没有加入任何商品")
        elif ss.get(p + "amount"):
            st.warning("上面还有一件填了金额但没加入，请先点「加入这一件」")
        elif commit_order(ss["dlg_m_date"], ss["dlg_m_store"], items,
                          extras_of(ss["dlg_m_ship"], ss["dlg_m_other"], ss["dlg_m_disc"]), ss.get("dlg_draft")):
            ss["flash"] = f"已记录订单，共 {len(items)} 件 ✓"
            st.rerun()
    if c2.button("存草稿", width="stretch"):
        if autosave():
            ss["flash"] = "已存入草稿箱"
            st.rerun()


@st.dialog("记交通")
def dlg_transport():
    ss, d = st.session_state, st.session_state["data"]
    tools, last = transport_hist(d)
    ss.setdefault("dlg_t_date", ss["today"])
    ss.setdefault("dlg_t_tool", None)
    ss.setdefault("dlg_t_last", None)
    st.date_input("日期", key="dlg_t_date")
    st.selectbox("交通工具", opts(tools, ss["dlg_t_tool"]), index=None, accept_new_options=True,
                 placeholder="选择，或直接输入", key="dlg_t_tool")
    if ss["dlg_t_tool"] != ss["dlg_t_last"]:
        ss["dlg_t_last"] = ss["dlg_t_tool"]
        if ss["dlg_t_tool"] in last:
            ss["dlg_t_amount"] = float(last[ss["dlg_t_tool"]])
    st.number_input("金额（元）", min_value=0.0, value=None, step=0.5, format="%.2f", placeholder="0.00", key="dlg_t_amount")
    if ss["dlg_t_tool"] in last:
        st.caption("金额已自动带出上次的值，不一样的话直接改。")
    if st.button("保存", type="primary", width="stretch"):
        tool = txt(ss.get("dlg_t_tool"))
        if not tool or not ss.get("dlg_t_amount"):
            st.warning("请选择交通工具并填写金额")
        else:
            order = {"id": uid(), "date": str(ss["dlg_t_date"]), "store": "", "extras": [],
                     "items": [{"id": uid(), "item": tool, "brand": "", "category": "交通",
                                "amount": round(float(ss["dlg_t_amount"]), 2), "big": False}]}

            def mut(dd):
                dd["categories"].setdefault("交通", {"kind": "casual"})
                dd["orders"].append(order)
            if write(mut, "add transport"):
                ss["flash"] = "已记录交通 ✓"
                st.rerun()


@st.dialog("编辑这一件")
def dlg_edit(rid):
    ss, d = st.session_state, st.session_state["data"]
    cats = list(d["categories"])
    r = next((x for x in an.records(d) if x["id"] == rid), None)
    if r is None:
        st.info("这条记录已不存在")
        return
    init = {"item": r["item"], "brand": r["brand"], "cat": r["category"], "unit": r["unit"], "amount": r["amount"],
            "qty": f"{r['qty']:g}" if r["qty"] else None, "big": r["kind"] == "big" and r["category"] in d["categories"]
            and d["categories"][r["category"]].get("kind") != "big"}
    st.caption(f"{r['date']}　{r['store']}")
    item_fields("dlg_e_", init, d)
    c1, c2 = st.columns(2)
    if c1.button("保存修改", type="primary", width="stretch"):
        it, err = read_item("dlg_e_", cats)
        if err:
            st.warning(err)
        else:
            def mut(dd):
                for o in dd["orders"]:
                    for x in o["items"]:
                        if x["id"] == rid:
                            x.update(item=it["item"], brand=it["brand"], category=it["category"],
                                     amount=it["amount"], big=it["big"])
                            x.pop("qty", None)
                            x.pop("unit", None)
                            if "qty" in it:
                                x["qty"], x["unit"] = it["qty"], it["unit"]
            if write(mut, "edit item"):
                ss["flash"] = "已保存修改"
                st.rerun()
    if not ss.get("dlg_e_confirm"):
        if c2.button("删除这件", width="stretch"):
            ss["dlg_e_confirm"] = True
            frag_rerun()
    else:
        st.warning("确定删除这一件吗？")
        d1, d2 = st.columns(2)
        if d1.button("确认删除", type="primary", width="stretch"):
            def mut(dd):
                for o in dd["orders"]:
                    o["items"] = [x for x in o["items"] if x["id"] != rid]
                dd["orders"] = [o for o in dd["orders"] if o["items"]]
            if write(mut, "delete item"):
                ss["flash"] = "已删除"
                st.rerun()
        if d2.button("取消", width="stretch"):
            ss["dlg_e_confirm"] = False
            frag_rerun()


@st.dialog("添加比价选项")
def dlg_cmp():
    ss, d = st.session_state, st.session_state["data"]
    H = hist(d)
    st.selectbox("品牌", opts(H["brands"], ss.get("dlg_c_brand")), index=None, accept_new_options=True,
                 placeholder="选择历史，或直接输入", key="dlg_c_brand")
    st.number_input("价格（元）", min_value=0.0, value=None, step=0.5, format="%.2f", key="dlg_c_price")
    st.number_input("数量", min_value=0.0, value=None, step=1.0, key="dlg_c_qty")
    ss.setdefault("dlg_c_unit", "g")
    st.selectbox("单位", calc.UNIT_LIST, key="dlg_c_unit")
    if st.button("添加", type="primary", width="stretch"):
        if not ss.get("dlg_c_price") or not ss.get("dlg_c_qty"):
            st.warning("价格和数量都要填")
        else:
            ss["cmp_opts"].append({"brand": txt(ss.get("dlg_c_brand")), "price": ss["dlg_c_price"],
                                   "qty": ss["dlg_c_qty"], "unit": ss["dlg_c_unit"]})
            st.rerun()


@st.dialog("记缴费")
def dlg_bill():
    ss, d = st.session_state, st.session_state["data"]
    names = sorted({b["name"] for b in d["bills"]} | {"房租", "物业", "电费", "水费", "燃气", "网费", "话费"})
    ss.setdefault("dlg_b_date", ss["today"])
    st.selectbox("名称", opts(names, ss.get("dlg_b_name")), index=None, accept_new_options=True,
                 placeholder="选择，或直接输入", key="dlg_b_name")
    st.date_input("缴费日期", key="dlg_b_date")
    st.number_input("金额（元）", min_value=0.0, value=None, step=10.0, format="%.2f", key="dlg_b_amt")
    if st.button("保存", type="primary", width="stretch"):
        if not txt(ss.get("dlg_b_name")) or not ss.get("dlg_b_amt"):
            st.warning("请填写名称和金额")
        else:
            rec = {"id": uid(), "name": txt(ss["dlg_b_name"]), "date": str(ss["dlg_b_date"]), "amount": float(ss["dlg_b_amt"])}
            if write(lambda dd: dd["bills"].append(rec), "add bill"):
                ss["flash"] = "已记录缴费 ✓"
                st.rerun()


@st.dialog("记收入")
def dlg_income():
    ss, d = st.session_state, st.session_state["data"]
    srcs = list(dict.fromkeys(x["source"] for x in d["income"]))
    ss.setdefault("dlg_i_date", ss["today"])
    st.selectbox("来源", opts(srcs, ss.get("dlg_i_src")), index=None, accept_new_options=True,
                 placeholder="比如：工资", key="dlg_i_src")
    st.date_input("日期", key="dlg_i_date")
    st.number_input("金额（元）", min_value=0.0, value=None, step=100.0, format="%.2f", key="dlg_i_amt")
    if st.button("保存", type="primary", width="stretch"):
        if not ss.get("dlg_i_amt"):
            st.warning("请填写金额")
        else:
            rec = {"id": uid(), "source": txt(ss.get("dlg_i_src")) or "收入", "date": str(ss["dlg_i_date"]),
                   "amount": float(ss["dlg_i_amt"])}
            if write(lambda dd: dd["income"].append(rec), "add income"):
                ss["flash"] = "已记录收入 ✓"
                st.rerun()


@st.dialog("确认删除")
def dlg_confirm(kind, rid, label):
    st.write(f"确定删除「{label}」吗？")
    c1, c2 = st.columns(2)
    if c1.button("确认删除", type="primary", width="stretch"):
        if write(lambda d: d.__setitem__(kind, [x for x in d[kind] if x["id"] != rid]), "delete " + kind):
            st.session_state["flash"] = "已删除"
            st.rerun()
    if c2.button("取消", width="stretch"):
        st.rerun()


def open_one(init=None, draft=None):
    clear_dlg()
    st.session_state["dlg_init"], st.session_state["dlg_draft"] = init or {}, draft
    dlg_one()


def open_multi(init=None, draft=None):
    clear_dlg()
    ss = st.session_state
    ss["dlg_init"], ss["dlg_draft"] = init or {}, draft
    ss["dlg_m_items"], ss["dlg_m_c"] = list((init or {}).get("items", [])), 0
    dlg_multi()


def open_plain(fn, *args):
    clear_dlg()
    fn(*args)


def lbl(r):
    return f"{r['item']}{'·' + r['brand'] if r['brand'] else ''}"


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
st.session_state["today"] = today
st.session_state.setdefault("cmp_opts", [])
if st.session_state.get("flash"):
    st.toast(st.session_state.pop("flash"))
cats = list(data["categories"])
recs = an.records(data)

t_add, t_rc, t_cmp, t_price, t_rep, t_life, t_set = st.tabs(["记账", "小票", "比价", "价格", "月报", "生活", "设置"])

# ---------------- 记账 ----------------
with t_add:
    b1, b2 = st.columns(2)
    if b1.button("＋ 记一件", type="primary", width="stretch"):
        open_one()
    if b2.button("＋ 记多件", width="stretch"):
        open_multi()
    if st.button("＋ 交通", width="stretch"):
        open_plain(dlg_transport)
    drafts = data["drafts"]
    if drafts:
        with st.expander(f"草稿箱（{len(drafts)}）"):
            for dr in sorted(drafts, key=lambda x: x["updated"], reverse=True):
                f = dr["form"]
                if dr["kind"] == "multi":
                    desc = f"记多件 · {f.get('date', '')} · {f.get('store') or '未填店铺'} · 已加 {len(f.get('items', []))} 件"
                else:
                    amt = f"¥{f['amount']:.2f}" if f.get("amount") else "未填金额"
                    desc = f"记一件 · {f.get('date', '')} · {f.get('item') or '未填物品'} · {amt}"
                st.write(desc + f"　（{dr['updated']}）")
                g1, g2 = st.columns(2)
                if g1.button("继续填写", key="drgo_" + dr["id"], width="stretch"):
                    (open_multi if dr["kind"] == "multi" else open_one)(f, dr["id"])
                if g2.button("删除草稿", key="drdel_" + dr["id"], width="stretch"):
                    if write(lambda d, i=dr["id"]: d.__setitem__("drafts", [x for x in d["drafts"] if x["id"] != i]), "del draft"):
                        st.rerun()
    trs = [r for r in recs if r["date"] == str(today)]
    st.caption(f"今天已记 ¥{sum(r['amount'] for r in trs):.2f}，共 {len(trs)} 件")
    for r in trs[-6:][::-1]:
        st.write(f"· {lbl(r)}　¥{r['amount']:.2f}")

# ---------------- 小票 ----------------
with t_rc:
    rday = st.date_input("日期", value=today, key="rday")
    rtxt = receipt.render_day(data, str(rday))
    st.markdown(receipt.render_day_html(data, str(rday)), unsafe_allow_html=True)
    with st.expander("文字版（复制 / 下载）"):
        st.code(rtxt, language=None)
        st.download_button("下载 .txt", rtxt, file_name=f"小票-{rday}.txt", width="stretch")
    drs = [r for r in recs if r["date"] == str(rday)]
    with st.expander(f"修改 / 删除当天记录（{len(drs)}）"):
        if not drs:
            st.caption("这一天没有记录。")
        for r in drs:
            a, b = st.columns([5, 1])
            a.write(f"{lbl(r)}　¥{r['amount']:.2f}")
            if b.button("改", key="ed_" + r["id"]):
                clear_dlg()
                dlg_edit(r["id"])

# ---------------- 比价 ----------------
with t_cmp:
    st.caption("把同一种东西的几个选项加进来，自动换算成同一单位，选出最划算的。")
    if st.button("＋ 添加选项", type="primary", width="stretch"):
        open_plain(dlg_cmp)
    for i, o in enumerate(st.session_state["cmp_opts"]):
        a, b = st.columns([6, 1])
        a.write(f"{o['brand'] or '（未填品牌）'}　¥{o['price']:g} / {o['qty']:g}{o['unit']}")
        if b.button("✕", key=f"cmpdel{i}"):
            st.session_state["cmp_opts"].pop(i)
            st.rerun()
    if st.session_state["cmp_opts"]:
        rows, err = calc.compare(st.session_state["cmp_opts"])
        if err:
            st.info(err)
        else:
            b0 = rows[0]
            st.success(f"最划算：{b0['brand']}，{b0['up']:.2f} {b0['label']}，比最贵的省 {b0['save_pct']:.0f}%")
            st.dataframe(pd.DataFrame([{"品牌": r["brand"], "单价": f"{r['up']:.2f} {r['label']}",
                                        "比最贵省": f"{r['save_pct']:.0f}%"} for r in rows]),
                         hide_index=True, width="stretch")
        if st.button("清空选项", width="stretch"):
            st.session_state["cmp_opts"] = []
            st.rerun()

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
        tbl = pd.DataFrame([{"日期": r["date"][5:], "品牌": r["brand"], "店铺": r["store"], "单价": round(r[key], 2),
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
    if rep["transport"]:
        st.write(f"交通明细（共 ¥{sum(x['amount'] for x in rep['transport']):.2f}）")
        st.dataframe(pd.DataFrame([{"交通工具": x["item"], "次数": x["n"], "金额": round(x["amount"], 2),
                                    "平均每次": round(x["amount"] / x["n"], 2)} for x in rep["transport"]]),
                     hide_index=True, width="stretch")
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
    l1, l2 = st.columns(2)
    if l1.button("＋ 记缴费", type="primary", width="stretch"):
        open_plain(dlg_bill)
    if l2.button("＋ 记收入", width="stretch"):
        open_plain(dlg_income)
    for t in an.bill_status(data, today):
        st.info(t)
    st.write("缴费记录")
    bl = sorted(data["bills"], key=lambda b: b["date"], reverse=True)
    if not bl:
        st.caption("还没有缴费记录。")
    for b in bl[:20]:
        a, c = st.columns([5, 1])
        a.write(f"{b['date']}　{b['name']}　¥{b['amount']:.2f}")
        if c.button("删", key="bd_" + b["id"]):
            open_plain(dlg_confirm, "bills", b["id"], f"{b['date']} {b['name']} ¥{b['amount']:.2f}")
    if len(bl) > 20:
        st.caption(f"只显示最近 20 条，共 {len(bl)} 条。")
    st.divider()
    st.write("收入记录")
    il = sorted(data["income"], key=lambda x: x["date"], reverse=True)
    if not il:
        st.caption("还没有收入记录。")
    for x in il[:20]:
        a, c = st.columns([5, 1])
        a.write(f"{x['date']}　{x['source']}　¥{x['amount']:.2f}")
        if c.button("删", key="id_" + x["id"]):
            open_plain(dlg_confirm, "income", x["id"], f"{x['date']} {x['source']} ¥{x['amount']:.2f}")

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
    st.write("分类设置（建议在电脑上改）")
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
            nm = txt(r["分类"])
            if nm:
                newc[nm] = {"kind": KIND_KEY[r["性质"] or "随手消费"], **({"thr": True} if r["超阈值转大件"] else {})}
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

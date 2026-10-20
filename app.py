"""관세청 수출입통계 대시보드 (Streamlit).

HS 2 -> 4 -> 6 자리 드릴다운, 5개년 월간 추이, YoY/QoQ, 관련 기업 관리.
데이터 출처: 관세청 Itemtrade/getItemtradeList (collector.py 로 사전 수집한 data/trade.db).

지표 정의:
  YoY = (당월 - 전년동월) / 전년동월 * 100
  QoQ = 월→분기 합산 후 (당분기 - 전분기) / 전분기 * 100
"""
import os
import sqlite3
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "data", "trade.db")

st.set_page_config(page_title="관세청 수출입통계 대시보드", layout="wide")


# ----------------------------- 데이터 접근 -----------------------------
@st.cache_resource
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    return conn


@st.cache_data(ttl=300)
def get_meta():
    conn = get_conn()
    try:
        rows = conn.execute("SELECT key, value FROM collection_meta").fetchall()
        return dict(rows)
    except sqlite3.OperationalError:
        return {}


@st.cache_data(ttl=300)
def level_summary(prefix: str, level: int, period: str):
    """주어진 레벨(2/4/6)에서 prefix 하위 그룹별 집계 (특정 월 기준 정렬용)."""
    conn = get_conn()
    sub = level
    sql = f"""
        SELECT SUBSTR(hs_code,1,{sub}) AS code,
               SUM(exp_dlr) AS exp_dlr,
               SUM(imp_dlr) AS imp_dlr,
               SUM(bal_pay) AS bal_pay
        FROM trade_raw
        WHERE period = ? AND hs_code LIKE ?
        GROUP BY code
        ORDER BY exp_dlr DESC
    """
    like = prefix + "%"
    df = pd.read_sql_query(sql, conn, params=(period, like))
    return df


@st.cache_data(ttl=300)
def representative_names(level: int):
    """각 레벨 코드의 대표 품목명(statKor) - 최신 기간에서 최대 금액 품목명 사용."""
    conn = get_conn()
    sql = f"""
        WITH ranked AS (
            SELECT SUBSTR(hs_code,1,{level}) AS code,
                   item_name,
                   SUM(exp_dlr + imp_dlr) AS vol,
                   ROW_NUMBER() OVER (
                       PARTITION BY SUBSTR(hs_code,1,{level})
                       ORDER BY SUM(exp_dlr + imp_dlr) DESC
                   ) AS rn
            FROM trade_raw
            GROUP BY code, item_name
        )
        SELECT code, item_name FROM ranked WHERE rn = 1
    """
    df = pd.read_sql_query(sql, conn)
    return dict(zip(df["code"], df["item_name"]))


@st.cache_data(ttl=300)
def monthly_series(prefix: str):
    """prefix(2/4/6자리)에 해당하는 월별 수출/수입 합계 시계열."""
    conn = get_conn()
    sql = """
        SELECT period,
               SUM(exp_dlr) AS exp_dlr,
               SUM(imp_dlr) AS imp_dlr
        FROM trade_raw
        WHERE hs_code LIKE ?
        GROUP BY period
        ORDER BY period
    """
    df = pd.read_sql_query(sql, conn, params=(prefix + "%",))
    return df


@st.cache_data(ttl=300)
def item_breakdown(prefix: str, period: str):
    """prefix 하위 10자리 품목을 특정 월 기준으로 나열 (관련 기업 탭 등 참고용)."""
    conn = get_conn()
    sql = """
        SELECT hs_code, item_name, exp_dlr, imp_dlr
        FROM trade_raw
        WHERE period = ? AND hs_code LIKE ?
        ORDER BY exp_dlr DESC
    """
    df = pd.read_sql_query(sql, conn, params=(period, prefix + "%"))
    return df


# ----------------------------- 지표 계산 -----------------------------
def add_yoy(df: pd.DataFrame, col: str) -> pd.Series:
    """전년동월 대비 증감률(%). period는 YYYYMM 문자열, 오름차순 가정."""
    s = df.set_index("period")[col]
    prev = s.shift(12)
    yoy = (s - prev) / prev.replace(0, pd.NA) * 100
    return yoy


def quarterly(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """월 시계열을 분기 합산으로 변환하고 QoQ(%) 계산."""
    d = df.copy()
    d["year"] = d["period"].str[:4].astype(int)
    d["q"] = ((d["period"].str[4:6].astype(int) - 1) // 3 + 1)
    g = d.groupby(["year", "q"], as_index=False)[col].sum()
    g = g.sort_values(["year", "q"]).reset_index(drop=True)
    g["label"] = g["year"].astype(str) + " Q" + g["q"].astype(str)
    g["qoq"] = g[col].pct_change() * 100
    return g


def fmt_usd(v) -> str:
    if v is None or pd.isna(v):
        return "-"
    v = float(v)
    if abs(v) >= 1e9:
        return f"${v/1e9:,.2f}B"
    if abs(v) >= 1e6:
        return f"${v/1e6:,.2f}M"
    if abs(v) >= 1e3:
        return f"${v/1e3:,.1f}K"
    return f"${v:,.0f}"


# ----------------------------- 관련 기업 -----------------------------
def add_company(hs_code, hs_level, company, note):
    conn = get_conn()
    conn.execute(
        "INSERT INTO related_companies (hs_code, hs_level, company, note, created_at) VALUES (?,?,?,?,?)",
        (hs_code, hs_level, company, note, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


def delete_company(cid):
    conn = get_conn()
    conn.execute("DELETE FROM related_companies WHERE id = ?", (cid,))
    conn.commit()


def list_companies(hs_code):
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT id, company, note, created_at FROM related_companies WHERE hs_code = ? ORDER BY created_at",
        conn,
        params=(hs_code,),
    )
    return df


# ----------------------------- UI 헬퍼 -----------------------------
def label_for(code, names):
    nm = names.get(code)
    return f"{code}  ·  {nm}" if nm else code


def render_detail(prefix: str, level: int, names: dict, latest: str):
    """선택된 HS 코드 상세: 5개년 월간차트, YoY/QoQ, 관련 기업."""
    nm = names.get(prefix, "")
    st.subheader(f"📊 HS {prefix} {('· ' + nm) if nm else ''}  ({level}자리)")

    series = monthly_series(prefix)
    if series.empty:
        st.info("데이터가 없습니다.")
        return

    # KPI
    latest_row = series[series["period"] == latest]
    exp_now = latest_row["exp_dlr"].iloc[0] if not latest_row.empty else 0
    imp_now = latest_row["imp_dlr"].iloc[0] if not latest_row.empty else 0
    yoy_exp = add_yoy(series, "exp_dlr")
    yoy_imp = add_yoy(series, "imp_dlr")
    yoy_exp_v = yoy_exp.get(latest)
    yoy_imp_v = yoy_imp.get(latest)
    q_exp = quarterly(series, "exp_dlr")
    qoq_exp_v = q_exp["qoq"].iloc[-1] if len(q_exp) else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("수출 (최근월)", fmt_usd(exp_now),
              f"{yoy_exp_v:+.1f}% YoY" if pd.notna(yoy_exp_v) else None)
    c2.metric("수입 (최근월)", fmt_usd(imp_now),
              f"{yoy_imp_v:+.1f}% YoY" if pd.notna(yoy_imp_v) else None)
    c3.metric("무역수지 (최근월)", fmt_usd(exp_now - imp_now))
    c4.metric("수출 QoQ (최근분기)", f"{qoq_exp_v:+.1f}%" if pd.notna(qoq_exp_v) else "-")

    # 월간 추이 차트
    pdt = pd.to_datetime(series["period"], format="%Y%m")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=pdt, y=series["exp_dlr"], name="수출(USD)", mode="lines", line=dict(color="#1f77b4")))
    fig.add_trace(go.Scatter(x=pdt, y=series["imp_dlr"], name="수입(USD)", mode="lines", line=dict(color="#d62728")))
    fig.update_layout(
        title="월간 수출·수입 추이 (최근 5개년)",
        xaxis_title="월", yaxis_title="USD", height=380,
        legend=dict(orientation="h", y=1.1), margin=dict(t=60, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)

    # YoY / QoQ 차트
    cc1, cc2 = st.columns(2)
    with cc1:
        fig_y = go.Figure()
        fig_y.add_trace(go.Bar(x=pdt, y=yoy_exp, name="수출 YoY%", marker_color="#1f77b4"))
        fig_y.add_trace(go.Bar(x=pdt, y=yoy_imp, name="수입 YoY%", marker_color="#d62728"))
        fig_y.update_layout(title="전년동월 대비 증감률 (YoY %)", height=320,
                            legend=dict(orientation="h", y=1.15), margin=dict(t=50, b=20),
                            barmode="group")
        st.plotly_chart(fig_y, use_container_width=True)
    with cc2:
        fig_q = go.Figure()
        fig_q.add_trace(go.Bar(x=q_exp["label"], y=q_exp["qoq"], name="수출 QoQ%", marker_color="#2ca02c"))
        fig_q.update_layout(title="전분기 대비 증감률 (수출 QoQ %)", height=320,
                            margin=dict(t=50, b=20))
        st.plotly_chart(fig_q, use_container_width=True)

    # 관련 기업
    st.markdown("#### 🏢 관련 기업")
    with st.form(key=f"add_company_{prefix}", clear_on_submit=True):
        fc1, fc2, fc3 = st.columns([2, 3, 1])
        company = fc1.text_input("기업명", key=f"co_{prefix}")
        note = fc2.text_input("메모 (선택)", key=f"note_{prefix}")
        submitted = fc3.form_submit_button("추가")
        if submitted and company.strip():
            add_company(prefix, level, company.strip(), note.strip())
            st.success(f"'{company}' 추가됨")
            st.rerun()

    cos = list_companies(prefix)
    if cos.empty:
        st.caption("등록된 관련 기업이 없습니다.")
    else:
        for _, row in cos.iterrows():
            rc1, rc2, rc3 = st.columns([3, 5, 1])
            rc1.write(f"**{row['company']}**")
            rc2.write(row["note"] or "")
            if rc3.button("삭제", key=f"del_{row['id']}"):
                delete_company(int(row["id"]))
                st.rerun()


# ----------------------------- 메인 -----------------------------
def main():
    meta = get_meta()
    latest = meta.get("latest_month")

    st.title("🇰🇷 관세청 수출입통계 대시보드")
    if not latest:
        st.error("수집 데이터가 없습니다. 먼저 `python collector.py` 를 실행하세요.")
        st.stop()

    rng = meta.get("range", "")
    st.caption(
        f"데이터 출처: 관세청 Itemtrade API · 기준월 **{latest[:4]}.{latest[4:]}** · "
        f"수집범위 {rng} · 수집시각 {meta.get('collected_at','')}"
    )

    # 세션 상태로 드릴다운 경로 관리
    if "hs2" not in st.session_state:
        st.session_state.hs2 = None
    if "hs4" not in st.session_state:
        st.session_state.hs4 = None
    if "hs6" not in st.session_state:
        st.session_state.hs6 = None

    names2 = representative_names(2)
    names4 = representative_names(4)
    names6 = representative_names(6)

    # --- 사이드바: 드릴다운 네비게이션 ---
    with st.sidebar:
        st.header("🔎 드릴다운")
        st.write("기준월 정렬: 수출 금액 내림차순")

        df2 = level_summary("", 2, latest)
        opts2 = ["— 선택 —"] + [label_for(c, names2) for c in df2["code"]]
        cur2 = label_for(st.session_state.hs2, names2) if st.session_state.hs2 else "— 선택 —"
        sel2 = st.selectbox("HS 2자리", opts2, index=opts2.index(cur2) if cur2 in opts2 else 0)
        new_hs2 = None if sel2 == "— 선택 —" else sel2.split("  ·")[0].strip()
        if new_hs2 != st.session_state.hs2:
            st.session_state.hs2 = new_hs2
            st.session_state.hs4 = None
            st.session_state.hs6 = None
            st.rerun()

        if st.session_state.hs2:
            df4 = level_summary(st.session_state.hs2, 4, latest)
            opts4 = ["— 선택 —"] + [label_for(c, names4) for c in df4["code"]]
            cur4 = label_for(st.session_state.hs4, names4) if st.session_state.hs4 else "— 선택 —"
            sel4 = st.selectbox("HS 4자리", opts4, index=opts4.index(cur4) if cur4 in opts4 else 0)
            new_hs4 = None if sel4 == "— 선택 —" else sel4.split("  ·")[0].strip()
            if new_hs4 != st.session_state.hs4:
                st.session_state.hs4 = new_hs4
                st.session_state.hs6 = None
                st.rerun()

        if st.session_state.hs4:
            df6 = level_summary(st.session_state.hs4, 6, latest)
            opts6 = ["— 선택 —"] + [label_for(c, names6) for c in df6["code"]]
            cur6 = label_for(st.session_state.hs6, names6) if st.session_state.hs6 else "— 선택 —"
            sel6 = st.selectbox("HS 6자리", opts6, index=opts6.index(cur6) if cur6 in opts6 else 0)
            new_hs6 = None if sel6 == "— 선택 —" else sel6.split("  ·")[0].strip()
            if new_hs6 != st.session_state.hs6:
                st.session_state.hs6 = new_hs6
                st.rerun()

        if st.button("↺ 초기화"):
            st.session_state.hs2 = st.session_state.hs4 = st.session_state.hs6 = None
            st.rerun()

    # --- 메인 영역 ---
    # 현재 선택 레벨 결정
    if st.session_state.hs6:
        render_detail(st.session_state.hs6, 6, names6, latest)
    elif st.session_state.hs4:
        render_detail(st.session_state.hs4, 4, names4, latest)
        _render_level_table(st.session_state.hs4, 6, names6, latest, "하위 HS 6자리", "hs6")
    elif st.session_state.hs2:
        render_detail(st.session_state.hs2, 4, names4, latest)  # 2자리 상세 + 하위표
        _render_level_table(st.session_state.hs2, 4, names4, latest, "하위 HS 4자리", "hs4")
    else:
        # 최상위: HS2 정렬표
        st.subheader("HS 2자리 — 수출 금액 순위")
        _render_level_table("", 2, names2, latest, None, "hs2")


def _render_level_table(prefix, level, names, latest, title, select_key):
    if title:
        st.markdown(f"#### {title} (기준월 {latest[:4]}.{latest[4:]})")
    df = level_summary(prefix, level, latest)
    if df.empty:
        st.info("하위 품목 데이터가 없습니다.")
        return
    disp = df.copy()
    disp["품목명"] = disp["code"].map(lambda c: names.get(c, ""))
    disp["무역수지"] = disp["exp_dlr"] - disp["imp_dlr"]
    disp = disp.rename(columns={"code": "HS코드", "exp_dlr": "수출(USD)", "imp_dlr": "수입(USD)"})
    disp = disp[["HS코드", "품목명", "수출(USD)", "수입(USD)", "무역수지"]]

    st.dataframe(
        disp.style.format({"수출(USD)": "{:,.0f}", "수입(USD)": "{:,.0f}", "무역수지": "{:,.0f}"}),
        use_container_width=True, height=min(430, 40 + 36 * len(disp)),
    )

    # 클릭 대신 선택박스로 드릴다운 (표에서 바로 선택)
    pick = st.selectbox(
        f"위 표에서 선택하여 드릴다운 ▸",
        ["— 선택 —"] + [label_for(c, names) for c in df["code"]],
        key=f"pick_{select_key}_{prefix}",
    )
    if pick != "— 선택 —":
        code = pick.split("  ·")[0].strip()
        if st.session_state.get(select_key) != code:
            st.session_state[select_key] = code
            if select_key == "hs2":
                st.session_state.hs4 = st.session_state.hs6 = None
            elif select_key == "hs4":
                st.session_state.hs6 = None
            st.rerun()


if __name__ == "__main__":
    main()

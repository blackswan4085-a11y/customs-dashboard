"""SQLite 집계 쿼리. pandas 없이 순수 SQL + 파이썬으로 계산.

trade_raw(period, hs_code, item_name, exp_dlr, imp_dlr, exp_wgt, imp_wgt, bal_pay)
를 SUBSTR + SUM 으로 HS 2/4/6 자리로 집계한다.

지표 정의:
  YoY = (당월 - 전년동월) / 전년동월 * 100
  QoQ = 월→분기 합산 후 (당분기 - 전분기) / 전분기 * 100
"""
from __future__ import annotations

import sqlite3
from typing import Any


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    """관련기업/메타 테이블이 없으면 생성 (collector 가 이미 만들지만 안전차원)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS related_companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hs_code TEXT NOT NULL,
            hs_level INTEGER NOT NULL,
            company TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS collection_meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.commit()


def get_meta(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        rows = conn.execute("SELECT key, value FROM collection_meta").fetchall()
        return {r["key"]: r["value"] for r in rows}
    except sqlite3.OperationalError:
        return {}


def latest_month(conn: sqlite3.Connection) -> str | None:
    meta = get_meta(conn)
    if meta.get("latest_month"):
        return meta["latest_month"]
    row = conn.execute("SELECT MAX(period) AS p FROM trade_raw").fetchone()
    return row["p"] if row and row["p"] else None


def level_summary(
    conn: sqlite3.Connection, prefix: str, level: int, period: str
) -> list[dict[str, Any]]:
    """prefix 하위의 level 자리 그룹을 특정 월 기준 수출금액 내림차순으로 반환."""
    sql = f"""
        SELECT SUBSTR(hs_code, 1, {level}) AS code,
               SUM(exp_dlr) AS exp_dlr,
               SUM(imp_dlr) AS imp_dlr
        FROM trade_raw
        WHERE period = ? AND hs_code LIKE ?
        GROUP BY code
        ORDER BY exp_dlr DESC
    """
    rows = conn.execute(sql, (period, prefix + "%")).fetchall()
    out = []
    for r in rows:
        exp, imp = r["exp_dlr"] or 0, r["imp_dlr"] or 0
        out.append(
            {"code": r["code"], "exp_dlr": exp, "imp_dlr": imp, "bal": exp - imp}
        )
    return out


def representative_names(conn: sqlite3.Connection, level: int) -> dict[str, str]:
    """각 level 코드에서 교역액 최대 10자리 품목명을 대표명으로."""
    sql = f"""
        WITH agg AS (
            SELECT SUBSTR(hs_code,1,{level}) AS code, item_name,
                   SUM(exp_dlr + imp_dlr) AS vol
            FROM trade_raw
            GROUP BY code, item_name
        ),
        ranked AS (
            SELECT code, item_name,
                   ROW_NUMBER() OVER (PARTITION BY code ORDER BY vol DESC) AS rn
            FROM agg
        )
        SELECT code, item_name FROM ranked WHERE rn = 1
    """
    rows = conn.execute(sql).fetchall()
    return {r["code"]: r["item_name"] for r in rows}


def name_for(conn: sqlite3.Connection, prefix: str) -> str:
    """단일 코드의 대표 품목명."""
    row = conn.execute(
        """
        SELECT item_name FROM trade_raw
        WHERE hs_code LIKE ?
        GROUP BY item_name
        ORDER BY SUM(exp_dlr + imp_dlr) DESC
        LIMIT 1
        """,
        (prefix + "%",),
    ).fetchone()
    return row["item_name"] if row else ""


def monthly_series(conn: sqlite3.Connection, prefix: str) -> list[dict[str, Any]]:
    """prefix 의 월별 수출/수입 합계 시계열 (오름차순)."""
    sql = """
        SELECT period,
               SUM(exp_dlr) AS exp_dlr,
               SUM(imp_dlr) AS imp_dlr
        FROM trade_raw
        WHERE hs_code LIKE ?
        GROUP BY period
        ORDER BY period
    """
    rows = conn.execute(sql, (prefix + "%",)).fetchall()
    return [
        {
            "period": r["period"],
            "exp_dlr": r["exp_dlr"] or 0,
            "imp_dlr": r["imp_dlr"] or 0,
        }
        for r in rows
    ]


def all_series_by_level(conn: sqlite3.Connection, level: int) -> dict[str, list[dict]]:
    """레벨의 모든 코드에 대한 월별 시계열을 단일 쿼리로 계산.

    반환: {code: [{period, exp_dlr, imp_dlr}, ...(오름차순)]}
    """
    sql = f"""
        SELECT SUBSTR(hs_code,1,{level}) AS code, period,
               SUM(exp_dlr) AS exp_dlr, SUM(imp_dlr) AS imp_dlr
        FROM trade_raw
        GROUP BY code, period
        ORDER BY code, period
    """
    out: dict[str, list[dict]] = {}
    for r in conn.execute(sql):
        out.setdefault(r["code"], []).append(
            {"period": r["period"], "exp_dlr": r["exp_dlr"] or 0, "imp_dlr": r["imp_dlr"] or 0}
        )
    return out


def all_companies(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """hs_code 별 관련기업 매핑."""
    out: dict[str, list[dict]] = {}
    for r in conn.execute(
        "SELECT id, hs_code, company, note, created_at FROM related_companies ORDER BY created_at"
    ):
        out.setdefault(r["hs_code"], []).append(
            {"id": r["id"], "company": r["company"], "note": r["note"], "created_at": r["created_at"]}
        )
    return out


# ----------------------------- 지표 계산 -----------------------------
def compute_yoy(series: list[dict], field: str) -> list[dict]:
    """각 월에 대해 전년동월 대비 증감률(%)을 붙여 반환."""
    by_period = {row["period"]: row[field] for row in series}
    out = []
    for row in series:
        p = row["period"]
        y, m = int(p[:4]), int(p[4:])
        prev_key = f"{y-1:04d}{m:02d}"
        prev = by_period.get(prev_key)
        cur = row[field]
        yoy = None
        if prev not in (None, 0):
            yoy = (cur - prev) / prev * 100
        out.append({"period": p, "value": cur, "yoy": yoy})
    return out


def compute_quarterly(series: list[dict], field: str) -> list[dict]:
    """월 시계열을 분기 합산으로 변환하고 QoQ(%)를 계산."""
    buckets: dict[tuple[int, int], int] = {}
    for row in series:
        p = row["period"]
        y, m = int(p[:4]), int(p[4:])
        q = (m - 1) // 3 + 1
        buckets[(y, q)] = buckets.get((y, q), 0) + row[field]
    keys = sorted(buckets.keys())
    out = []
    prev_val = None
    for (y, q) in keys:
        val = buckets[(y, q)]
        qoq = None
        if prev_val not in (None, 0):
            qoq = (val - prev_val) / prev_val * 100
        out.append({"label": f"{y} Q{q}", "value": val, "qoq": qoq})
        prev_val = val
    return out


# ----------------------------- 관련 기업 -----------------------------
def list_companies(conn: sqlite3.Connection, hs_code: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, company, note, created_at FROM related_companies WHERE hs_code = ? ORDER BY created_at",
        (hs_code,),
    ).fetchall()
    return [dict(r) for r in rows]


def add_company(
    conn: sqlite3.Connection, hs_code: str, hs_level: int, company: str, note: str, created_at: str
) -> None:
    conn.execute(
        "INSERT INTO related_companies (hs_code, hs_level, company, note, created_at) VALUES (?,?,?,?,?)",
        (hs_code, hs_level, company, note, created_at),
    )
    conn.commit()


def delete_company(conn: sqlite3.Connection, cid: int) -> None:
    conn.execute("DELETE FROM related_companies WHERE id = ?", (cid,))
    conn.commit()

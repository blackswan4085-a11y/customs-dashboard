"""관세청 품목별 수출입실적 수집기.

최신 가용 월을 탐지한 뒤, 그 달 기준 과거 60개월(5년)을 월별로 전량 호출하여
10자리 원본(trade_raw)을 SQLite(data/trade.db)에 저장한다.

- API: https://apis.data.go.kr/1220000/Itemtrade/getItemtradeList
- 월별 hsSgn="" 호출 = 해당 월 전체 10자리 품목 반환 (API는 집계하지 않음)
- 총계행(year='총계', hsCode='-')은 제외
- resultCode != '00' 또는 네트워크 오류 시 재시도
"""
import datetime as dt
import os
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET

import requests

BASE = "https://apis.data.go.kr/1220000/Itemtrade/getItemtradeList"
HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "data", "trade.db")
MONTHS = 60  # 과거 5년
MAX_RETRIES = 3
RETRY_WAIT = 3  # 초
REQUEST_WAIT = 0.3  # 호출 간 간격(초), TPS 완화


def load_api_key():
    key = os.environ.get("CUSTOMS_API_KEY")
    if key:
        return key
    env_path = os.path.join(HERE, ".env")
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("CUSTOMS_API_KEY="):
                return line.split("=", 1)[1]
    raise RuntimeError("CUSTOMS_API_KEY not found in environment or .env")


def init_db(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_raw (
            period      TEXT NOT NULL,   -- YYYYMM
            hs_code     TEXT NOT NULL,   -- 10자리
            item_name   TEXT,            -- statKor (10자리 품목명)
            exp_dlr     INTEGER,
            imp_dlr     INTEGER,
            exp_wgt     INTEGER,
            imp_wgt     INTEGER,
            bal_pay     INTEGER,
            PRIMARY KEY (period, hs_code)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS related_companies (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            hs_code     TEXT NOT NULL,
            hs_level    INTEGER NOT NULL,
            company     TEXT NOT NULL,
            note        TEXT,
            created_at  TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS collection_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_period ON trade_raw(period)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_hs ON trade_raw(hs_code)")
    conn.commit()


def to_int(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        try:
            return int(float(text))
        except (TypeError, ValueError):
            return 0


def fetch_month(key, yymm):
    """한 달 전체 품목 반환. (resultCode, rows) 반환. rows는 dict 리스트."""
    params = {
        "serviceKey": key,
        "strtYymm": yymm,
        "endYymm": yymm,
        "hsSgn": "",
    }
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(BASE, params=params, timeout=120)
            root = ET.fromstring(r.text)
            result_code = root.findtext(".//resultCode")
            if result_code != "00":
                msg = root.findtext(".//resultMsg")
                last_err = f"resultCode={result_code} msg={msg}"
                time.sleep(RETRY_WAIT)
                continue
            rows = []
            for it in root.findall(".//item"):
                hs = (it.findtext("hsCode") or "").strip()
                year = (it.findtext("year") or "").strip()
                if hs in ("", "-") or year == "총계":
                    continue  # 총계행 제외
                rows.append(
                    {
                        "period": yymm,
                        "hs_code": hs,
                        "item_name": (it.findtext("statKor") or "").strip(),
                        "exp_dlr": to_int(it.findtext("expDlr")),
                        "imp_dlr": to_int(it.findtext("impDlr")),
                        "exp_wgt": to_int(it.findtext("expWgt")),
                        "imp_wgt": to_int(it.findtext("impWgt")),
                        "bal_pay": to_int(it.findtext("balPayments")),
                    }
                )
            return result_code, rows
        except (requests.RequestException, ET.ParseError) as e:
            last_err = str(e)
            time.sleep(RETRY_WAIT)
    raise RuntimeError(f"[{yymm}] failed after {MAX_RETRIES} retries: {last_err}")


def detect_latest_month(key):
    today = dt.date.today()
    y, m = today.year, today.month
    for _ in range(24):
        yymm = f"{y:04d}{m:02d}"
        _, rows = fetch_month(key, yymm)
        if rows:
            return yymm
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    raise RuntimeError("No available month found in last 24 months")


def month_range(latest_yymm, count):
    """latest 포함 과거 count개월의 YYYYMM 리스트 (오름차순)."""
    y, m = int(latest_yymm[:4]), int(latest_yymm[4:])
    months = []
    for _ in range(count):
        months.append(f"{y:04d}{m:02d}")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return sorted(months)


def save_rows(conn, rows):
    conn.executemany(
        """
        INSERT OR REPLACE INTO trade_raw
            (period, hs_code, item_name, exp_dlr, imp_dlr, exp_wgt, imp_wgt, bal_pay)
        VALUES
            (:period, :hs_code, :item_name, :exp_dlr, :imp_dlr, :exp_wgt, :imp_wgt, :bal_pay)
        """,
        rows,
    )
    conn.commit()


def run_collection(progress=None, incremental=True, db_path=None):
    """데이터 수집 실행.

    progress: callable(dict) — 진행상황 콜백 (서버 업데이트 버튼용)
    incremental: True 면 이미 저장된 가장 최신월 이후만 수집 (기존 데이터 유지).
                 신규 월이 없으면 최신월 1개는 재수집(갱신)한다.
    반환: 요약 dict
    """
    def emit(**kw):
        if progress:
            progress(kw)

    key = load_api_key()
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    init_db(conn)

    emit(phase="detect", message="최신 가용 월 탐지 중...")
    latest = detect_latest_month(key)
    emit(phase="detected", latest=latest, message=f"최신 가용 월: {latest}")

    full_months = month_range(latest, MONTHS)

    # 증분: 기존 최신월 이후(+기존 최신월 1개 갱신)만
    existing = conn.execute("SELECT MAX(period) AS p FROM trade_raw").fetchone()[0]
    if incremental and existing:
        months = [m for m in full_months if m >= existing]
    else:
        months = full_months

    emit(phase="start", total=len(months), first=months[0], last=months[-1],
         message=f"수집 대상 {months[0]}~{months[-1]} ({len(months)}개월)")

    total = 0
    for i, yymm in enumerate(months, 1):
        _, rows = fetch_month(key, yymm)
        save_rows(conn, rows)
        total += len(rows)
        emit(phase="month", index=i, total=len(months), period=yymm,
             rows=len(rows), cumulative=total,
             message=f"[{i}/{len(months)}] {yymm}: {len(rows)} rows")
        time.sleep(REQUEST_WAIT)

    for k, v in (
        ("latest_month", latest),
        ("collected_at", dt.datetime.now().isoformat(timespec="seconds")),
        ("range", f"{full_months[0]}-{full_months[-1]}"),
    ):
        conn.execute("INSERT OR REPLACE INTO collection_meta(key, value) VALUES (?, ?)", (k, v))
    conn.commit()

    cnt = conn.execute("SELECT COUNT(*) FROM trade_raw").fetchone()[0]
    mn = conn.execute("SELECT MIN(period), MAX(period) FROM trade_raw").fetchone()
    conn.close()
    summary = {"latest_month": latest, "months_fetched": len(months),
               "rows_added": total, "total_rows": cnt,
               "range": f"{mn[0]}~{mn[1]}"}
    emit(phase="done", **summary, message=f"완료. 총 {cnt} 행, 기간 {mn[0]}~{mn[1]}")
    return summary


def main():
    # CLI 는 전체 재수집 (기존 동작 유지)
    run_collection(progress=lambda e: print("  "+e.get("message","")), incremental=False)


if __name__ == "__main__":
    main()

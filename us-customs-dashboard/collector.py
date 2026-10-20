"""미국 Census International Trade API 수집기.

U.S. Census Bureau 의 월별 수출입 통계를 HS2 단위로 전량 수집하여
국가별 원본(trade_raw)을 SQLite(data/ustrade.db)에 저장한다.

- API(수입): https://api.census.gov/data/timeseries/intltrade/imports/hs
- API(수출): https://api.census.gov/data/timeseries/intltrade/exports/hs
- 응답 형식: JSON 2차원 배열 (첫 행이 헤더)
- time 범위 필터(`time=from YYYY-MM to YYYY-MM`)로 60개월을 한 번에 수신 가능
  → HS2 코드(약 98개) × {수입,수출} = 약 196회 호출로 전량 수집

수집 전략(전체 국가):
1. 최신 가용 월 탐지
2. HS2 코드 목록 확보 (CTY_CODE=- 전체합계로 1개월 호출)
3. 각 HS2 코드마다 수입/수출을 국가별 × 60개월 범위로 호출하여 저장

HS4/HS6 은 서버에서 드릴다운 시 온디맨드로 수집한다(collect_detail 참조).
"""
import datetime as dt
import os
import sqlite3
import time

import requests

IMPORTS_URL = "https://api.census.gov/data/timeseries/intltrade/imports/hs"
EXPORTS_URL = "https://api.census.gov/data/timeseries/intltrade/exports/hs"

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "data", "ustrade.db")
MONTHS = 60  # 과거 5년
MAX_RETRIES = 3
RETRY_WAIT = 3  # 초
REQUEST_WAIT = 0.2  # 호출 간 간격(초)

# 흐름(flow)별 Census 변수 이름 매핑.
# 수출은 품목코드 변수가 E_COMMODITY, 금액이 ALL_VAL_MO.
# 수입은 품목코드 변수가 I_COMMODITY, 금액이 GEN_VAL_MO.
FLOW = {
    "imp": {
        "url": IMPORTS_URL,
        "commodity": "I_COMMODITY",
        "sdesc": "I_COMMODITY_SDESC",
        "value": "GEN_VAL_MO",
    },
    "exp": {
        "url": EXPORTS_URL,
        "commodity": "E_COMMODITY",
        "sdesc": "E_COMMODITY_SDESC",
        "value": "ALL_VAL_MO",
    },
}


def load_api_key():
    key = os.environ.get("CENSUS_API_KEY")
    if key:
        return key
    env_path = os.path.join(HERE, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("CENSUS_API_KEY="):
                    return line.split("=", 1)[1]
    raise RuntimeError("CENSUS_API_KEY not found in environment or .env")


def init_db(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_raw (
            flow      TEXT NOT NULL,     -- 'imp' | 'exp'
            period    TEXT NOT NULL,     -- YYYY-MM
            cty_code  TEXT NOT NULL,     -- Census 국가코드
            cty_name  TEXT,              -- 국가명
            hs_code   TEXT NOT NULL,     -- HS 코드 (2/4/6자리)
            hs_level  INTEGER NOT NULL,  -- 2 | 4 | 6
            descr     TEXT,              -- 품목 간이설명(SDESC)
            value     INTEGER,           -- 금액(USD)
            PRIMARY KEY (flow, period, cty_code, hs_code)
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
        "CREATE TABLE IF NOT EXISTS collection_meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_period ON trade_raw(period)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_hs ON trade_raw(hs_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_cty ON trade_raw(cty_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_level ON trade_raw(hs_level)")
    conn.commit()


def to_int(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        try:
            return int(float(text))
        except (TypeError, ValueError):
            return 0


def _get(key, url, params):
    """Census API 호출 → 레코드(dict) 리스트. 재시도 포함.

    응답은 [[header...], [row...], ...] 형태의 JSON 배열.
    빈 결과면 빈 리스트, 오류면 재시도 후 예외.
    """
    params = dict(params)
    params["key"] = key
    last_err = None
    for _ in range(MAX_RETRIES):
        try:
            r = requests.get(url, params=params, timeout=120)
            if r.status_code == 204 or not r.text.strip():
                return []
            # Census 오류는 본문이 "error: ..." 텍스트로 올 수 있음
            if r.text.lstrip().startswith("error"):
                last_err = r.text.strip()[:200]
                time.sleep(RETRY_WAIT)
                continue
            data = r.json()
            if not data or len(data) < 2:
                return []
            header = data[0]
            return [dict(zip(header, row)) for row in data[1:]]
        except (requests.RequestException, ValueError) as e:
            last_err = str(e)
            time.sleep(RETRY_WAIT)
    raise RuntimeError(f"API 호출 실패 ({url}): {last_err}")


def month_str(d: dt.date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def add_months(year: int, month: int, delta: int):
    idx = (year * 12 + (month - 1)) + delta
    return idx // 12, idx % 12 + 1


def detect_latest_month(key) -> str:
    """최신 가용 월 탐지. 전체합계(CTY_CODE=-) HS2=85 로 가벼운 조회."""
    today = dt.date.today()
    y, m = today.year, today.month
    for _ in range(24):
        yymm = f"{y:04d}-{m:02d}"
        rows = _get(key, IMPORTS_URL, {
            "get": FLOW["imp"]["value"],
            "COMM_LVL": "HS2",
            "I_COMMODITY": "85",
            "CTY_CODE": "-",
            "time": yymm,
        })
        if rows:
            return yymm
        y, m = add_months(y, m, -1)
    raise RuntimeError("최근 24개월 내 가용 데이터를 찾지 못했습니다.")


def hs2_codes(key, period) -> list[tuple[str, str]]:
    """가용 HS2 코드 목록 [(code, sdesc), ...]. 수입 전체합계 1개월로 조회."""
    f = FLOW["imp"]
    rows = _get(key, f["url"], {
        "get": f"{f['commodity']},{f['sdesc']},{f['value']}",
        "COMM_LVL": "HS2",
        "CTY_CODE": "-",
        "time": period,
    })
    seen = {}
    for r in rows:
        code = (r.get(f["commodity"]) or "").strip()
        if code and code not in seen:
            seen[code] = (r.get(f["sdesc"]) or "").strip()
    return sorted(seen.items())


def time_range(start: str, end: str) -> str:
    return f"from {start} to {end}"


def _rows_from(resp, flow, level):
    """Census 응답(dict 리스트) → trade_raw 저장용 dict 리스트."""
    f = FLOW[flow]
    out = []
    for r in resp:
        code = (r.get(f["commodity"]) or "").strip()
        cty = (r.get("CTY_CODE") or "").strip()
        if not code or not cty:
            continue
        out.append({
            "flow": flow,
            "period": (r.get("time") or "").strip(),
            "cty_code": cty,
            "cty_name": (r.get("CTY_NAME") or "").strip(),
            "hs_code": code,
            "hs_level": level,
            "descr": (r.get(f["sdesc"]) or "").strip(),
            "value": to_int(r.get(f["value"])),
        })
    return out


def fetch_level(key, flow, hs_code, level, start, end, country=None):
    """HS2 전량 수집용: 정확히 'level' 자리 코드(hs_code)를 국가별 × 기간범위로 조회.

    HS2 조회(level==len(hs_code))는 Census 에서 빠르다. 국가 차원 전체 포함.
    """
    f = FLOW[flow]
    params = {
        "get": f"{f['commodity']},{f['sdesc']},{f['value']},CTY_CODE,CTY_NAME",
        "COMM_LVL": f"HS{level}",
        "time": time_range(start, end),
    }
    if hs_code:
        params[f["commodity"]] = hs_code
    if country:
        params["CTY_CODE"] = country
    return _rows_from(_get(key, f["url"], params), flow, level)


def fetch_sublevel_month(key, flow, hs_prefix, level, period):
    """드릴다운 목록용: 특정 월의 'level' 자리 전체합계(CTY=-)를 받아 prefix 로 필터.

    Census 는 '상위코드 지정+하위레벨' 이나 '와일드카드+기간범위' 조합이 매우 느려
    타임아웃이 난다. 반대로 'COMM_LVL=HSn + CTY_CODE=- + 단일 월' 전량 조회는
    수 초 내 응답하므로, 그걸 받아 클라이언트에서 prefix 로 거른다.
    """
    f = FLOW[flow]
    params = {
        "get": f"{f['commodity']},{f['sdesc']},{f['value']},CTY_CODE,CTY_NAME",
        "COMM_LVL": f"HS{level}",
        "CTY_CODE": "-",
        "time": period,
    }
    resp = _get(key, f["url"], params)
    rows = _rows_from(resp, flow, level)
    return [r for r in rows if r["hs_code"].startswith(hs_prefix)]


def fetch_code_series(key, flow, hs_code, level, start, end):
    """드릴다운 시계열용: 단일 HS 코드의 전체합계(CTY=-) 기간범위 시계열.

    단일 코드 + 범위 + '-' 조합은 2~3초로 빠르다.
    """
    f = FLOW[flow]
    params = {
        "get": f"{f['commodity']},{f['sdesc']},{f['value']},CTY_CODE,CTY_NAME",
        "COMM_LVL": f"HS{level}",
        f["commodity"]: hs_code,
        "CTY_CODE": "-",
        "time": time_range(start, end),
    }
    return _rows_from(_get(key, f["url"], params), flow, level)


def save_rows(conn, rows):
    if not rows:
        return
    conn.executemany(
        """
        INSERT OR REPLACE INTO trade_raw
            (flow, period, cty_code, cty_name, hs_code, hs_level, descr, value)
        VALUES
            (:flow, :period, :cty_code, :cty_name, :hs_code, :hs_level, :descr, :value)
        """,
        rows,
    )
    conn.commit()


def have_sublevel(conn, flow, hs_prefix, sublevel) -> bool:
    """flow 별 hs_prefix 하위 sublevel 자리(전체합계 '-') 데이터가 이미 있는지."""
    row = conn.execute(
        "SELECT 1 FROM trade_raw WHERE flow=? AND hs_level=? AND cty_code='-' AND hs_code LIKE ? LIMIT 1",
        (flow, sublevel, hs_prefix + "%"),
    ).fetchone()
    return row is not None


def have_series(conn, flow, hs_code, level) -> bool:
    """flow 별 단일 코드(전체합계 '-') 시계열이 이미 있는지(여러 달)."""
    n = conn.execute(
        "SELECT COUNT(DISTINCT period) FROM trade_raw WHERE flow=? AND hs_level=? AND cty_code='-' AND hs_code=?",
        (flow, level, hs_code),
    ).fetchone()[0]
    return n > 1


def collect_detail(conn, key, hs_prefix, sublevel, months=MONTHS, force=False):
    """드릴다운 온디맨드 수집(전체합계 '-' 기준, 양방향).

    1) hs_prefix 자체 시계열(단일코드 × 60개월)  — 상세 차트용
    2) hs_prefix 하위 sublevel 목록(최근월 전량 → prefix 필터) — 드릴다운 표용

    둘 다 CTY_CODE='-' (전체 국가 합계) 로만 받는다(속도/안정성).
    이미 있으면 건너뛴다. 반환: 저장된 행 수.
    """
    latest = latest_in_db(conn) or detect_latest_month(key)
    y, m = int(latest[:4]), int(latest[5:])
    sy, sm = add_months(y, m, -(months - 1))
    start = f"{sy:04d}-{sm:02d}"
    plevel = len(hs_prefix)
    total = 0

    for flow in ("imp", "exp"):
        # 1) prefix 자체 시계열 (HS2 는 기본 수집에서 '-' 시계열이 이미 있음 → 보통 skip)
        if force or not have_series(conn, flow, hs_prefix, plevel):
            rows = fetch_code_series(key, flow, hs_prefix, plevel, start, latest)
            rows = [r for r in rows if r["hs_code"] == hs_prefix]
            save_rows(conn, rows)
            total += len(rows)
            time.sleep(REQUEST_WAIT)

        # 2) 하위 레벨 목록(최근월)
        if sublevel and sublevel <= 6 and (force or not have_sublevel(conn, flow, hs_prefix, sublevel)):
            rows = fetch_sublevel_month(key, flow, hs_prefix, sublevel, latest)
            save_rows(conn, rows)
            total += len(rows)
            time.sleep(REQUEST_WAIT)

    return total


def have_country_breakdown(conn, flow, hs_code, period) -> bool:
    """특정 코드/월의 국가별(개별국가) 데이터가 이미 있는지."""
    row = conn.execute(
        "SELECT 1 FROM trade_raw WHERE flow=? AND hs_code=? AND period=? "
        "AND cty_code<>'-' AND cty_code NOT LIKE '0%' AND cty_code NOT LIKE '%X%' LIMIT 1",
        (flow, hs_code, period),
    ).fetchone()
    return row is not None


def collect_country_breakdown(conn, key, hs_code, period=None, force=False):
    """온디맨드: 특정 HS 코드의 '국가별' 데이터를 최근월 1개월만 수집(양방향).

    기본 수집은 전체합산('-')만 받으므로, 상세 화면의 국가별 순위가 필요할 때
    이 함수로 해당 품목의 개별 국가 데이터를 그때그때 받는다.
    단일 코드 × 1개월 × 전체국가는 수 초 내로 응답한다.
    반환: 저장된 행 수.
    """
    period = period or latest_in_db(conn) or detect_latest_month(key)
    level = len(hs_code)
    total = 0
    for flow in ("imp", "exp"):
        if not force and have_country_breakdown(conn, flow, hs_code, period):
            continue
        rows = fetch_level(key, flow, hs_code, level, period, period)
        rows = [r for r in rows if r["hs_code"] == hs_code]
        save_rows(conn, rows)
        total += len(rows)
        time.sleep(REQUEST_WAIT)
    return total


def latest_in_db(conn):
    try:
        row = conn.execute("SELECT MAX(period) AS p FROM trade_raw").fetchone()
        return row[0] if row and row[0] else None
    except sqlite3.OperationalError:
        return None


def run_collection(progress=None, incremental=True, db_path=None, months=MONTHS):
    """HS2 전량 수집(전체 국가, 수입·수출).

    progress: callable(dict) — 진행상황 콜백
    incremental: True 면 기존 최신월 이후만 재수집(증분). HS2 전량은
                 범위 호출이므로 증분이어도 start 를 기존 최신월로 좁혀 호출량을 줄인다.
    반환: 요약 dict.
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

    y, m = int(latest[:4]), int(latest[5:])
    sy, sm = add_months(y, m, -(months - 1))
    full_start = f"{sy:04d}-{sm:02d}"

    existing = latest_in_db(conn)
    if incremental and existing and existing < latest:
        start = existing  # 기존 최신월부터 갱신
    elif incremental and existing:
        start = existing  # 신규월 없음 → 최신월만 재수집
    else:
        start = full_start

    emit(phase="hs2list", message="HS2 품목 목록 조회 중...")
    codes = hs2_codes(key, latest)
    emit(phase="start", total=len(codes) * 2, first=start, last=latest,
         message=f"HS2 {len(codes)}종 × 수입/수출 수집 ({start}~{latest})")

    total = 0
    step = 0
    for code, _sdesc in codes:
        for flow in ("imp", "exp"):
            step += 1
            # 전체 국가 합산('-')만 수집 → 품목당 1줄 × 개월수 (한국판 수준으로 가벼움).
            # 국가별 세부는 상세 화면에서 필요 시 온디맨드(collect_country_breakdown).
            rows = fetch_code_series(key, flow, code, 2, start, latest)
            rows = [r for r in rows if r["hs_code"] == code]
            save_rows(conn, rows)
            total += len(rows)
            emit(phase="step", index=step, total=len(codes) * 2,
                 hs=code, flow=flow, rows=len(rows), cumulative=total,
                 message=f"[{step}/{len(codes) * 2}] HS{code} {flow}: {len(rows)} rows")
            time.sleep(REQUEST_WAIT)

    for k, v in (
        ("latest_month", latest),
        ("collected_at", dt.datetime.now().isoformat(timespec="seconds")),
        ("range", f"{full_start}~{latest}"),
        ("months", str(months)),
    ):
        conn.execute("INSERT OR REPLACE INTO collection_meta(key, value) VALUES (?, ?)", (k, v))
    conn.commit()

    cnt = conn.execute("SELECT COUNT(*) FROM trade_raw WHERE hs_level=2").fetchone()[0]
    mn = conn.execute("SELECT MIN(period), MAX(period) FROM trade_raw").fetchone()
    conn.close()
    summary = {"latest_month": latest, "steps": step, "rows_added": total,
               "hs2_rows": cnt, "range": f"{mn[0]}~{mn[1]}"}
    emit(phase="done", **summary,
         message=f"완료. HS2 {cnt} 행, 기간 {mn[0]}~{mn[1]}")
    return summary


def main():
    run_collection(progress=lambda e: print("  " + e.get("message", "")), incremental=False)


if __name__ == "__main__":
    main()

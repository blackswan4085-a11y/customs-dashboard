# 일본 재무성 무역통계(e-Stat) 수출입 대시보드

일본 재무성 普通貿易統計(e-Stat)을 사용해 HS 품목 코드별 일본 수출입 실적을
**2자리 → 4자리 → 6자리** 로 드릴다운하며 분석하는 웹 대시보드입니다.
한국 `customs-dashboard`(관세청판) / `us-customs-dashboard`(미국 Census판)와
**동일한 아키텍처·UI** 를 일본 데이터 특성에 맞춰 이식했습니다.

**서버·대시보드는 파이썬 표준 라이브러리만 사용합니다(외부 웹 프레임워크·차트 라이브러리 없음).**
`http.server` 기반 서버 + 바닐라 HTML/JS, 차트는 **순수 인라인 SVG**로 그립니다.
데이터 수집(`collector.py`)에만 `requests` 가 필요합니다.

## 핵심: 두 통계표를 분리 사용

일본 무역통계에는 두 종류의 표가 있고, 각각 쓰임이 다릅니다.

| 표 | 내용 | 제공 방식 | 용도 |
|---|---|---|---|
| **統計品別表** | HS 품목 × **전 세계 합계** | CSV 파일 | 기본 수집(세계 합계) |
| **品別国別表** | HS 품목 × **상대국별** | getStatsData API(DB) | 국가별 순위(온디맨드) |

미국 Census 의 `CTY_CODE=-`(전체 합산)에 해당하는 것이 일본에서는 **統計品別表** 입니다.
국가별 229개를 받아 직접 합산할 필요 없이, **일본 정부가 계산해 둔 전 세계 합계 CSV**를
그대로 받습니다. 덕분에 기본 수집이 가볍습니다(연도당 CSV 1개).

## 데이터 흐름

1. **기본 수집(`collector.py`)**: `getDataCatalog` API 로 統計品別表(수출/수입)의
   연도별 CSV 다운로드 URL 을 얻어 내려받습니다. 각 CSV 는 그 해 1~12월 월별 금액을
   담고 있으며, 일본 9자리 통계품목을 **HS6/HS4/HS2 로 집계**해 SQLite(`trade_hs`)에 저장합니다.
   - 5년치 = 수출 5 + 수입 5 = **약 10개 CSV**, 전체 수집 **약 1분** 내외.
   - CSV 컬럼: `Exp or Imp, Year, HS, Value-Year, Value-Jan..Dec` (금액 단위: **천 엔**).
2. **국가별 순위(온디맨드)**: HS6 상세를 열 때, 品別国別表(`getStatsData`)로 그 품목의
   상대국별 금액을 받아 수입/수출 TOP 15 를 계산합니다(`trade_country`). 한 번 받으면 캐시됩니다.

> **품목명**: 統計品別表 CSV 에는 품목 라벨이 없어, HS 는 국제 공통 분류인 점을 이용해
> 표준 HS2/HS4 영문명(`jp_customs/hsnames.py`)으로 표기합니다. HS6 는 상위 HS4 명으로 폴백.
> **국가명**: e-Stat area 코드 → 일본어 국가명(`jp_customs/areanames.py`).

## 주요 기능

- **종합 개요**: 총수출/총수입/무역수지(+YoY·QoQ), 전체 월간 추이, 수출 TOP 10, HS2 순위표
- **드릴다운**: HS 2 → 4 → 6 (표 클릭, 브레드크럼으로 상위 이동) — 전부 사전 수집돼 즉시
- **5개년 월간 추이**: 선택 HS 코드의 월별 수출·수입 SVG 라인차트(십자선·배지·툴팁)
- **YoY / QoQ 지표**: 전년동월·전분기 대비 증감률
- **국가별 순위**: HS6 상세에서 상대국 수입/수출 TOP 15 (품별국별표 온디맨드)
- **관련 기업 관리**: HS 코드별 관련 기업 입력·삭제 (SQLite 영구 저장)

> 금액 단위는 **천 엔**이며, 화면에는 兆/億/万엔으로 환산 표기합니다.

## 설치 & 실행

### 1. appId 설정

[e-Stat API 기능](https://www.e-stat.go.jp/api/)에서 발급받은 appId 를 `.env` 에 저장합니다.

```
ESTAT_APP_ID=발급받은_appId
```

> `.env` 와 `*.db`, `*.csv` 는 `.gitignore` 로 제외됩니다.
> (또는 `config.yaml` 의 `estat.app_id` 에 직접 지정할 수도 있습니다.)

### 2. 의존성 설치 (수집용)

```bash
uv venv && uv pip install -e .
# 또는: python -m venv .venv && source .venv/bin/activate && pip install -e .
```

### 3. 데이터 수집

```bash
python run.py --collect      # 또는: python collector.py
```

統計品別表 CSV 약 10개를 받아 `data/jptrade.db` 를 생성합니다(약 1분).

### 4. 대시보드 실행

```bash
python run.py                # http://localhost:8002 자동 오픈
python run.py --port 8080    # 포트 지정
python run.py --no-open      # 브라우저 자동 오픈 끄기
```

## 파일 구성

```
jp-customs-dashboard/
├── run.py                 # 진입점 (--port/--no-open/--collect)
├── config.yaml            # 포트/수집 설정
├── collector.py           # e-Stat 수집기 (統計品別表 CSV + 品別国別表 온디맨드)
├── jp_customs/
│   ├── config.py          # 설정 로딩
│   ├── db.py              # SQLite 집계/지표 계산
│   ├── hsnames.py         # HS2/HS4 영문 품목명 사전
│   ├── areanames.py       # e-Stat area 코드 → 국가명 사전
│   ├── report.py          # HTML 셸 + 클라이언트 JS/CSS + SVG 차트
│   └── server.py          # http.server 기반 서버 + JSON API 라우팅
├── data/jptrade.db        # 수집 데이터 (git 제외)
└── .env                   # appId (git 제외)
```

## 설정 (`config.yaml`)

| 항목 | 설명 |
|---|---|
| `port` | 서버 포트 (기본 8002) |
| `auto_open` | 서버 실행 시 브라우저 자동 오픈 |
| `estat.app_id` | appId(지정 시 `.env` 보다 우선) |
| `estat.years` | 수집할 과거 연수 (기본 5) |
| `estat.db_path` | SQLite 경로 (기본 `data/jptrade.db`) |

## DB 스키마

- `trade_hs(flow, period, hs_code, hs_level, value)` — 세계 합계(천엔), 레벨별 사전 집계
- `trade_country(flow, period, hs_code, cty_code, cty_name, value)` — 국가별(온디맨드)
- `related_companies(...)` / `collection_meta(key, value)`

## 보안 참고

작업/공유 후에는 e-Stat 에서 **appId 재발급**을 권장합니다.

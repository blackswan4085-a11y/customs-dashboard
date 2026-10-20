# 미국 Census 수출입통계 대시보드

U.S. Census Bureau 의 International Trade API(`timeseries/intltrade/{imports,exports}/hs`)를
사용해 HS 품목 코드별 미국 수출입 실적을 **2자리 → 4자리 → 6자리** 로 드릴다운하며
분석하는 웹 대시보드입니다. 한국 [`customs-dashboard`](https://github.com/blackswan4085-a11y/customs-dashboard)
(관세청판)와 **동일한 아키텍처·UI** 를 미국 데이터 특성에 맞춰 이식했습니다.

**서버·대시보드는 파이썬 표준 라이브러리만 사용합니다(외부 웹 프레임워크·차트 라이브러리 없음).**
`http.server` 기반 서버 + 바닐라 HTML/JS, 차트는 **순수 인라인 SVG**로 그립니다.
데이터 수집(`collector.py`)에만 `requests` 가 필요합니다.

## 한국판과의 차이 (미국 데이터 특성)

| 항목 | 한국(관세청) | 미국(Census) |
|---|---|---|
| 기관/API | 관세청 `Itemtrade` (XML) | U.S. Census `timeseries/intltrade` (JSON 배열) |
| 수출/수입 | 한 응답에 함께 | 엔드포인트 분리(`exports`/`imports`) |
| **국가 구분** | 없음(전체 집계) | **있음** (`CTY_CODE`) — 상단 국가 선택 드롭다운 |
| 금액 변수 | `expDlr`/`impDlr` | `ALL_VAL_MO`(수출) / `GEN_VAL_MO`(수입) |
| 품목명 | `statKor` | `E_/I_COMMODITY_SDESC` (API가 직접 제공) |
| 기간 포맷 | `YYYYMM` | `YYYY-MM` |
| 기간 조회 | 월별 호출 | `time=from..to` 범위 필터 지원 |

### 미국판 고유 기능
- **국가 선택**: 상단 드롭다운에서 특정 국가(예: KOREA, CHINA, MEXICO)를 고르면 그 국가와의
  미국 교역만 기준으로 개요·시계열이 다시 그려집니다. (기본값: 전체 국가)
- **국가별 순위**: HS 코드 상세 화면에서 해당 품목을 미국에 가장 많이 수출/수입하는
  상대국 TOP 15 를 가로 막대로 표시합니다.

## 주요 기능

- **종합 개요(첫 화면)**: 총수출/총수입/무역수지 + YoY·QoQ 히어로 카드, 전체 월간 추이,
  수출 상위 품목 TOP 10 랭킹, HS 2자리 순위표(행마다 수출 YoY/QoQ 포함)
- **드릴다운**: HS 2 → 4 → 6 자리로 표의 행을 클릭해 단계별 탐색 (상단 브레드크럼으로 상위 이동)
- **5개년 월간 추이**: 선택한 HS 코드의 월별 수출·수입 추이 SVG 라인차트
  (주식 차트식 십자선 + x축 날짜/y축 값 배지 + hover 툴팁)
- **YoY / QoQ 지표**
  - YoY = (당월 − 전년동월) / 전년동월 × 100
  - QoQ = 월→분기 합산 후 (당분기 − 전분기) / 전분기 × 100 (상승=빨강/하락=파랑)
- **데이터 업데이트 버튼**: 헤더의 `⟳ 데이터 업데이트` 로 Census API에서 최신 데이터를 증분 수집
- **관련 기업 관리**: HS 코드별 관련 기업을 직접 입력·삭제 (SQLite 파일에 영구 저장)

## 데이터 흐름 (전체 국가 전략)

Census API 는 **국가 × HS × 월** 단위로 데이터를 제공하며, HS 레벨(2/4/6)을 `COMM_LVL` 로
직접 지정할 수 있습니다. 전체 국가 × 전체 HS2 × 전체 기간을 한 번에 요청하면 응답이
너무 커 타임아웃되므로, 다음과 같이 분할합니다.

1. **기본 수집(`collector.py`)**: HS2 코드(약 98종)마다 수입/수출을 각각
   `time=from..to` 범위(60개월) + 전체 국가로 호출(약 196회). `trade_raw` 에 저장.
2. **드릴다운(온디맨드)**: HS4/HS6 은 데이터량이 커 서버가 **필요할 때** 수집합니다.
   - 하위 목록: `COMM_LVL=HSn + CTY_CODE=-`(전체합계) + 최근월 1개월 전량 조회 후 prefix 필터
   - 상세 시계열: 선택한 단일 코드 × 60개월 범위(전체합계)
   이 두 조합만 Census 에서 빠르게(수 초) 응답합니다.

> **집계 코드 처리**: Census 는 개별 국가 외에 지역/경제권 집계(EU/OECD/APEC/NAFTA,
> 대륙 `nXXX` 등)와 전체합계(`-`)도 반환합니다. 전체 금액은 `-`(TOTAL) 행만 사용해
> 이중 합산을 방지하고, 국가 목록·순위에서는 개별 국가만 노출합니다.

## 설치 & 실행

### 1. API 키 설정

[Census Developers](https://api.census.gov/data/key_signup.html)에서 무료 발급받은 키를
`.env` 에 저장합니다.

```
CENSUS_API_KEY=발급받은_키
```

> `.env` 와 `*.db` 는 `.gitignore` 로 제외됩니다. 키·데이터는 커밋되지 않습니다.
> (또는 `config.yaml` 의 `census.api_key` 에 직접 지정할 수도 있습니다.)

### 2. 의존성 설치 (수집용)

```bash
# uv 사용 (권장)
uv venv && uv pip install -e .

# 또는 pip
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

> 서버 실행만 한다면 추가 설치 없이 파이썬 표준 라이브러리로 동작합니다.
> `requests` 는 데이터 수집 단계에만 필요합니다.

### 3. 데이터 수집

```bash
python run.py --collect      # 또는: python collector.py
```

최신월 탐지 후 HS2 전량(약 196회 호출)을 수집합니다. `data/ustrade.db` 가 생성됩니다.

### 4. 대시보드 실행

```bash
python run.py                # http://localhost:8001 자동 오픈
python run.py --port 8080    # 포트 지정
python run.py --no-open      # 브라우저 자동 오픈 끄기
```

## CLI 옵션 (`run.py`)

| 옵션 | 설명 |
|---|---|
| `--port N` | 서버 포트 (기본 `config.yaml` 의 `port`, 8001) |
| `--no-open` | 브라우저 자동 오픈 끄기 |
| `--collect` | API 데이터 수집 후 종료 |
| `--config PATH` | 설정 파일 경로 |

## 파일 구성

```
us-customs-dashboard/
├── run.py                 # 진입점 (argparse: --port/--no-open/--collect)
├── config.yaml            # 포트/수집 설정
├── collector.py           # Census API 수집기 → data/ustrade.db
├── us_customs/
│   ├── config.py          # 설정 로딩 (PyYAML 없이도 동작)
│   ├── db.py              # SQLite 집계/지표 계산 (pandas 없음)
│   ├── report.py          # HTML 셸 + 클라이언트 JS/CSS + SVG 차트
│   └── server.py          # http.server 기반 서버 + JSON API 라우팅
├── data/ustrade.db        # 수집 데이터 (git 제외)
└── .env                   # API 키 (git 제외)
```

## 설정 (`config.yaml`)

| 항목 | 설명 |
|---|---|
| `port` | 서버 포트 (기본 8001) |
| `auto_open` | 서버 실행 시 브라우저 자동 오픈 |
| `census.api_key` | API 키(지정 시 `.env` 보다 우선) |
| `census.months` | 수집할 과거 개월 수 (기본 60 = 5년) |
| `census.db_path` | SQLite 경로 (기본 `data/ustrade.db`) |

## DB 스키마

- `trade_raw(flow, period, cty_code, cty_name, hs_code, hs_level, descr, value)`
  — 흐름('imp'/'exp') × 국가 × HS(2/4/6) × 월 금액
- `related_companies(id, hs_code, hs_level, company, note, created_at)` — 사용자 입력 관련 기업
- `collection_meta(key, value)` — 수집 메타 (최신월, 수집시각, 범위)

## 보안 참고

작업/공유 후에는 Census Developers 에서 **API 키 재발급**을 권장합니다.

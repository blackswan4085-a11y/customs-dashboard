# 관세청 수출입통계 대시보드

관세청 수출입 무역통계 Open API(`Itemtrade/getItemtradeList`)를 사용해 HS 품목 코드별
수출입 실적을 **2자리 → 4자리 → 6자리** 로 드릴다운하며 분석하는 웹 대시보드입니다.

**서버·대시보드는 파이썬 표준 라이브러리만 사용합니다(외부 웹 프레임워크·차트 라이브러리 없음).**
`http.server` 기반 서버 + 바닐라 HTML/JS, 차트는 **순수 인라인 SVG**로 그립니다.
데이터 수집(`collector.py`)에만 `requests` 가 필요합니다.

## 주요 기능

- **HS 2자리 정렬표**: 최신 가용 월 기준 수출 금액 내림차순 순위표 (컬럼 클릭 정렬)
- **드릴다운**: HS 2 → 4 → 6 자리로 표의 행을 클릭해 단계별 탐색 (상단 브레드크럼으로 상위 이동)
- **5개년 월간 추이**: 선택한 HS 코드의 월별 수출·수입 추이 SVG 라인차트
- **YoY / QoQ 지표**
  - YoY = (당월 − 전년동월) / 전년동월 × 100  (수출·수입 그룹 막대)
  - QoQ = 월→분기 합산 후 (당분기 − 전분기) / 전분기 × 100  (수출 막대)
- **관련 기업 관리**: HS 코드별 관련 기업을 직접 입력·삭제 (SQLite 파일에 영구 저장)

## 데이터 흐름

관세청 API는 **집계를 제공하지 않고 항상 10자리 품목 단위**로 반환하며,
국가 구분이 없는 전체 집계 API입니다. 조회 기간은 1년 이내 제약이 있어 **월 단위로 호출**합니다.

1. `collector.py` 가 최신 가용 월을 자동 탐지한 뒤, 그 달 기준 **과거 60개월(5년)** 을
   월별로 전량(`hsSgn=""`) 호출하여 10자리 원본을 SQLite(`data/trade.db`)에 저장합니다.
2. `run.py`(서버)가 조회 시점에 `SUBSTR(hs_code, 1, 2/4/6)` + `SUM()` 으로 직접 집계해
   JSON API로 제공하고, 브라우저의 바닐라 JS가 표와 SVG 차트를 그립니다.

> HS 분류명: API 응답에는 2/4/6자리 분류명이 없으므로, 각 레벨에서 교역액이 가장 큰
> 10자리 품목명(`statKor`)을 대표명으로 자동 생성해 표시합니다.

## 설치 & 실행

### 1. API 키 설정

[공공데이터포털](https://www.data.go.kr)에서 발급받은 서비스 키를 `.env` 에 저장합니다.

```
CUSTOMS_API_KEY=발급받은_서비스_키
```

> `.env` 와 `*.db` 는 `.gitignore` 로 제외됩니다. 키·데이터는 커밋되지 않습니다.
> (또는 `config.yaml` 의 `customs.api_key` 에 직접 지정할 수도 있습니다.)

### 2. 의존성 설치 (수집용)

```bash
# uv 사용 (권장)
uv venv
uv pip install -e .

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

최신월 탐지 후 60개월을 수집합니다(약 2~3분, 60회 호출). `data/trade.db` 가 생성됩니다.

### 4. 대시보드 실행

```bash
python run.py                # http://localhost:8000 자동 오픈
python run.py --port 8080    # 포트 지정
python run.py --no-open      # 브라우저 자동 오픈 끄기
```

### 5. (선택) 정적 HTML 내보내기

서버 없이 열람 가능한 단일 HTML을 생성합니다. 관련기업 편집은 비활성화되며,
용량 문제로 **HS 6자리 상세 차트는 제외**합니다(드릴다운 표는 포함).

```bash
python run.py --static       # output/index.html 생성
```

## CLI 옵션 (`run.py`)

| 옵션 | 설명 |
|---|---|
| `--port N` | 서버 포트 (기본 `config.yaml` 의 `port`, 8000) |
| `--no-open` | 브라우저 자동 오픈 끄기 |
| `--collect` | API 데이터 수집 후 종료 |
| `--static` | 서버 없이 정적 HTML 1개 생성 |
| `--config PATH` | 설정 파일 경로 |

## 파일 구성

```
customs-dashboard/
├── run.py                 # 진입점 (argparse: --port/--no-open/--collect/--static)
├── config.yaml            # 포트/수집 설정
├── collector.py           # API 수집기 → data/trade.db
├── customs/
│   ├── config.py          # 설정 로딩 (PyYAML 없이도 동작)
│   ├── db.py              # SQLite 집계/지표 계산 (pandas 없음)
│   ├── report.py          # HTML 셸 + 클라이언트 JS/CSS + SVG 차트
│   └── server.py          # http.server 기반 서버 + JSON API 라우팅
├── data/trade.db          # 수집 데이터 (git 제외)
└── .env                   # API 키 (git 제외)
```

## 설정 (`config.yaml`)

| 항목 | 설명 |
|---|---|
| `port` | 서버 포트 (기본 8000) |
| `auto_open` | 서버 실행 시 브라우저 자동 오픈 |
| `customs.api_key` | API 키(지정 시 `.env` 보다 우선) |
| `customs.months` | 수집할 과거 개월 수 (기본 60 = 5년) |
| `customs.db_path` | SQLite 경로 (기본 `data/trade.db`) |

## DB 스키마

- `trade_raw(period, hs_code, item_name, exp_dlr, imp_dlr, exp_wgt, imp_wgt, bal_pay)` — 10자리 원본
- `related_companies(id, hs_code, hs_level, company, note, created_at)` — 사용자 입력 관련 기업
- `collection_meta(key, value)` — 수집 메타 (최신월, 수집시각, 범위)

## 보안 참고

작업/공유 후에는 공공데이터포털에서 **API 키 재발급**을 권장합니다.

# 관세청 수출입통계 대시보드

관세청 수출입 무역통계 Open API(`Itemtrade/getItemtradeList`)를 사용해 HS 품목 코드별
수출입 실적을 **2자리 → 4자리 → 6자리** 로 드릴다운하며 분석하는 Streamlit 대시보드입니다.

## 주요 기능

- **HS 2자리 정렬표**: 최신 가용 월 기준 수출 금액 내림차순 순위표
- **드릴다운**: HS 2 → 4 → 6 자리로 단계별 탐색 (사이드바 또는 표에서 선택)
- **5개년 월간 추이**: 선택한 HS 코드의 월별 수출·수입 추이 차트
- **YoY / QoQ 지표**
  - YoY = (당월 − 전년동월) / 전년동월 × 100
  - QoQ = 월→분기 합산 후 (당분기 − 전분기) / 전분기 × 100
- **관련 기업 관리**: HS 코드별 관련 기업을 직접 입력·삭제 (SQLite 영구 저장)

## 데이터 흐름

관세청 API는 **집계를 제공하지 않고 항상 10자리 품목 단위**로 반환하며,
국가 구분이 없는 전체 집계 API입니다. 조회 기간은 1년 이내 제약이 있어 **월 단위로 호출**합니다.

1. `collector.py` 가 최신 가용 월을 자동 탐지한 뒤, 그 달 기준 **과거 60개월(5년)** 을
   월별로 전량(`hsSgn=""`) 호출하여 10자리 원본을 SQLite(`data/trade.db`)에 저장합니다.
   (총계행 `year='총계'` 은 제외)
2. `app.py`(대시보드)가 조회 시점에 `SUBSTR(hs_code, 1, 2/4/6)` + `SUM()` 으로 직접 집계합니다.

> HS 분류명: API 응답에는 2/4/6자리 분류명이 없으므로, 각 레벨에서 교역액이 가장 큰
> 10자리 품목명(`statKor`)을 대표명으로 자동 생성해 표시합니다.

## 설치 & 실행

### 1. API 키 설정

[공공데이터포털](https://www.data.go.kr)에서 발급받은 서비스 키를 `.env` 에 저장합니다.

```
CUSTOMS_API_KEY=발급받은_서비스_키
```

> `.env` 와 `*.db` 는 `.gitignore` 로 제외됩니다. 키는 커밋되지 않습니다.

### 2. 의존성 설치

```bash
# uv 사용 (권장)
uv venv
uv pip install -e .

# 또는 pip
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

### 3. 데이터 수집

```bash
.venv/bin/python collector.py
```

최신월 탐지 후 60개월을 수집합니다(약 2~3분, 60회 호출). `data/trade.db` 가 생성됩니다.

### 4. 대시보드 실행

```bash
.venv/bin/streamlit run app.py
```

브라우저에서 `http://localhost:8501` 접속.

## 파일 구성

| 파일 | 설명 |
|------|------|
| `collector.py` | API 수집기 (최신월 탐지 + 60개월 적재) |
| `app.py` | Streamlit 대시보드 |
| `data/trade.db` | 수집 데이터 (SQLite, git 제외) |
| `.env` | API 키 (git 제외) |

## DB 스키마

- `trade_raw(period, hs_code, item_name, exp_dlr, imp_dlr, exp_wgt, imp_wgt, bal_pay)` — 10자리 원본
- `related_companies(id, hs_code, hs_level, company, note, created_at)` — 사용자 입력 관련 기업
- `collection_meta(key, value)` — 수집 메타 (최신월, 수집시각, 범위)

## 보안 참고

작업/공유 후에는 공공데이터포털에서 **API 키 재발급**을 권장합니다.

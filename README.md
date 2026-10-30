# 🏠 서울 아파트 시세 인사이트 대시보드

국토교통부 아파트 매매 실거래가 데이터를 수집·정제해 DB에 적재하고, LLM으로 지역별 인사이트를 자동 생성해 대시보드로 보여주는 풀스택 서비스입니다.

## 아키텍처

```
[공공데이터포털 API] ──XML──▶ collector ─▶ cleaner ─▶ loader ─▶ [PostgreSQL]
                                                                    │
                       [LLM API] ◀── insight_service ◀── aggregator ◀┘
                                           │
                                           ▼
                              [FastAPI] ◀── HTTP ── [Streamlit 대시보드]
```

| 단계 | 파일 | 역할 |
| --- | --- | --- |
| 수집 | `services/collector.py` | API 호출, 페이지네이션, 재시도(지수 백오프), 오류 응답 감지 |
| 정제 | `services/cleaner.py` | 금액·날짜·면적 변환, 평당가 계산, 해제거래·결측 제거 |
| 적재 | `services/loader.py` | ORM 저장, 단지 자동 등록, 중복 거래 방지 |
| 집계 | `services/aggregator.py` | 월별/구별 통계, LLM 입력용 숫자 요약 |
| 인사이트 | `services/insight_service.py` + `llm_client.py` | 프롬프트 구성 → LLM 호출 → 저장 (실패 시 규칙 기반 대체) |
| 파이프라인 | `services/pipeline.py` | 지역×월 단위 실행, 실패 격리, `pipeline_log` 기록 |

## ERD

```mermaid
erDiagram
    region ||--o{ apartment : has
    apartment ||--o{ transaction : has
    region |o--o{ insight : "about (NULL=서울 전체)"
    region { int id PK; string lawd_cd UK; string sido; string sigungu }
    apartment { int id PK; int region_id FK; string name; string dong; int build_year }
    transaction { int id PK; int apartment_id FK; date deal_date; int price; float area; int floor; float price_per_pyeong }
    insight { int id PK; int region_id FK; date period_start; date period_end; text summary_text; string source; string prompt_version; datetime created_at }
    pipeline_log { int id PK; string lawd_cd; string deal_ym; string status; int fetched_rows; int inserted_rows; text error_msg; datetime run_at }
```

- `transaction`은 (단지, 계약일, 면적, 층, 가격)에 UNIQUE 제약 → 같은 달을 다시 수집해도 중복되지 않습니다.
- `insight.source`는 `llm` 또는 `fallback`, `prompt_version`으로 프롬프트 실험 결과를 비교할 수 있습니다.

## 빠른 시작

### 0) 준비
1. [공공데이터포털](https://www.data.go.kr)에서 **국토교통부_아파트 매매 실거래가 상세 자료** 활용신청
2. `cp .env.example .env` 후 `DATA_GO_KR_SERVICE_KEY`(Decoding 키)와 LLM 정보 입력

### 1) Docker로 실행 (권장)
```bash
docker compose up -d --build
docker compose exec backend python -m app.cli collect --start 202501 --end 202509
docker compose exec backend python -m app.cli insight --months 6
```
- API 문서: http://localhost:8000/docs
- 대시보드: http://localhost:8501

### 2) 로컬 실행 (SQLite)
```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m app.cli collect --start 202501 --end 202509 --lawd 11680   # 강남구만 빠르게
python -m app.cli insight --months 6
uvicorn app.main:app --reload

# 새 터미널
cd dashboard && pip install -r requirements.txt && streamlit run app.py
```

> 💡 **API 키 승인 전에 화면부터 만들고 싶다면** `python -m app.cli seed-sample`로 가짜 데이터("샘플단지")를 넣을 수 있습니다. 실제 수집 전에는 DB 파일(`realestate.db`)을 지우고 시작하세요.

## CLI

| 명령 | 설명 |
| --- | --- |
| `collect --start YYYYMM --end YYYYMM [--lawd 코드...]` | 실거래가 수집 (생략 시 서울 25개 구) |
| `insight --months N [--lawd 코드...]` | 서울 전체 + 구별 인사이트 생성 |
| `run --months N` | 최근 N개월 수집 + 인사이트 (cron 등 스케줄러용) |
| `seed-sample` | UI 개발용 가짜 데이터 |

## 주요 API

| Method | Path | 설명 |
| --- | --- | --- |
| GET | `/regions` | 서울 25개 구 |
| GET | `/transactions?lawd_cd=&limit=&offset=` | 최근 거래 목록 |
| GET | `/stats/monthly?lawd_cd=&months=` | 월별 평균가·평당가·거래량 |
| GET | `/stats/regions?months=` | 구별 비교 |
| GET | `/insights/latest?lawd_cd=` | 최신 인사이트 |
| POST | `/insights/generate` | 인사이트 생성 `{"lawd_cd": "11680", "months": 6}` |
| POST | `/pipeline/collect` | 수집 실행 |
| GET | `/pipeline/logs?only_failed=true` | 수집 이력·실패 내역 |

## 예외 처리·로깅

- 단계별 예외(`CollectError`, `LLMError` 등) → 원인 구분이 쉬움
- 지역×월 작업 하나가 실패해도 나머지는 계속, 실패는 `pipeline_log`에 저장
- API 일시 오류는 최대 3회 재시도, 인증키 오류(`SERVICE_KEY_IS_NOT_REGISTERED_ERROR` 등)는 메시지 그대로 기록
- LLM 실패 시 규칙 기반 요약으로 대체 → 대시보드가 비지 않음
- 로그: 콘솔 + `logs/app.log` (5MB 회전)

## LLM 연동 메모

`llm_client.py`는 **OpenAI 호환 `/chat/completions` 형식**을 가정합니다. 과정에서 제공된 LLM API 형식이 다르면 `LLMClient.chat()`만 수정하면 됩니다. LLM에는 원본 거래가 아니라 **집계된 숫자(JSON)만** 전달하고, 제공된 숫자 외 내용은 지어내지 않도록 프롬프트로 제한합니다.

## 테스트

```bash
cd backend && pytest -q
```
실제 API 없이 Mock으로 수집·정제·적재·중복방지·인사이트·API 응답을 검증합니다.

## 알려진 데이터 특성

- 실거래 신고 기한이 계약 후 30일이라 **최근 1~2개월 거래량은 적게 집계**될 수 있습니다. 매달 지난 2개월치를 다시 수집하세요 (중복은 자동 방지).
- 해제(취소)된 거래(`cdealType=O`)는 제외합니다.

# API demo (FastAPI + container)

> **호스팅 브라우저 데모는 별도 경로**: 클릭 한 번으로 동작하는 라이브
> 데모는 Streamlit-on-HF-Spaces입니다 →
> [`docs/operations/deployment.md#hugging-face-spaces`](./deployment.md#hugging-face-spaces).
> 본 문서는 프로그래매틱 FastAPI surface를 다룹니다.

이 페이지는 issue #75 에서 추가된 **리뷰어용 데모 표면**을
문서화한다. CLI 평가(evaluation) 흐름과는 의도적으로 분리되어 있다:

| Flow | Entry point | What it's for |
|---|---|---|
| **CLI eval** | `scripts/build_index.py`, `app.py`, `eval/run_eval.py` | 재현 가능한 측정, ablation, 벤치마크 리포트. 진실의 출처. |
| **API demo** | `api/main.py` (this doc) | 명령을 이어붙이지 않고도 리뷰어가 HTTP 로 시스템을 찔러볼 수 있게 함. |

API 는 인덱스를 스스로 빌드하지 않는다; 디스크에 준비된 것을 로드해
`rag_core.run_rag_query` 를 세 개의 작은 엔드포인트 뒤에 감싼다.

## 엔드포인트

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Readiness probe. 인덱스가 로드되면 200, 아니면 503. `chunk_count`, `doc_count`, `default_pipeline` 보고. |
| `GET` | `/pipelines` | `POST /query` 가 받는 파이프라인 preset 목록 + 설정된 기본값. |
| `POST` | `/query` | RAG 쿼리 한 건 실행. body 는 `app.py` 의 CLI flag 와 일치. 응답은 raw `run_rag_query` dict — `outputs/answer.json` 이 가졌을 것과 같은 형태. |
| `GET` | `/docs` | FastAPI 내장 Swagger UI (자동 생성). |

### `POST /query` body

```json
{
  "query": "기관 A의 보안 통제 요구사항은?",
  "pipeline": "agentic_full",        // optional
  "top_k": 8,                         // optional
  "retrieval_mode": "flat",           // optional: "flat" | "hierarchical"
  "context_entities": ["기관 A"],    // optional, for follow-up turns
  "conversation_state": null          // optional, pass back the prior response's value
}
```

`query` 만 필수다. 응답은 grounded
answer / citation 계약을 보존한다 — 스키마 세부사항은 `docs/agentic/answer-policy.md` 와
`docs/eval/citation-grounding-eval.md` 를 참조하라.

## 로컬 시작 (Docker 없이)

```bash
make index          # builds data/index from eval/fixtures/smoke_rfp/raw (one-time)
make api            # uvicorn on :8000 with --reload
```

그다음:

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/query \
  -H 'content-type: application/json' \
  -d '{"query":"기관 A와 기관 B의 AI 요구사항 차이 알려줘"}'
```

## 컨테이너 시작 (단일 명령)

```bash
make api-docker
# equivalent to:
#   docker build -t bidmate-demo .
#   docker run --rm -p 8000:8000 bidmate-demo
```

`docker-entrypoint.sh` 는 컨테이너 안의 `data/index/index.json` 을
확인하고, 첫 시작 시 hashing embedding 백엔드(네트워크 불필요)를 사용해
`eval/fixtures/smoke_rfp/raw` 로부터 빌드한다. 이후 시작은
기존 인덱스를 재사용한다.

실행 간 인덱스를 영속화하려면 호스트 볼륨을 마운트한다:

```bash
docker run --rm -p 8000:8000 -v "$(pwd)/data/index:/app/data/index" bidmate-demo
```

## 구성

| Env var | Default | Purpose |
|---|---|---|
| `BIDMATE_INDEX_DIR` | `data/index` (local), `/app/data/index` (container) | API 가 `index.json` 을 찾는 위치. |
| `BIDMATE_DEFAULT_PIPELINE` | `agentic_full` | 요청이 `"pipeline"` 을 생략할 때 사용하는 파이프라인. 이름이 등록되지 않았으면 CLI 기본값으로 fallback. |
| `BIDMATE_API_HOST` / `BIDMATE_API_PORT` | `0.0.0.0` / `8000` | 컨테이너 entrypoint 바인딩. |
| `EMBEDDING_BACKEND` | `hashing` (container) | entrypoint 가 인덱스를 auto-build 할 때 `scripts/build_index.py` 로 전달됨. |

## 예상 산출물

성공적인 데모 실행은 다음을 생성한다:

- `:8000` 의 라이브 HTTP 서버(`/health` 가 200 반환).
- 컨테이너가 첫 시작 시 빌드했다면 `data/index/index.json`.
- `outputs/answer.json` 은 기록되지 않음 — API 는 답변을
  인라인으로 반환한다. 파일을 emit 하는 CLI 흐름에는 `make ask` / `app.py` 를 사용하라.

## 이 데모가 의도적으로 **하지 않는** 것

- 인증, rate limiting, persistence 레이어 없음 — 리뷰어용
  데모의 범위 밖.
- HTML UI 없음 — `/docs` 의 OpenAPI Swagger 페이지로 충분.
- multi-stage Docker 빌드 / 이미지 크기 최적화 없음 — 문제가 되면
  별도로 추적.
- 컨테이너는 `make eval` 이나 어떤 벤치마크도 실행하지 않음. 그것들은
  CLI 평가의 관심사이며 거기에 머문다.

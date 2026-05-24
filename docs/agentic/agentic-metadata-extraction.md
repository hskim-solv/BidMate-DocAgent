# Agentic Metadata Extraction (issue #180 / ADR 0017)

> **Status:** `ingestion.py` 에 additive `metadata["extracted"]`
> sidecar 로 연결됨. 기본 backend 는 `regex`(ADR 0001 불변식)다.
> LLM backend 는 API 키가 필요하며 `BIDMATE_METADATA_BACKEND` 를 통해
> opt-in 이다.

기존 regex / CSV 컬럼 passthrough 는 RFP 메타데이터(`agency`, `project`,
`budget`, 마감일)를 저렴하고 결정론적으로 채운다 — 이것이 기본값이며
변경 없이 출하된다. 이 모듈은 동일한 본문 텍스트를 읽어 tool / function
calling 으로 엄격한 8개 필드 JSON 페이로드를 반환하는 **additive**
LLM 기반 추출 경로를 추가한다. 두 경로는 같은 chunk 에 공존하며,
하위 소비자는 필드별로 어느 쪽을 신뢰할지 고를 수 있다.

## Schema

`rag_metadata_extraction.MetadataExtraction`(8개 필드):

| Field                 | Type           | Notes                                                |
|-----------------------|----------------|------------------------------------------------------|
| `agency`              | `str \| None`  | 발주 기관 short name (한글 가능).                    |
| `project_name`        | `str \| None`  | 사업명.                                              |
| `budget_amount`       | `float \| None`| 금액만 — `원` / `만원` / 쉼표 없음.                   |
| `budget_currency`     | `str \| None`  | ISO 4217 (한국 RFP 는 기본 KRW).                      |
| `deadline_iso`        | `str \| None`  | `YYYY-MM-DD`.                                        |
| `submission_date_iso` | `str \| None`  | `YYYY-MM-DD`.                                        |
| `contact_email`       | `str \| None`  | 본문 텍스트에서 매치된 첫 이메일.                     |
| `contact_name`        | `str \| None`  | 보수적 — regex 기준선은 이를 `None` 으로 둠.          |

tool schema(`rag_metadata_extraction.py` 의 `TOOL_DEFINITION`)는
`additionalProperties: false` 를 사용하므로 LLM 응답이 예기치 않은
필드를 chunk 메타데이터에 몰래 끼워 넣을 수 없다.

## Backends

`BIDMATE_METADATA_BACKEND` 로 전환:

| Backend                | Default | Deterministic | Network | Notes                                                                                       |
|------------------------|---------|---------------|---------|---------------------------------------------------------------------------------------------|
| `regex`                | ✅      | ✅            | —       | ADR 0001 불변식. CSV 컬럼 + 본문 텍스트의 이메일 regex 를 읽음.                              |
| `stub`                 | —       | ✅            | —       | `regex` 에 위임. 테스트용. `stub == regex` 를 bit 단위로 보장.                              |
| `anthropic_tool_use`   | —       | —             | yes     | Claude API(`extract_rfp_metadata` tool). `ANTHROPIC_API_KEY` 필요.                          |
| `openai_function_call` | —       | —             | yes     | OpenAI 호환(`BIDMATE_METADATA_API_KEY` + `BIDMATE_METADATA_MODEL` + `_BASE_URL`).           |

실패 처리: 어떤 backend 예외(SDK 부재, 키 부재, 잘못된 응답, 네트워크
오류)든 조용히 regex 기준선으로 fallback 한다. 파이프라인은 tool-use
오류로 메타데이터를 잃지 않는다.

## 연결(wire-up)

`ingestion.normalize_ingestion_row` 가 이음새(seam)다 — 성공적으로
인덱싱된 모든 행은 문서가 ingestion 경로를 떠나기 전에 추출된 sidecar 를
얻는다:

```python
document = {
    "doc_id": validation.doc_id,
    "title": clean_cell(row.get("사업명")) or Path(validation.file_name).stem,
    "agency": clean_cell(row.get("발주 기관")),
    "project": clean_cell(row.get("사업명")),
    "metadata": metadata,
    "sections": [{"heading": "본문", "text": text}],
    "source_path": str(validation.source_path),
}
document["metadata"]["extracted"] = extract_rfp_metadata(document).as_dict()
```

최상위 `agency` / `project` 필드는 의도적으로 손대지 않는다 — 이들은
answer/citation 계약(ADR 0003)과 metadata-first 검색에 투입되며,
파이프라인 중간에 LLM 값으로 재바인딩하면 public fixture smoke surface 의
결정론이 깨진다. LLM 값은 sidecar 에 두어 reviewer 가 필드별로 A/B
할 수 있게 한다.

## Eval ablation

`eval/config.yaml` 의 `full_llm_metadata` 행은 LLM backend 가 활성화된
상태로 빌드한 인덱스에 대해 표준 `agentic_full` 파이프라인을 실행한다.
추출이 *ingest* 시점에 일어나므로, 이 행은 인덱스가
`BIDMATE_METADATA_BACKEND=anthropic_tool_use`(또는
`openai_function_call`)로 빌드되었을 때만 의미가 있다. 기본 `regex`
backend 에서는 `full` 과 동일하다. latency 예산은 `full` 을 그대로
따른다 — query 당 latency 는 변하지 않고, 비용은 1회성 인덱스 빌드로
이동한다.

## 로컬에서 A/B 하는 법

```bash
# 1. Build a regex-extracted index (the default).
python scripts/build_index.py

# 2. Build an LLM-extracted index into a separate directory.
BIDMATE_METADATA_BACKEND=anthropic_tool_use \
ANTHROPIC_API_KEY=$YOUR_KEY \
BIDMATE_INDEX_DIR=data/index_llm_metadata \
  python scripts/build_index.py

# 3. Compare per-field extraction agreement on the two payloads
#    (script lives operator-side per ADR 0005; see issue #180
#    acceptance criteria for the per-field accuracy table).
```

필드별 정확도 표(`eval/fixtures/smoke_rfp/raw` + 비공개 100-doc 코퍼스에서 regex vs.
`anthropic_tool_use`)는 ADR 0005 에 따라 operator 측에서 캡처되며 여기에
커밋하지 않고 `reports/eval_summary.json` 델타로 표면화된다 — 비공개
코퍼스 행이 권위 있는 신호이며 절대 public 저장소에 들어가지 않는다.

## 실패 모드 & 에스컬레이션

| Symptom                                                       | Likely cause                                                                                      | Fix                                                                                  |
|---------------------------------------------------------------|---------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| `metadata["extracted"]` 가 regex 기준선과 동일               | backend env 미설정, SDK 부재, 또는 API 키가 비어 있음 — `extract_rfp_metadata` 가 fallback 됨.    | `BIDMATE_METADATA_BACKEND` + `ANTHROPIC_API_KEY` 확인 후 `build_index.py` 재실행.    |
| `anthropic_tool_use` 에서 인덱스 빌드가 느림                 | 문서당 Claude 호출 1회 — 의도된 설계. synthesis-prompt + tool schema 는 서버측 캐싱됨.            | ingest 를 1회 실행하고 `data/index` 재사용. query 당 latency 는 변하지 않음.         |
| 한국어 RFP 에서 필드별 정확도가 regex 보다 낮음              | 보수적 프롬프트 drift — LLM 은 필드를 지어내지 말고 *생략*해야 함.                                | `SYSTEM_PROMPT` 점검 후 다음 ADR follow-up 에서 대조(contrastive) 예시 추가.         |

## 관련 문서

- [ADR 0001 — preserve naive baseline](../adr/0001-preserve-naive-baseline.md)
- [ADR 0003 — structured answer / citation contract](../adr/0003-structured-answer-citation-contract.md)
- [ADR 0011 — LLM synthesis as additive ablation](../adr/0011-llm-synthesis-as-additive-ablation.md)
- [ADR 0017 — LLM metadata extraction as additive](../adr/0017-llm-metadata-extraction-additive.md)
- [`rag_metadata_extraction.py`](../../rag_metadata_extraction.py) — backends + tool schema
- [`ingestion.py`](../../ingestion.py) — 연결 이음새(wire-up seam)
- [`tests/test_ingestion_metadata_wireup_regression.py`](../../tests/test_ingestion_metadata_wireup_regression.py) — additive-contract 테스트 스위트

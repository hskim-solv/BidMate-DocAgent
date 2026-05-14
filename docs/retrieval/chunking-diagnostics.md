# Chunking diagnostics

## 목적
RFP 문서는 heading, 요구사항 목록, 제출조건 같은 구조가 검색 품질에 직접 영향을 준다. 이 저장소의 CLI 기본값은 naive baseline 재현을 위해 fixed-size chunking을 사용하고, section-aware metadata는 `--chunking_strategy auto` 또는 `section`으로 명시해 비교한다.

## 인덱스 schema
각 chunk에는 아래 진단 필드가 포함된다.

- `section_id` / `parent_section_id`: parent section과 child chunk를 연결한다.
- `section_path`: heading 계층을 보존한다. 공개 synthetic 문서는 1단계 heading을 사용한다.
- `chunk_seq_in_section`: 같은 parent section 안에서 child chunk 순서를 나타낸다 (1-indexed).
- `total_chunks_in_section`: 같은 parent section을 구성하는 child chunk의 총 수. issue #73 진단 필드 — `chunk_seq_in_section`과 함께 보면 "section을 N등분 중 M번째를 가져왔다"가 evidence 단계에서 바로 읽힌다.
- `chunking_strategy`: 실제 적용된 전략이다. 값은 `section` 또는 `fixed`이다.
- `regions` / `page_span`: visual parsing v2 입력에서만 포함되는 page/bbox 근거 위치 metadata다.

`index.json`의 `parent_sections`에는 parent section text와 metadata가 저장된다. visual parsing v2 문서라면 parent section에도 `regions`와 `page_span`이 보존된다. `build.chunking`에는 요청 전략, `chunk_max_chars`, overlap, 문서별 실제 전략, parent section 수, chunk 수가 기록된다.

## 동작 방식
baseline 인덱싱 명령은 다음 옵션과 같다.

```bash
python3 scripts/build_index.py \
  --input_dir data/raw \
  --output_dir data/index \
  --chunking_strategy fixed \
  --chunk_max_chars 520 \
  --chunk_overlap_sentences 1
```

- `fixed`: 문서 전체를 parent section으로 묶고 fixed-size child chunk를 만든다. 현재 CLI 기본값이며 `naive_baseline`의 기준 chunking이다.
- `auto`: 문서에 여러 section이 있거나 heading 구조가 있으면 `section`을 사용한다.
- `section`: section 경계를 강제로 유지한다.

질의 기본값은 `flat` retrieval이다. `--retrieval_mode hierarchical`은 child chunk를 먼저 점수화한 뒤 `parent_section_id` 기준으로 section text를 재조립해 evidence로 반환한다.

## 공개 synthetic 평가 결과
2026-04-30에 hashing embedding으로 동일 평가셋을 비교했다.

| Index strategy | Chunks | Parent sections | Retrieval | Accuracy | Groundedness | Citation | Abstention | Retry |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| auto | 13 | 13 | flat | 1.000 | 1.000 | 1.000 | 1.000 | 0.250 |
| auto | 13 | 13 | hierarchical | 1.000 | 1.000 | 1.000 | 1.000 | 0.250 |
| fixed | 4 | 4 | flat | 1.000 | 1.000 | 1.000 | 1.000 | 0.250 |
| fixed | 4 | 4 | hierarchical | 1.000 | 1.000 | 1.000 | 1.000 | 0.250 |

현재 공개 synthetic 문서는 짧고 heading이 명확해 fixed와 section-aware의 품질 차이가 지표로 드러나지 않는다. 대신 section-aware 인덱스는 chunk별 `section_path`와 parent-child 연결을 제공해 citation 해석과 긴 문서 디버깅에 더 유리하다.

## 해석 기준
- 기본 flat retrieval은 naive baseline과 agentic full pipeline 모두의 기본 retrieval mode다.
- hierarchical retrieval은 긴 section이 여러 child chunk로 나뉠 때 주변 문맥을 함께 확인하는 실험 옵션이다.
- 품질 비교는 `reports/eval_summary.json`의 `hierarchical` ablation run과 fixed/auto 임시 인덱스 평가 결과를 함께 본다.

## Chunk-boundary probe set (issue #73)

공개 synthetic 문서는 모두 1 chunk 안에 들어갈 만큼 짧아서 chunk-boundary 실패 모드(real-data taxonomy C3)를 자연스럽게 노출시키지 못한다. 이 격차를 메우기 위해 의도적으로 multi-chunk로 분할되는 probe fixture와 probe query를 별도로 추가했다.

**Probe fixture**: [`data/raw/rfp_agency_d_spectrometer_probe.json`](../../data/raw/rfp_agency_d_spectrometer_probe.json)
- 기관 D · 분광기 시스템 운영 (현존하지 않는 가상 기관 — 다른 eval case와 metadata 충돌 없음)
- 두 개 본문 section: 사업 개요 (~1100자) + 운영 자동화 세부 요구사항 (~750자)
- 기본 `max_chars=520` + `auto`/`section` 전략에서 각 section이 2 chunk로 분할되어 총 4 chunk 생성

**Probe queries** (`eval/config.yaml`, `hardcase_categories: chunk_boundary`):

| Probe id | 답이 위치한 chunk | 무엇을 잡는가 |
|---|---|---|
| `chunk_probe_external_audit_period` | section 1, chunk 2/2 | 첫 chunk 너머에 있는 fact retrieval — 첫 chunk의 metadata 토큰 밀도가 더 높아도 정답 chunk를 surface해야 함 |
| `chunk_probe_report_storage` | section 2, chunk 2/2 | section 경계를 넘는 retrieval — 섹션 1만 보지 않고 섹션 2를 골라야 함 |
| `chunk_probe_calibration_overlap` | section 1, chunk 1/2와 2/2 모두 (overlap region) | `DEFAULT_CHUNK_OVERLAP_SENTENCES=1` 메커니즘이 살아있는지 — overlap된 문장이 양쪽 chunk에서 retrieve 가능해야 함 |

**진단 활용**: 위 probe가 실패하면 `outputs/answer.json`의 `evidence[*].chunk_seq_in_section / total_chunks_in_section` 값을 본다.

- evidence가 비어있으면 → upstream retrieval 실패 (entity / metadata filter 문제, C1/C2)
- evidence는 있는데 `chunk_seq_in_section`이 정답 chunk 번호와 다르면 → chunking failure (C3) 자체
- 두 chunk가 같은 section에서 나왔는데 답에 필요한 chunk만 빠져 있으면 → top-k 산정 또는 score 균형 문제

이 분리는 real-data taxonomy C3의 "chunk boundary, masked by upstream miss"를 풀기 위한 첫 단계다. 자연 real-data에서는 이 두 실패 모드가 한 case에서 동시에 일어나기 쉬우므로 합성 probe로 분리해서 본다.

**확장 가이드**: 새 chunking 전략을 비교할 때 같은 probe set을 양쪽 인덱스에 돌리면 되돌아오는 `chunk_seq_in_section / total_chunks_in_section` 분포로 분할 정책 차이를 한눈에 본다. 답 텍스트를 변경하지 않은 채 수치 격차만 비교 가능하다는 점이 핵심이다.

## Strategy ablation (issue #62)

issue #73의 probe set이 갖춰진 뒤, chunking 전략 차이를 정량적으로 비교 가능해졌다. [`scripts/run_chunking_ablation.py`](../../scripts/run_chunking_ablation.py)는 동일 코퍼스(`data/raw/`)를 fixed / section / auto 세 전략으로 인덱싱한 뒤 chunk_boundary probe queries에 대한 top-evidence score를 표로 출력한다.

```bash
python3 scripts/run_chunking_ablation.py
```

**2026-05-11 측정 결과** (hashing backend, max_chars=520, overlap_sentences=1):

| Probe | fixed | section | auto |
|---|:---:|:---:|:---:|
| chunk_probe_external_audit_period | ✓ 0.7951 (2/3) | ✓ **0.849** (2/2) | ✓ **0.849** (2/2) |
| chunk_probe_report_storage | ✓ **0.7342** (3/3) | ✓ 0.7084 (1/2) | ✓ 0.7084 (1/2) |
| chunk_probe_calibration_overlap | ✓ 0.7913 (1/3) | ✓ **0.7995** (2/2) | ✓ **0.7995** (2/2) |
| **mean score Δ vs fixed** | — | **+0.012** | **+0.012** |

해석:

- **section / auto가 평균적으로 약 +0.012 score gain**. 3개 probe 중 2개에서 fixed보다 높은 top-score를 달성한다 (`external_audit`, `calibration_overlap`). 모든 probe가 정답 doc + 정답 term을 포함하는 evidence를 returns.
- **section은 자연 경계를 보존**한다. fixed는 한 doc을 단일 parent로 묶고 character cap에서 자른다. section은 heading 단위로 분리하므로 같은 사업의 여러 측면(개요 vs 자동화)이 다른 chunk로 분리된다.
- **report_storage probe는 fixed가 약간 더 좋다** (0.7342 vs 0.7084). 정답이 마지막 section의 후반부에 있을 때, fixed는 더 큰 chunk에 답이 포함되어 dense 매칭에 유리. section은 같은 답을 더 작은 chunk로 좁혀 노이즈는 줄지만 score는 약간 낮아진다.
- **현재 CLI 기본값은 `fixed`** ([ADR 0001](../adr/0001-preserve-naive-baseline.md) — naive_baseline 재현성). 위 결과는 multi-section RFP 코퍼스에서는 `--chunking_strategy auto`를 명시적으로 사용할 때 chunk_boundary slice 평균이 미약하게 개선됨을 시사한다. 명시적 옵션으로 두고 default는 변경하지 않는다 (베이스라인 보호).

**언제 strategy를 바꿀지 가이드**:
- 짧은 단일 section RFP가 다수일 때 → `fixed`가 합리적 (chunk 수 최소화)
- 긴 multi-section RFP가 많고 chunk_boundary slice 점수가 낮을 때 → `auto` 또는 `section`을 ablation으로 검증 후 선택
- 비교 ablation은 `python3 scripts/run_chunking_ablation.py` 한 번이면 충분

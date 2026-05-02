# Chunking diagnostics

## 목적
RFP 문서는 heading, 요구사항 목록, 제출조건 같은 구조가 검색 품질에 직접 영향을 준다. 이 저장소의 CLI 기본값은 naive baseline 재현을 위해 fixed-size chunking을 사용하고, section-aware metadata는 `--chunking_strategy auto` 또는 `section`으로 명시해 비교한다.

## 인덱스 schema
각 chunk에는 아래 진단 필드가 포함된다.

- `section_id` / `parent_section_id`: parent section과 child chunk를 연결한다.
- `section_path`: heading 계층을 보존한다. 공개 synthetic 문서는 1단계 heading을 사용한다.
- `chunk_seq_in_section`: 같은 parent section 안에서 child chunk 순서를 나타낸다.
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

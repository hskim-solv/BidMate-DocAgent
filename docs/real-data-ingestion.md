# PDF/HWP ingestion

이 문서는 비공개 PDF/HWP 원본과 `data_list.csv`를 로컬에서 인덱싱하는 v1 경로를 설명한다. 공개 baseline인 `data/raw` synthetic RFP 실행 흐름은 그대로 유지한다. 원본 PDF/image를 직접 파싱하는 v2 경로는 [`visual-ingestion-v2.md`](./visual-ingestion-v2.md)에 별도로 정리한다.

## 입력
- `data/data_list.csv`: `공고 번호`, `공고 차수`, `사업명`, `사업 금액`, `발주 기관`, 날짜 필드, `사업 요약`, `파일형식`, `파일명`, `텍스트` 컬럼을 사용한다. 컬럼 audits는 [pre-flight 검증](#pre-flight-검증-issue-51)으로 분리해 본다.
- `data/files/`: CSV의 `파일명`이 가리키는 PDF/HWP 파일 디렉터리다.
- v1은 PDF/HWP 바이너리를 직접 파싱하지 않고, CSV의 `텍스트` 컬럼을 본문 소스로 사용한다.
- `공고 번호`가 비어 있으면 파일명 stem을 `doc_id`로 사용하고, 이 사실은 metadata의 `doc_id_source`에 기록한다([canonical doc_id rule](#canonical-doc_id-rule)).

## Canonical doc_id rule
([이슈 #52](https://github.com/hskim-solv/BidMate-DocAgent/issues/52))

`ingestion.canonical_doc_id`가 모든 ingestion 경로에서 단일 규칙으로 doc_id를 생성한다.

1. **우선순위 1** — `공고 번호`가 비어 있지 않으면 `slug(공고 번호)[-slug(공고 차수)]`. 차수가 비어 있으면 공고 번호만 사용한다. 예: `20240001-0`, `20240003-1.0`.
2. **우선순위 2** — 공고 번호가 비어 있을 때만 `slug(파일명 stem)`. 이 사실은 `metadata.doc_id_source = "file_name"`에 기록되어 평가 단계에서 추적할 수 있다.
3. 두 경로 모두 NFC 정규화 + 내부 공백 collapse를 적용해, 같은 row가 OS·plaftform 차이와 무관하게 같은 doc_id를 만든다.
4. 둘 다 비어 있으면 row는 `missing_doc_id`로 실패 처리한다.

### 중복 doc_id 처리
같은 base doc_id가 두 row에서 발생하면 두 가지 정책 중 하나로 처리한다.

- `on_duplicate_doc_id="fail"` (기본): 두 번째 row는 `duplicate_doc_id`로 실패 처리되고, `record.duplicate_resolution`에 `first_seen_row`, `suggested_doc_id`(`<base>-2` 등)가 기록된다.
- `on_duplicate_doc_id="suffix"` (옵트인): 두 번째 row의 doc_id를 deterministic suffix(`<base>-2`, `<base>-3`, ...)로 자동 부여한다. 부여 결과는 row metadata에 `doc_id_resolution=suffix`, `doc_id_base=<base>`로 함께 기록되어 downstream 평가에서 추적 가능하다.

`build_index.py`는 v1에서 기본값(`fail`)으로 동작한다. 자동 suffix는 라이브러리 호출(`load_documents_from_metadata_csv(..., on_duplicate_doc_id="suffix")`)에서만 활성화된다.

## Pre-flight 검증 (issue #51)

인덱싱을 돌리기 전에 CSV 자체의 schema/필수값/중복을 먼저 잡고 싶을 때는 [`scripts/validate_data_list.py`](../scripts/validate_data_list.py)를 사용한다. 이 스크립트는 본문 텍스트는 로드하지 않고 row별 메타데이터만 audits한다.

```bash
python3 scripts/validate_data_list.py \
  --metadata_csv data/data_list.csv \
  --files_dir data/files \
  --output_path reports/real100/data_list_validation.json
```

- exit code: 0 = 통과 / 1 = row-level 실패 또는 schema 위반 / 2 = CLI/입력 오류.
- 출력 JSON에는 `summary.failure_reasons`, `summary.failure_examples`, `summary.duplicate_doc_ids`, `summary.blank_field_warnings`가 포함되어 있어 어떤 row가 어떤 사유로 실패했는지를 한눈에 본다.
- `--on_duplicate_doc_id suffix`를 주면 어떤 doc_id가 자동 suffix로 들어가는지 미리 미리보기 할 수 있다.

## 실행
```bash
python3 scripts/build_index.py \
  --metadata_csv data/data_list.csv \
  --files_dir data/files \
  --output_dir data/index \
  --embedding_backend hashing
```

## Optional real-data profile
공개 baseline은 `data/raw` synthetic 흐름으로 유지한다. 로컬에 비공개 원본과 `data_list.csv`가 있는 환경에서는 다음 smoke profile로 실데이터 end-to-end를 확인한다.

```bash
bash scripts/smoke_real.sh
```

기본값은 다음과 같다.
- 입력: `data/data_list.csv`, `data/files/`
- 인덱스: `data/index/real100/`
- 질의 출력: `outputs/real100/answer.json`
- 평가 출력: `reports/real100/eval_summary.json`
- 평가 설정: `eval/real_config.local.yaml`

`eval/real_config.local.yaml`이 없으면 인덱싱과 대표 질의까지만 실행하고, 실데이터 gold 평가를 건너뛴다. 새 환경에서는 `eval/real_config.example.yaml`을 복사해 로컬 expected doc id/term/target을 채운다(상세 가이드: [`docs/local-gold-authoring.md`](./local-gold-authoring.md)). `eval/*.local.yaml`, 실데이터 원본, 실데이터 산출물은 Git 추적 대상이 아니다.

## 출력
- `data/index/index.json`: 기존 RAG index schema를 유지하되, 문서와 chunk에 normalized metadata를 포함한다.
- `data/index/ingestion_report.json`: CSV row별 `indexed` 또는 `failed` 상태와 실패 사유를 기록한다.

optional profile을 사용할 때도 index schema는 동일하며, 기본 경로만 `data/index/real100/`로 분리한다.

## v1 / v2 비교
- v1 기본값은 `--ingestion_mode csv-text`이며, CSV의 `텍스트` 컬럼을 본문으로 사용한다.
- v2는 `--ingestion_mode visual`을 명시했을 때만 활성화된다.
- v2에서 PDF/image는 visual parser artifact를 만들고, HWP는 native visual parsing 대신 CSV 텍스트 fallback을 사용한다.
- HWP fallback 문서는 metadata에 `visual_fallback_reason: visual_fallback_hwp`, `text_source: data_list_csv_text`를 유지한다.
- 두 모드 모두 기본 산출물 경로는 `data/index/index.json`과 `data/index/ingestion_report.json`이다. v2는 추가로 `data/index/visual_artifacts/*.visual.json`을 생성한다.

## 실패 처리 (issue #53)
다음 row는 전체 인덱싱을 중단하지 않고 리포트에 실패로 남긴다.

| reason | stage | downstream 영향 |
|---|---|---|
| `missing_file_name` | row | row를 어떤 source 파일에도 매칭할 수 없다. |
| `missing_doc_id` | row | 안정적인 식별자가 없어 평가가 row를 참조할 수 없다. |
| `duplicate_doc_id` | row | 두 row가 인덱스에서 충돌하므로 뒤 row를 drop한다. |
| `unsupported_file_format` | row | v1은 `pdf`, `hwp`만 지원한다. |
| `missing_file` | filesystem | CSV가 가리키는 원본 파일이 디스크에 없다. |
| `empty_text` | text | 본문 텍스트가 비어 있어 chunking·embedding 대상이 없다. |

이 표는 `ingestion_report.json`의 `failure_taxonomy` 필드와 동일한 키를 사용한다(`ingestion.FAILURE_TAXONOMY`). reviewer가 산출물을 읽을 때 별도 코드 검색 없이 의미를 파악할 수 있다.

`ingestion_report.json`의 `summary` 섹션은 다음을 노출한다.
- `failure_reasons`: reason → count.
- `failure_examples`: reason → 최대 3개의 예시 row(row_number, doc_id, file_name, file_format).
- `doc_id_sources`: `notice_id` / `file_name` 분포.
- `file_formats`: 형식별 row 수.
- `duplicate_doc_ids`: base doc_id → 충돌한 row_number 목록.
- `on_duplicate_doc_id`: 이번 실행에서 적용된 정책(`fail` 또는 `suffix`).

성공적으로 인덱싱 가능한 문서가 0개이면 입력 오류로 보고 빌드를 실패시킨다.

## 회귀 보호 (issue #54)
v1 PDF/HWP 혼합 ingestion 경로는 [`tests/test_mixed_format_ingestion_regression.py`](../tests/test_mixed_format_ingestion_regression.py)가 회귀 가드 역할을 한다. 다음을 assert한다.

- PDF + HWP 성공 row가 안정적인 doc_id로 인덱싱된다.
- 한 mixed corpus에서 `missing_file` / `unsupported_file_format` / `duplicate_doc_id` 세 가지 실패 reason이 grouped count로 잡힌다.
- `on_duplicate_doc_id="suffix"` 옵트인은 두 번째 row를 정상 인덱싱하고 metadata에 resolution 흔적을 남긴다.
- `validate_data_list.py` CLI는 실패가 있으면 exit code 1, clean하면 0을 반환한다.

새로운 fixture를 추가할 때는 이 파일의 `_build_mixed_corpus`를 모방하면 된다. 실데이터 원본을 그대로 옮겨오지 말고, 의도하는 실패 패턴을 만족하는 최소 stub만 만든다(예: PDF 헤더 4 byte, 빈 본문 텍스트).

## 현재 로컬 검증 기준
현재 로컬 실데이터 샘플은 100개 row로 구성되며, CSV 텍스트 기반 v1 경로에서 100개 문서가 모두 인덱싱된다. 이 수치는 private local data 기준이므로 공개 README 성능표에는 반영하지 않는다.

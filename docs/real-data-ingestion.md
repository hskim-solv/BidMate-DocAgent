# PDF/HWP ingestion

이 문서는 비공개 PDF/HWP 원본과 `data_list.csv`를 로컬에서 인덱싱하는 v1 경로를 설명한다. 공개 baseline인 `data/raw` synthetic RFP 실행 흐름은 그대로 유지한다. 원본 PDF/image를 직접 파싱하는 v2 경로는 [`visual-ingestion-v2.md`](./visual-ingestion-v2.md)에 별도로 정리한다.

## 입력
- `data/data_list.csv`: `공고 번호`, `공고 차수`, `사업명`, `사업 금액`, `발주 기관`, 날짜 필드, `사업 요약`, `파일형식`, `파일명`, `텍스트` 컬럼을 사용한다.
- `data/files/`: CSV의 `파일명`이 가리키는 PDF/HWP 파일 디렉터리다.
- v1은 PDF/HWP 바이너리를 직접 파싱하지 않고, CSV의 `텍스트` 컬럼을 본문 소스로 사용한다.
- `공고 번호`가 비어 있으면 파일명 stem을 `doc_id`로 사용하고, 이 사실은 metadata의 `doc_id_source`에 기록한다.

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

`eval/real_config.local.yaml`이 없으면 인덱싱과 대표 질의까지만 실행하고, 실데이터 gold 평가를 건너뛴다. 새 환경에서는 `eval/real_config.example.yaml`을 복사해 로컬 expected doc id/term/target을 채운다. `eval/*.local.yaml`, 실데이터 원본, 실데이터 산출물은 Git 추적 대상이 아니다.

## 출력
- `data/index/index.json`: 기존 RAG index schema를 유지하되, 문서와 chunk에 normalized metadata를 포함한다.
- `data/index/ingestion_report.json`: CSV row별 `indexed` 또는 `failed` 상태와 실패 사유를 기록한다.

optional profile을 사용할 때도 index schema는 동일하며, 기본 경로만 `data/index/real100/`로 분리한다.

## v1 / v2 비교
- v1 기본값은 `--ingestion_mode csv-text`이며, CSV의 `텍스트` 컬럼을 본문으로 사용한다.
- v2는 `--ingestion_mode visual`을 명시했을 때만 활성화된다.
- v2에서 PDF/image는 visual parser artifact를 만들고, HWP는 `hwp5txt` adapter가 있으면 native text extraction을 시도한다. adapter가 없으면 CSV 텍스트 fallback을 사용한다.
- HWP fallback 문서는 metadata에 `visual_fallback_reason: visual_fallback_hwp`, `text_source: data_list_csv_text`를 유지하고 artifact diagnostics에 `hwp_parser_unavailable`을 남긴다.
- 두 모드 모두 기본 산출물 경로는 `data/index/index.json`과 `data/index/ingestion_report.json`이다. v2는 추가로 `data/index/visual_artifacts/*.visual.json`을 생성한다.

## 실패 처리
다음 row는 전체 인덱싱을 중단하지 않고 리포트에 실패로 남긴다.
- 원본 파일이 없는 경우: `missing_file`
- CSV 텍스트가 비어 있는 경우: `empty_text`
- `pdf`, `hwp` 외 형식인 경우: `unsupported_file_format`
- 동일 `doc_id`가 반복되는 경우: `duplicate_doc_id`

단, 성공적으로 인덱싱 가능한 문서가 0개이면 입력 오류로 보고 빌드를 실패시킨다.

## 현재 로컬 검증 기준
현재 로컬 실데이터 샘플은 100개 row로 구성되며, CSV 텍스트 기반 v1 경로에서 100개 문서가 모두 인덱싱된다. 이 수치는 private local data 기준이므로 공개 README 성능표에는 반영하지 않는다.

실데이터 평가를 실행하면 `reports/real100/eval_summary.json` 외에 `reports/real100/eval_aggregate.json`도 생성한다. aggregate 파일은 case별 query/answer를 제거하고 accuracy, retrieval, grounding, citation, abstention, latency/retry 같은 집계값만 남기기 위한 로컬 공유용 산출물이다.

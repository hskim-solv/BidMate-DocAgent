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

## 출력
- `data/index/index.json`: 기존 RAG index schema를 유지하되, 문서와 chunk에 normalized metadata를 포함한다.
- `data/index/ingestion_report.json`: CSV row별 `indexed` 또는 `failed` 상태와 실패 사유를 기록한다.

## v1 / v2 비교
- v1 기본값은 `--ingestion_mode csv-text`이며, CSV의 `텍스트` 컬럼을 본문으로 사용한다.
- v2는 `--ingestion_mode visual`을 명시했을 때만 활성화된다.
- v2에서 PDF/image는 visual parser artifact를 만들고, HWP는 native visual parsing 대신 CSV 텍스트 fallback을 사용한다.
- HWP fallback 문서는 metadata에 `visual_fallback_reason: visual_fallback_hwp`, `text_source: data_list_csv_text`를 유지한다.
- 두 모드 모두 기본 산출물 경로는 `data/index/index.json`과 `data/index/ingestion_report.json`이다. v2는 추가로 `data/index/visual_artifacts/*.visual.json`을 생성한다.

## 실패 처리
다음 row는 전체 인덱싱을 중단하지 않고 리포트에 실패로 남긴다.
- 원본 파일이 없는 경우: `missing_file`
- CSV 텍스트가 비어 있는 경우: `empty_text`
- `pdf`, `hwp` 외 형식인 경우: `unsupported_file_format`
- 동일 `doc_id`가 반복되는 경우: `duplicate_doc_id`

단, 성공적으로 인덱싱 가능한 문서가 0개이면 입력 오류로 보고 빌드를 실패시킨다.

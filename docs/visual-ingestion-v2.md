# Visual parsing v2

이 문서는 이슈 #14의 PDF/image visual parsing v2 경로를 설명한다. 기존 공개 baseline(`data/raw`)과 CSV-text v1 ingestion은 기본 동작으로 유지한다.

## 목적
- 원본 PDF/이미지에서 text, page, bbox, region metadata를 함께 추출한다.
- parser artifact를 기존 RAG document schema로 정규화해 chunking, retrieval, citation 흐름에서 재사용한다.
- HWP는 이번 단계에서 native visual parsing을 하지 않고 CSV 텍스트 fallback으로 비교 가능성을 유지한다.

## 입력
- `--visual_input_dir`: PDF 또는 이미지(`pdf`, `png`, `jpg`, `jpeg`, `tif`, `tiff`, `bmp`, `webp`) 파일 디렉터리.
- `--metadata_csv --files_dir --ingestion_mode visual`: 기존 `data_list.csv` 메타데이터를 사용하되 PDF/image는 v2 parser로 처리하고 HWP는 v1 텍스트 fallback으로 처리한다.
- `--visual_artifact_dir`: v2 artifact 저장 위치. 생략하면 `<output_dir>/visual_artifacts`를 사용한다.

## 출력
- `index.json`: 기존 RAG index schema를 유지하면서 section/chunk/evidence/citation에 `regions`와 `page_span`을 선택적으로 포함한다.
- `ingestion_report.json`: 문서별 `parsed`, `partial`, `fallback`, `failed` 상태와 실패 사유를 기록한다.
- `*.visual.json`: `schema_version: 2` artifact. `pages[*].blocks[*]`, `tables`, `field_candidates`, `sections`, `diagnostics`를 포함한다.
- `parser_eval_summary.json`: parser-stage gold와 artifact를 비교한 OCR/layout/section/table/field/bbox 평가 리포트다.

## Parser stages
- PDF text layer: PyMuPDF로 page block, bbox, layout type을 추출한다.
- OCR: PDF page text가 부족하거나 이미지 입력일 때 OCR adapter를 호출한다.
- Table candidates: pdfplumber table 추출과 layout text heuristic을 함께 사용한다.
- Field candidates: `key: value`, `key=value` 형태의 line을 후보로 기록한다.
- Section detection: heading-like block을 section boundary로 사용하고, 없으면 문서 전체 section으로 묶는다.

## Failure policy
- `pdf_parser_unavailable`: PyMuPDF를 사용할 수 없어 PDF를 열 수 없음.
- `ocr_unavailable`: pytesseract 또는 시스템 Tesseract 실행이 불가능함.
- `empty_visual_text`: text layer와 OCR 모두에서 인덱싱 가능한 text가 없음.
- `visual_fallback_hwp`: HWP native visual parsing은 후속 과제로 남기고 CSV `텍스트` 컬럼을 사용함.

OCR 품질은 자동으로 개선되었다고 간주하지 않는다. v2의 1차 성공 기준은 page/bbox region artifact 생성, 기존 retrieval 호환성, v1/v2 비교 가능성이다.

## Parser-stage evaluation
QA end-to-end 지표만으로는 parser 품질 저하가 retrieval 문제인지, OCR/layout/table/field 단계 문제인지 분리하기 어렵다. `eval/run_parser_eval.py`는 이미 생성된 `*.visual.json` artifact를 gold YAML과 비교해 parser 단계별 지표를 독립적으로 기록한다.

```bash
python3 eval/run_parser_eval.py \
  --artifact_dir eval/fixtures/parser_visual_v2 \
  --gold eval/parser_visual_v2_gold.yaml \
  --output_dir reports \
  --run_name visual_v2_fixture \
  --parser_version 2
```

실제 visual ingestion 결과를 비교할 때는 `--artifact_dir data/index/visual_artifacts`를 사용하고, gold의 `doc_id`와 artifact 파일명을 해당 run에 맞춘다. report schema는 `eval/parser_metrics.schema.json`에 둔다.

주요 지표는 다음과 같다.
- OCR: gold text snippet recall과 normalized char-F1 proxy.
- Layout: block text/type/page 기준 precision, recall, F1.
- Section: heading과 `page_span` 기준 boundary recall.
- Table: cell, row, column-count reconstruction F1.
- Field: key-value candidate precision, recall, F1.
- Bbox/page-region: anchor block의 bbox 존재율과, gold bbox가 있을 때 IoU threshold 충족률.

실패 taxonomy는 `ocr_missing_text`, `layout_type_mismatch`, `section_boundary_missing`, `table_cell_mismatch`, `field_missing`, `field_value_mismatch`, `bbox_missing`, `bbox_misaligned`를 포함한다. 이 코드는 downstream 분석에서 retrieval miss, noisy chunking, wrong field grounding, weak bbox citation 같은 QA 실패 원인과 연결한다.

## 실행 예시
```bash
python3 scripts/build_index.py \
  --visual_input_dir data/visual_samples \
  --output_dir data/index \
  --embedding_backend hashing
```

```bash
python3 scripts/build_index.py \
  --metadata_csv data/data_list.csv \
  --files_dir data/files \
  --ingestion_mode visual \
  --output_dir data/index \
  --embedding_backend hashing
```

## 검증
기본 회귀는 기존과 동일하게 유지한다.

```bash
python3 -m unittest discover -s tests -q
python3 scripts/build_index.py --input_dir data/raw --output_dir /private/tmp/agentic-vlm-index --embedding_backend hashing
python3 app.py --input_dir /private/tmp/agentic-vlm-index --output_dir /private/tmp/agentic-vlm-outputs --query "기관 A와 기관 B의 AI 요구사항 차이 알려줘"
python3 eval/run_eval.py --index_dir /private/tmp/agentic-vlm-index --output_dir /private/tmp/agentic-vlm-reports --config eval/config.yaml
python3 eval/run_parser_eval.py --artifact_dir eval/fixtures/parser_visual_v2 --gold eval/parser_visual_v2_gold.yaml --output_dir /private/tmp/agentic-vlm-parser-reports --run_name visual_v2_fixture --parser_version 2
python3 scripts/update_readme_metrics.py --report reports/eval_summary.json --readme README.md --check
```

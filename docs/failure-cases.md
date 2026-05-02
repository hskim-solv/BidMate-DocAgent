# 실패 사례 분석

## 관찰된 실패 유형
1. 메타데이터 불일치로 인한 후보 문서 누락
2. 비교 질의에서 한쪽 문서만 상위 노출
3. 후속 질문에서 문맥 엔터티 소실
4. 근거가 부족한 질문에서 unsupported claim 생성
5. claim과 citation chunk가 같은 내용을 직접 지지하지 않는 citation drift
6. OCR 누락으로 parser artifact의 본문 text가 retrieval 후보에 들어오지 않는 경우
7. layout/section boundary 오류로 heading과 본문이 잘못 묶여 chunk가 노이즈를 포함하는 경우
8. table/field 추출 오류로 요구사항 표나 key-value 사실이 누락 또는 오인식되는 경우
9. bbox/page-region 누락 또는 오정렬로 citation이 원문 위치까지 설명하지 못하는 경우

## 대응 전략
- 필터 완화 + 질의 재작성
- top-k/rerank 파라미터 조정
- 세션 컨텍스트 보강 및 검증 로그 점검
- 공개본에서는 agency/project/title metadata를 정규화해 exact/partial/fuzzy 후보를 확장한다.
- verifier가 topic/entity/doc coverage를 확인하고 실패 시 strict → reduced → relaxed 단계로 metadata filter를 완화한다.
- retrieval diagnostics에는 단계별 filter, 후보 수, 검증 실패 사유를 남겨 metadata mismatch를 추적한다.
- 최종 답변은 `supported`/`partial`/`insufficient` 상태를 명시하고, claim마다 citation을 연결한다.
- 근거가 없으면 `claims`를 비우고 `insufficiency`에 missing target/topic과 검증 실패 사유를 남긴다.
- visual parsing v2는 `eval/run_parser_eval.py`로 QA 이전 단계의 OCR/layout/section/table/field/bbox 오류를 분리해 기록한다.
- parser failure taxonomy는 downstream 실패와 연결해 해석한다. 예를 들어 `ocr_missing_text`는 retrieval miss, `section_boundary_missing`은 noisy chunking, `table_cell_mismatch`는 표 기반 요구사항 누락, `field_value_mismatch`는 잘못된 metadata-like claim, `bbox_missing`/`bbox_misaligned`는 약한 citation grounding으로 이어질 수 있다.

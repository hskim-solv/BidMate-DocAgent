# 0049: kordoc이 HWP/PDF 파서 backend로 pyhwp/hwp5 대체

- **Status**: proposed
- **Date**: 2026-05-15
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (csv_text 기준선 보존), [ADR 0036](./0036-hwp-native-loader-pyhwp-gated-default.md) (본 ADR 이 superseded), issue [#890](https://github.com/hskim-solv/BidMate-DocAgent/issues/890) (본 ADR), issue [#801](https://github.com/hskim-solv/BidMate-DocAgent/issues/801) (`hwp_native_rate > 0.0` 목표 — superseded 표면), PR [#856](https://github.com/hskim-solv/BidMate-DocAgent/pull/856) (closed: pyhwp 0.1b15 sections API adapt — 본 ADR 이 supersedes), PR [#895](https://github.com/hskim-solv/BidMate-DocAgent/pull/895) (본 PR — kordoc-vs-csv_text PDF 측정이 22×–757× 컨텐츠 크기 갭 보인 후 PDF 까지 mid-review 확장)

## TL;DR

- pyhwp/hwp5 backend 를 `kordoc` (Node CLI) 로 교체, PDF 도 같이 (csv_text 22×–757× 갭)
- `csv_text` fallback 무조건 유지 → ADR 0001 baseline 보존
- 단일 `npx kordoc` 호출로 HWP + PDF 묶음 처리, telemetry surface ADR 0036 모양 유지

## 배경

2026-05-15 까지 비공개 100-doc real-eval 이 `hwp_native_rate = 0.0` 기록 — 96개 HWP 파일 모두 `data_list_csv_text` (단일 컬럼 CSV 텍스트) 로 fallback. 근본 원인은 pyhwp 0.1b15 API drift (`BodyText.section_list()` 가 `sections` attribute 로 변경, paragraph traversal 이 event stream 으로 교체). PR #787 이 결과 `AttributeError` 를 fallback tuple 에 추가해 빌드가 더 이상 abort 안 했지만, silent degradation 이 회귀 숨김 — ADR 0036 의 "pyhwp-gated native default" 결정이 비공개 코퍼스에서 사실상 dead code 화.

PR #856 가 `ingestion._extract_hwp_native` 에서 pyhwp API 두 세대 모두 adapt. adaptation 이 41개 단위 테스트 통과하지만 (1) real-eval 델타 dev host 에서 측정 불가 (pyhwp 가 dev host 가 없는 opt-in 의존성) + (2) pyhwp 작동해도 paragraph-only 추출이 공개 RFP 문서가 의존하는 테이블 구조, 헤딩, 폼-문서 레이아웃 discard.

2026-05-15 Phase 1 dump 실험이 `data/files/` 대상 [chrisryugj/kordoc](https://github.com/chrisryugj/kordoc) (npm, MIT) 실행: HWP 96 + PDF 4 = **100/100 변환**, 13.5s + 19.5s = 33s 총, 19MB Markdown 출력. 출력은 `colspan`/`rowspan` HTML `<table>`, 한국어 헤딩 (`### □`, `### ⚬`), footnote, nested-table 마커 보존 — paragraph-only pyhwp 추출이 잃는 구조 그대로.

## 결정

`ingestion.HwpNativeLoader` 의 pyhwp/hwp5 backend 를 `HwpKordocLoader` 로 교체 + `PdfCsvTextLoader` 의 기본 경로를 `PdfKordocLoader` 로 교체. 둘 다 단일 `npx -y -p kordoc -p pdfjs-dist kordoc <files…> -d <out>/` ingestion run 당 1회 호출 (`_prime_kordoc_batches` orchestrate) 후 결과 Markdown 을 파일 확장자별 per-format loader 캐시로 route. `csv_text` 를 두 형식 모두 무조건 fallback 으로 유지해 ADR 0001 naive baseline 보존.

PDF 는 본 ADR 첫 iteration 에서 scope out 이었으나 mid-review 측정 후 pull back: csv_text PDF 추출이 문서당 220–2,716 자만 hold (커버 + TOC 만), kordoc 가 60,572–268,877 자 + 각각 24–198 `<table>` 블록 — 4-PDF 비공개 슬라이스의 22×–757× 컨텐츠 크기 갭, 본 ADR 을 원래 동기 부여한 HWP `hwp_native_rate=0.0` silent-failure 갭보다 큼.

- **env 스위치**: `BIDMATE_HWP_LOADER=kordoc` (기본) | `csv_text`; `BIDMATE_PDF_LOADER=kordoc` (기본) | `csv_text`. 각 형식 독립 flip. 둘 다 `node --version` 실패 또는 `npx` exit-code 에러 시 `csv_text` 로 auto-degrade, ADR 0036 fallback 규율 mirror
- **Telemetry surface**: `{Hwp,Pdf}KordocLoader.last_text_source ∈ {"kordoc", "data_list_csv_text"}` + `last_fallback_reason` 이 ADR 0036 loader 가 established 한 모양 유지, 본 PR 후 `reports/eval_summary.json::text_source_counts` 가 `{"hwp": {"kordoc": N}, "pdf": {"kordoc": M}}` 읽음. 원래 HWP 타겟인 eval `kordoc_rate` aggregation 이 두 형식 모두 적용
- **단일 subprocess batching**: `_prime_kordoc_batches` 가 HWP + PDF 경로를 1개 `npx kordoc` 호출로 pool 해 npm fetch + Node spin-up 비용을 ingestion 당 1회 지불, 2회 아님. 서브프로세스 반환 후 per-format 캐시 routing
- **pyhwp/hwp5 제거**: pyhwp 는 어떤 `requirements*.txt` 에도 pin 안 됨 — `ingestion.py` 가 `find_spec("hwp5")` 게이트로만 lazy import. 본 PR 이 lazy import + 게이트 제거; requirements diff 불필요. pyhwp 가 다른 dev shell 에 거주하면 이제 dead weight, zero-risk 미래 cleanup 으로 제거 가능

## 결과

- **비공개 코퍼스 정보 이득**. 테이블 구조, 헤딩, 폼-문서 레이아웃 survive — 대부분 retrieval-failure-mode 분석이 missing 으로 pin 한 표면. Real-eval 델타가 측정 계약 (issue #890 acceptance criterion 7)
- **Host 의존성 단순화**. PR #856 의 §5b real-data 델타 block 한 "pyhwp 가 이 worktree 에 미설치" 경고 사라짐 — `node --version` 이 단일 체크, fallback 경로 (`csv_text`) 가 오늘 동작과 동일
- **새 런타임 의존성: Node.js 18+**. CI runner + `make install` 흐름이 Node setup step 획득 (`pr-eval.yml` 변경은 issue #890 범위). 첫 실행 `npx kordoc` 가 ~수십 MB fetch; runner 에 캐시. Air-gapped 환경은 `csv_text` 강제 (graceful, telemetry-visible)
- **kordoc OSS 안정성 위험**. kordoc 가 2026-04 ship + 1인 저자. pyhwp 깨뜨린 같은 drift 모드가 kordoc 깨뜨릴 수 있음 — 그러나 telemetry surface (`last_text_source` / `last_fallback_reason` / `text_source_counts`) 가 동일, 다음 drift 가 ADR 0036 메트릭 아무도 watching 안 해서 pyhwp drift 가 silent 했던 것과 같은 큰 신호 (`kordoc_rate → 0`) 생산
- **csv_text 불변량 lock**. naive-baseline `csv_text` 추출 경로가 이제 ADR 0001 비교용만이 아니라 *offline correctness 에 load-bearing* — 제거가 kordoc-missing-host 케이스 깨뜨림. csv_text 제거 제안하는 미래 ADR 은 이 fallback surface 명시 교체 필수
- **ADR 0036 supersede**. ADR 0036 의 "pyhwp-gated native default" 가 더 이상 live 설계 아님; 같은 PR 이 ADR 0036 Status 블록을 `superseded by 0049` + 1-라인 해소 노트로 업데이트

## 검토한 대안

- **pyhwp 0.1b15 sections-API adapt (PR #856)**. 41개 단위 테스트 통과하지만 real-eval 델타가 dev-host pyhwp 부재로 block (PR #856 §5b 인정) + paragraph-only 추출이 RFP 가 의존하는 테이블 구조 잃음. 거부: §5b 인정만으로도 CLAUDE.md load-bearing real-data-delta 요구사항 실패 + 구조적 손실이 pyhwp surface 내부에서 복구 불가
- **LibreOffice `--headless --convert-to`**. JVM/Java 런타임, 파일당 느림 + table-to-markdown 도 별도 post-process step 필요. 거부: 추가하는 Node 18 의존성보다 무겁고, 구조 보존 worse
- **pdfminer/PyMuPDF + 대안 HWP parser 조합**. PDF + HWP 경로가 두 무관한 코드 surface 로 fork; kordoc 가 1개 CLI 호출 아래 collapse. 거부: 통합 surface bloat
- **kordoc MCP server (`kordoc mcp`)** vs CLI 서브프로세스. ingestion 파이프라인이 deterministic batch — MCP message-passing 모델이 batch 케이스에 upside 없이 asynchrony 오버헤드 추가. 거부: 인덱싱 경로에 잘못된 도구; MCP 서버는 interactive AI-client 사용에 옳음, 본 ADR 범위 외

## Verification

Decision 이 4개 측정 surface bind. pre-commit lint 가 kordoc PR land 시 아래 키를 기존 파일로 resolve (새 파일은 kordoc PR 자체가 생성):

<!-- verifies-key: ingestion.py:HwpKordocLoader -->
<!-- verifies-key: ingestion.py:PdfKordocLoader -->
<!-- verifies-key: tests/test_ingestion_kordoc_regression.py:test_ -->
<!-- verifies-key: reports/eval_summary.json:text_source_counts -->
<!-- verifies-key: docs/adr/0036-hwp-native-loader-pyhwp-gated-default.md:superseded -->

읽기 가이드:

- `ingestion.py:HwpKordocLoader` — `HwpNativeLoader` 교체 loader 클래스; `last_text_source` enum + fallback 시맨틱이 본 ADR Decision 이 ship 된 런타임 증거
- `tests/test_ingestion_kordoc_regression.py:test_` — (a) kordoc CLI 호출 모양, (b) Node-missing → `csv_text` fallback, (c) telemetry-key 안정성 pin 회귀 테스트. Skip-guarded 라 Node 없는 CI 도 fallback 케이스 실행
- `reports/eval_summary.json:text_source_counts` — `{"kordoc": N, "data_list_csv_text": M}` emit 하는 eval surface. kordoc PR 의 real-eval 델타 (issue #890 §7) 가 첫 read; 미래 drift 감지 (ADR 0036 silent 실패 모드 유사) 가 재read
- `docs/adr/0036-hwp-native-loader-pyhwp-gated-default.md:superseded` — ADR 0036 의 Status 블록이 같은 PR 에서 `superseded by 0049` 로 업데이트. Lint 가 lockstep catch — 본 ADR 이 ADR 0036 업데이트 없이 ship 하면 마커는 resolve 되지만 `superseded` substring 부재

repo root 에서 `python3 scripts/_governance.py --lint-adr-consequences docs/adr/0049-kordoc-replaces-pyhwp-backend.md` 실행이 kordoc PR 파일 commit 후 exit 0 필수.

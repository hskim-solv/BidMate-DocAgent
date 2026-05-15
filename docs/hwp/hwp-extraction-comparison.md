# HWP native parse 비교 실험: hwp5txt vs libreoffice → visual-v2 (issue #121)

## 목적

한국 정부조달 RFP 코퍼스의 상당 비율이 HWP/HWPX 포맷이다. 본 시스템의
현재 기본 ingestion 경로는 `data_list.csv` 의 `텍스트` 컬럼을 본문 소스로
쓰는 fallback ([`HwpCsvTextLoader` (ingestion.py:104)](../../ingestion.py)) 이며,
이는 사용자가 사전에 추출한 plain text 에 의존하는 외부 preprocessing 부채를
남긴다. v3 사이클의 한 축은 이 의존성을 native parse 로 대체하는 것이고,
그 첫 단계로 두 후보 경로의 정량 비교를 수행한다.

- **Path A — `hwp5txt` (pyhwp CLI):** OLE binary 를 파싱해 paragraph/text_chunk
  단위로 plain text 만 추출한다. 표·이미지·layout 정보는 없다.
- **Path B — `libreoffice --headless --convert-to pdf`:** HWP → PDF 변환 후
  기존 [`visual_ingestion.parse_pdf_artifact` (visual_ingestion.py:322)](../../visual_ingestion.py)
  를 그대로 통과시킨다. 텍스트 + 표 + page/bbox 메타데이터까지 모두 visual-v2
  스택의 산출물 형식으로 들어온다.

본 문서는 두 경로의 결정 근거를 비교 측정 결과로 뒷받침한다.

## What this is NOT

- **Productionization 아님.** 기본 ingestion 경로(CSV `텍스트`)는 변경 없이
  유지된다 (ADR 0001 baseline invariant). 본 PR 은 비교 실험 한 건만 추가한다.
- **ADR 0001 baseline 교체 아님.** adopt 결정은 별도 PR + ADR 에서.
- **HWPX 지원 아님.** XML 기반 HWPX 변종은 별도 이슈로 분리한다 (#121 out-of-scope).
- **CI 포함 아님.** libreoffice 는 200 MB 급 의존성이고 라이선스 (MPL-2) 도
  별개 검토 필요. 본 비교 스크립트는 **로컬 실험 전용**이다 (#121 risks 참고).
- **`pyhwp` 라이브러리 spike 와 중복 아님.** 사촌 이슈 #167 / [`docs/hwp-native-spike.md`](./hwp-native-spike.md)
  은 *CSV baseline vs `pyhwp` (Python API)* 의 1:1 비교다. 본 문서는 *두 native
  경로 사이의 2:2 비교* — 텍스트만이냐 vs 표/레이아웃까지냐 — 다.

## Scope

| 차원 | hwp5txt | libreoffice → visual-v2 |
|---|---|---|
| 본문 텍스트 추출 | ✅ paragraph plain text | ✅ PDF text-layer block |
| 표 (table) 재구성 | ❌ (plain text 만) | ✅ pdfplumber 기반 cell 추출 |
| 읽기 순서 / heading 구조 | partial (paragraph order) | ✅ page/bbox + block ordering |
| 이미지 / OCR | ❌ | ✅ tesseract / donut adapter (text-poor page) |
| 인코딩 (한글 자모, ㈜/₩/㎡) | 직접 측정 | 직접 측정 (PDF 변환 통과 여부) |
| latency / doc | 직접 측정 | 변환 + 파싱 합산 |

5 차원 측정:

1. **Text recall** — 추출된 본문 char 수 (Δ).
2. **표 재구성** — table_count, 셀 수 (path A 는 항상 0).
3. **읽기 순서 보존** — heading → body → footnote 순서 (path B 만 측정 가능).
4. **인코딩** — 자모 분리·결합, 특수문자 손상 건수.
5. **Latency** — doc 1 건 처리 시간 (median, p95). Path B 는 변환/파싱 분리 보고.

## 설계

[`scripts/compare_hwp_extraction.py`](../../scripts/compare_hwp_extraction.py) 가
다음을 수행한다.

1. `--hwp-dir <DIR>` 에 있는 `*.hwp` 파일을 순회.
2. 각 파일에 대해:
   - **Path A:** `subprocess.run(["hwp5txt", <file>])` → stdout char 수, line 수,
     첫 500 자 sample, latency 기록.
   - **Path B:** `subprocess.run(["libreoffice", "--headless", "--convert-to",
     "pdf", "--outdir", <tmp>, <file>])` 후 생성된 PDF 를 `visual_ingestion.
     parse_pdf_artifact` 로 통과시켜 page_count / block_count / char_count /
     table_count / ocr_block_count / diagnostics_reasons 를 수집.
3. 결과를 `outputs/hwp_extraction_comparison.json` (gitignored, ADR 0005
   boundary) 에 dump 하고 summary 를 stdout 으로 print.

### Failure policy

`HwpNativeLoader` 의 3-단 fallback 패턴을 그대로 따른다:

- **Tool 미설치:** 해당 경로 `status: "skipped"`, `reason: "hwp5txt_not_installed"`
  또는 `"libreoffice_not_installed"`. 다른 경로는 정상 진행.
- **Parse 실패:** `status: "failed"`, `reason` + `stderr_tail` (최대 400 자).
- **Timeout:** 파일당 120 초 hard cap, `status: "failed"`, `reason: "timeout"`.

스크립트는 어떤 경우에도 **crash 하지 않는다.** CI 가 import 만 해도 안전하다
(라이브러리/실행파일 없이 `--help` 통과).

### Output schema (v1)

```json
{
  "schema_version": 1,
  "hwp_dir": "<DIR>",
  "files": [
    {
      "file": "sample.hwp",
      "size_bytes": 123456,
      "hwp5txt": {"status": "ok", "char_count": 12345, "line_count": 234,
                  "text_sample": "...", "latency_ms": 412.3},
      "libreoffice_visual_v2": {
        "status": "ok", "convert_latency_ms": 3210.4, "parse_latency_ms": 184.1,
        "latency_ms": 3394.5,
        "page_count": 12, "block_count": 487, "char_count": 11982,
        "table_count": 3, "ocr_block_count": 0, "diagnostics_reasons": []
      }
    }
  ],
  "summary": {
    "file_count": 1,
    "hwp5txt": {"status_counts": {...}, "char_count": {...}, "latency_ms": {...}},
    "libreoffice_visual_v2": {"status_counts": {...}, "char_count": {...},
                              "latency_ms": {...}}
  },
  "tool_availability": {"hwp5txt": true, "libreoffice": true}
}
```

## 측정 실행 가이드

원본 HWP 샘플은 ADR 0005 (private data boundary) 에 따라 커밋되지 않는다.
사용자가 로컬에 보유한 비공개 RFP 샘플 또는 공개 정부조달 RFP 일부를
`<HWP_DIR>` 에 두고 실행한다.

### 준비

```bash
# Path A (text-only) - pyhwp CLI
pip install pyhwp

# Path B (visual-v2) - libreoffice
# macOS:
brew install --cask libreoffice
# Debian/Ubuntu:
sudo apt-get install -y libreoffice

# PDF 파싱 의존성 (이미 설치되어 있다면 skip)
pip install pymupdf pdfplumber
```

### 실행

```bash
python3 scripts/compare_hwp_extraction.py --hwp-dir <HWP_DIR>
# 또는 출력 경로 지정:
python3 scripts/compare_hwp_extraction.py --hwp-dir <HWP_DIR> \
    --out outputs/hwp_extraction_comparison.json
```

stdout 으로 summary JSON, `outputs/hwp_extraction_comparison.json` 에 per-file
detail 이 기록된다. 둘 중 한 도구만 설치된 환경에서도 스크립트는 끝까지 돌고,
미설치 경로는 `status: "skipped"` 로 마킹된다.

## 결과

샘플 N = 15 개 (로컬 `data/files/*.hwp` 96 개 중 alphabetical 첫 15, HWP 5.x;
측정 일 2026-05-12).

측정 환경: macOS (Apple silicon) / Python 3.11.4 / pyhwp `hwp5txt`
(homebrew) / LibreOffice 26.2.3 (homebrew cask, base install). 실행 명령:

```
python3 scripts/compare_hwp_extraction.py --hwp-dir <HWP_DIR>
```

| 차원 | hwp5txt | libreoffice → visual-v2 | Δ / 비고 |
|---|---|---|---|
| 본문 char 길이 (median) | 24,085 (p95 33,096; mean 23,094) | 측정 불가 | Path B 가 PDF 변환 단계에서 실패 → 직접 비교 불가 |
| 표 재구성 (table_count, 5 건 표본) | 0 (구조적, 셀 데이터는 `<표>` 플레이스홀더만) | 측정 불가 | Path A 는 표 셀 손실; Path B 미실행 |
| OCR fallback page 비율 | n/a (text-only path) | 측정 불가 | Path B 가 parse 진입 이전 단계에서 실패 |
| 인코딩 오류 (자모 분리, ㈜/₩/㎡ 손상) 건수 | 0 / 15 (자동 스캔 + 정성 sample 점검) | 측정 불가 | U+FFFD / orphan jamo / `?{3,}` 패턴 없음; 첫 500 자 sample 에서 「」·‘’·₩·괄호숫자 등 한글·기호 손상 없음 |
| Latency / doc (median, p95 ms) | 4,645 / 18,277 (mean 8,106) | 측정 불가 | hwp5txt CLI subprocess; p95 outlier 는 본문 페이지 수 많은 1 건 |
| 실패율 (status != ok) | 0 / 15 | **15 / 15** (`pdf_not_produced`) | LibreOffice 26.2.3 base install (macOS homebrew, 2026-05-12 기준) 에 **HWP import filter 미포함** — stderr `"source file could not be loaded"`. H2Orestart 등 third-party `.oxt` extension 별도 설치 필요 |

샘플 raw 결과 JSON 은 `outputs/hwp_extraction_comparison.json` 에 남는다 (gitignored).

### Path C — `pyhwp` Python API with table extraction (2026-05-13, PR-C1)

본 비교 문서가 Path A `hwp5txt` 의 `table_count = 0` 한계 (CLI 가 `<표>`
플레이스홀더만 emit) 를 짚어, [`docs/hwp-native-spike.md`](./hwp-native-spike.md)
의 "표 셀 reconstruction 난이도" 위험 항목과 함께 후속 PR-C1 의 트리거가
되었다. PR-C1 (#506) 는 pyhwp 의 Python API 를
[`ingestion._extract_hwp_native_with_tables`](../../ingestion.py) 로 사용,
cooked xmlmodel event stream 을 순회해 `TableBody` / `TableCell` 진입 시
셀 좌표 (row, col, rowspan, colspan) 와 셀 텍스트를 분리 수집한다. opt-in:
`BIDMATE_HWP_LOADER=native_tables`. 셀은 별도 `sections` 항목
(`heading: "표 N (HWP native)"`) 으로 surface 되어 downstream section-aware
chunking 이 자동으로 표를 별도 retrieval 단위로 다룬다. 셀 텍스트는 본문에
누설되지 않아 BM25 중복 색인 위험이 없다 (테스트 `test_body_text_outside_tables_excludes_cell_text`
가 회귀 가드).

| 차원 | hwp5txt (Path A) | libreoffice → visual-v2 (Path B) | pyhwp + tables (Path C, PR-C1) | Δ / 비고 |
|---|---|---|---|---|
| 본문 char 길이 | 24,085 (median) | 측정 불가 | 측정 TBD | Path C 는 본문 paragraph 만 — `native` 와 동일 |
| 표 재구성 (셀 좌표) | 0 (구조 손실) | 측정 불가 | TBD (event-stream 기반, row/col/span 보존) | Path A 한계 해소 |
| 표 셀 ↔ 본문 분리 | n/a (한 stream) | 측정 불가 | ✅ (셀 텍스트가 본문에 누설 안 됨) | BM25 이중 색인 방지 |
| Latency / doc | 4,645 ms (median) | 측정 불가 | 측정 TBD | event stream 순회 추가 비용 — 사용자 측정 필요 |
| CI 안정성 | subprocess 의존 | libreoffice 미포함 | ✅ pyhwp 의존 (`requirements.txt`); 미설치 시 silent CSV fallback | never-raise 컨트랙트 동일 |

## 결정 (TBD)

비교 결과 확인 후 다음 중 하나를 선택한다. 결정 사유는 1-2 문장으로 본
섹션에 기록.

- [ ] **Adopt `hwp5txt`** — text-only 충분 + visual 비용 과대. 후속 PR 에서
  ingestion v3 의 HWP loader 로 등록 (`BIDMATE_HWP_LOADER=hwp5txt` opt-in →
  품질 검증 후 default 승격, ADR 작성).
- [ ] **Adopt `libreoffice → visual-v2`** — 표/레이아웃 보존 가치 > 변환 latency
  + libreoffice 운영 비용. 후속 PR 에서 visual-v2 ingestion 의 HWP path 로
  등록 (지금의 `visual_fallback_hwp` 마커를 native 경로로 교체).
- [ ] **Adopt both as dual-mode** — text-only 질의는 hwp5txt, 표/레이아웃 필요
  질의는 libreoffice 경로. metadata flag 로 dispatch.
- [ ] **Reject both** — 측정 결과가 CSV baseline 대비 의미 있는 개선을 보이지
  않는다. 본 비교 문서는 결정 근거의 기록으로만 남긴다.

결정 사유: _측정 결과 (위 결과 표) 를 바탕으로 1-2 문장으로 기록 — 결정의
근거가 된 행 + 외생 변수 (예: Path B 의 HWP filter 부재로 인한 100% 실패)
를 어떻게 평가했는지 포함._

## 위험

- **libreoffice 의존성.** 200 MB 급 설치 + Java 런타임. CI 미포함이 합리적이며,
  사내 배포 시 Docker base image 부피를 고려해야 한다. 라이선스는 **MPL-2** —
  RFP 처리 워크플로에 호환되나 별도 표기 필요.
- **변환 fidelity.** HWP → PDF 변환은 layout/font/표 셀 결합에서 손실이 발생할
  수 있다. 특히 한글 폰트 fallback / 표 multi-row 헤더는 약점 가능성.
- **Latency.** libreoffice 첫 호출 시 JVM warm-up 으로 수 초 추가. p95 측정
  시 `--norestore` 등 옵션 검토 가능 (현재 스크립트는 default 옵션).
- **HWP 샘플 confidentiality.** 합성 HWP 또는 공개 정부조달 RFP 일부로 측정.
  raw 파일은 `data/files/` 와 동일하게 비공개 (#121 risks).
- **pyhwp 유지보수 / 라이선스.** 사촌 spike (#167) 와 동일 리스크 — pinned
  version, GPL-3 호환성 확인 필요.

## 관련

- 이슈: [#121](https://github.com/hskim-solv/BidMate-DocAgent/issues/121),
  parent [#118](https://github.com/hskim-solv/BidMate-DocAgent/issues/118)
- 사촌 spike: [#167](https://github.com/hskim-solv/BidMate-DocAgent/issues/167)
  — pyhwp Python API vs CSV baseline, [`docs/hwp-native-spike.md`](./hwp-native-spike.md)
- ADR: [0001 — preserve naive baseline](../adr/0001-preserve-naive-baseline.md),
  [0005 — eval-split public-synthetic / private-local](../adr/0005-eval-split-public-synthetic-private-local.md)
- 선행 문서: [`docs/visual-ingestion-v2.md`](../vision/visual-ingestion-v2.md) "What this is NOT" §
- 후속: HWPX 별도 이슈, native adopt 시 ADR 작성

---

## HWPX (.hwpx) scope — out-of-scope for this document (issue #543)

`.hwpx`는 HWP의 XML 기반 후속 포맷이다 (ZIP archive + `Contents/content.hpf`). pyhwp는 `.hwpx`를 지원하지 않으며, 현재 `ingestion.py:SUPPORTED_FILE_FORMATS = {"pdf", "hwp"}`에 포함되어 있지 않다.

**이 문서의 범위 밖**: 본 문서는 `.hwp` (OLE binary) 경로 비교 실험에만 해당. HWPX 지원은 별도 이슈 [#543](https://github.com/hskim-solv/BidMate-DocAgent/issues/543)에서 추적한다.

**구현 노트** (HWPX가 지원될 때):
- ZIP 언패킹 → `Contents/content.hpf` XML 파싱 (pyhwp 없이 `xml.etree` 단독으로 가능)
- 단락 / 표 셀 추출은 `HwpNativeLoader` 출력 스키마와 일치해야 함 (ADR 0003 answer contract 보존)
- 시각적 경로 (`visual_ingestion.parse_pdf_artifact`) 는 HWPX → PDF 변환 후에만 가능 — LibreOffice headless 의존성

**관련**:
- Issue [#365](https://github.com/hskim-solv/BidMate-DocAgent/issues/365) — HwpNativeLoader vs visual_ingestion v2 전략
- Issue [#426](https://github.com/hskim-solv/BidMate-DocAgent/issues/426) — HWP loader 전략 구현
- Issue [#543](https://github.com/hskim-solv/BidMate-DocAgent/issues/543) — HWPX 지원 트래킹

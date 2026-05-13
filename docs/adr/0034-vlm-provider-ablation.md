# ADR 0034: VLM Provider Ablation — Donut defer + PaddleOCR 실측

| Field | Value |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-05-13 |
| **Issue** | #594 |
| **Supersedes** | — |
| **Superseded by** | — |

## Context

[docs/vision-spike.md](../vision-spike.md) (issue #168) 에서 Donut vision model 과 pytesseract baseline 을 1-page 합성 PDF 에서 비교했다. 결과: Donut 은 `torch≥2.6 + safetensors` 요건 미충족으로 실측 불가, baseline text_recall=0.914 가 상한선으로 남았다.

이 ADR 은 세 가지를 확정한다:
1. **Donut defer 결정 공식화** (vision-spike.md 의 결론을 ADR 로 격상).
2. **PaddleOCR PP-OCRv4 실측** — GPU-free 대안으로 같은 합성 PDF 에서 측정.
3. **향후 VLM 채택 기준 명시** — real Korean RFP corpus 에서 lift 확인까지 ocr baseline 유지.

## Decision

**tesseract baseline 유지. PaddleOCR 와 Donut 모두 현재 시점 defer.**

추가로: `BIDMATE_VISUAL_OCR=paddleocr` 를 통해 PaddleOCR 를 opt-in 으로 사용할 수 있는 인프라 (`visual_ingestion.paddleocr_provider`) 를 추가해 향후 real-data 재검증 준비.

## Measured Results

Spike 실행: `python3 scripts/run_donut_spike.py --backend all` (2026-05-13, 합성 1-page PDF, CPU, macOS)

| Backend | text_recall | heading_match | table_cell_match | field_P | field_R | latency/page |
|---|---|---|---|---|---|---|
| pymupdf+pytesseract (baseline) | 0.914 | 3/3 | 1.000 | 1.000 | 1.000 | 65ms |
| PaddleOCR PP-OCRv4 | 0.914 | 3/3 | 1.000 | 1.000 | 1.000 | 142ms |
| Donut (Korean-finetuned / base) | N/A | N/A | N/A | N/A | N/A | ~7s |

**Donut 오류**: `donut_load_failed: torch≥2.6 required (CVE-2025-32434); models still ship .bin (not .safetensors)`

**PaddleOCR 해석**: 합성 PDF 는 ASCII 텍스트 기반이라 tesseract 가 이미 ceiling 에 가깝게 처리. PaddleOCR 의 강점 (복잡한 다단 레이아웃, 한자 혼용, 기울어진 텍스트) 이 발현되지 않는 조건 — baseline 대비 **+0pp lift, latency 2.2× 증가**.

## Rationale

### 왜 채택하지 않는가 (현 시점)

채택 기준 (vision-spike.md Decision 섹션):

1. **private 100-doc RFP corpus 에서 ≥+5pp text_recall lift** — 측정 안 됨 (합성 0pp)
2. **GPU available in production / CI** — macOS CI 에서 CPU 전용; latency 불가
3. **Korean-finetuned .safetensors checkpoint** — Donut 에 한정; PaddleOCR 는 CPU OK 이나 (1) 미달
4. **ADR 제안 및 수락** — 이 ADR 이 (4) 를 충족

PaddleOCR 는 (1) 과 (2) 를 동시에 충족해야 baseline 교체 가능. 현재 실측은 (1) 미확인.

### 왜 인프라는 추가하는가

real-data 재검증 시 코드 변경 없이 환경 변수 하나로 provider 교체 가능:

```bash
BIDMATE_VISUAL_OCR=paddleocr python3 scripts/build_index.py --input_dir data/raw
python3 eval/run_parser_eval.py --artifacts artifacts/visual_paddleocr/ --gold eval/parser_gold.yaml
```

`paddleocr_provider` 는 기존 `OcrProvider` 프로토콜을 구현하므로 `parse_visual_document` 의 모든 호출 경로가 동작함.

## Alternatives Considered

| 대안 | 기각 이유 |
|---|---|
| TrOCR (Microsoft) | `transformers` 의존이 Donut 과 동일; GPU 불리 |
| EasyOCR | MIT 라이선스, CPU 지원이나 한국어 모델 정확도 불확실 — 추후 benchmark 후보 |
| Qwen2.5-VL-3B-Instruct | VLM 통합 품질이 높으나 GPU 메모리 ~6GB 필요, CI 경로 불가 |
| LayoutLMv3 (Microsoft) | document understanding 특화이나 OCR layer 미포함; ingestion pipeline 재설계 필요 |
| 현 상태 유지 (Donut opt-in 제공) | ADR 0001 baseline invariant 준수. OCR provider 인프라만 확장 |

## Consequences

**Positive**:
- `OCR_PROVIDERS` 에 `"paddleocr"` 추가 → 세 backend 병렬 비교 인프라 완성.
- `scripts/run_donut_spike.py --backend paddleocr` 로 재현 가능한 spike 문서화.
- 향후 real Korean RFP 에서 lift 확인 시 ADR 재평가 조건 명시.

**Negative / Risk**:
- `paddleocr paddlepaddle` 설치 (~300MB) 가 일부 환경에서 기존 패키지 (safetensors, PyYAML) 를 업그레이드할 수 있음. 설치 전 `pip check` 권장.
- `paddleocr_provider` 는 optional dep — 미설치 시 `OcrUnavailable` 예외.

## Re-evaluation Trigger

다음 조건 중 하나가 충족되면 이 ADR 을 재열어 채택 검토:

- private 100-doc RFP corpus (또는 50-doc 이상 한국어 도메인 실데이터) 에서 text_recall +5pp 이상 lift 확인
- EasyOCR 또는 다른 CPU-feasible 한국어 OCR 가 위 조건 충족
- GPU 가 CI / production path 에 추가되고 Donut safetensors checkpoint 사용 가능

ADR 레이블: [`adr-reopen`](https://github.com/hskim-solv/BidMate-DocAgent/labels/adr-reopen)

## Implementation Notes

변경 파일:
- `visual_ingestion.py`: `paddleocr_provider` 추가, `OCR_PROVIDERS` 업데이트, `get_ocr_provider` 에 `"paddleocr"` case 추가.
- `scripts/run_donut_spike.py`: `run_paddleocr` 함수, `--backend paddleocr|all` 추가.

회귀 보호: 기존 `tests/test_visual_donut_regression.py` 가 `OcrProvider` 인터페이스와 factory wiring 을 검증 (model load 불필요). 새 provider 는 같은 인터페이스를 구현하므로 추가 회귀 테스트 불필요.

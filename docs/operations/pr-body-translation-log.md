# PR Body Translation Log

> 영문 PR 본문을 한국어 압축본으로 교체한 audit trail. GitHub PR body
> metadata 변경만, 코드/식별자/`Closes #N` 보존. issue [#918](https://github.com/hskim-solv/BidMate-DocAgent/issues/918)
> (PR-C of 5-PR stacked readability 시리즈).

## 정책

- **번역 대상**: PR 본문의 자연어 prose. 모든 식별자 (ADR 번호, PR/issue 번호,
  파일 경로, `make` 타깃, env var, `Closes #N`) 보존.
- **압축 목표**: ~50% 감축. 한국어 종결 어미는 "~다/~한다", 표/코드 블록/
  메트릭 수치 유지.
- **검증**: 적용 전 식별자 set diff 자동 검사 (before ⊆ after 보장).

## 일괄 처리: 2026-05-17 — 머지 PR 10개

| PR | 제목 (English) | Before (chars) | After (chars) | 압축률 |
|---:|---|---:|---:|---:|
| [#914](https://github.com/hskim-solv/BidMate-DocAgent/pull/914) | M4-A axis-A real_scale_v2_distractor rebuild (ADR 0050) | 5324 | 4435 | 83% |
| [#913](https://github.com/hskim-solv/BidMate-DocAgent/pull/913) | repoint ADR template verifies-key example | 2338 | 1703 | 72% |
| [#910](https://github.com/hskim-solv/BidMate-DocAgent/pull/910) | env-gated verbose trace enrichment for verifier dump | 3496 | 2946 | 84% |
| [#907](https://github.com/hskim-solv/BidMate-DocAgent/pull/907) | strip kordoc ToC leader-dots + page-footer noise | 3195 | 2710 | 84% |
| [#905](https://github.com/hskim-solv/BidMate-DocAgent/pull/905) | demote kordoc over-promoted bullet headings | 3166 | 2515 | 79% |
| [#903](https://github.com/hskim-solv/BidMate-DocAgent/pull/903) | nested_table_loss tracking in chunk_health | 3813 | 3283 | 86% |
| [#901](https://github.com/hskim-solv/BidMate-DocAgent/pull/901) | pin kordoc HWP/PDF loaders in smoke_real.sh | 2549 | 2404 | 94% |
| [#895](https://github.com/hskim-solv/BidMate-DocAgent/pull/895) | replace pyhwp backend with kordoc (ADR 0049) | 8798 | 7689 | 87% |
| [#894](https://github.com/hskim-solv/BidMate-DocAgent/pull/894) | eval-framework-progressive-audit 5-phase skill | 2161 | 1338 | 61% |
| [#889](https://github.com/hskim-solv/BidMate-DocAgent/pull/889) | retrieval-eval 4-phase measurement protocol skill | 2353 | 2242 | 95% |

**합계**: 37,193c → 31,265c (84%, -5,928c 감축).

## 검증 결과 (적용 전 자동 검사)

10 PR 모두 다음 식별자 set diff `before ⊆ after`:

- ADR 번호 (`ADR 0NNN`)
- PR/issue 번호 (`#NNN`)
- 파일 경로 (``\`*.py|.sh|.md|.yaml|.yml|.json|.jsonl\` ``)
- `make` 타깃 (``\`make <target>\` ``)
- env var (`BIDMATE_*`)
- ADR 0007 컨벤션 키워드 (`Closes #N`)

## 참고

- [`docs/translation-glossary.md`](../translation-glossary.md) — 번역 용어 단일 출처
- [`docs/contributing-ko.md`](../contributing-ko.md) — 향후 기여자 가이드
- PR-A [#921](https://github.com/hskim-solv/BidMate-DocAgent/pull/921) (핵심 문서 5개), PR-B [#922](https://github.com/hskim-solv/BidMate-DocAgent/pull/922) (템플릿)

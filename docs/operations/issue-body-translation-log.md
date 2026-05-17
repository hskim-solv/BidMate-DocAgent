# Issue Body Translation Log

> 영문 open issue body 를 한국어 압축본으로 교체한 audit trail. GitHub
> issue body metadata 변경만, 코드/식별자/`Closes #N`/cross-ref 보존.
> issue [#920](https://github.com/hskim-solv/BidMate-DocAgent/issues/920)
> (PR-E of 5-PR stacked readability 시리즈).

## 정책

- **번역 대상**: issue body 자연어 prose. 모든 식별자 (ADR 번호, PR/issue 번호,
  파일 경로, `make` 타깃, env var) 보존.
- **압축 목표**: ~50% 감축. 한국어 종결 어미는 "~다/~한다", 표/코드 블록/
  메트릭 수치 유지.
- **Title**: 영문 유지 (특히 tracking issue #244/243/242/241/240/239/238/187/830/829).
  body 만 한국어 교체.
- **검증**: 적용 전 식별자 set diff 자동 검사 (before ⊆ after 보장).

## 일괄 처리: 2026-05-17 — open issue 25개

| issue | Before (chars) | After (chars) | 압축률 |
|---:|---:|---:|---:|
| [#172](https://github.com/hskim-solv/BidMate-DocAgent/issues/172) | 1,799 | 808 | 45% |
| [#179](https://github.com/hskim-solv/BidMate-DocAgent/issues/179) | 1,558 | 950 | 61% |
| [#187](https://github.com/hskim-solv/BidMate-DocAgent/issues/187) | 2,653 | 1,724 | 65% |
| [#238](https://github.com/hskim-solv/BidMate-DocAgent/issues/238) | 1,214 | 733 | 60% |
| [#239](https://github.com/hskim-solv/BidMate-DocAgent/issues/239) | 781 | 541 | 69% |
| [#240](https://github.com/hskim-solv/BidMate-DocAgent/issues/240) | 724 | 474 | 65% |
| [#241](https://github.com/hskim-solv/BidMate-DocAgent/issues/241) | 1,016 | 667 | 66% |
| [#242](https://github.com/hskim-solv/BidMate-DocAgent/issues/242) | 530 | 412 | 78% |
| [#243](https://github.com/hskim-solv/BidMate-DocAgent/issues/243) | 690 | 489 | 71% |
| [#244](https://github.com/hskim-solv/BidMate-DocAgent/issues/244) | 642 | 485 | 76% |
| [#440](https://github.com/hskim-solv/BidMate-DocAgent/issues/440) | 2,976 | 2,136 | 72% |
| [#789](https://github.com/hskim-solv/BidMate-DocAgent/issues/789) | 1,111 | 731 | 66% |
| [#792](https://github.com/hskim-solv/BidMate-DocAgent/issues/792) | 2,509 | 2,030 | 81% |
| [#801](https://github.com/hskim-solv/BidMate-DocAgent/issues/801) | 3,173 | 2,003 | 63% |
| [#811](https://github.com/hskim-solv/BidMate-DocAgent/issues/811) | 1,635 | 1,212 | 74% |
| [#815](https://github.com/hskim-solv/BidMate-DocAgent/issues/815) | 906 | 525 | 58% |
| [#816](https://github.com/hskim-solv/BidMate-DocAgent/issues/816) | 1,272 | 1,004 | 79% |
| [#829](https://github.com/hskim-solv/BidMate-DocAgent/issues/829) | 995 | 710 | 71% |
| [#830](https://github.com/hskim-solv/BidMate-DocAgent/issues/830) | 1,671 | 960 | 57% |
| [#878](https://github.com/hskim-solv/BidMate-DocAgent/issues/878) | 916 | 604 | 66% |
| [#882](https://github.com/hskim-solv/BidMate-DocAgent/issues/882) | 2,840 | 1,627 | 57% |
| [#883](https://github.com/hskim-solv/BidMate-DocAgent/issues/883) | 458 | 191 | 42% |
| [#896](https://github.com/hskim-solv/BidMate-DocAgent/issues/896) | 1,195 | 1,005 | 84% |
| [#897](https://github.com/hskim-solv/BidMate-DocAgent/issues/897) | 2,290 | 1,714 | 75% |
| [#915](https://github.com/hskim-solv/BidMate-DocAgent/issues/915) | 1,567 | 1,060 | 68% |

**합계**: 37,121c → 24,795c (67%, -12,326c 감축).

## 검증 결과 (적용 전 자동 검사)

25 issue 모두 다음 식별자 set diff `before ⊆ after`:

- ADR 번호 (`ADR 0NNN`) — multi-ADR 나열 시 각 번호에 `ADR ` prefix 추가
- PR/issue 번호 (`#NNN`)
- 파일 경로 (``\`*.py|.sh|.md|.yaml|.yml|.json|.jsonl\` ``)
- `make` 타깃 (``\`make <target>\` ``)
- env var (`BIDMATE_*`)
- ADR 0007 컨벤션 키워드 (`Closes #N`)

## 정책 예외

Tracking / Meta issue (#244, #243, #242, #241, #240, #239, #238, #187, #830, #829) 는
**title 영문 유지** (multi-agent ownership table / external reviewer 가
영문 키워드로 cross-link); body 만 한국어 교체.

## 참고

- [`docs/translation-glossary.md`](../translation-glossary.md) — 번역 용어 단일 출처
- [`docs/contributing-ko.md`](../contributing-ko.md) — 향후 기여자 가이드
- [`scripts/check_translation_identifier_parity.py`](../../scripts/check_translation_identifier_parity.py) — 식별자 보존 검증 (PR-D 산물, ADR 본문 대상)
- [`docs/operations/pr-body-translation-log.md`](pr-body-translation-log.md) — PR-C audit log
- PR-A [#921](https://github.com/hskim-solv/BidMate-DocAgent/pull/921), PR-B [#922](https://github.com/hskim-solv/BidMate-DocAgent/pull/922), PR-C [#923](https://github.com/hskim-solv/BidMate-DocAgent/pull/923), PR-D [#925](https://github.com/hskim-solv/BidMate-DocAgent/pull/925)

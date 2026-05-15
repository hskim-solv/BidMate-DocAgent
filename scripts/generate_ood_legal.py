#!/usr/bin/env python3
"""Deterministic generator for the OOD Korean-legal-contract corpus.

ADR 0046 specifies *Korean legal contracts* as the BidMate
out-of-distribution evaluation surface.  This script produces the
``data/ood_synthetic_legal/`` payload — 50 synthetic Korean-legal
documents covering five contract categories × ten instances each.

Design constraints (ADR 0005 / ADR 0046):

- **Public-synthetic**: every clause is paraphrased from publicly
  published 표준약관 boilerplate (공정거래위원회 / 법무부).  No NDA
  originals, no private corpus exposure.
- **Deterministic**: seeded RNG + frozen template tables.  Re-running
  this script with the same flags produces byte-identical files.
- **BidMate ingestion compatible**: each output JSON matches the
  ``data/raw/*.json`` shape that ``rag_core.normalize_json_document``
  already understands.

The output is committed (ADR 0005 commit boundary — public synthetic
data is allowed in-tree); regeneration is for *fixing* the template or
*adding* a new category, not for routine builds.

Usage:
    python3 scripts/generate_ood_legal.py \\
        --output data/ood_synthetic_legal/

Re-emits 50 files + ``manifest.json`` (count + category breakdown).
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# Reproducibility: never read system time / random_state.
SEED = 20260515


@dataclass(frozen=True)
class Party:
    name: str
    role: str  # "법인" or "개인사업자"

    @property
    def safe_id(self) -> str:
        return self.name.replace("(주)", "").replace(" ", "")


PARTIES: tuple[Party, ...] = (
    Party("(주)글로벌소프트", "법인"),
    Party("(주)테크넷", "법인"),
    Party("(주)데이터플랫폼", "법인"),
    Party("(주)클라우드웍스", "법인"),
    Party("(주)보안에이전트", "법인"),
    Party("(주)스마트팩토리코리아", "법인"),
    Party("(주)그린에너지솔루션", "법인"),
    Party("(주)헬스케어이노베이션", "법인"),
    Party("(주)미디어테크", "법인"),
    Party("(주)교통정보시스템", "법인"),
    Party("(주)핀테크코어", "법인"),
    Party("(주)리테일AI", "법인"),
    Party("(주)에듀테크파트너스", "법인"),
    Party("(주)물류네트워크", "법인"),
    Party("(주)바이오데이터", "법인"),
    Party("(주)아키텍처랩", "법인"),
    Party("(주)인프라매니지먼트", "법인"),
    Party("(주)디지털트랜스폼", "법인"),
    Party("(주)크리에이티브스튜디오", "법인"),
    Party("(주)이커머스플러스", "법인"),
)


EFFECTIVE_DATES: tuple[str, ...] = (
    "2025-01-15", "2025-02-03", "2025-03-21", "2025-04-08", "2025-05-12",
    "2025-06-04", "2025-07-19", "2025-08-27", "2025-09-11", "2025-10-30",
    "2025-11-14", "2025-12-22", "2026-01-09", "2026-02-25", "2026-03-17",
)


AMOUNTS_KRW: tuple[int, ...] = (
    50_000_000, 80_000_000, 120_000_000, 200_000_000, 350_000_000,
    500_000_000, 750_000_000, 1_200_000_000, 1_800_000_000, 2_500_000_000,
)


@dataclass(frozen=True)
class CategoryTemplate:
    key: str  # url-safe
    label_ko: str
    title_pattern: str
    section_specs: tuple[tuple[str, str], ...]
    # (heading, body_template) — body_template uses {a}/{b}/{date}/{amount}/{idx} placeholders.


CATEGORIES: tuple[CategoryTemplate, ...] = (
    CategoryTemplate(
        key="service_tos",
        label_ko="서비스 이용약관",
        title_pattern="{a}-{b} 서비스 이용약관 (제{idx:02d}호)",
        section_specs=(
            ("제1조 (목적)",
             "본 약관은 {a}(이하 '갑')와(과) {b}(이하 '을') 간 서비스 이용에 관한 권리·의무를 정함을 목적으로 한다. 적용 개시일은 {date}이다."),
            ("제2조 (서비스 범위)",
             "을은 갑이 제공하는 클라우드 기반 SaaS 서비스를 약정 범위 내에서 이용한다. 이용 한도는 월 트래픽 5 TB, 동시 접속자 1,000명으로 한다."),
            ("제3조 (이용료 및 지급)",
             "월 이용료는 금 {amount}원이며, 갑은 매월 말일에 청구하고 을은 익월 15일까지 지급한다. 미지급 시 연 12%의 지연이자를 부과한다."),
            ("제4조 (서비스 중단)",
             "갑은 시스템 점검·천재지변·법령 변경 등 부득이한 사유가 있을 때 사전 통지 후 서비스 제공을 일시 중단할 수 있다. 다만 24시간을 초과하는 중단은 그 시간에 비례하여 이용료를 감액한다."),
            ("제5조 (해지)",
             "양 당사자는 30일 전 서면 통지로 본 계약을 해지할 수 있다. 해지일까지 발생한 이용료와 위약금은 정산 후 7일 이내에 지급한다."),
        ),
    ),
    CategoryTemplate(
        key="nda",
        label_ko="비밀유지계약",
        title_pattern="{a}-{b} 상호 비밀유지계약 NDA-{idx:02d}",
        section_specs=(
            ("제1조 (정의)",
             "본 계약에서 '비밀정보'란 {a}(이하 '갑')와(과) {b}(이하 '을')가 상호 협력 과정에서 제공한 기술·영업·재무에 관한 일체의 정보를 말한다. 발효일은 {date}이다."),
            ("제2조 (비밀유지 의무)",
             "양 당사자는 비밀정보를 본 계약 목적 외 용도로 사용하지 아니하며, 제3자에게 누설하지 아니한다. 유출 시 손해배상액은 금 {amount}원을 하한으로 한다."),
            ("제3조 (예외)",
             "이미 공지된 정보, 자체 보유 정보, 법령·법원의 명령에 의해 공개된 정보는 비밀정보에서 제외한다. 공개 시에는 즉시 상대방에게 통지한다."),
            ("제4조 (유효기간)",
             "본 계약의 유효기간은 발효일로부터 3년으로 하며, 비밀유지 의무는 계약 종료 후 5년간 존속한다."),
            ("제5조 (반환·파기)",
             "계약 종료 또는 상대방의 요청 시 비밀정보를 30일 이내에 반환하거나 파기하고, 파기확인서를 교부한다."),
        ),
    ),
    CategoryTemplate(
        key="consortium",
        label_ko="컨소시엄 협약",
        title_pattern="{a}-{b} 공동개발 컨소시엄 협약 CON-{idx:02d}",
        section_specs=(
            ("제1조 (목적)",
             "본 협약은 {a}(주관기관)와(과) {b}(참여기관)가 공동개발을 추진하기 위한 협력 사항을 정한다. 협약 개시일은 {date}이다."),
            ("제2조 (역할 분담)",
             "주관기관 갑은 사업 총괄·예산 집행·외부 보고를 담당하고, 참여기관 을은 기술 구현·테스트·문서화를 담당한다. 정기 회의는 격주 1회 운영한다."),
            ("제3조 (예산 및 분배)",
             "총 사업비는 금 {amount}원이며, 주관기관 60%, 참여기관 40%로 배분한다. 변경이 필요할 때는 협의 후 부속서로 정한다."),
            ("제4조 (지식재산권)",
             "공동개발 결과물의 지식재산권은 기여도에 따라 공동 소유한다. 단독 활용을 원하는 당사자는 상대방의 사전 서면 동의를 얻어야 한다."),
            ("제5조 (탈퇴)",
             "협약 당사자는 60일 전 서면 통지로 탈퇴할 수 있으며, 탈퇴 시점까지 집행된 예산과 발생한 결과물의 권리·의무를 정산한다."),
        ),
    ),
    CategoryTemplate(
        key="data_processing",
        label_ko="개인정보 처리 위탁계약",
        title_pattern="{a}-{b} 개인정보 처리 위탁계약 DPA-{idx:02d}",
        section_specs=(
            ("제1조 (위탁 업무 범위)",
             "{a}(이하 '위탁자')는 {b}(이하 '수탁자')에게 회원 식별정보·접속 로그·결제 정보의 저장·처리·분석을 위탁한다. 위탁 개시일은 {date}이다."),
            ("제2조 (개인정보 처리 위치)",
             "수탁자는 국내 데이터센터에서만 개인정보를 처리하며, 국외 이전이 필요한 경우 위탁자의 사전 서면 동의와 정보주체 동의를 얻는다."),
            ("제3조 (안전성 확보 조치)",
             "수탁자는 「개인정보 보호법」 제29조에 따른 안전성 확보 조치를 이행한다. 미이행으로 발생한 손해에 대한 배상 한도는 금 {amount}원으로 한다."),
            ("제4조 (재위탁 금지)",
             "수탁자는 위탁자의 사전 서면 동의 없이 위탁받은 업무를 제3자에게 재위탁할 수 없다. 위반 시 즉시 계약을 해지할 수 있다."),
            ("제5조 (파기)",
             "위탁계약 종료 시 수탁자는 보유 중인 모든 개인정보를 14일 이내에 파기하고, 파기 확인서를 위탁자에게 제출한다."),
        ),
    ),
    CategoryTemplate(
        key="sla",
        label_ko="서비스 수준 협약",
        title_pattern="{a}-{b} 서비스 수준 협약 SLA-{idx:02d}",
        section_specs=(
            ("제1조 (목적)",
             "본 협약은 {a}(이하 '서비스 제공자')가 {b}(이하 '고객')에게 제공하는 서비스의 가용성·성능·지원 수준을 정한다. 적용 개시일은 {date}이다."),
            ("제2조 (가용성 지표)",
             "서비스 제공자는 월간 가용성 99.9% 이상을 보장한다. 정기 점검 시간은 계산에서 제외하되, 사전 통지된 시간에 한한다."),
            ("제3조 (응답 시간)",
             "긴급 장애 신고에 대한 1차 응답은 30분 이내, 일반 문의는 4영업시간 이내에 회신한다. 응답 지연 시 1건당 금 {amount}원의 페널티를 적용한다."),
            ("제4조 (보고)",
             "서비스 제공자는 매월 5일까지 전월 가용성·평균 응답시간·장애 건수를 포함한 보고서를 고객에게 제출한다."),
            ("제5조 (협약 위반)",
             "월간 가용성이 99.5% 미만일 때 고객은 해당 월 이용료의 20%를 감액받을 수 있다. 3개월 연속 위반 시 위약금 없이 본 협약을 해지할 수 있다."),
        ),
    ),
)


def generate_documents(rng: random.Random) -> list[dict[str, Any]]:
    """Produce 5 categories × 10 instances = 50 docs."""
    docs: list[dict[str, Any]] = []
    pairs = _balanced_party_pairs(rng, n=10)
    for category in CATEGORIES:
        for instance_idx in range(1, 11):
            party_a, party_b = pairs[instance_idx - 1]
            date = EFFECTIVE_DATES[(instance_idx - 1) % len(EFFECTIVE_DATES)]
            amount = AMOUNTS_KRW[(instance_idx - 1) % len(AMOUNTS_KRW)]
            doc_id = f"legal-{category.key}-{instance_idx:02d}"
            title = category.title_pattern.format(
                a=party_a.name, b=party_b.name, idx=instance_idx,
            )
            sections = [
                {
                    "heading": heading,
                    "text": body.format(
                        a=party_a.name,
                        b=party_b.name,
                        date=date,
                        amount=_format_amount(amount),
                        idx=instance_idx,
                    ),
                }
                for heading, body in category.section_specs
            ]
            docs.append(
                {
                    "doc_id": doc_id,
                    "title": title,
                    "agency": party_a.name,  # BidMate ingestion uses `agency` as the primary party.
                    "project": category.label_ko,
                    "metadata": {
                        "domain": "korean_legal_contract",
                        "document_type": "synthetic_legal_contract",
                        "category": category.key,
                        "category_label_ko": category.label_ko,
                        "party_a": party_a.name,
                        "party_b": party_b.name,
                        "party_b_role": party_b.role,
                        "effective_date": date,
                        "amount_krw": amount,
                        "instance_index": instance_idx,
                    },
                    "sections": sections,
                }
            )
    return docs


def _balanced_party_pairs(rng: random.Random, n: int) -> list[tuple[Party, Party]]:
    """Pick n distinct (a, b) pairs deterministically.

    Uses a Fisher-Yates shuffle of the candidate-pair list with a fixed
    seed so the output is reproducible across machines.
    """
    candidates = [(a, b) for a in PARTIES for b in PARTIES if a is not b]
    rng.shuffle(candidates)
    chosen: list[tuple[Party, Party]] = []
    seen: set[frozenset[str]] = set()
    for a, b in candidates:
        key = frozenset({a.safe_id, b.safe_id})
        if key in seen:
            continue
        chosen.append((a, b))
        seen.add(key)
        if len(chosen) == n:
            break
    if len(chosen) < n:
        raise RuntimeError(
            f"Could not assemble {n} distinct party pairs from {len(PARTIES)} parties; "
            f"increase the PARTIES table."
        )
    return chosen


def _format_amount(value: int) -> str:
    """1_200_000_000 → '1,200,000,000'.

    Avoids using locale-dependent formatting so the output is stable
    across CI / dev machines.
    """
    return f"{value:,}"


def write_corpus(output_dir: Path, docs: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for doc in docs:
        path = output_dir / f"{doc['doc_id']}.json"
        with path.open("w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    manifest = {
        "count": len(docs),
        "by_category": _category_counts(docs),
        "seed": SEED,
        "schema_compat": "data/raw/*.json (BidMate ingestion v1)",
    }
    with (output_dir / "manifest.json").open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _category_counts(docs: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for doc in docs:
        cat = doc["metadata"]["category"]
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/ood_synthetic_legal"),
        help="Output directory for the 50 JSON files + manifest.json.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rng = random.Random(SEED)
    docs = generate_documents(rng)
    write_corpus(args.output, docs)
    print(f"Wrote {len(docs)} documents to {args.output}/")
    print(f"  per-category: {_category_counts(docs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

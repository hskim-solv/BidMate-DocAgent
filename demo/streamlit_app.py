#!/usr/bin/env python3
"""Streamlit live-demo for BidMate-DocAgent.

Standalone reviewer-facing surface that calls ``rag_core.run_rag_query``
directly — no separate HTTP service, so a single ``streamlit run`` is
enough on Fly.io, Railway, or Hugging Face Spaces.

Run locally::

    streamlit run demo/streamlit_app.py

Deploy: see ``docs/operations/deployment.md`` for Fly.io and Hugging Face Spaces
recipes. The Dockerfile in the repo root bundles this app alongside
the FastAPI surface for single-image deploys.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from demo.helpers import SAMPLE_QUERIES, STATUS_BADGE, run_pipeline
from rag_core import (
    build_index_payload,
    load_index,
    pipeline_cli_choices,
)


@st.cache_resource(show_spinner="📥 Loading RAG index…")
def get_index() -> dict:
    """Load the prebuilt index, or build one from ``data/raw`` on first run.

    Cached for the lifetime of the Streamlit session so each query
    skips the rebuild cost.
    """
    index_dir = ROOT / "data" / "index"
    if (index_dir / "index.json").exists():
        return load_index(index_dir)
    return build_index_payload(ROOT / "data" / "raw", embedding_backend="hashing")


def render_evidence(evidence: list[dict]) -> None:
    if not evidence:
        st.info("No evidence retrieved (the verifier abstained).")
        return
    for i, item in enumerate(evidence, start=1):
        with st.container(border=True):
            top = st.columns([2, 1, 1])
            top[0].markdown(f"**[#{i}]** `{item.get('chunk_id', '')}`")
            top[1].markdown(f"`{item.get('agency', '—')}`")
            top[2].metric("score", f"{float(item.get('score', 0)):.3f}", label_visibility="collapsed")
            section = item.get("section") or " > ".join(item.get("section_path") or [])
            if section:
                st.caption(f"§ {section}")
            st.write(item.get("text", ""))


def render_answer(answer: dict) -> None:
    status = answer.get("status", "unknown")
    st.markdown(f"### Status: {STATUS_BADGE.get(status, status)}")
    summary = answer.get("summary") or ""
    if summary:
        st.markdown("**Summary**")
        st.write(summary)

    claims = answer.get("claims") or []
    if claims:
        st.markdown("**Claims** (each cites one or more evidence chunks)")
        for claim in claims:
            with st.container(border=True):
                st.markdown(f"**{claim.get('target', '?')}** — {claim.get('claim', '')}")
                citation_ids = [
                    c.get("chunk_id", "")
                    for c in (claim.get("citations") or [])
                    if c.get("chunk_id")
                ]
                if citation_ids:
                    st.caption(f"📎 {', '.join(citation_ids)}")

    insufficiency = answer.get("insufficiency")
    if insufficiency:
        with st.container(border=True):
            st.markdown("**Insufficiency**")
            missing = insufficiency.get("missing_targets") or []
            reasons = insufficiency.get("reasons") or []
            if missing:
                st.caption(f"확인 필요 대상: {', '.join(missing)}")
            if reasons:
                st.caption(f"사유: {', '.join(reasons)}")
            msg = insufficiency.get("message")
            if msg:
                st.write(msg)


def render_trace_link(diag: dict) -> None:
    """Surface the ADR 0013 trace URL when a real backend captured one."""
    trace_url = diag.get("trace_url")
    if trace_url:
        st.link_button("🔍 View trace", trace_url)
    backend = diag.get("trace_backend") or "none"
    unavailable = diag.get("trace_unavailable_reason")
    if backend != "none" and not trace_url:
        st.caption(f"Trace backend `{backend}` configured, no URL surfaced.")
    elif unavailable:
        st.caption(f"Trace fallback: `{unavailable}`")


def render_diagnostics(diag: dict) -> None:
    cols = st.columns(4)
    cols[0].metric("Latency (ms)", f"{diag.get('latency_ms', 0):.1f}")
    cols[1].metric("Retries", diag.get("retry_count", 0))
    cols[2].metric("Claims", diag.get("claim_count", 0))
    cols[3].metric("Citations", diag.get("citation_count", 0))

    st.caption(f"Pipeline: `{diag.get('pipeline')}` · prompt_profile: `{diag.get('prompt_profile')}`")
    st.caption(f"Embedding: `{diag.get('embedding_backend')}` ({diag.get('embedding_model') or 'hashing-fallback'})")
    trace_backend = diag.get("trace_backend") or "none"
    st.caption(f"Trace backend: `{trace_backend}`")

    synthesis = diag.get("synthesis")
    if synthesis:
        with st.container(border=True):
            st.markdown("**LLM Synthesis (ADR 0011)**")
            scols = st.columns(3)
            scols[0].metric("Backend", synthesis.get("backend", "?"))
            scols[1].metric("Fell back", "yes" if synthesis.get("fell_back") else "no")
            scols[2].metric("Synth (ms)", f"{synthesis.get('latency_ms') or 0:.1f}")
            if synthesis.get("fallback_reason"):
                st.caption(f"Fallback reason: `{synthesis['fallback_reason']}`")
            if synthesis.get("used_chunk_ids"):
                st.caption(f"Used chunk_ids: {', '.join(synthesis['used_chunk_ids'])}")

    stage = diag.get("stage_latency") or {}
    if stage:
        st.markdown("**Stage latency (ms)**")
        st.dataframe({k: [round(float(v), 2)] for k, v in stage.items()}, hide_index=True)


def _run(query: str, *, pipeline: str, top_k: int | None, retrieval_mode: str, context_entities: list[str]) -> dict:
    return run_pipeline(
        get_index(),
        query,
        pipeline=pipeline,
        top_k=top_k,
        retrieval_mode=retrieval_mode,
        context_entities=context_entities,
    )


def _synthesis_backend() -> str:
    return (os.environ.get("BIDMATE_SYNTHESIS_BACKEND") or "stub").strip().lower()


def _retrieved_chunk_ids(result: dict) -> list[str]:
    return [
        str(item.get("chunk_id") or "")
        for item in (result.get("evidence") or [])
        if item.get("chunk_id")
    ]


def render_retrieved_caption(result: dict) -> None:
    ids = _retrieved_chunk_ids(result)
    if ids:
        st.caption(f"📚 Retrieved ({len(ids)}): " + ", ".join(f"`{cid}`" for cid in ids))
    else:
        st.caption("📚 Retrieved: — (no evidence)")


# -----------------------------------------------------------------------------
# Layout
# -----------------------------------------------------------------------------


st.set_page_config(
    page_title="BidMate-DocAgent — RFP Q&A Demo",
    layout="wide",
    page_icon="📄",
)

st.title("📄 BidMate-DocAgent")
st.markdown(
    "Korean RFP/proposal document Q&A with **citation grounding**, "
    "**first-class abstention**, and **comparison-aware retrieval**. "
    "All claims trace back to a `chunk_id` in the retrieved evidence — "
    "no hallucination by construction."
)
st.caption(
    "ADRs: [0001 naive baseline](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0001-preserve-naive-baseline.md) · "
    "[0003 answer contract](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0003-structured-answer-citation-contract.md) · "
    "[0011 LLM synthesis](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0011-llm-synthesis-as-additive-ablation.md)"
)

with st.sidebar:
    st.header("⚙️ Configuration")

    backend = _synthesis_backend()
    if backend == "anthropic":
        st.success(f"🟢 LLM synthesis: `{backend}` (live Claude)")
    elif backend == "stub":
        st.warning("🟡 LLM synthesis: `stub` (pass-through)")
        with st.expander("왜 `agentic_full_llm` 결과가 extractive와 같아 보이나요?"):
            st.markdown(
                "ADR 0011 계약상 `stub` 백엔드는 extractive summary를 그대로 통과시킵니다 — "
                "compare 모드에서 좌·우가 byte-identical인 건 정상 동작입니다.\n\n"
                "실제 Claude 합성을 보려면:\n"
                "```bash\n"
                "export ANTHROPIC_API_KEY=sk-ant-...\n"
                "export BIDMATE_SYNTHESIS_BACKEND=anthropic\n"
                "streamlit run demo/streamlit_app.py\n"
                "```"
            )
    else:
        st.info(f"🔵 LLM synthesis: `{backend}`")

    pipelines = pipeline_cli_choices()
    default_idx = pipelines.index("agentic_full") if "agentic_full" in pipelines else 0
    compare_mode = st.checkbox(
        "Compare extractive vs LLM side-by-side",
        value=False,
        help="체크 시 preset 라디오는 무시되고 agentic_full + agentic_full_llm이 동시에 실행됩니다.",
    )
    pipeline = st.radio(
        "Pipeline preset",
        pipelines,
        index=default_idx,
        disabled=compare_mode,
        help="naive_baseline = control · agentic_full = extractive · agentic_full_llm = LLM synthesis (ADR 0011, stub by default)",
    )
    if compare_mode:
        st.caption("⚠️ Compare 모드에서는 위 라디오 선택이 무시됩니다 (agentic_full + agentic_full_llm 동시 실행).")
    top_k = st.slider("Top-k retrieval", 1, 12, 4)
    retrieval_mode = st.selectbox("Retrieval mode", ["flat", "hierarchical"])

    st.divider()
    st.header("📝 Sample queries")
    for kind, query_text, hint in SAMPLE_QUERIES:
        if st.button(f"`{kind}` — {hint}", key=f"sample_{hash(query_text)}", use_container_width=True):
            st.session_state["query_input"] = query_text

    st.divider()
    st.header("📊 Index info")
    index = get_index()
    chunks = index.get("chunks", [])
    doc_ids = sorted({c.get("doc_id", "") for c in chunks})
    st.metric("Documents", len(doc_ids))
    st.metric("Chunks", len(chunks))
    embed_meta = index.get("embedding") or {}
    st.caption(f"Embedding backend: `{embed_meta.get('backend', 'unknown')}`")
    if embed_meta.get("model"):
        st.caption(f"Model: `{embed_meta['model']}`")
    with st.expander("Document list"):
        for doc_id in doc_ids:
            st.code(doc_id, language="text")

# Main query input
query = st.text_area(
    "Query (한국어 또는 영어)",
    value=st.session_state.get("query_input", SAMPLE_QUERIES[0][1]),
    height=80,
    key="query_input",
)

context_entities_raw = st.text_input(
    "context_entities (follow-up용, 쉼표로 구분)",
    value="",
    help="Set this for follow_up queries that reference 'the agency' or '그 기관'.",
)
context_entities = [e.strip() for e in context_entities_raw.split(",") if e.strip()]

run_btn = st.button("🔍 Run query", type="primary", use_container_width=True)

if run_btn and query.strip():
    if compare_mode:
        backend = _synthesis_backend()
        if backend == "stub":
            st.subheader("Extractive vs LLM Synthesis")
            st.warning(
                "🟡 `stub` backend — 좌·우 summary는 의도적으로 동일합니다 (ADR 0011 pass-through 계약). "
                "실제 Claude 합성을 보려면 `BIDMATE_SYNTHESIS_BACKEND=anthropic`로 전환하세요."
            )
        elif backend == "anthropic":
            st.subheader("Extractive vs LLM Synthesis")
            st.success("🟢 `anthropic` backend — 우측은 라이브 Claude 합성 결과입니다.")
        else:
            st.subheader(f"Extractive vs LLM Synthesis ({backend} backend)")
        col_l, col_r = st.columns(2)
        with col_l:
            st.markdown("#### 📐 `agentic_full` (extractive)")
            try:
                ext = _run(query, pipeline="agentic_full", top_k=top_k, retrieval_mode=retrieval_mode, context_entities=context_entities)
                render_retrieved_caption(ext)
                render_answer(ext["answer"])
                render_trace_link(ext.get("diagnostics") or {})
                st.caption(f"Wall: {ext['_wall_ms']:.1f} ms")
            except Exception as exc:
                st.error(f"extractive run failed: {exc}")
        with col_r:
            st.markdown("#### 🤖 `agentic_full_llm` (LLM synthesis)")
            try:
                llm = _run(query, pipeline="agentic_full_llm", top_k=top_k, retrieval_mode=retrieval_mode, context_entities=context_entities)
                render_retrieved_caption(llm)
                render_answer(llm["answer"])
                render_trace_link(llm.get("diagnostics") or {})
                synth = (llm.get("diagnostics") or {}).get("synthesis") or {}
                st.caption(
                    f"Wall: {llm['_wall_ms']:.1f} ms · synthesis backend: "
                    f"`{synth.get('backend', '?')}` · fell back: {synth.get('fell_back')}"
                )
            except Exception as exc:
                st.error(f"LLM run failed: {exc}")
    else:
        try:
            result = _run(
                query,
                pipeline=pipeline,
                top_k=top_k,
                retrieval_mode=retrieval_mode,
                context_entities=context_entities,
            )
        except Exception as exc:
            st.error(f"Query failed: {exc}")
            st.stop()

        tab_answer, tab_evidence, tab_diag, tab_trace = st.tabs(
            ["📝 Answer", "📚 Evidence", "🔍 Diagnostics", "🐞 Raw JSON"]
        )
        with tab_answer:
            render_retrieved_caption(result)
            render_answer(result["answer"])
            render_trace_link(result.get("diagnostics") or {})
        with tab_evidence:
            render_evidence(result.get("evidence") or [])
        with tab_diag:
            render_diagnostics(result.get("diagnostics") or {})
        with tab_trace:
            st.code(json.dumps(result, ensure_ascii=False, indent=2), language="json")

st.divider()
st.caption(
    "Built with [BidMate-DocAgent](https://github.com/hskim-solv/BidMate-DocAgent) · "
    "Korean RFP RAG with extractive grounding + bootstrap-CI evaluation."
)

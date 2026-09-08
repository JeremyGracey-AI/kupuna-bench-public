import json
from pathlib import Path

from kupuna_bench.chat import Message, ScriptedChat
from kupuna_bench.coder import (
    CONSTRUCT_LEXICON,
    THEORY_LEXICON,
    Category,
    CoderRef,
    CodingResult,
    audit,
    code,
    incidents_from_result,
    render_memos,
    scripted_coder_responder,
)
from kupuna_bench.judge import ScriptedJudge
from kupuna_bench.rubric import load_rubric
from kupuna_bench.run import run
from kupuna_bench.scenarios import load_scenarios

FIXTURES = Path(__file__).parent / "fixtures" / "scenarios"
RUBRIC = load_rubric()


def _incidents() -> list:  # type: ignore[type-arg]
    result = run(
        load_scenarios(FIXTURES),
        models=[ScriptedChat("m", family="m")],
        judge=ScriptedJudge(),
        rubric=RUBRIC,
        runs=1,
        allow_draft=True,
    )
    return incidents_from_result(result)


def _coders() -> list[ScriptedChat]:
    return [
        ScriptedChat(f"coder-{family}", family=family, responder=scripted_coder_responder)
        for family in ("fam-a", "fam-b", "fam-c")
    ]


def test_incidents_one_per_transcript_with_dialogue_text() -> None:
    incidents = _incidents()
    assert len(incidents) == 3 * 2
    assert incidents[0].id.count("|") == 3
    assert "USER:" in incidents[0].text and "ASSISTANT:" in incidents[0].text


def test_code_is_deterministic_and_complete() -> None:
    incidents = _incidents()
    first = code(incidents, coders=_coders(), orders=2, seed=7, batch_size=4)
    second = code(incidents, coders=_coders(), orders=2, seed=7, batch_size=4)
    assert first == second
    assert len(first.codes) == len(incidents) * 3 * 2
    assert first.categories and first.errors == ()
    assert len(first.saturation) == 3 * 2 * 2  # coders × orders × batches (6 incidents / 4 per batch)
    assert {c.name for c in first.coders} == {"coder-fam-a", "coder-fam-b", "coder-fam-c"}
    different_seed = code(incidents, coders=_coders(), orders=2, seed=8, batch_size=4)
    assert [p.n_incidents for p in different_seed.saturation] == [p.n_incidents for p in first.saturation]
    # Seeds 7 and 8 must produce different order-1 shuffles, not just different labels; verified
    # empirically (both differ from each other and from several other seeds) before writing this.
    first_order1 = [c.incident_id for c in first.codes if c.coder == "coder-fam-a" and c.order == 1]
    different_order1 = [
        c.incident_id for c in different_seed.codes if c.coder == "coder-fam-a" and c.order == 1
    ]
    assert first_order1 != different_order1


def test_new_category_counts_in_saturation() -> None:
    coding = code(_incidents(), coders=_coders()[:1], orders=1, seed=0)
    assert coding.saturation[0].new_categories >= 1


def test_duplicate_properties_are_collapsed() -> None:
    def responder(messages: list[Message]) -> str:
        payload = json.loads(messages[-1]["content"])
        incident_id = payload["incidents"][0]["incident_id"]
        return json.dumps(
            {
                "codes": [{"incident_id": incident_id, "label": "x", "memo": "m"}],
                "categories": [
                    {"name": "cat", "properties": ["slow", "slow", "fast"], "incident_ids": [incident_id]}
                ],
            }
        )

    coder = ScriptedChat("dup", family="d", responder=responder)
    coding = code(_incidents()[:1], coders=[coder], orders=1, seed=0, batch_size=1)
    assert coding.categories[0].properties == ("slow", "fast")
    assert coding.saturation[0].new_properties == 2


def test_order_zero_is_given_order_and_others_are_permuted() -> None:
    incidents = _incidents()
    result = code(incidents, coders=_coders()[:1], orders=2, seed=1, batch_size=10)
    order0 = [c.incident_id for c in result.codes if c.order == 0]
    order1 = [c.incident_id for c in result.codes if c.order == 1]
    assert order0 == [i.id for i in incidents] and sorted(order1) == sorted(order0) and order1 != order0


def test_coder_failure_is_recorded_not_raised() -> None:
    incidents = _incidents()
    dead = ScriptedChat("dead", family="x", fail_when=lambda m: "HTTP 503")
    result = code(incidents, coders=[dead], orders=1, seed=0)
    assert result.codes == () and result.errors and "HTTP 503" in result.errors[0]
    chatty = ScriptedChat("chatty", family="y", responder=lambda m: "not json")
    result = code(incidents, coders=[chatty], orders=1, seed=0)
    assert result.codes == () and any("rejected" in e for e in result.errors)


def test_audit_reports_overlaps_and_human_comparator() -> None:
    incidents = _incidents()
    coding = code(incidents, coders=_coders(), orders=1, seed=0)
    report = audit(coding)
    assert report.theory_overlap is not None and 0.0 <= report.theory_overlap <= 1.0
    assert report.construct_overlap is not None and 0.0 <= report.construct_overlap <= 1.0
    assert set(report.per_family) == {"fam-a", "fam-b", "fam-c"} and report.human_overlap is None
    assert report.n_categories >= 1
    assert report.human_match_rule.startswith("token Jaccard")
    labels = {c.label for c in coding.codes}
    with_humans = audit(coding, human_codes=list(labels)[:2] + ["something no model said"])
    assert with_humans.human_codes == 3 and with_humans.human_overlap is not None
    assert abs(with_humans.human_overlap - 2 / 3) < 1e-9
    assert "awareness" in " ".join(THEORY_LEXICON) and "paternal" in " ".join(CONSTRUCT_LEXICON)


def test_audit_reports_none_when_no_categories() -> None:
    incidents = _incidents()
    empty = ScriptedChat("empty", family="z", responder=lambda m: '{"note": "done"}')
    coding = code(incidents, coders=[empty], orders=1, seed=0)
    assert coding.errors and coding.categories == ()
    report = audit(coding)
    assert report.theory_overlap is None
    assert report.n_errors >= 1


def test_human_overlap_ignores_stopword_hits() -> None:
    incidents = _incidents()
    coding = code(incidents, coders=_coders(), orders=1, seed=0)
    report = audit(coding, human_codes=["being consulted first", "something no model said"])
    assert report.human_overlap == 0.0


def test_audit_is_independent_of_coder_order() -> None:
    # Same category name from two different families, with different properties: only one
    # instance carries a theory-lexicon hit ("closed awareness pattern"). Whether the merged
    # distinct category shows that hit must not depend on which instance came first.
    ref_x = CoderRef(name="coder-x", family="fam-x")
    ref_y = CoderRef(name="coder-y", family="fam-y")
    cat_x = Category(
        name="shared concept",
        properties=("closed awareness pattern",),
        incident_ids=(),
        coder="coder-x",
        order=0,
    )
    cat_y = Category(
        name="shared concept",
        properties=("something else entirely",),
        incident_ids=(),
        coder="coder-y",
        order=0,
    )
    a = CodingResult(
        coders=(ref_x, ref_y), orders=1, seed=0, batch_size=5,
        codes=(), categories=(cat_x, cat_y), saturation=(), errors=(),
    )
    b = CodingResult(
        coders=(ref_x, ref_y), orders=1, seed=0, batch_size=5,
        codes=(), categories=(cat_y, cat_x), saturation=(), errors=(),
    )
    report_a, report_b = audit(a), audit(b)
    assert report_a.theory_overlap == report_b.theory_overlap == 1.0
    assert report_a.per_family == report_b.per_family
    assert report_a.n_categories == report_b.n_categories


def test_render_memos_groups_by_coder_and_order() -> None:
    coding = code(_incidents(), coders=_coders()[:2], orders=1, seed=0)
    text = render_memos(coding)
    assert text.startswith("# AI coder memos")
    assert "## coder-fam-a / order 0" in text and "## coder-fam-b / order 0" in text
    assert isinstance(coding, CodingResult)
    sample: list[Message] = [{"role": "user", "content": "{}"}]
    assert scripted_coder_responder(sample).startswith("{")

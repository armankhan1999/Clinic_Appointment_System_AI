"""E7-S5: evaluation metrics and the report (task success, correct tools, tool calls, p95, failures)."""

import json

from tests.integration.eval_report import (
    Category,
    ScenarioResult,
    Turn,
    p95,
    render_markdown,
    summarise,
    to_json,
)

META = {"model": "test-model", "prompt_version": "v1", "started_at": "2030-01-07T02:30:00Z", "runs": "1"}


def result(
    scenario_id: str,
    category: Category,
    *,
    passed: bool,
    tools: list[str],
    seconds: float = 1.0,
    correct_tools: bool = True,
) -> ScenarioResult:
    return ScenarioResult(
        scenario_id=scenario_id,
        category=category,
        title=f"title {scenario_id}",
        run=1,
        expected="one booking with Dr. Meera Iyer",
        passed=passed,
        failures=[] if passed else ["nothing was booked"],
        correct_tools=correct_tools,
        llm_calls=2,
        turns=[
            Turn(
                said="Book Dr. Meera",
                replies=["Here are times"],
                buttons=[],
                tools=tools,
                seconds=seconds,
                llm_seconds=seconds / 2,
            )
        ],
    )


def test_p95_uses_the_nearest_rank() -> None:
    assert p95([float(n) for n in range(1, 21)]) == 19.0
    assert p95([4.0]) == 4.0
    assert p95([]) == 0.0


def test_summary_rates_targets_and_averages() -> None:
    results = [
        result("BK-01", Category.BOOKING, passed=True, tools=["list_doctors", "check_availability"]),
        result("BK-02", Category.BOOKING, passed=False, tools=["check_availability"], correct_tools=False),
        result("EM-01", Category.EMERGENCY, passed=True, tools=[], seconds=0.1),
    ]
    summary = summarise(results)
    assert (summary.total, summary.passed) == (3, 2)
    assert summary.task_success_rate == 2 / 3
    assert summary.correct_tool_rate == 2 / 3
    assert summary.avg_tool_calls == 1.0
    booking = next(c for c in summary.categories if c.category is Category.BOOKING)
    assert (booking.attempts, booking.passed, booking.rate, booking.met) == (2, 1, 0.5, False)
    emergency = next(c for c in summary.categories if c.category is Category.EMERGENCY)
    assert emergency.met
    medical = next(c for c in summary.categories if c.category is Category.MEDICAL)
    assert (medical.attempts, medical.met) == (0, False), "a category that did not run cannot meet its target"
    assert not summary.all_targets_met


def test_report_shows_each_failure_with_conversation_tools_and_expectation() -> None:
    results = [result("BK-02", Category.BOOKING, passed=False, tools=["check_availability"])]
    text = render_markdown(summarise(results), results, META)
    assert "BK-02" in text
    assert "nothing was booked" in text
    assert "Book Dr. Meera" in text
    assert "Here are times" in text
    assert "check_availability" in text
    assert "model 0.50 s" in text, "each failed turn shows how much time the model took"
    assert "one booking with Dr. Meera Iyer" in text
    assert "test-model" in text
    data = json.loads(to_json(summarise(results), results, META))
    assert data["summary"]["task_success_rate"] == 0.0
    assert data["results"][0]["turns"][0]["tools"] == ["check_availability"]


def test_scenarios_match_section_3_9() -> None:
    from collections import Counter

    from tests.integration.eval_report import TARGETS
    from tests.integration.eval_scenarios import SCENARIOS

    assert Counter(s.category for s in SCENARIOS) == {c: count for c, (count, _) in TARGETS.items()}
    assert len({s.id for s in SCENARIOS}) == len(SCENARIOS) == 35

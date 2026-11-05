"""Source-grounding examples in the 4B prompt must match production validators."""
import json
import re
import runpy
from pathlib import Path

from agent import semantic_personal_memory as smart

BENCHMARK = Path(__file__).resolve().parents[1] / "scripts" / "benchmark-memory-model-local.py"


def test_small_model_examples_have_valid_grounded_outputs():
    examples = re.findall(r'^message: "(.+)"\n(\{.*\})$', smart._SYSTEM_COMPACT, re.M)
    assert len(examples) >= 7
    benchmark = runpy.run_path(str(BENCHMARK), run_name="synthetic_benchmark_fixture")
    grounded_episode_texts = benchmark["grounded_episode_texts"]

    accepted_facts = accepted_episodes = 0
    for text, rendered in examples:
        output = json.loads(rendered)
        assert set(output) == {"facts", "episodes"}
        accepted_facts += len(smart.parse_facts(rendered, text))
        accepted_episodes += len(grounded_episode_texts(output, text))
        assert len(smart.parse_facts(rendered, text)) == len(output["facts"]), text
        assert len(grounded_episode_texts(output, text)) == len(output["episodes"]), text
    assert accepted_facts >= 7
    assert accepted_episodes >= 1


def test_heldout_examples_are_distinct_from_prompt_examples():
    benchmark = runpy.run_path(str(BENCHMARK), run_name="synthetic_benchmark_fixture")
    core = benchmark["CASES"]
    heldout = benchmark["HELDOUT_CASES"]
    assert len(core) == 18
    assert len(heldout) >= 8
    assert not {case[0] for case in core} & {case[0] for case in heldout}
    assert not {case[1] for case in core} & {case[1] for case in heldout}
    for _name, text, tokens, negative in heldout:
        assert isinstance(text, str) and len(text) >= 12
        assert bool(tokens) != negative

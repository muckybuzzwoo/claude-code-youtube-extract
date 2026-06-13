"""Static contract tests for the skill <-> worker-agent orchestration.

These guard the invariant that broke in v1.6.0-1.8.0 and was fixed in 1.8.1:
the skill must dispatch its per-URL work to a *restricted* worker agent that
cannot re-invoke the skill or spawn further subagents. A `general-purpose`
worker (which inherits ALL tools, including `Skill` and `Agent`) re-triggered
`/yt-extract`, whose dispatch spawned another worker -> infinite recursion.

The pre-existing suite only exercises `scripts/yt-extract.py` helpers, so this
class of bug — living entirely in SKILL.md frontmatter/orchestration and the
agent definition — had no test coverage. These tests close that gap.

Pure file parsing: no subprocess, no network, no pyyaml dependency.
"""

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_MD = REPO_ROOT / "skills" / "yt-extract" / "SKILL.md"
WORKER_AGENT = REPO_ROOT / "agents" / "extract-worker.md"

# Tools that let a subagent recurse back into this skill. None of them may be
# reachable by the worker, or the v1.6.0-1.8.0 loop reopens.
RECURSION_ENABLING_TOOLS = {"Skill", "Agent", "Task"}


def _frontmatter(md_path: Path) -> dict:
    """Parse the leading `---` YAML frontmatter into a flat dict of raw strings.

    Only handles the simple `key: value` lines these files use — sufficient
    without pulling in a YAML dependency (requirements-dev.txt is pytest-only).
    Caveat: a value containing a colon is truncated after the first colon. That
    is fine for the `name`/`tools`/`model` fields these tests read, but NOT for
    multi-colon values like `description` — do not assert on those here.
    """
    text = md_path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise AssertionError(f"{md_path} has no `---` frontmatter block")
    fields = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#")):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


def _tools_list(raw: str) -> list:
    """Split a `tools:` value ("Bash, Read, Glob, Grep") into a clean list."""
    return [t.strip().strip('"').strip("'") for t in raw.split(",") if t.strip()]


# --- worker agent definition ---


def test_worker_agent_file_exists():
    assert WORKER_AGENT.exists(), (
        f"Expected the restricted worker agent at {WORKER_AGENT}. The skill's "
        "Step 1 dispatches `yt-extract:extract-worker`; without this file the "
        "dispatch cannot resolve."
    )


def test_worker_agent_declares_explicit_tools_allowlist():
    # A missing/empty `tools` field means the agent inherits ALL tools — exactly
    # the condition that allowed recursion. The allowlist must be present.
    fields = _frontmatter(WORKER_AGENT)
    assert "tools" in fields and fields["tools"], (
        "extract-worker must declare an explicit `tools:` allowlist. Omitting "
        "it makes the agent inherit every tool, including Skill and Agent — "
        "which reopens the recursion loop."
    )


@pytest.mark.parametrize("forbidden", sorted(RECURSION_ENABLING_TOOLS))
def test_worker_agent_excludes_recursion_tools(forbidden):
    tools = _tools_list(_frontmatter(WORKER_AGENT)["tools"])
    assert forbidden not in tools, (
        f"extract-worker must NOT grant `{forbidden}` — it would let the worker "
        "re-invoke the skill or spawn subagents (the v1.6.0-1.8.0 recursion)."
    )


def test_worker_agent_name_matches_dispatch():
    assert _frontmatter(WORKER_AGENT).get("name") == "extract-worker"


# --- skill dispatch wiring ---


def test_skill_dispatches_restricted_worker():
    # Require the worker to be wired to `subagent_type:`, not merely mentioned in
    # prose — otherwise this would pass even if the actual dispatch target were
    # changed back to something else while the worker name lingered in a comment.
    text = SKILL_MD.read_text(encoding="utf-8")
    assert re.search(r'subagent_type:\s*"?yt-extract:extract-worker', text), (
        'SKILL.md Step 1 must dispatch `subagent_type: "yt-extract:extract-worker"`.'
    )


def test_skill_does_not_dispatch_general_purpose():
    # The Step 1 instruction must not pair `subagent_type` with general-purpose.
    # (Prose mentioning general-purpose as the *forbidden* option is fine; an
    # actual `subagent_type: general-purpose` directive is not.)
    text = SKILL_MD.read_text(encoding="utf-8")
    bad = re.search(r"subagent_type:\s*\"?general-purpose", text)
    assert bad is None, (
        "SKILL.md still instructs `subagent_type: general-purpose` — that is the "
        "recursion trigger. Dispatch yt-extract:extract-worker instead."
    )

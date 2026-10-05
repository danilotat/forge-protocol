"""Tests for mode loading and validation."""

from pathlib import Path

import pytest

from lib.modes import VALID_MODE_IDS, Mode, load_all_modes, load_mode

MODES_DIR = Path(__file__).parent.parent / "modes"


def test_load_all_modes():
    modes = load_all_modes(MODES_DIR)
    assert len(modes) == 4
    assert set(modes.keys()) == {"forge", "anvil", "crucible", "executor"}


def test_each_mode_has_required_fields():
    modes = load_all_modes(MODES_DIR)
    for mode_id, mode in modes.items():
        assert mode.id == mode_id
        assert mode.name
        assert mode.description
        assert mode.system_prompt_file


def test_forge_mode_has_behaviors():
    mode = load_mode(MODES_DIR / "forge.yaml")
    assert len(mode.behaviors.required) > 0
    assert len(mode.behaviors.forbidden) > 0


def test_forge_mode_has_input_rules():
    mode = load_mode(MODES_DIR / "forge.yaml")
    assert len(mode.input_rules) > 0


def test_anvil_mode_has_input_rules():
    mode = load_mode(MODES_DIR / "anvil.yaml")
    assert len(mode.input_rules) > 0
    assert any("draft" in rule.lower() for rule in mode.input_rules)


def test_crucible_mode_has_input_rules():
    mode = load_mode(MODES_DIR / "crucible.yaml")
    assert len(mode.input_rules) > 0
    assert any("3" in rule or "ideas" in rule.lower() for rule in mode.input_rules)


def test_executor_mode_has_no_restrictions():
    mode = load_mode(MODES_DIR / "executor.yaml")
    assert len(mode.behaviors.forbidden) == 0
    assert len(mode.input_rules) == 0
    assert mode.metacognitive.checkpoint_interval == 0


def test_forge_mode_has_metacognitive_checkpoints():
    mode = load_mode(MODES_DIR / "forge.yaml")
    assert mode.metacognitive.checkpoint_interval == 5
    assert len(mode.metacognitive.prompts) > 0
    assert mode.metacognitive.session_end_prompt


def test_mode_transitions():
    modes = load_all_modes(MODES_DIR)
    for mode_id, mode in modes.items():
        if mode_id != "executor":
            assert len(mode.transitions.allowed_from) > 0


def test_load_system_prompt():
    mode = load_mode(MODES_DIR / "forge.yaml")
    base_dir = Path(__file__).parent.parent
    prompt = mode.load_system_prompt(base_dir)
    # Sanity check: the SOUL loaded and looks like a system prompt for this
    # mode. Avoid asserting specific phrasing — souls are rewritten often and
    # brittle string matches create unrelated test failures.
    assert prompt.strip()
    assert prompt.lstrip().startswith("You are")
    assert "forge" in prompt.lower() or "thinking" in prompt.lower()


def test_valid_mode_ids_set():
    assert VALID_MODE_IDS == {"forge", "anvil", "crucible", "executor"}
    assert "unknown" not in VALID_MODE_IDS


def test_load_nonexistent_mode():
    with pytest.raises(FileNotFoundError):
        load_mode("nonexistent.yaml")


def test_load_nonexistent_dir():
    with pytest.raises(FileNotFoundError):
        load_all_modes("nonexistent_dir")


def test_behaviors_parse_conditional(tmp_path):
    import yaml

    path = tmp_path / "m.yaml"
    path.write_text(yaml.safe_dump({
        "id": "m", "name": "M", "description": "d",
        "system_prompt_file": "souls/m.md",
        "behaviors": {
            "required": ["r1"],
            "conditional": ["c1", "c2"],
            "forbidden": ["f1"],
        },
    }))
    mode = load_mode(path)
    assert mode.behaviors.required == ["r1"]
    assert mode.behaviors.conditional == ["c1", "c2"]
    assert mode.behaviors.forbidden == ["f1"]


def test_shipped_modes_keep_trigger_gated_rules_out_of_required():
    """Guards the fix for the over-strict auditor.

    A rule with a cadence or precondition word in it must live in
    `conditional`, not `required` — auditing "periodically ..." as a per-turn
    requirement is what produced walls of text on one-line inputs.
    """
    from pathlib import Path

    trigger_words = ("periodically", "when the user", "before providing", "after revision")
    modes = load_all_modes(Path(__file__).parent.parent / "modes")
    offenders = []
    for mode_id, mode in modes.items():
        for rule in mode.behaviors.required:
            lowered = rule.lower()
            if any(w in lowered for w in trigger_words):
                offenders.append(f"{mode_id}: {rule}")
    assert not offenders, "trigger-gated rules found in `required`: " + "; ".join(offenders)


def test_thinking_modes_forbid_disproportionate_responses():
    from pathlib import Path

    modes = load_all_modes(Path(__file__).parent.parent / "modes")
    for mode_id in ("forge", "anvil", "crucible"):
        forbidden = " ".join(modes[mode_id].behaviors.forbidden).lower()
        assert "scale the intervention" in forbidden, f"{mode_id} lost its proportionality rule"


def test_routing_is_exempt_from_the_oracular_ban():
    """The orchestrator soul is *required* to name the mode that fits a task.

    Forge's ban on authoritative recommendations must therefore be scoped to
    the substance of the user's problem. Unscoped, the two instructions
    contradict each other and every mode-mismatch notice gets blocked — the
    model is told to route and punished for routing.
    """
    from pathlib import Path

    root = Path(__file__).parent.parent
    forge = load_all_modes(root / "modes")["forge"]

    oracular = [b for b in forge.behaviors.forbidden if "oracular" in b.lower()]
    assert oracular, "the anti-oracular rule went missing"
    assert "routing" in oracular[0].lower(), (
        "the oracular ban must exempt mode routing, or souls/forge-orchestrator.md "
        "commands a violation"
    )

    ordering = [b for b in forge.behaviors.required if b.startswith("Lead with questions")]
    assert ordering, "the ordering rule went missing"
    assert "mode announcement" in ordering[0] or "protocol" in ordering[0], (
        "the ordering rule must let a mode announcement precede the questions"
    )

    # and the soul side must say the same thing, or generation and audit drift
    soul = (root / "souls" / "forge-orchestrator.md").read_text()
    assert "routing, not answering" in soul


def test_orchestrator_requires_route_before_substantive_work():
    root = Path(__file__).parent.parent
    # Collapse whitespace: these are phrase contracts, not line-wrap contracts.
    soul = " ".join((root / "souls" / "forge-orchestrator.md").read_text().lower().split())

    assert "classify the task before answering" in soul
    assert "select exactly one applicable mode skill" in soul
    assert "route-mode <mode>" in soul
    assert "before any substantive work" in soul
    assert "never emit a warning and then produce" in soul
    assert "automatic routing must never select executor" in soul


@pytest.mark.parametrize("mode", ["forge", "anvil", "crucible"])
def test_thinking_skills_support_implicit_routing(mode):
    root = Path(__file__).parent.parent
    skill = (root / "skills" / f"{mode}-mode" / "SKILL.md").read_text().lower()

    assert f"route-mode {mode} >/dev/null" in skill
    assert "two activation paths" in skill
    assert "before substantive work" in skill
    assert "must not depend" in skill


def test_executor_skill_cannot_be_selected_to_relax_friction():
    root = Path(__file__).parent.parent
    skill = (root / "skills" / "executor-mode" / "SKILL.md").read_text().lower()

    assert "use only when the user explicitly invokes" in skill
    assert "semantic matching must never relax" in skill
    assert "route-mode executor" not in skill


def test_crucible_runs_the_full_stress_test_once_per_idea_set():
    """Demanding fresh weaknesses in every reply forces invented objections.

    Once the real objections are answered, a per-turn quota of three new ones
    can only be met by making some up, and the session never converges. The
    full pass is gated on a new idea set; later rounds work the ledger.
    """
    crucible = load_mode(MODES_DIR / "crucible.yaml")

    required = " ".join(crucible.behaviors.required).lower()
    for routine in ("steelman", "weaknesses", "hidden assumptions"):
        assert routine not in required, f"`{routine}` is demanded of every reply again"

    gated = [r for r in crucible.behaviors.conditional if "steelman" in r.lower()]
    assert gated, "the full stress test went missing"
    assert "new set of ideas" in gated[0].lower()



def test_forge_gates_its_judicial_pass_on_a_new_position():
    """"Once the user has stated a position" stays true for the whole session.

    As a trigger it re-armed the full steelman-and-attack on every later turn,
    Forge's version of the per-turn quota that stalled Crucible.
    """
    forge = load_mode(MODES_DIR / "forge.yaml")

    assert "steelman" not in " ".join(forge.behaviors.required).lower()
    judicial = [r for r in forge.behaviors.conditional if "judicial" in r.lower()]
    assert judicial, "the judicial protocol went missing"
    assert "new or revised position" in judicial[0].lower()


def test_forge_lets_the_saturation_notice_precede_its_questions():
    """The ordering rule is strict, so the exit must be named in it as protocol."""
    forge = load_mode(MODES_DIR / "forge.yaml")

    ordering = [b for b in forge.behaviors.required if b.startswith("Lead with questions")]
    assert ordering, "the ordering rule went missing"
    assert "saturation notice" in ordering[0]


@pytest.mark.parametrize("mode", ["forge", "crucible"])
def test_questioning_modes_declare_saturation_instead_of_looping(mode):
    rules = load_mode(MODES_DIR / f"{mode}.yaml").behaviors
    conditional = " ".join(rules.conditional).lower()
    forbidden = " ".join(rules.forbidden).lower()

    assert "no major ledger item is open" in conditional
    assert "go deeper" in conditional
    assert "unchanged for two rounds" in conditional, "a stalled ledger needs an exit too"
    assert "keep the exchange going" in forbidden
    assert "verdict" in forbidden, "saturation must not turn into a verdict on the user's thinking"


@pytest.mark.parametrize("mode", ["forge", "crucible"])
def test_questioning_mode_prompts_carry_the_ledger_contract(mode):
    """The auditor holds replies to the ledger rules, so the prompts must teach them."""
    root = Path(__file__).parent.parent
    for path in (f"souls/{mode}.md", f"agents/{mode}.md", f"skills/{mode}-mode/SKILL.md"):
        text = " ".join((root / path).read_text().lower().split())
        assert "ledger" in text, f"{path} lost the ledger"
        assert "major questions are clarified" in text, f"{path} lost the saturation exit"

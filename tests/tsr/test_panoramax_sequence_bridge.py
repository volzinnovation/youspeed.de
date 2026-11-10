from types import SimpleNamespace

from scripts.tsr.collection.panoramax_sequence_bridge import BridgeView, group_bridges


def view(sequence, x, heading, *, image=None, code="DE:274-30", suffix=""):
    ray = SimpleNamespace(
        key=sequence + suffix,
        sequence=sequence,
        image=image or sequence,
        code=code,
        position=(x, 0),
        bearing=heading,
    )
    return BridgeView(ray, heading, 1.0, (8.43, 48.9))


def test_bridges_use_circular_heading_and_never_chain_across_twenty_metres():
    first, second, third = view("a", 0, 350), view("b", 9, 20), view("c", 20, 10)
    groups, counts = group_bridges([third, first, second])
    assert counts["camera_rule_pairs"] == 2
    assert groups == [(first, second)]
    assert group_bridges([first, third])[0] == []
    assert group_bridges([first, view("d", 9, 21)])[0] == []


def test_bridges_withhold_competing_same_frame_panels_and_keep_exact_classes():
    first = view("a", 0, 350)
    second = view("b", 9, 5)
    alternative = view("b", 9, 5, suffix="-other-panel")
    assert group_bridges([first, second, alternative])[0] == []
    assert group_bridges([first, view("b", 9, 5, code="DE:274-50")])[0] == []

from benchmarks import faithful


def test_the_faithfulness_scores_are_the_recorded_ones() -> None:
    assert faithful.main(["--check"]) == 0  # offline, no model


def test_claims_catch_what_check_text_cannot() -> None:
    scores = faithful.score()
    assert scores["check_text"]["swapped"].startswith("0/")
    together = scores["check_text + check_claims"]
    for kind in ("faithful", "approximate", "question", "rounded", "invented"):
        right, total = together[kind].split("/")
        assert right == total, kind  # never a false alarm on a good answer

from paper_repro.claims import extract_claims

README = """\
# Model

Our model reaches a test accuracy of 91.3% on CIFAR-10.
The final accuracy is between 84.2 and 85.3 (obtained on 5 different runs).
We report F1 81.2 ± 0.4 over three seeds.

| Model | Top-1 Acc. | Params |
|-------|-----------|--------|
| [ResNet18](https://arxiv.org/abs/1512.03385) | **93.02%** | 11M |
| Ours | 94.10 | 9M |

| Hyperparameter | Value |
|---|---|
| lr | 0.001 |

```bash
python train.py --lr 0.001 --eval_loss=0.5
# expected output: accuracy 0.913
```
"""


def test_claims_found():
    cs = extract_claims(README, "README.md")
    simple = [(c["metric"], c["value"], c["lo"], c["hi"], c["kind"]) for c in cs]
    assert ("test_accuracy", 91.3, None, None, "prose") in simple
    assert ("final_accuracy", None, 84.2, 85.3, "prose") in simple
    f1 = [c for c in cs if c["metric"] == "f1"]
    assert f1 and f1[0]["value"] == 81.2 and f1[0]["plus_minus"] == 0.4
    table = [c for c in cs if c["kind"] == "table"]
    assert [(c["row"], c["value"], c["percent"]) for c in table] == [
        ("ResNet18", 93.02, True),
        ("Ours", 94.1, False),
    ]
    assert all(c["confidence"] == "high" for c in table)
    # hyperparameter tables and command-line flags are not claims
    assert not any(c["value"] == 0.001 for c in cs)
    assert not any(c["value"] == 0.5 for c in cs)
    code = [c for c in cs if c["kind"] == "code"]
    assert [c["value"] for c in code] == [0.913]


def test_line_numbers_point_at_source():
    cs = extract_claims(README, "README.md")
    lines = README.splitlines()
    for c in cs:
        assert c["text"] == lines[c["line"] - 1].strip()[:400]

import pytest

from paper_repro.metrics import extract_from_csv, extract_from_json, extract_from_text


def by_name(values):
    return {v["name"]: v for v in values}


@pytest.mark.parametrize(
    "line,name,value,percent",
    [
        ("accuracy: 0.913", "accuracy", 0.913, False),
        ("acc=91.3%", "accuracy", 91.3, True),
        ("F1 81.2", "f1", 81.2, False),
        ("Test set results: loss= 0.6634 accuracy= 0.8410", "accuracy", 0.841, False),
        ("step 2000: train loss 1.7621, val loss 1.8822", "val_loss", 1.8822, False),
        ("the best validation loss is 1.4697. Based on", "best_val_loss", 1.4697, False),
        ("gets us a loss of only 1.88 and therefore", "loss", 1.88, False),
        ("top-1 accuracy 76.1%", "top1_accuracy", 76.1, True),
        ("BLEU = 27.3", "bleu", 27.3, False),
        ("acc_val: 0.5200 time: 0.4s", "val_accuracy", 0.52, False),
        ("perplexity 3.2e+01", "perplexity", 32.0, False),
    ],
)
def test_text_forms(line, name, value, percent):
    found = by_name(extract_from_text(line, "log"))
    assert name in found, found
    assert found[name]["value"] == pytest.approx(value)
    assert found[name]["percent"] is percent
    assert found[name]["line"] == 1
    assert found[name]["text"] == line.strip()


def test_fraction_form():
    (v,) = [
        x
        for x in extract_from_text(
            "Test set: Average loss: 0.0331, Accuracy: 9897/10000 (99%)", "log"
        )
        if x["name"] == "accuracy"
    ]
    assert v["value"] == pytest.approx(0.9897)
    assert v["fraction"] == "9897/10000"


def test_ignores_words_and_versions():
    assert extract_from_text("lossless compression, accurate results, python 3.11", "log") == []
    assert extract_from_text("RuntimeError: CUDA error 2", "log") == []


def test_line_numbers():
    text = "starting\nepoch 1 loss 0.5\nepoch 2 loss 0.4\n"
    vals = extract_from_text(text, "log")
    assert [v["line"] for v in vals] == [2, 3]


def test_json_and_csv():
    j = extract_from_json('{\n  "test": {\n    "accuracy": 0.91,\n    "f1": 0.88\n  }\n}', "r.json")
    names = by_name(j)
    assert names["test.accuracy"]["value"] == 0.91
    assert names["test.accuracy"]["line"] == 3
    c = extract_from_csv("model,accuracy,f1\nours,0.9,0.8\nbase,0.7,0.6\n", "r.csv")
    assert [(v["name"], v["row"], v["value"]) for v in c][:2] == [
        ("accuracy", "ours", 0.9),
        ("f1", "ours", 0.8),
    ]
    assert c[2]["line"] == 3


def test_json_lines():
    vals = extract_from_json('{"step": 1, "loss": 2.0}\n{"step": 2, "loss": 1.5}\n', "log.jsonl")
    losses = [v for v in vals if v["name"] == "loss"]
    assert [v["value"] for v in losses] == [2.0, 1.5]
    assert [v["line"] for v in losses] == [1, 2]

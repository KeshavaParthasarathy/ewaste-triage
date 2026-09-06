import numpy as np


def test_neutral_prediction_formatter_preserves_the_product_result_contract():
    from server.prediction import prediction_from_probabilities

    result = prediction_from_probabilities(
        np.array([0.1, 0.7, 0.2], dtype=np.float32),
        ["0301_computer_mouse", "0306_mobile_phone", "unknown"],
        0.75,
    )

    assert result == {
        "class_name": "0306_mobile_phone",
        "unu_key": "0306",
        "confidence": 0.7,
        "low_confidence": True,
        "topk": [
            {"class_name": "0306_mobile_phone", "confidence": 0.7},
            {"class_name": "unknown", "confidence": 0.2},
            {"class_name": "0301_computer_mouse", "confidence": 0.1},
        ],
    }


def test_training_classifier_keeps_the_legacy_prediction_formatter_import():
    from server.classifier import prediction_from_probabilities as training_formatter
    from server.prediction import prediction_from_probabilities as neutral_formatter

    assert training_formatter is neutral_formatter

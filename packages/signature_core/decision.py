"""Verdict + confidence. Exact port of the legacy Streamlit logic (shared_ui.py)."""
from dataclasses import dataclass

THRESHOLD = 0.3999

BORDERLINE_MARGIN = 0.05


def mean_distance(distances: list[float]) -> float:
    return sum(distances) / len(distances)


def calculate_confidence(distance: float, threshold: float) -> float:
    if distance <= threshold:
        conf = 99.0 - (distance / threshold) * 19.0
    else:
        conf = 79.0 - min(1.0, (distance - threshold) / (2.0 - threshold)) * 79.0
    return max(0.0, min(99.9, conf))


def band(distance: float, threshold: float) -> str:
    """valid | fraud | borderline — three outcomes, not two.

    A distance within BORDERLINE_MARGIN of the threshold is a coin flip from an
    84%-accurate model, and saying so is the point. Computed here and sent to the client,
    which used to re-derive it with its own copy of the margin and its own comparison.
    """
    if abs(distance - threshold) < BORDERLINE_MARGIN:
        return "borderline"
    return "valid" if distance < threshold else "fraud"


@dataclass(frozen=True)
class Decision:
    verdict: str
    distance: float
    confidence: float
    threshold: float
    band: str


def decide(distances: list[float], threshold: float = THRESHOLD) -> Decision:
    avg = mean_distance(distances)
    verdict = "VALID" if avg < threshold else "FRAUD"
    return Decision(verdict=verdict, distance=avg,
                    confidence=calculate_confidence(avg, threshold), threshold=threshold,
                    band=band(avg, threshold))

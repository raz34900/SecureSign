"""Verdict + confidence. Exact port of the legacy Streamlit logic (shared_ui.py)."""
from dataclasses import dataclass

THRESHOLD = 0.3999

BORDERLINE_MARGIN = 0.05

# How far past a writer's own spread a query may sit and still be called genuine.
# Chosen on five real cards: 0.35 caught every measured forgery - including one that
# scored 0.27, comfortably genuine under the global threshold - at the cost of flagging
# the four specimens already known to disagree with their own cards.
SPREAD_FACTOR = 0.35


def writer_threshold(intra_distances: list[float], ceiling: float = THRESHOLD) -> float:
    """A threshold matched to how consistently this writer actually signs.

    A tight card means a forgery does not have to be far to be foreign: one measured
    at 0.27 was accepted by the global threshold and sat outside its writer's own
    spread. A loose card gets the global ceiling, never more - this only ever
    tightens. With fewer than two distinct references there is no spread to measure,
    and the ceiling stands.
    """
    if len(intra_distances) < 2:
        return ceiling
    mean = sum(intra_distances) / len(intra_distances)
    variance = sum((d - mean) ** 2 for d in intra_distances) / len(intra_distances)
    spread = variance ** 0.5
    if spread == 0.0:
        return ceiling
    return min(mean + SPREAD_FACTOR * spread, ceiling)


def mean_distance(distances: list[float]) -> float:
    return sum(distances) / len(distances)


def calculate_confidence(distance: float, threshold: float) -> float:
    if distance <= threshold:
        conf = 99.0 - (distance / threshold) * 19.0
    else:
        conf = 79.0 - min(1.0, (distance - threshold) / (2.0 - threshold)) * 79.0
    return max(0.0, min(99.9, conf))


def band(distance: float, threshold: float) -> str:
    """valid | fraud | borderline - three outcomes

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

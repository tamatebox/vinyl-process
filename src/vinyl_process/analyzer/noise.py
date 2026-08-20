"""Surface noise floor — the level the record itself contributes."""

from __future__ import annotations

import numpy as np

from vinyl_process.analyzer.base import AnalyzerContext
from vinyl_process.analyzer.registry import analyzer
from vinyl_process.models.analysis import RmsProfileSection, SurfaceNoiseSection
from vinyl_process.models.common import SectionMeta


@analyzer(
    name="surface_noise",
    version="1.0",
    description="Noise-floor level and how stable it is.",
    requires=("rms_profile",),
    defaults={"floor_percentile": 5.0, "spread_percentile": 10.0},
)
def analyze_surface_noise(context: AnalyzerContext) -> SurfaceNoiseSection:
    profile = context.typed_section("rms_profile", RmsProfileSection)
    values = np.asarray(profile.values_db, dtype=np.float64)
    if values.size == 0:
        return SurfaceNoiseSection(
            meta=SectionMeta(confidence=0.0), noise_floor_db=-240.0, stability_db=0.0
        )

    floor = float(np.percentile(values, context.number("floor_percentile")))
    quietest = values[values <= np.percentile(values, context.number("spread_percentile"))]
    spread = float(np.std(quietest)) if quietest.size > 1 else 0.0
    # A vinyl noise floor is a stable plateau: the tighter the quietest decile
    # clusters, the more confident we are that we measured noise, not music.
    confidence = float(np.clip(1.0 - spread / 6.0, 0.1, 0.99))
    return SurfaceNoiseSection(
        meta=SectionMeta(confidence=round(confidence, 2)),
        noise_floor_db=round(floor, 2),
        stability_db=round(spread, 2),
    )

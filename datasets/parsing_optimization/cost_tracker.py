"""
Cost tracking for the PDF parsing optimization pipeline.

Update the pricing constants below to match current rates:
  Upstage Document Parse → https://console.upstage.ai  (Pricing tab)
  solar-pro2             → https://console.upstage.ai  (Pricing tab)
  Datalab Document Parse → https://www.datalab.to      (Pricing page)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# ─────────────────────────────────────────────────────────────
# ⚠  Pricing constants — verify before relying on cost estimates
# ─────────────────────────────────────────────────────────────

# Upstage Document Parse  (USD per page)
UPSTAGE_PARSE_PER_PAGE: float = 0.01

# Datalab Document Parse  (USD per page) — set to actual value
DATALAB_PARSE_PER_PAGE: float = 0.01

# solar-pro2  (USD per 1 million tokens)
SOLAR_PRO2_INPUT_PER_1M: float = .15
SOLAR_PRO2_OUTPUT_PER_1M: float = .60


# ─────────────────────────────────────────────────────────────
# Internal record
# ─────────────────────────────────────────────────────────────

@dataclass
class _Entry:
    phase: Literal["process", "evaluate"]   # which script generated this
    version: str                             # e.g. "v1", "v5", "eval_v3"
    pdf: str
    service: str                             # e.g. "upstage_parse", "solar-pro2"
    detail: str                              # human-readable unit breakdown
    cost_usd: float


# ─────────────────────────────────────────────────────────────
# CostTracker
# ─────────────────────────────────────────────────────────────

class CostTracker:
    """Accumulates API usage across the pipeline and prints a cost report."""

    def __init__(self) -> None:
        self._entries: list[_Entry] = []

    # ── Logging helpers ──────────────────────────────────────

    def log_upstage_parse(
        self,
        *,
        version: int,
        pdf: str,
        pages: int,
        phase: Literal["process", "evaluate"] = "process",
    ) -> None:
        cost = pages * UPSTAGE_PARSE_PER_PAGE
        self._entries.append(
            _Entry(
                phase=phase,
                version=f"v{version}",
                pdf=pdf,
                service="upstage_parse",
                detail=f"{pages} pages × ${UPSTAGE_PARSE_PER_PAGE:.4f}/page",
                cost_usd=cost,
            )
        )

    def log_datalab_parse(
        self,
        *,
        version: int,
        pdf: str,
        pages: int,
        phase: Literal["process", "evaluate"] = "process",
    ) -> None:
        cost = pages * DATALAB_PARSE_PER_PAGE
        self._entries.append(
            _Entry(
                phase=phase,
                version=f"v{version}",
                pdf=pdf,
                service="datalab_parse",
                detail=f"{pages} pages × ${DATALAB_PARSE_PER_PAGE:.4f}/page",
                cost_usd=cost,
            )
        )

    def log_solar_llm(
        self,
        *,
        version: int | str,
        pdf: str,
        purpose: str,
        input_tokens: int,
        output_tokens: int,
        phase: Literal["process", "evaluate"] = "process",
    ) -> None:
        cost = (
            input_tokens / 1_000_000 * SOLAR_PRO2_INPUT_PER_1M
            + output_tokens / 1_000_000 * SOLAR_PRO2_OUTPUT_PER_1M
        )
        ver_label = f"v{version}" if isinstance(version, int) else version
        self._entries.append(
            _Entry(
                phase=phase,
                version=ver_label,
                pdf=pdf,
                service=f"solar-pro2 ({purpose})",
                detail=(
                    f"{input_tokens:,} in + {output_tokens:,} out tokens  "
                    f"(${SOLAR_PRO2_INPUT_PER_1M}/M in, ${SOLAR_PRO2_OUTPUT_PER_1M}/M out)"
                ),
                cost_usd=cost,
            )
        )

    # ── Aggregation ──────────────────────────────────────────

    def total_by_version(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for e in self._entries:
            totals[e.version] = totals.get(e.version, 0.0) + e.cost_usd
        return totals

    def total_by_phase(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for e in self._entries:
            totals[e.phase] = totals.get(e.phase, 0.0) + e.cost_usd
        return totals

    def grand_total(self) -> float:
        return sum(e.cost_usd for e in self._entries)

    # ── Report ───────────────────────────────────────────────

    def print_report(self) -> None:
        if not self._entries:
            print("No cost data recorded.")
            return

        print()
        print("=" * 80)
        print("COST REPORT  (estimated — verify prices at provider dashboards)")
        print("=" * 80)

        # Group by phase
        for phase in ("process", "evaluate"):
            entries = [e for e in self._entries if e.phase == phase]
            if not entries:
                continue

            phase_total = sum(e.cost_usd for e in entries)
            print(f"\n  Phase: {phase.upper()}  (total: ${phase_total:.4f})")
            print(f"  {'Version':<10} {'PDF':<40} {'Service':<30} {'Detail'}")
            print(f"  {'-'*10} {'-'*40} {'-'*30} {'-'*40}")

            for e in entries:
                print(
                    f"  {e.version:<10} {e.pdf:<40} {e.service:<30} "
                    f"{e.detail}  →  ${e.cost_usd:.4f}"
                )

        # Per-version summary
        print()
        print("  Per-version totals:")
        for ver, total in sorted(self.total_by_version().items()):
            print(f"    {ver}: ${total:.4f}")

        print()
        print(f"  Grand total: ${self.grand_total():.4f}")
        print()
        print(
            "  ⚠ Prices are placeholder estimates. "
            "Update constants in cost_tracker.py to match your actual plan."
        )
        print("=" * 80)

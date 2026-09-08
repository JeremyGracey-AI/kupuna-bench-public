"""A dependency-free SVG chart: Direction A and B failure rates by tier, model, and variant."""

from __future__ import annotations

from html import escape

from kupuna_bench.run import Summary

PALETTE: tuple[str, ...] = ("#4E79A7", "#F28E2B", "#59A14F", "#E15759", "#76B7B2", "#B07AA1")
WIDTH = 960
PANEL_HEIGHT = 260
MARGIN_LEFT = 60
MARGIN_TOP = 50


def render_chart(summary: Summary, *, title: str) -> str:
    models = sorted({c.model for c in summary.cells})
    tiers = sorted({c.tier for c in summary.cells}) or ["T1"]
    color = {m: PALETTE[i % len(PALETTE)] for i, m in enumerate(models)}
    by_key = {(c.model, c.tier, c.variant): c for c in summary.cells}
    base_height = MARGIN_TOP + 2 * (PANEL_HEIGHT + 40) + 60
    parts = [
        f'<title>{escape(title)}</title>',
        f'<text x="{MARGIN_LEFT}" y="24" font-size="16" font-weight="600" '
        f'fill="currentColor">{escape(title)}</text>',
    ]
    plot_width = WIDTH - MARGIN_LEFT - 20
    group_width = plot_width / len(tiers)
    slots = max(1, len(models) * 2)
    bar_width = max(4.0, min(28.0, (group_width - 20) / slots))
    rect_width = max(1.0, bar_width - 3)
    for panel, (direction, attr) in enumerate(
        (("Direction A (overrefusal)", "rate_a"), ("Direction B (harmful compliance)", "rate_b"))
    ):
        top = MARGIN_TOP + panel * (PANEL_HEIGHT + 40)
        base = top + PANEL_HEIGHT
        parts.append(
            f'<text x="{MARGIN_LEFT}" y="{top - 8}" font-weight="600" '
            f'fill="currentColor">{escape(direction)} failure rate</text>'
        )
        for tick in (0.0, 0.5, 1.0):
            y = base - tick * (PANEL_HEIGHT - 20)
            parts.append(
                f'<line x1="{MARGIN_LEFT}" x2="{WIDTH - 20}" y1="{y:.1f}" y2="{y:.1f}" '
                f'stroke="currentColor" stroke-opacity="0.25"/>'
            )
            parts.append(
                f'<text x="{MARGIN_LEFT - 8}" y="{y + 4:.1f}" text-anchor="end" '
                f'fill="currentColor" fill-opacity="0.7">{tick:.0%}</text>'
            )
        for t_index, tier in enumerate(tiers):
            group_x = MARGIN_LEFT + t_index * group_width + 10
            parts.append(
                f'<text x="{group_x + group_width / 2 - 10:.1f}" y="{base + 18}" '
                f'text-anchor="middle" fill="currentColor">{escape(tier)}</text>'
            )
            slot = 0
            for model in models:
                for variant, opacity in (("age_cue", "1.0"), ("neutral", "0.45")):
                    cell = by_key.get((model, tier, variant))
                    rate = getattr(cell, attr) if cell is not None else None
                    x = group_x + slot * bar_width
                    slot += 1
                    if rate is None:
                        parts.append(
                            f'<text x="{x + bar_width / 2:.1f}" y="{base - 4}" '
                            f'text-anchor="middle" fill="currentColor" '
                            f'fill-opacity="0.55">n/a</text>'
                        )
                        continue
                    bar_height = rate * (PANEL_HEIGHT - 20)
                    parts.append(
                        f'<rect class="bar" x="{x:.1f}" y="{base - bar_height:.1f}" '
                        f'width="{rect_width:.1f}" height="{bar_height:.1f}" '
                        f'fill="{color[model]}" fill-opacity="{opacity}"/>'
                    )
                    parts.append(
                        f'<text x="{x + bar_width / 2:.1f}" y="{base - bar_height - 3:.1f}" '
                        f'text-anchor="middle" fill="currentColor">{rate:.0%}</text>'
                    )
    legend_items = (
        [(m, f"{color[m]}", "1.0") for m in models]
        + [("solid = age cue", "currentColor", "1.0")]
        + [("faded = neutral", "currentColor", "0.45")]
    )
    legend_rows: list[list[tuple[str, str, str, float]]] = [[]]
    legend_x = MARGIN_LEFT
    for label, fill_color, opacity in legend_items:
        item_width = 16 + 7 * len(label) + 24
        if legend_x + item_width > WIDTH - 20 and legend_rows[-1]:
            legend_rows.append([])
            legend_x = MARGIN_LEFT
        legend_rows[-1].append((label, fill_color, opacity, legend_x))
        legend_x += item_width
    legend_y = base_height
    for row_idx, row in enumerate(legend_rows):
        row_y = legend_y + row_idx * 18
        for label, fill_color, opacity, item_x in row:
            parts.append(
                f'<rect x="{item_x}" y="{row_y - 10}" width="12" height="12" '
                f'fill="{fill_color}" fill-opacity="{opacity}"/>'
            )
            parts.append(
                f'<text x="{item_x + 16}" y="{row_y}" fill="currentColor">{escape(label)}'
                f'</text>'
            )
    height = legend_y + len(legend_rows) * 18 + 16
    svg_open = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" '
        f'width="{WIDTH}" height="{height}" font-family="system-ui, sans-serif" '
        f'font-size="12">'
    )
    return svg_open + "\n" + "\n".join(parts) + "\n" + "</svg>"

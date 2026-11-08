"""Chart builders: data in, alt.Chart out. Pure (Altair, no Streamlit), so encodings are
unit-tested.

Colour comes from the active Streamlit theme, so charts follow the light/dark switch:
topic series use a domain of colour slots (syllabus.color_domain: a topic sits at its
position in its domain's syllabus) and no range, and Streamlit fills it with that scheme's
chartCategoricalColors (config.TOPIC_PALETTE). A topic is therefore the same colour in every
chart. Neutral marks keep the theme's defaults; quiz outcomes use config.OUTCOME_COLORS.

Views render the `*_spec` functions with st.vega_lite_chart: the same charts as plain
Vega-Lite, built once per distinct data (see the note above them).
"""

import json
import math
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from functools import lru_cache

import altair as alt
import pandas as pd

from piq import syllabus
from piq.config import BRAND_COLOR, DIFFICULTIES, OUTCOME_COLORS, PALETTE, WEAK_THRESHOLD

FONT = "Atkinson Hyperlegible Next"
HEADING_FONT = "Bricolage Grotesque"
ROW_PX = 34  # one horizontal bar plus breathing room
LEGEND_PX = 80  # an x axis and a two-row legend under a chart
# Marks that must read in either scheme (Vega cannot follow the theme switch for them):
# this grey keeps >= 3:1 on both page backgrounds.
NEUTRAL = PALETTE["light"]["border"]


def topic_scale(topics: Sequence[str]) -> alt.Scale:
    """The colour scale for these topics: each at its slot of the theme's categorical colours."""
    return alt.Scale(domain=syllabus.color_domain(topics))


def _by_slot(topics: Sequence[str]) -> list[str]:
    """Topics in syllabus order (their colour slot), unknown ones last."""
    return sorted(
        dict.fromkeys(topics),
        key=lambda t: (syllabus.color_slot(t) is None, syllabus.color_slot(t) or 0),
    )


def themed[C: alt.TopLevelMixin](chart: C) -> C:
    """The shared look: theme fonts, no frame, quiet axes, a left-aligned takeaway title."""
    return (
        chart.configure(font=FONT)
        .configure_view(strokeWidth=0)
        .configure_axis(
            labelFontSize=13,
            titleFontSize=13,
            labelPadding=6,
            domain=False,
            ticks=False,
            gridOpacity=0.5,
        )
        .configure_title(font=HEADING_FONT, fontSize=17, fontWeight=600, anchor="start", offset=12)
    )


def weakness_bars(weakness: Mapping[str, float], title: str | None = None) -> alt.LayerChart:
    """Weakness per topic as horizontal bars, weakest first, with the weak threshold dashed.
    Each axis label carries the topic and its value ("OS  43%"): a direct label that the
    theme colours correctly in both schemes, where text marks do not."""
    df = pd.DataFrame({"topic": list(weakness), "weakness": [float(v) for v in weakness.values()]})
    df["label"] = [f"{t}  {w:.0%}" for t, w in zip(df["topic"], df["weakness"], strict=True)]
    order = df.sort_values("weakness", ascending=False, kind="stable")["label"].tolist()
    y = alt.Y("label:N", sort=order, title=None, axis=alt.Axis(labelFontSize=14, labelPadding=8))
    x = alt.X(
        "weakness:Q",
        scale=alt.Scale(domain=[0, 1]),
        # Three ticks: they stay apart on a phone, and 50% is the weak threshold.
        axis=alt.Axis(format="%", values=[0, WEAK_THRESHOLD, 1], title=None),
    )
    tooltip = [
        alt.Tooltip("topic:N", title="Topic"),
        alt.Tooltip("weakness:Q", title="Weakness", format=".0%"),
    ]
    bars = (
        alt.Chart(df)
        .mark_bar(cornerRadiusEnd=4, size=18)
        .encode(
            y=y,
            x=x,
            color=alt.Color("topic:N", scale=topic_scale(list(weakness)), legend=None),
            tooltip=tooltip,
        )
    )
    threshold = (
        alt.Chart(pd.DataFrame({"weakness": [WEAK_THRESHOLD]}))
        .mark_rule(strokeDash=[4, 4], strokeWidth=1.5, color=NEUTRAL)
        .encode(x="weakness:Q", tooltip=alt.value(f"Weak above {WEAK_THRESHOLD:.0%}"))
    )
    layered = alt.layer(bars, threshold).properties(height=ROW_PX * len(df))
    return themed(layered.properties(title=title) if title else layered)


def minutes_shift(
    before: Mapping[str, int], after: Mapping[str, int], weeks: tuple[int, int]
) -> alt.LayerChart:
    """Minutes per topic in two weeks as a dumbbell: a hollow grey dot for the earlier week, a
    filled dot in the topic's colour for the later one, joined by a line, so the shift reads
    as movement and the weeks differ by shape, not colour alone. Axis labels carry the
    numbers ("OS  600 → 840"); the busiest topic comes first."""
    topics = _by_slot([*before, *after])
    df = pd.DataFrame(
        {
            "topic": topics,
            "before": [int(before.get(t, 0)) for t in topics],
            "after": [int(after.get(t, 0)) for t in topics],
        }
    )
    df["change"] = df["after"] - df["before"]
    df["label"] = [f"{t}  {b} → {a}" for t, b, a in zip(df.topic, df.before, df.after, strict=True)]
    order = df.sort_values(["after", "before"], ascending=False, kind="stable")["label"].tolist()
    y = alt.Y(
        "label:N",
        sort=order,
        title=None,
        axis=alt.Axis(labelFontSize=14, labelPadding=8, labelLimit=0),  # never cut a number
    )
    # Three ticks in whole hours (0, half, top) stay apart on a phone.
    top = max(60, 60 * math.ceil(int(df[["before", "after"]].max().max()) / 60))
    scale = alt.Scale(domain=[0, top])
    axis = alt.Axis(title=None, format="d", values=[0, top // 2, top])
    tooltip = [
        alt.Tooltip("topic:N", title="Topic"),
        alt.Tooltip("before:Q", title=f"Week {weeks[0]} (min)"),
        alt.Tooltip("after:Q", title=f"Week {weeks[1]} (min)"),
        alt.Tooltip("change:Q", title="Change (min)", format="+d"),
    ]
    base = alt.Chart(df).encode(y=y, tooltip=tooltip)
    line = base.mark_rule(strokeWidth=2, color=NEUTRAL, opacity=0.6).encode(
        x=alt.X("before:Q", scale=scale, axis=axis), x2="after:Q"
    )
    earlier = base.mark_point(size=110, strokeWidth=2, color=NEUTRAL, filled=False).encode(
        x=alt.X("before:Q", scale=scale, axis=axis)
    )
    later = base.mark_circle(size=150, opacity=1).encode(
        x=alt.X("after:Q", scale=scale, axis=axis),
        color=alt.Color("topic:N", scale=topic_scale(topics), legend=None),
    )
    return themed(alt.layer(line, earlier, later).properties(height=ROW_PX * len(df)))


def readiness_ring(score: int) -> alt.Chart:
    """Readiness out of 100 as a ring: the filled arc in the brand teal (>= 3:1 in both
    schemes), the rest a faint track. The number itself is shown next to it as text."""
    df = pd.DataFrame({"part": ["Ready", "To go"], "value": [score, 100 - score], "order": [0, 1]})
    ring = (
        alt.Chart(df)
        .mark_arc(innerRadius=34, outerRadius=52)
        .encode(
            theta=alt.Theta("value:Q", stack=True),
            order=alt.Order("order:Q"),
            color=alt.Color(
                "part:N",
                scale=alt.Scale(domain=["Ready", "To go"], range=[BRAND_COLOR, NEUTRAL]),
                legend=None,
            ),
            opacity=alt.condition(alt.datum.part == "Ready", alt.value(1.0), alt.value(0.25)),
            tooltip=[alt.Tooltip("part:N", title=" "), alt.Tooltip("value:Q", title="Points")],
        )
        .properties(width=112, height=112)
    )
    return themed(ring)


# --- specs for the views ----------------------------------------------------------------
# Layering and validating an Altair chart costs 40-60 ms, on every rerun. The views
# therefore render plain Vega-Lite specs, built once per distinct data and cached as JSON
# text (immutable; each caller gets a fresh dict). Keyed by the values, never by student, so
# a cached spec is right for whoever asks, after any write.


def to_spec(chart: alt.TopLevelMixin) -> dict:
    """The chart as a Vega-Lite dict with its data inline. Altair's schema check is skipped
    (the builders are unit-tested) and so is the default size Altair's theme adds, because
    Streamlit sizes charts itself."""
    spec = chart.to_dict(validate=False)
    view = spec.get("config", {}).get("view", {})
    for key in ("continuousWidth", "continuousHeight"):
        view.pop(key, None)
    return spec


def weakness_spec(weakness: Mapping[str, float]) -> dict:
    return json.loads(_weakness_json(tuple(weakness.items())))


@lru_cache(maxsize=128)
def _weakness_json(items: tuple[tuple[str, float], ...]) -> str:
    return json.dumps(to_spec(weakness_bars(dict(items))))


def minutes_shift_spec(
    before: Mapping[str, int], after: Mapping[str, int], weeks: tuple[int, int]
) -> dict:
    return json.loads(_minutes_shift_json(tuple(before.items()), tuple(after.items()), weeks))


@lru_cache(maxsize=128)
def _minutes_shift_json(
    before: tuple[tuple[str, int], ...], after: tuple[tuple[str, int], ...], weeks: tuple[int, int]
) -> str:
    return json.dumps(to_spec(minutes_shift(dict(before), dict(after), weeks)))


def readiness_ring_spec(score: int) -> dict:
    return json.loads(_readiness_ring_json(score))


@lru_cache(maxsize=128)
def _readiness_ring_json(score: int) -> str:
    return json.dumps(to_spec(readiness_ring(score)))


# --- dashboard ----------------------------------------------------------------------------


def score_spark(topic: str, scores: Sequence[float]) -> alt.LayerChart:
    """One topic's quiz scores in attempt order as a sparkline in its colour: 0-100%, no axes
    (the latest score is written beside it), a tooltip on every point."""
    df = pd.DataFrame(
        {"topic": topic, "attempt": range(1, len(scores) + 1), "score": [float(s) for s in scores]}
    )
    base = alt.Chart(df).encode(
        x=alt.X("attempt:Q", axis=None, scale=alt.Scale(domain=[1, max(len(scores), 2)])),
        y=alt.Y("score:Q", axis=None, scale=alt.Scale(domain=[0, 100])),
        color=alt.Color("topic:N", scale=topic_scale([topic]), legend=None),
        tooltip=[
            alt.Tooltip("attempt:Q", title="Quiz"),
            alt.Tooltip("score:Q", title="Score (%)", format=".0f"),
        ],
    )
    line = base.mark_line(strokeWidth=2)
    points = base.mark_circle(size=36, opacity=1)
    return themed(alt.layer(line, points).properties(height=56))


def week_mix(weeks: Mapping[int, Mapping[str, int]]) -> alt.Chart:
    """Each week's minutes as one bar, split by topic in topic colours (stacked in syllabus
    order), oldest week on top; the legend names the colours."""
    topics = _by_slot([t for minutes in weeks.values() for t, m in minutes.items() if m])
    rows = [
        {"week": f"Week {w}", "topic": t, "minutes": int(m), "rank": topics.index(t)}
        for w, minutes in weeks.items()
        for t, m in minutes.items()
        if m
    ]
    order = [f"Week {w}" for w in weeks]
    chart = (
        alt.Chart(pd.DataFrame(rows))
        .mark_bar(size=18)
        .encode(
            y=alt.Y("week:N", sort=order, title=None, axis=alt.Axis(labelFontSize=14)),
            x=alt.X("minutes:Q", title=None, axis=alt.Axis(format="d", tickCount=3)),
            color=alt.Color(
                "topic:N",
                scale=topic_scale(topics),
                # Three columns wrap on a phone, where one row was cut off. `values` keeps the
                # scale's unused colour slots out of the legend.
                legend=alt.Legend(
                    orient="bottom", title=None, columns=3, labelFontSize=13, values=topics
                ),
            ),
            order=alt.Order("rank:Q"),
            tooltip=[
                alt.Tooltip("week:N", title="Week"),
                alt.Tooltip("topic:N", title="Topic"),
                alt.Tooltip("minutes:Q", title="Minutes"),
            ],
        )
        # Streamlit fits the whole chart into `height`, axis and legend included.
        .properties(height=ROW_PX * len(order) + LEGEND_PX + 18 * (len(topics) // 4))
    )
    return themed(chart)


def _trend(
    values: Sequence[float],
    labels: Sequence[str],
    *,
    top: float,
    noun: str,
    title: str,
    fmt: str,
) -> alt.LayerChart:
    """One score over time, one point per event (`noun` n on the x axis), as a line in the
    brand teal: not a topic, so not a topic colour. `labels` describe each event."""
    df = pd.DataFrame(
        {"n": range(1, len(values) + 1), "value": [float(v) for v in values], "label": list(labels)}
    )
    base = alt.Chart(df).encode(
        x=alt.X(
            "n:O", title=None, axis=alt.Axis(labelAngle=0, labelExpr=f"'{noun} ' + datum.value")
        ),
        y=alt.Y(
            "value:Q",
            title=None,
            scale=alt.Scale(domain=[0, top]),
            axis=alt.Axis(values=[0, top / 2, top], format=fmt),
        ),
        tooltip=[
            alt.Tooltip("label:N", title=noun),
            alt.Tooltip("value:Q", title=title, format=fmt),
        ],
    )
    line = base.mark_line(strokeWidth=2, color=BRAND_COLOR)
    points = base.mark_circle(size=60, opacity=1, color=BRAND_COLOR)
    return themed(alt.layer(line, points).properties(height=180))


def interview_trend(averages: Sequence[float], labels: Sequence[str]) -> alt.LayerChart:
    """Each interview session's average score (0-5) in order."""
    return _trend(averages, labels, top=5, noun="Session", title="Average (/5)", fmt=".1f")


def readiness_trend(scores: Sequence[int], labels: Sequence[str]) -> alt.LayerChart:
    """Readiness (0-100) at each profile, oldest first."""
    return _trend(scores, labels, top=100, noun="Profile", title="Readiness (/100)", fmt="d")


def score_spark_spec(topic: str, scores: Sequence[float]) -> dict:
    return json.loads(_score_spark_json(topic, tuple(scores)))


@lru_cache(maxsize=256)
def _score_spark_json(topic: str, scores: tuple[float, ...]) -> str:
    return json.dumps(to_spec(score_spark(topic, scores)))


def week_mix_spec(weeks: Mapping[int, Mapping[str, int]]) -> dict:
    key = tuple((w, tuple(m.items())) for w, m in weeks.items())
    return json.loads(_week_mix_json(key))


@lru_cache(maxsize=128)
def _week_mix_json(weeks: tuple[tuple[int, tuple[tuple[str, int], ...]], ...]) -> str:
    return json.dumps(to_spec(week_mix({w: dict(m) for w, m in weeks})))


def interview_trend_spec(averages: Sequence[float], labels: Sequence[str]) -> dict:
    return json.loads(_interview_trend_json(tuple(averages), tuple(labels)))


@lru_cache(maxsize=128)
def _interview_trend_json(averages: tuple[float, ...], labels: tuple[str, ...]) -> str:
    return json.dumps(to_spec(interview_trend(averages, labels)))


def readiness_trend_spec(scores: Sequence[int], labels: Sequence[str]) -> dict:
    return json.loads(_readiness_trend_json(tuple(scores), tuple(labels)))


@lru_cache(maxsize=128)
def _readiness_trend_json(scores: tuple[int, ...], labels: tuple[str, ...]) -> str:
    return json.dumps(to_spec(readiness_trend(scores, labels)))


def activity_heatmap(days: Mapping[date, int], today: date, weeks: int = 12) -> alt.Chart:
    """The last `weeks` weeks as a calendar: a column per week (oldest on the left), a row per
    weekday, each day in the brand teal, stronger the more quizzes and interviews it had; a
    day without any is a faint neutral cell."""
    first = today - timedelta(days=today.weekday() + 7 * (weeks - 1))  # a Monday
    rows = [
        {
            "date": day.isoformat(),
            "week": (day - first).days // 7,
            "weekday": day.strftime("%a"),
            "count": int(days.get(day, 0)),
        }
        for day in (first + timedelta(days=i) for i in range((today - first).days + 1))
    ]
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    chart = (
        alt.Chart(pd.DataFrame(rows))
        .mark_rect(cornerRadius=3, stroke=None)
        .encode(
            x=alt.X("week:O", axis=None),
            y=alt.Y(
                "weekday:O",
                sort=weekdays,
                title=None,
                axis=alt.Axis(
                    labelExpr="indexof(['Mon','Wed','Fri'], datum.value) >= 0 ? datum.value : ''"
                ),
            ),
            # One teal for study, stronger for busier days; a palette ramp put one quiz
            # lighter than an empty day in light mode.
            color=alt.condition(alt.datum.count == 0, alt.value(NEUTRAL), alt.value(BRAND_COLOR)),
            opacity=alt.condition(
                alt.datum.count == 0,
                alt.value(0.18),
                alt.Opacity(
                    "count:Q",
                    legend=None,
                    scale=alt.Scale(domain=[1, 3], range=[0.5, 1], clamp=True),
                ),
            ),
            tooltip=[
                alt.Tooltip("date:T", title="Day", format="%a %d %b"),
                alt.Tooltip("count:Q", title="Quizzes and interviews"),
            ],
        )
        .properties(height=7 * 18)
    )
    return themed(chart)


def activity_heatmap_spec(days: Mapping[date, int], today: date) -> dict:
    key = tuple(sorted((d.isoformat(), int(n)) for d, n in days.items()))
    return json.loads(_activity_heatmap_json(key, today.isoformat()))


@lru_cache(maxsize=128)
def _activity_heatmap_json(days: tuple[tuple[str, int], ...], today: str) -> str:
    counts = {date.fromisoformat(d): n for d, n in days}
    return json.dumps(to_spec(activity_heatmap(counts, date.fromisoformat(today))))


# --- quiz results ------------------------------------------------------------------------

OUTCOMES = tuple(OUTCOME_COLORS)  # Correct, Wrong, Skipped: stacked in this order


def outcome_bars(rows: Sequence[tuple[str, int, int, int]]) -> alt.Chart:
    """One horizontal bar per slice (topic, difficulty or thinking level) split into correct,
    wrong and skipped answers, in that order and in fixed outcome colours (readable in both
    schemes). Axis labels carry the score ("OS  7/10"); the legend and tooltips name the
    outcomes, so colour is never the only cue. `rows`: (label, correct, wrong, skipped)."""
    data = []
    order = []
    for label, correct, wrong, skipped in rows:
        total = correct + wrong + skipped
        shown = f"{label}  {correct}/{total}"
        order.append(shown)
        for rank, (outcome, n) in enumerate(zip(OUTCOMES, (correct, wrong, skipped), strict=True)):
            if n:
                data.append(
                    {"slice": shown, "outcome": outcome, "n": n, "rank": rank, "total": total}
                )
    chart = (
        alt.Chart(pd.DataFrame(data, columns=["slice", "outcome", "n", "rank", "total"]))
        .mark_bar(size=18)
        .encode(
            y=alt.Y(
                "slice:N",
                sort=order,
                title=None,
                axis=alt.Axis(labelFontSize=14, labelPadding=8, labelLimit=0),
            ),
            x=alt.X("n:Q", stack="zero", title=None, axis=alt.Axis(format="d", tickCount=4)),
            color=alt.Color(
                "outcome:N",
                scale=alt.Scale(domain=list(OUTCOMES), range=list(OUTCOME_COLORS.values())),
                legend=alt.Legend(orient="bottom", title=None, labelFontSize=13),
            ),
            order=alt.Order("rank:Q"),
            tooltip=[
                alt.Tooltip("slice:N", title="Slice"),
                alt.Tooltip("outcome:N", title="Answers"),
                alt.Tooltip("n:Q", title="Questions"),
            ],
        )
        # Streamlit fits axis and legend inside `height`, so both get their full room.
        .properties(height=ROW_PX * len(order) + LEGEND_PX)
    )
    return themed(chart)


def accuracy_grid(cells: Sequence[tuple[str, str, int, int]]) -> alt.Chart:
    """Accuracy per topic and difficulty as a grid of teal cells, stronger for a higher share
    correct; a cell without questions stays empty. Tooltips give the counts. `cells`:
    (topic, difficulty, correct, total)."""
    data = [
        {
            "topic": t,
            "difficulty": d.capitalize(),
            "correct": c,
            "total": n,
            "accuracy": c / n if n else 0.0,
        }
        for t, d, c, n in cells
        if n
    ]
    topics = _by_slot([row["topic"] for row in data])
    chart = (
        alt.Chart(
            pd.DataFrame(data, columns=["topic", "difficulty", "correct", "total", "accuracy"])
        )
        .mark_rect(cornerRadius=3)
        .encode(
            x=alt.X(
                "difficulty:N",
                sort=[d.capitalize() for d in DIFFICULTIES],
                title=None,
                axis=alt.Axis(labelAngle=0, orient="top", labelFontSize=13),
            ),
            y=alt.Y(
                "topic:N", sort=topics, title=None, axis=alt.Axis(labelFontSize=13, labelLimit=0)
            ),
            color=alt.value(BRAND_COLOR),
            opacity=alt.Opacity(
                "accuracy:Q", legend=None, scale=alt.Scale(domain=[0, 1], range=[0.15, 1])
            ),
            tooltip=[
                alt.Tooltip("topic:N", title="Topic"),
                alt.Tooltip("difficulty:N", title="Difficulty"),
                alt.Tooltip("accuracy:Q", title="Correct", format=".0%"),
                alt.Tooltip("correct:Q", title="Right answers"),
                alt.Tooltip("total:Q", title="Questions"),
            ],
        )
        .properties(height=ROW_PX * max(len(topics), 1))
    )
    return themed(chart)


def ats_trend(scores: Sequence[int], labels: Sequence[str]) -> alt.LayerChart:
    """ATS score (0-100) of each saved resume version, oldest first."""
    return _trend(scores, labels, top=100, noun="Version", title="ATS score (/100)", fmt="d")


def outcome_bars_spec(rows: Sequence[tuple[str, int, int, int]]) -> dict:
    return json.loads(_outcome_bars_json(tuple(tuple(r) for r in rows)))


@lru_cache(maxsize=128)
def _outcome_bars_json(rows: tuple[tuple[str, int, int, int], ...]) -> str:
    return json.dumps(to_spec(outcome_bars(rows)))


def accuracy_grid_spec(cells: Sequence[tuple[str, str, int, int]]) -> dict:
    return json.loads(_accuracy_grid_json(tuple(sorted(tuple(c) for c in cells))))


@lru_cache(maxsize=128)
def _accuracy_grid_json(cells: tuple[tuple[str, str, int, int], ...]) -> str:
    return json.dumps(to_spec(accuracy_grid(cells)))


def ats_trend_spec(scores: Sequence[int], labels: Sequence[str]) -> dict:
    return json.loads(_ats_trend_json(tuple(scores), tuple(labels)))


@lru_cache(maxsize=128)
def _ats_trend_json(scores: tuple[int, ...], labels: tuple[str, ...]) -> str:
    return json.dumps(to_spec(ats_trend(scores, labels)))


# --- faculty dashboard: the cohort ----------------------------------------------------------
# Streams and rubric criteria are not topics, so every mark is the brand teal (topic colours
# mean topics); values sit in the axis labels, and hovering a bar dims the others.


def _hover(fields: list[str]) -> alt.Parameter:
    return alt.selection_point(on="pointerover", clear="pointerout", fields=fields, empty=True)


def _label_bars(
    df: pd.DataFrame, *, value: str, top: float, fmt: str, tooltip: list[alt.Tooltip]
) -> alt.Chart:
    """Horizontal brand-teal bars, one per `label` row, in the frame's order; hover dims the
    rest. The label already carries the value, so the bars need no text marks."""
    hover = _hover(["label"])
    chart = (
        alt.Chart(df)
        .mark_bar(size=18, color=BRAND_COLOR, cornerRadiusEnd=3)
        .encode(
            y=alt.Y(
                "label:N",
                sort=df["label"].tolist(),
                title=None,
                axis=alt.Axis(labelFontSize=14, labelPadding=8, labelLimit=0),
            ),
            x=alt.X(
                f"{value}:Q",
                scale=alt.Scale(domain=[0, top]),
                title=None,
                axis=alt.Axis(values=[0, top / 2, top], format=fmt),
            ),
            opacity=alt.condition(hover, alt.value(1.0), alt.value(0.45)),
            tooltip=tooltip,
        )
        .add_params(hover)
        .properties(height=ROW_PX * max(1, len(df)) + 30)
    )
    return themed(chart)


def stream_readiness(rows: Sequence[tuple[str, int, float, str]]) -> alt.Chart:
    """Average placement readiness per stream (0-100). `rows`: (stream, students, readiness,
    detail for the tooltip), best first."""
    df = pd.DataFrame(rows, columns=["stream", "students", "readiness", "detail"])
    df = df.sort_values("readiness", ascending=False, kind="stable")
    df["label"] = [f"{s}  {r:.0f}" for s, r in zip(df["stream"], df["readiness"], strict=True)]
    return _label_bars(
        df,
        value="readiness",
        top=100,
        fmt="d",
        tooltip=[
            alt.Tooltip("stream:N", title="Stream"),
            alt.Tooltip("students:Q", title="Students"),
            alt.Tooltip("readiness:Q", title="Average readiness (/100)", format=".1f"),
            alt.Tooltip("detail:N", title="Parts"),
        ],
    )


def rubric_breakdown(averages: Mapping[str, float]) -> alt.Chart:
    """Average of each voice rubric criterion (0-5), in rubric order."""
    df = pd.DataFrame({"criterion": list(averages), "average": list(averages.values())})
    df["label"] = [f"{c}  {a:.1f}" for c, a in zip(df["criterion"], df["average"], strict=True)]
    return _label_bars(
        df,
        value="average",
        top=5,
        fmt="d",
        tooltip=[
            alt.Tooltip("criterion:N", title="Criterion"),
            alt.Tooltip("average:Q", title="Average (/5)", format=".1f"),
        ],
    )


def gap_bars(gaps: Sequence[tuple[str, int]], students: int) -> alt.Chart:
    """The most common missing skills: how many students' latest scan lacks each."""
    df = pd.DataFrame(gaps, columns=["skill", "students"])
    df["label"] = [f"{s}  {n}" for s, n in zip(df["skill"], df["students"], strict=True)]
    df["share"] = df["students"] / max(1, students)
    return _label_bars(
        df,
        value="students",
        top=max(1, students),
        fmt="d",
        tooltip=[
            alt.Tooltip("skill:N", title="Skill"),
            alt.Tooltip("students:Q", title="Students missing it"),
            alt.Tooltip("share:Q", title="Share of scanned students", format=".0%"),
        ],
    )


def histogram_bands(values: Sequence[float], *, top: int, step: int) -> list[tuple[str, int]]:
    """(band label, count) of `values` on 0..top. step 1: one band per whole score, top
    included ("0" .. "15"); wider: "0-10" .. "90-100", the last band including top."""
    if step == 1:
        labels = [str(n) for n in range(top + 1)]
        index = [min(max(int(v), 0), top) for v in values]
    else:
        edges = range(0, top, step)
        labels = [f"{lo}-{min(lo + step, top)}" for lo in edges]
        index = [min(int(max(0.0, v) // step), len(labels) - 1) for v in values]
    counts = [0] * len(labels)
    for i in index:
        counts[i] += 1
    return list(zip(labels, counts, strict=True))


def histogram(values: Sequence[float], *, top: int, step: int, noun: str) -> alt.Chart:
    """How many of `values` fall in each band (histogram_bands): binned here, so tests check
    the counts, not Vega's binning."""
    bands = histogram_bands(values, top=top, step=step)
    labels = [b for b, _ in bands]
    df = pd.DataFrame(bands, columns=["band", "count"])
    hover = _hover(["band"])
    chart = (
        alt.Chart(df)
        .mark_bar(color=BRAND_COLOR, cornerRadiusEnd=3)
        .encode(
            x=alt.X("band:O", sort=labels, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("count:Q", title=None, axis=alt.Axis(format="d", tickMinStep=1)),
            opacity=alt.condition(hover, alt.value(1.0), alt.value(0.45)),
            tooltip=[
                alt.Tooltip("band:N", title=noun),
                alt.Tooltip("count:Q", title="Count"),
            ],
        )
        .add_params(hover)
        .properties(height=200)
    )
    return themed(chart)


def cohort_trend(weeks: Sequence[tuple[str, float, int]]) -> alt.LayerChart:
    """Average quiz score (%) per week. `weeks`: (week label, average, attempts)."""
    return _trend(
        [a for _, a, _ in weeks],
        [f"Week of {w} ({n} attempts)" for w, _, n in weeks],
        top=100,
        noun="Week",
        title="Average quiz score (%)",
        fmt="d",
    )


def stream_readiness_spec(rows: Sequence[tuple[str, int, float, str]]) -> dict:
    return json.loads(_stream_readiness_json(tuple(rows)))


@lru_cache(maxsize=64)
def _stream_readiness_json(rows: tuple[tuple[str, int, float, str], ...]) -> str:
    return json.dumps(to_spec(stream_readiness(rows)))


def rubric_breakdown_spec(averages: Mapping[str, float]) -> dict:
    return json.loads(_rubric_breakdown_json(tuple(averages.items())))


@lru_cache(maxsize=64)
def _rubric_breakdown_json(items: tuple[tuple[str, float], ...]) -> str:
    return json.dumps(to_spec(rubric_breakdown(dict(items))))


def gap_bars_spec(gaps: Sequence[tuple[str, int]], students: int) -> dict:
    return json.loads(_gap_bars_json(tuple(gaps), students))


@lru_cache(maxsize=64)
def _gap_bars_json(gaps: tuple[tuple[str, int], ...], students: int) -> str:
    return json.dumps(to_spec(gap_bars(gaps, students)))


def histogram_spec(values: Sequence[float], *, top: int, step: int, noun: str) -> dict:
    return json.loads(_histogram_json(tuple(values), top, step, noun))


@lru_cache(maxsize=64)
def _histogram_json(values: tuple[float, ...], top: int, step: int, noun: str) -> str:
    return json.dumps(to_spec(histogram(values, top=top, step=step, noun=noun)))


def cohort_trend_spec(weeks: Sequence[tuple[str, float, int]]) -> dict:
    return json.loads(_cohort_trend_json(tuple(weeks)))


@lru_cache(maxsize=64)
def _cohort_trend_json(weeks: tuple[tuple[str, float, int], ...]) -> str:
    return json.dumps(to_spec(cohort_trend(weeks)))


# --- organization portal: funnel, tiers, topics and the skill-gap heatmap ------------------------
# Same rules as the cohort charts above: brand teal marks (a stage, a tier or a skill is not a
# topic), values in the labels, a tooltip on every mark, hover dims the rest.


def funnel_bars(stages: Sequence[tuple[str, int, float, float]]) -> alt.Chart:
    """The readiness funnel, widest first. `stages`: (label, students, share of enrolled, share
    of the stage before), in journey order."""
    df = pd.DataFrame(stages, columns=["stage", "students", "of_enrolled", "of_previous"])
    df["label"] = [f"{s}  {n}" for s, n in zip(df["stage"], df["students"], strict=True)]
    return _label_bars(
        df,
        value="students",
        top=max(1, int(df["students"].max()) if len(df) else 1),
        fmt="d",
        tooltip=[
            alt.Tooltip("stage:N", title="Stage"),
            alt.Tooltip("students:Q", title="Students"),
            alt.Tooltip("of_enrolled:Q", title="Of all enrolled", format=".0%"),
            alt.Tooltip("of_previous:Q", title="Of the stage before", format=".0%"),
        ],
    )


def tier_bars(tiers: Sequence[tuple[str, int]]) -> alt.Chart:
    """How many students are in each readiness tier (Ready, In Progress, At Risk)."""
    df = pd.DataFrame(tiers, columns=["tier", "students"])
    total = max(1, int(df["students"].sum()) if len(df) else 1)
    df["label"] = [f"{t}  {n}" for t, n in zip(df["tier"], df["students"], strict=True)]
    df["share"] = df["students"] / total
    return _label_bars(
        df,
        value="students",
        top=total,
        fmt="d",
        tooltip=[
            alt.Tooltip("tier:N", title="Tier"),
            alt.Tooltip("students:Q", title="Students"),
            alt.Tooltip("share:Q", title="Share of the batch", format=".0%"),
        ],
    )


def momentum_bars(stages: Sequence[tuple[str, int]]) -> alt.Chart:
    """How many students are in each momentum stage:
    Placement Ready, On Track, Falling Behind, Stalled."""
    df = pd.DataFrame(stages, columns=["stage", "students"])
    total = max(1, int(df["students"].sum()) if len(df) else 1)
    df["label"] = [f"{s}  {n}" for s, n in zip(df["stage"], df["students"], strict=True)]
    df["share"] = df["students"] / total
    return _label_bars(
        df,
        value="students",
        top=total,
        fmt="d",
        tooltip=[
            alt.Tooltip("stage:N", title="Momentum Stage"),
            alt.Tooltip("students:Q", title="Students"),
            alt.Tooltip("share:Q", title="Share of the batch", format=".0%"),
        ],
    )


def percent_bars(items: Sequence[tuple[str, float]], noun: str = "Score") -> alt.Chart:
    """Scores out of 100 per name (one student's average per topic), lowest first so the
    weakest topic leads."""
    df = pd.DataFrame(items, columns=["name", "percent"])
    df["label"] = [f"{n}  {p:.0f}%" for n, p in zip(df["name"], df["percent"], strict=True)]
    return _label_bars(
        df,
        value="percent",
        top=100,
        fmt="d",
        tooltip=[
            alt.Tooltip("name:N", title="Topic"),
            alt.Tooltip("percent:Q", title=f"{noun} (%)", format=".1f"),
        ],
    )


HEAT_LOW = "#DCE9E9"  # the faint end of the heatmap ramp; dark text reads on it in either scheme


def gap_heatmap(cells: Sequence[tuple[str, str, int, int]]) -> alt.LayerChart:
    """Skills (rows, most missing first) by group (columns): each cell's tint is the share of the
    group's scanned students missing the skill, and its number is how many. `cells`: (skill,
    group, students missing, students scanned in the group)."""
    df = pd.DataFrame(cells, columns=["skill", "group", "missing", "scanned"])
    df["share"] = df["missing"] / df["scanned"].clip(lower=1)
    skills = list(dict.fromkeys(df["skill"]))
    groups = sorted(set(df["group"]))
    base = alt.Chart(df).encode(
        x=alt.X("group:N", sort=groups, title=None, axis=alt.Axis(labelAngle=0, labelLimit=140)),
        y=alt.Y("skill:N", sort=skills, title=None, axis=alt.Axis(labelLimit=0, labelPadding=8)),
    )
    rect = base.mark_rect(cornerRadius=3, stroke=None).encode(
        color=alt.Color(
            "share:Q",
            scale=alt.Scale(domain=[0, 1], range=[HEAT_LOW, BRAND_COLOR], clamp=True),
            legend=alt.Legend(title="Share missing", format=".0%", orient="bottom"),
        ),
        tooltip=[
            alt.Tooltip("skill:N", title="Skill"),
            alt.Tooltip("group:N", title="Group"),
            alt.Tooltip("missing:Q", title="Students missing it"),
            alt.Tooltip("scanned:Q", title="Students scanned"),
            alt.Tooltip("share:Q", title="Share missing", format=".0%"),
        ],
    )
    text = base.mark_text(fontSize=12, fontWeight="bold").encode(
        text=alt.Text("missing:Q", format="d"),
        color=alt.condition(alt.datum.share > 0.55, alt.value("#FFFFFF"), alt.value("#1A2326")),
    )
    return themed(alt.layer(rect, text).properties(height=ROW_PX * max(1, len(skills)) + 70))


def funnel_spec(stages: Sequence[tuple[str, int, float, float]]) -> dict:
    return json.loads(_funnel_json(tuple(stages)))


@lru_cache(maxsize=64)
def _funnel_json(stages: tuple[tuple[str, int, float, float], ...]) -> str:
    return json.dumps(to_spec(funnel_bars(stages)))


def tier_spec(tiers: Sequence[tuple[str, int]]) -> dict:
    return json.loads(_tier_json(tuple(tiers)))


@lru_cache(maxsize=64)
def _tier_json(tiers: tuple[tuple[str, int], ...]) -> str:
    return json.dumps(to_spec(tier_bars(tiers)))


def momentum_spec(stages: Sequence[tuple[str, int]]) -> dict:
    return json.loads(_momentum_json(tuple(stages)))


@lru_cache(maxsize=64)
def _momentum_json(stages: tuple[tuple[str, int], ...]) -> str:
    return json.dumps(to_spec(momentum_bars(stages)))


def percent_bars_spec(items: Sequence[tuple[str, float]], noun: str = "Score") -> dict:
    return json.loads(_percent_bars_json(tuple(items), noun))


@lru_cache(maxsize=64)
def _percent_bars_json(items: tuple[tuple[str, float], ...], noun: str) -> str:
    return json.dumps(to_spec(percent_bars(items, noun)))


def gap_heatmap_spec(cells: Sequence[tuple[str, str, int, int]]) -> dict:
    return json.loads(_gap_heatmap_json(tuple(cells)))


@lru_cache(maxsize=64)
def _gap_heatmap_json(cells: tuple[tuple[str, str, int, int], ...]) -> str:
    return json.dumps(to_spec(gap_heatmap(cells)))


def quiz_trend(percents: Sequence[float], labels: Sequence[str]) -> alt.LayerChart:
    """One student's quiz scores (%) in order, one point per attempt."""
    return _trend(percents, labels, top=100, noun="Attempt", title="Quiz score (%)", fmt="d")


def quiz_trend_spec(percents: Sequence[float], labels: Sequence[str]) -> dict:
    return json.loads(_quiz_trend_json(tuple(percents), tuple(labels)))


@lru_cache(maxsize=64)
def _quiz_trend_json(percents: tuple[float, ...], labels: tuple[str, ...]) -> str:
    return json.dumps(to_spec(quiz_trend(percents, labels)))

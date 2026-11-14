"""Calendar and task checklist export utilities for study plans.

Method B: Google Calendar deep links and RFC-5545 compliant .ics calendar files.
Method C: Markdown/plain-text checklist formatting for Google Keep, Apple Notes, and Tasks.
"""

import json
import re
import urllib.parse
from collections.abc import Collection, Sequence
from datetime import UTC, date, datetime, timedelta


def build_gcal_url(
    title: str,
    details: str,
    target_date: date | None = None,
    duration_min: int = 60,
) -> str:
    """Build a Google Calendar TEMPLATE URL for one-click scheduling in a new tab."""
    params = {
        "action": "TEMPLATE",
        "text": title,
        "details": details,
    }
    if target_date:
        start_str = target_date.strftime("%Y%m%d")
        end_date = target_date + timedelta(days=1)
        end_str = end_date.strftime("%Y%m%d")
        params["dates"] = f"{start_str}/{end_str}"
    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote_plus)
    return f"https://calendar.google.com/calendar/render?{query}"


def _ics_escape(text: str) -> str:
    """Escape text for iCalendar RFC-5545 compliance."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _ics_fold(line: str, max_len: int = 75) -> str:
    """Fold lines exceeding max_len bytes with CRLF and a space as per RFC-5545."""
    encoded = line.encode("utf-8")
    if len(encoded) <= max_len:
        return line
    parts = []
    while len(encoded) > max_len:
        split_at = max_len
        # Avoid splitting multi-byte UTF-8 character sequences
        while split_at > 0 and (encoded[split_at] & 0xC0) == 0x80:
            split_at -= 1
        parts.append(encoded[:split_at].decode("utf-8"))
        encoded = b" " + encoded[split_at:]
    parts.append(encoded.decode("utf-8"))
    return "\r\n".join(parts)


def _get_day_attr(item: object, attr: str, default: object = None) -> object:
    if hasattr(item, attr):
        return getattr(item, attr)
    if isinstance(item, dict):
        return item.get(attr, default)
    return default


def generate_plan_ics(
    plan: object,
    start_date: date | None = None,
    now: datetime | None = None,
) -> bytes:
    """Generate an RFC-5545 compliant .ics file containing all 7 days of tasks as all-day events."""
    now_utc = now or datetime.now(UTC)
    start = start_date or (date.today() + timedelta(days=(7 - date.today().weekday()) % 7 or 7))

    week_no = getattr(plan, "week_no", 1)
    days_data = getattr(plan, "days", [])
    if isinstance(days_data, Sequence):
        sorted_days = sorted(days_data, key=lambda d: _get_day_attr(d, "day", 0))  # type: ignore
    else:
        sorted_days = []

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Skill Scout Nexus//7-Day Study Schedule//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:Skill Scout Nexus - Week {week_no} Plan",
        "X-WR-TIMEZONE:UTC",
    ]

    for d in sorted_days:
        day_num = _get_day_attr(d, "day", 1)
        topic = str(_get_day_attr(d, "topic", ""))
        goal = str(_get_day_attr(d, "practice_goal", ""))
        dur = int(_get_day_attr(d, "duration_min", 60))  # type: ignore
        subtopics = _get_day_attr(d, "subtopics", [])
        sub_str = ", ".join(subtopics) if isinstance(subtopics, list) else str(subtopics)

        event_date = start + timedelta(days=day_num - 1)  # type: ignore
        next_date = event_date + timedelta(days=1)

        summary = f"Day {day_num}: {topic} ({dur} min)"
        description = (
            f"Placement Preparation - Week {week_no}, Day {day_num}\n"
            f"Topic: {topic}\n"
            f"Study Goal: {goal}\n"
            f"Key Subtopics: {sub_str}\n"
            f"Duration: {dur} minutes"
        )

        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:ssn-w{week_no}-d{day_num}-{event_date:%Y%m%d}@skillscoutnexus",
                f"DTSTAMP:{now_utc:%Y%m%dT%H%M%SZ}",
                f"DTSTART;VALUE=DATE:{event_date:%Y%m%d}",
                f"DTEND;VALUE=DATE:{next_date:%Y%m%d}",
                f"SUMMARY:{_ics_escape(summary)}",
                f"DESCRIPTION:{_ics_escape(description)}",
                "STATUS:CONFIRMED",
                "TRANSP:TRANSPARENT",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    return ("\r\n".join(_ics_fold(line) for line in lines) + "\r\n").encode("utf-8")


def format_tasks_checklist(
    plan: object,
    week_no: int | None = None,
    done_days: Collection[int] | None = None,
) -> str:
    """Format the 7-day study plan as a Markdown checklist ready for Google Keep/Tasks."""
    w_no = week_no or getattr(plan, "week_no", 1)
    days_data = getattr(plan, "days", [])
    done = set(done_days or ())

    lines = [
        f"# 📅 7-Day Placement Preparation Plan (Week {w_no})",
        "",
        "Copy and paste this checklist directly into Google Keep, Apple Notes, or Notion.",
        "",
    ]

    for d in days_data:
        day_num = _get_day_attr(d, "day", 1)
        topic = str(_get_day_attr(d, "topic", ""))
        goal = str(_get_day_attr(d, "practice_goal", ""))
        dur = int(_get_day_attr(d, "duration_min", 60))  # type: ignore
        subtopics = _get_day_attr(d, "subtopics", [])

        box = "[x]" if day_num in done else "[ ]"
        lines.append(f"{box} Day {day_num}: {topic} ({dur} min)")
        if goal:
            lines.append(f"    - Goal: {goal}")
        if subtopics and isinstance(subtopics, list):
            for sub in subtopics:
                lines.append(f"    - [ ] Practice: {sub}")
        lines.append("")

    return "\n".join(lines).strip()


def copy_clipboard_button_html(text_to_copy: str, button_id: str = "btn-copy-tasks") -> str:
    """Return a clean HTML/JS button component that copies text directly to system clipboard.

    The text sits in an inline <script>: `<`, `>` and `&` are written as JSON escapes, so text
    holding "</script>" (plan text comes from the AI) cannot close the script and inject markup.
    The id becomes part of JS function names, so it is reduced to letters, digits and "_"."""
    safe_json = (
        json.dumps(text_to_copy)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    b_id = re.sub(r"\W", "_", button_id, flags=re.ASCII) or "btn"
    return f"""
    <div style="margin: 8px 0;">
        <button id="{b_id}" onclick='copyText_{b_id}()'
            style="
                display: inline-flex;
                align-items: center;
                gap: 8px;
                padding: 8px 16px;
                background-color: #0d6670;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                font-family: system-ui, -apple-system, sans-serif;
                font-size: 14px;
                font-weight: 600;
                cursor: pointer;
                transition: background-color 0.2s ease;
            "
            onmouseover="this.style.backgroundColor='#0a525a'"
            onmouseout="this.style.backgroundColor='#0d6670'"
        >
            <span>📋</span> Copy Checklist to Clipboard
        </button>
        <span id="msg_{b_id}" style="margin-left: 10px; font-size: 13px; color: #16a34a;
            font-weight: 500; display: none;">
            ✅ Copied to clipboard!
        </span>
    </div>
    <script>
    function copyText_{b_id}() {{
        const text = {safe_json};
        if (navigator.clipboard && navigator.clipboard.writeText) {{
            navigator.clipboard.writeText(text).then(() => showSuccess_{b_id}());
        }} else {{
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            showSuccess_{b_id}();
        }}
    }}
    function showSuccess_{b_id}() {{
        const msg = document.getElementById("msg_{b_id}");
        if (msg) {{
            msg.style.display = "inline";
            setTimeout(() => {{ msg.style.display = "none"; }}, 2500);
        }}
    }}
    </script>
    """

#!/usr/bin/env python3
"""School Bot - GitHub edition.  Sends messages to Telegram from data/school.yml.

  python bot.py weekly     this week: study week, projector team, events
  python bot.py month      exams & holidays of a month (--month 10  or  --month 2026-10)
  python bot.py schedule   the class timetable
  python bot.py chats      list the chats that talked to the bot (to find CHAT_IDS)
  python bot.py check      check data/school.yml for mistakes
Add --dry-run to only preview.  Needs env BOT_TOKEN and CHAT_IDS (GitHub secrets).
"""
import argparse
import calendar
import html
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

DATA_FILE = Path(__file__).resolve().parent / "data" / "school.yml"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
ICON = {"exam": "📝", "holiday": "🎉", "other": "📌"}
TITLE = {"exam": "Exams", "holiday": "Holidays", "other": "Other"}
esc = html.escape


class DataError(Exception):
    pass


# ---------------------------------------------------------------- reading + checking the data file
def as_date(v, where):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return date.fromisoformat(v.strip())
        except ValueError:
            pass
    raise DataError(f"{where}: '{v}' is not a date. Write it like 2026-09-14")


def monday_of(d):
    return d - timedelta(days=d.weekday())


def load():
    try:
        raw = yaml.safe_load(DATA_FILE.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise DataError("The file data/school.yml is missing.")
    except yaml.YAMLError as e:
        raise DataError("data/school.yml has a typing mistake (look at the line number below).\n"
                        "Common causes: a colon (:) inside a title without \"quotes\", or wrong spaces at the start of a line.\n\n"
                        + str(e))
    if not isinstance(raw, dict):
        raise DataError("data/school.yml should contain sections like semester:, projector:, events:, schedule:")

    errors = []

    def guard(fn, *a):
        try:
            return fn(*a)
        except DataError as e:
            errors.append(str(e))

    tzname = str(raw.get("timezone") or "Asia/Phnom_Penh").strip().replace(" ", "_")
    try:
        tz = ZoneInfo(tzname)
    except Exception:
        errors.append(f"timezone: '{tzname}' is not a known time zone (example: Asia/Phnom_Penh)")
        tz = ZoneInfo("UTC")

    sem = raw.get("semester") or {}
    nums = {}
    for name, default, lo, hi in (("year", 1, 1, 10), ("number", 1, 1, 4), ("weeks", 18, 1, 60)):
        val = sem.get(name, default)
        if isinstance(val, bool) or not isinstance(val, int) or not lo <= val <= hi:
            errors.append(f"semester.{name} must be a whole number from {lo} to {hi}")
            val = default
        nums[name] = val
    start = guard(as_date, sem["start"], "semester.start") if sem.get("start") else None

    pr = raw.get("projector") or {}
    teams = [str(t).strip() for t in (pr.get("teams") or []) if str(t).strip()]
    rot = guard(as_date, pr["rotation_start"], "projector.rotation_start") if pr.get("rotation_start") else start
    if teams and not rot:
        errors.append("projector.rotation_start is needed (the week that uses the first team)")
    overrides = {}
    for k, v in (pr.get("overrides") or {}).items():
        d = guard(as_date, k, "projector.overrides")
        if d and str(v).strip():
            overrides[monday_of(d)] = str(v).strip()

    events = []
    for i, e in enumerate(raw.get("events") or [], 1):
        where = f"events, item {i}"
        if not isinstance(e, dict):
            errors.append(f"{where}: each event needs lines like title:, type:, start:")
            continue
        title = str(e.get("title") or "").strip()
        typ = str(e.get("type") or "other").strip().lower()
        if not title:
            errors.append(f"{where}: title is missing")
        if typ not in ICON:
            errors.append(f"{where} ({title}): type must be exam, holiday or other")
            typ = "other"
        s = guard(as_date, e.get("start"), f"{where} ({title}) start")
        en = guard(as_date, e.get("end") or e.get("start"), f"{where} ({title}) end")
        if s and en and en < s:
            errors.append(f"{where} ({title}): end is before start")
        if title and s and en:
            events.append({"title": title, "type": typ, "start": s, "end": max(s, en),
                           "note": str(e.get("note") or "").strip()})

    classes = []
    for i, c in enumerate(raw.get("schedule") or [], 1):
        where = f"schedule, item {i}"
        if not isinstance(c, dict):
            errors.append(f"{where}: each class needs lines like day:, time:, subject:")
            continue
        subject = str(c.get("subject") or "").strip()
        day = str(c.get("day") or "").strip().title()
        m = re.fullmatch(r"(\d{1,2}):(\d\d)\s*-\s*(\d{1,2}):(\d\d)", str(c.get("time") or "").strip())
        if not subject:
            errors.append(f"{where}: subject is missing")
        if day not in DAYS:
            errors.append(f"{where} ({subject}): day must be Monday ... Sunday")
        if not m or int(m[1]) > 23 or int(m[3]) > 23 or int(m[2]) > 59 or int(m[4]) > 59:
            errors.append(f"{where} ({subject}): time must look like \"08:00-09:30\" (with quotes)")
        if subject and day in DAYS and m:
            classes.append({"day": DAYS.index(day), "subject": subject,
                            "time": f"{int(m[1]):02d}:{m[2]}–{int(m[3]):02d}:{m[4]}",
                            "room": str(c.get("room") or "").strip(),
                            "teacher": str(c.get("teacher") or "").strip()})
    classes.sort(key=lambda c: (c["day"], c["time"]))

    if errors:
        raise DataError("Please fix these in data/school.yml:\n - " + "\n - ".join(errors))
    return {"tz": tz, "year": nums["year"], "number": nums["number"], "weeks": nums["weeks"],
            "start": start, "teams": teams, "rot": rot, "overrides": overrides,
            "events": sorted(events, key=lambda e: (e["start"], e["title"])), "classes": classes}


# ---------------------------------------------------------------- message texts
def short(d):
    return f"{d.day} {d:%b}"


def fmt_range(s, e):
    if s == e:
        return f"{s:%a} {short(s)}"
    if (s.year, s.month) == (e.year, e.month):
        return f"{s.day}–{e.day} {s:%b}"
    return f"{short(s)} – {short(e)}"


def status(ev, t):
    if ev["end"] < t:
        return "✔️ Finished"
    if ev["start"] <= t <= ev["end"]:
        return "🔴 Today" if ev["start"] == ev["end"] else f"🔴 Happening now · until {short(ev['end'])}"
    days = (ev["start"] - t).days
    return "⏳ Tomorrow" if days == 1 else f"⏳ In {days} days"


def events_between(D, a, b):
    return [e for e in D["events"] if e["start"] <= b and e["end"] >= a]


def year_for_month(month, t):
    """Only a month is given: show the 3 months before and 8 months after today."""
    off = month - t.month
    return t.year - 1 if off > 8 else t.year + 1 if off < -3 else t.year


def team_for(D, d):
    mon = monday_of(d)
    if mon in D["overrides"]:
        return D["overrides"][mon]
    if not D["teams"] or not D["rot"]:
        return None
    n = (mon - monday_of(D["rot"])).days // 7
    return D["teams"][n % len(D["teams"])] if n >= 0 else None


def semester_parts(D, d):
    sub = f"Semester {D['number']} · Year {D['year']}"
    if not D["start"]:
        return sub, ""
    n = (monday_of(d) - monday_of(D["start"])).days // 7 + 1
    if n < 1:
        return f"Starts in {1 - n} week(s)", sub
    if n > D["weeks"]:
        return "Semester finished", sub
    return f"Week {n} of {D['weeks']}", sub


def weekly_text(D, t):
    mon, sun = monday_of(t), monday_of(t) + timedelta(days=6)
    rng = f"{mon.day} – {sun.day} {sun:%b %Y}" if mon.month == sun.month else f"{short(mon)} – {short(sun)} {sun:%Y}"
    big, sub = semester_parts(D, t)
    lines = [f"📢 <b>This week</b>\n{rng}", f"\n🎓 <b>{big}</b>"]
    if sub:
        lines.append(sub)
    team = team_for(D, t)
    lines += ["\n📽 <b>Projector team</b>", esc(team) if team else "Not assigned yet"]
    evs = events_between(D, mon, sun)
    if evs:
        lines.append("\n📌 <b>Events this week</b>")
        lines += [f"{ICON[e['type']]} {fmt_range(e['start'], e['end'])} — {esc(e['title'])}" for e in evs]
    return "\n".join(lines)


def month_text(D, year, month, t):
    first, last = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    lines = [f"📅 <b>{first:%B %Y}</b>"]
    if first <= t <= last:
        lines.append(f"Today is {t:%A}, {short(t)}")
    evs = events_between(D, first, last)
    if not evs:
        lines.append("\n✅ No exams or holidays this month.")
    for typ in ("exam", "holiday", "other"):
        group = [e for e in evs if e["type"] == typ]
        if group:
            lines.append(f"\n{ICON[typ]} <b>{TITLE[typ]}</b>")
            for e in group:
                lines.append(f"▪️ <b>{fmt_range(e['start'], e['end'])}</b> — {esc(e['title'])}")
                if e["note"]:
                    lines.append(f"      ℹ️ {esc(e['note'])}")
                lines.append(f"      {status(e, t)}")
    return "\n".join(lines)


def schedule_text(D, t):
    if not D["classes"]:
        return "🗓 The class schedule has not been added yet."
    out = ["🗓 <b>Class schedule</b>"]
    for d in range(7):
        day = [c for c in D["classes"] if c["day"] == d]
        if day:
            out.append(f"\n<b>{DAYS[d]}</b>")
            for c in day:
                out.append(f"⏰ {c['time']}  <b>{esc(c['subject'])}</b>")
                extra = ([f"📍 {esc(c['room'])}"] if c["room"] else []) + ([f"👤 {esc(c['teacher'])}"] if c["teacher"] else [])
                if extra:
                    out.append("      " + "  ·  ".join(extra))
    return "\n".join(out)


# ---------------------------------------------------------------- Telegram
def plain(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def chunks(text, limit=3900):
    out, cur = [], ""
    for line in text.split("\n"):
        if cur and len(cur) + len(line) + 1 > limit:
            out.append(cur)
            cur = ""
        cur += ("\n" if cur else "") + line
    return out + ([cur] if cur else [])


def api(token, method, **payload):
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        r = requests.post(url, json=payload, timeout=20)
        if r.status_code == 429:  # too many messages: wait once and retry
            try:
                wait = r.json().get("parameters", {}).get("retry_after", 3)
            except ValueError:
                wait = 3
            time.sleep(min(wait, 30))
            r = requests.post(url, json=payload, timeout=20)
        try:
            return r.json()
        except ValueError:
            return {"ok": False, "description": f"Telegram did not answer properly (HTTP {r.status_code})"}
    except Exception as e:
        return {"ok": False, "description": "Could not reach Telegram: " + str(e).replace(token, "***")}


def broadcast(text, dry):
    if dry:
        print("---------- PREVIEW (nothing is sent) ----------")
        print(plain(text))
        print("-----------------------------------------------")
        return True
    token = os.getenv("BOT_TOKEN", "").strip()
    ids = [x.strip() for x in os.getenv("CHAT_IDS", "").split(",") if x.strip()]
    if not token:
        sys.exit("❌ The BOT_TOKEN secret is missing. See README step 4.")
    if not ids:
        sys.exit("❌ The CHAT_IDS secret is missing. See README step 5-6.")
    ok = True
    for cid in ids:
        for part in chunks(text):
            res = api(token, "sendMessage", chat_id=cid, text=part, parse_mode="HTML", disable_web_page_preview=True)
            if res.get("ok"):
                print(f"✅ sent to {cid}")
            else:
                ok = False
                print(f"❌ {cid}: {res.get('description')}")
                break
        time.sleep(0.1)
    return ok


def find_chats():
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        sys.exit("❌ The BOT_TOKEN secret is missing. See README step 4.")
    res = api(token, "getUpdates", timeout=0, allowed_updates=["message", "my_chat_member", "callback_query"])
    if not res.get("ok"):
        sys.exit(f"❌ Telegram said: {res.get('description')}\n"
                 "(If it mentions 'Conflict', another copy of this bot is running somewhere. Stop it first.)")
    seen = {}
    for u in res["result"]:
        chat = (u.get("message") or u.get("my_chat_member") or (u.get("callback_query") or {}).get("message") or {}).get("chat")
        if chat:
            seen[chat["id"]] = chat
    if not seen:
        print("No chats found yet.\nAdd the bot to your group (or open the bot and press Start), send /start, then run this again.")
        return
    print("Copy the number(s) into the CHAT_IDS secret (separate several with commas):\n")
    for cid, c in seen.items():
        name = c.get("title") or " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x) or c.get("username", "")
        print(f"  {cid}    {c.get('type')}    {name}")


# ---------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser()
    p.add_argument("what", choices=["weekly", "month", "schedule", "chats", "check"])
    p.add_argument("--month", default="", help="10  or  2026-10  (empty = this month)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--today", default="", help="pretend today is YYYY-MM-DD (for testing)")
    a = p.parse_args()

    if a.what == "chats":
        return find_chats()
    try:
        D = load()
    except DataError as e:
        print(f"❌ {e}")
        sys.exit(1)
    t = date.fromisoformat(a.today) if a.today else datetime.now(D["tz"]).date()

    if a.what == "check":
        print(f"✅ data/school.yml is fine: {len(D['events'])} event(s), {len(D['classes'])} class(es), "
              f"{len(D['teams'])} team(s).\n")
        if not D["start"]:
            print("Note: semester.start is empty, so the week number is not shown.")
        if not team_for(D, t):
            print("Note: no projector team is set for this week.")
        return broadcast(weekly_text(D, t), dry=True)

    if a.what == "weekly":
        text = weekly_text(D, t)
    elif a.what == "schedule":
        text = schedule_text(D, t)
    else:
        m = a.month.strip()
        if re.fullmatch(r"\d{4}-\d{1,2}", m):
            y, mo = map(int, m.split("-"))
        elif re.fullmatch(r"\d{1,2}", m):
            mo = int(m)
            y = year_for_month(mo, t)
        elif m == "":
            y, mo = t.year, t.month
        else:
            sys.exit("❌ month must look like 10 or 2026-10")
        if not 1 <= mo <= 12 or not 2000 <= y <= 2100:
            sys.exit("❌ month must be between 1 and 12")
        text = month_text(D, y, mo, t)
    if not broadcast(text, a.dry_run):
        sys.exit(1)


if __name__ == "__main__":
    main()

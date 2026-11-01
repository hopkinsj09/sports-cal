#!/usr/bin/env python3
"""Pull games from the Crossbar iCal feed; write docs/schedule.ics and docs/schedule.pdf."""
import html, re, sys, urllib.request
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo

SRC = "https://www.accounts.crossbar.org/calendar/ical/302628"
TZ = ZoneInfo("America/Chicago")
TEAM = "10U A2 Garrett"
CAL_NAME = f"{TEAM} Games"
GAME_RE = re.compile(r"\s(vs|@)\s", re.I)
NOT_GAME = re.compile(r"practice|pictures|serving night", re.I)


def fetch(path=None):
    if path:
        return open(path, encoding="utf-8").read()
    req = urllib.request.Request(SRC, headers={"User-Agent": "sports-cal/1.0"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8")


def parse(text):
    text = re.sub(r"\r?\n[ \t]", "", text)  # unfold
    events = []
    for blk in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        f = {}
        for line in blk.strip().splitlines():
            k, _, v = line.partition(":")
            f[k.split(";")[0] + (";D" if "VALUE=DATE" in k else "")] = v
        events.append(f)
    return events


def clean(s):
    return html.unescape(s.replace("\\,", ",").replace("\\n", " ")).strip()


def games(events):
    out = []
    for e in events:
        title = clean(e.get("SUMMARY", ""))
        if not GAME_RE.search(title) or NOT_GAME.search(title):
            continue
        tbd = "DTSTART;D" in e
        if tbd:
            s = datetime.strptime(e["DTSTART;D"], "%Y%m%d").date()
            end = None
        else:
            s = datetime.strptime(e["DTSTART"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(TZ)
            end = datetime.strptime(e["DTEND"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(TZ)
        desc = clean(e.get("DESCRIPTION", ""))
        away = bool(re.search(r"\s@\s", title)) or desc.lower().startswith("away")
        out.append(dict(uid=e["UID"], title=title.replace("[TBD] ", ""), tbd=tbd, start=s, end=end,
                        loc=re.sub(r"\s+", " ", clean(e.get("LOCATION", ""))), desc=desc, away=away))
    out.sort(key=lambda g: (g["start"] if g["tbd"] else g["start"].date(), 1 if g["tbd"] else 0,
                            g["start"].isoformat()))
    return out


def esc(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    b, out = line.encode(), []
    while len(b) > 74:
        cut = 74
        while b[cut] & 0xC0 == 0x80:
            cut -= 1
        out.append(b[:cut].decode()); b = b[cut:]; b = b" " + b
    out.append(b.decode())
    return "\r\n".join(out)


def write_ics(gs, path):
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//sports-cal//10U A2 Garrett//EN", "CALSCALE:GREGORIAN",
         "METHOD:PUBLISH", f"X-WR-CALNAME:{CAL_NAME}", "X-WR-TIMEZONE:America/Chicago",
         "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"]
    for g in gs:
        L += ["BEGIN:VEVENT", f"UID:{g['uid']}", "DTSTAMP:20260101T000000Z"]  # stable => no spurious diffs
        title = ("[TBD] " if g["tbd"] else "") + g["title"]
        L.append("SUMMARY:" + esc(title))
        if g["tbd"]:
            nxt = date.fromordinal(g["start"].toordinal() + 1)
            L += [f"DTSTART;VALUE=DATE:{g['start']:%Y%m%d}", f"DTEND;VALUE=DATE:{nxt:%Y%m%d}"]
        else:
            L += [f"DTSTART:{g['start'].astimezone(timezone.utc):%Y%m%dT%H%M%SZ}",
                  f"DTEND:{g['end'].astimezone(timezone.utc):%Y%m%dT%H%M%SZ}"]
        if g["loc"]: L.append("LOCATION:" + esc(g["loc"]))
        if g["desc"]: L.append("DESCRIPTION:" + esc(g["desc"]))
        L += ["END:VEVENT"]
    L.append("END:VCALENDAR")
    open(path, "w", newline="", encoding="utf-8").write("\r\n".join(fold(l) for l in L) + "\r\n")


def short(g):
    t = g["title"].replace(TEAM, "").strip()
    t = re.sub(r"^(vs|@)\s+", "", t)
    return ("@ " if g["away"] else "vs ") + t


def venue(g):
    if g["tbd"]:
        return ""
    m = re.match(r"(.*?)(?=\s+\d|\s{2}|$)", g["loc"])
    return m.group(1).strip() if m else ""


def write_pdf(gs, path):
    import calendar
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Paragraph
    W, H = landscape(letter)
    c = canvas.Canvas(path, pagesize=(W, H), pageCompression=1)
    c.setTitle(f"{TEAM} Game Schedule")
    gm = ParagraphStyle("g", fontName="Helvetica-Bold", fontSize=7, leading=8)
    gv = ParagraphStyle("v", fontName="Helvetica-Oblique", fontSize=6, leading=7, textColor=colors.HexColor("#555555"))
    by = {}
    for g in gs:
        by.setdefault(g["start"] if g["tbd"] else g["start"].date(), []).append(g)
    d0, d1 = min(by), max(by)
    months, y, m = [], d0.year, d0.month
    while (y, m) <= (d1.year, d1.month):
        months.append((y, m)); m += 1
        if m == 13: y, m = y + 1, 1
    upd = datetime.now(TZ).strftime("%b %d, %Y")
    L, R, T, B = 0.4*inch, W - 0.4*inch, H - 0.95*inch, 0.55*inch
    cw = (R - L) / 7
    calendar.setfirstweekday(6)
    for y, m in months:
        weeks = calendar.monthcalendar(y, m)
        ch = (T - 0.25*inch - B) / len(weeks)
        c.setFont("Helvetica-Bold", 22); c.setFillColor(colors.black)
        c.drawString(L, H - 0.6*inch, f"{calendar.month_name[m]} {y}")
        c.setFont("Helvetica", 9); c.setFillColor(colors.grey)
        c.drawRightString(R, H - 0.6*inch, f"{TEAM} games  |  AWAY = @  |  shaded = time TBD")
        for i, n in enumerate(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]):
            c.setFillColor(colors.HexColor("#333333")); c.rect(L + i*cw, T - 0.25*inch, cw, 0.25*inch, fill=1, stroke=0)
            c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 9)
            c.drawCentredString(L + i*cw + cw/2, T - 0.18*inch, n)
        for r, wk in enumerate(weeks):
            top = T - 0.25*inch - r*ch
            for i, day in enumerate(wk):
                x = L + i*cw
                c.setStrokeColor(colors.HexColor("#999999")); c.setLineWidth(0.5)
                c.setFillColor(colors.HexColor("#f2f2f2") if day == 0 else colors.white)
                c.rect(x, top - ch, cw, ch, fill=1, stroke=1)
                if not day: continue
                c.setFillColor(colors.black); c.setFont("Helvetica-Bold", 9)
                c.drawString(x + 3, top - 11, str(day))
                cy = top - 15
                for g in by.get(date(y, m, day), []):
                    parts = [("TBD " if g["tbd"] else f"{g['start']:%I:%M%p}".lstrip("0").lower() + " ") + short(g)]
                    p1 = Paragraph(html.escape(parts[0]), gm)
                    p2 = Paragraph(html.escape(venue(g)), gv)
                    _, h1 = p1.wrap(cw - 8, 100); _, h2 = p2.wrap(cw - 8, 100)
                    hh = h1 + h2 + 3
                    c.setFillColor(colors.HexColor("#fff3cd") if g["tbd"] else
                                   colors.HexColor("#fde2e2") if g["away"] else colors.HexColor("#dff0d8"))
                    c.rect(x + 2, cy - hh, cw - 4, hh, fill=1, stroke=0)
                    p1.drawOn(c, x + 4, cy - h1 - 1); p2.drawOn(c, x + 4, cy - h1 - h2 - 1)
                    cy -= hh + 2
        c.setFont("Helvetica", 8); c.setFillColor(colors.grey)
        c.drawString(L, 0.3*inch, f"Updated {upd}. Times are Central. Green = home, red = away.")
        c.showPage()
    c.save()


if __name__ == "__main__":
    gs = games(parse(fetch(sys.argv[1] if len(sys.argv) > 1 else None)))
    write_ics(gs, "docs/schedule.ics")
    write_pdf(gs, "docs/schedule.pdf")
    print(f"{len(gs)} games written")

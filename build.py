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


def write_pdf(gs, path):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    sm = ParagraphStyle("sm", fontName="Helvetica", fontSize=8.5, leading=10.5)
    smb = ParagraphStyle("smb", parent=sm, fontName="Helvetica-Bold")
    H = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=18, leading=24, spaceAfter=4)
    sub = ParagraphStyle("s", fontName="Helvetica", fontSize=9, textColor=colors.grey, spaceAfter=8)
    P = lambda t, st=sm: Paragraph(html.escape(t), st)
    rows = [[P("Date", smb), P("Time", smb), P("Game", smb), P("Location / Notes", smb)]]
    tbd_rows = []
    for g in gs:
        s = g["start"]
        d = f"{s:%a %b} {s.day}"
        t = "TBD" if g["tbd"] else f"{s:%I:%M %p}".lstrip("0")
        place = g["loc"] + (f"\n{g['desc']}" if g["desc"] else "")
        cell = Paragraph(html.escape(place).replace("\n", "<br/>"), sm)
        tag = "AWAY  " if g["away"] else ""
        rows.append([P(d), P(t), P(tag + g["title"]), cell])
        if g["tbd"]: tbd_rows.append(len(rows) - 1)
    tbl = Table(rows, colWidths=[0.95*inch, 0.75*inch, 2.9*inch, 2.4*inch], repeatRows=1)
    st = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#bbbbbb")),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    for r in tbd_rows: st.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#fff3cd")))
    tbl.setStyle(TableStyle(st))
    upd = datetime.now(TZ).strftime("%b %d, %Y")
    foot = lambda c, d: (c.setFont("Helvetica", 8), c.setFillColor(colors.grey),
                         c.drawString(0.5*inch, 0.35*inch, f"Updated {upd}. Times are Central. Shaded = date/time TBD."),
                         c.drawRightString(8*inch, 0.35*inch, f"Page {d.page}"))
    doc = SimpleDocTemplate(path, pagesize=letter, leftMargin=0.5*inch, rightMargin=0.5*inch,
                            topMargin=0.5*inch, bottomMargin=0.6*inch, title=f"{TEAM} Game Schedule")
    doc.build([Paragraph(f"{TEAM} — Game Schedule", H),
               Paragraph(f"{len(gs)} games. Home games unmarked; AWAY = @ opponent.", sub), tbl],
              onFirstPage=foot, onLaterPages=foot)


if __name__ == "__main__":
    gs = games(parse(fetch(sys.argv[1] if len(sys.argv) > 1 else None)))
    write_ics(gs, "docs/schedule.ics")
    write_pdf(gs, "docs/schedule.pdf")
    print(f"{len(gs)} games written")

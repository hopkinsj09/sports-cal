#!/usr/bin/env python3
"""Pull games from the Crossbar iCal feed; write docs/schedule.ics and docs/schedule.pdf."""
import html, os, re, sys, urllib.request
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
TEAM = "10U A2 Garrett"
CAL_NAME = "Connor's Hockey Schedule"
GAME_RE = re.compile(r"\s(vs|@)\s", re.I)
NOT_GAME = re.compile(r"practice|pictures|serving night", re.I)


def fetch(path=None):
    if path:
        return open(path, encoding="utf-8").read()
    src = os.environ.get("CROSSBAR_FEED_URL", "").strip()
    if not src.startswith("https://"):
        sys.exit("Set CROSSBAR_FEED_URL to the https:// feed link (a GitHub secret in Actions), or pass a local .ics path.")
    req = urllib.request.Request(src, headers={"User-Agent": "sports-cal/1.0"})
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
                        loc=re.sub(r"\s+", " ", clean(e.get("LOCATION", ""))), raw_loc=clean(e.get("LOCATION", "")), desc=desc, away=away))
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


def address(g):
    loc = g["loc"]
    if g["tbd"]:  # feed repeats the city, e.g. "Wisconsin Dells  Wisconsin Dells WI"
        loc = re.sub(r"^(.+?)\s{2,}\1\b", r"\1", g["raw_loc"]).strip()
        return loc
    v = venue(g)
    return loc[len(v):].strip() if loc.startswith(v) else loc


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
    c.setTitle(CAL_NAME)
    def styles(k):
        return (ParagraphStyle("g", fontName="Helvetica-Bold", fontSize=7*k, leading=8*k),
                ParagraphStyle("v", fontName="Helvetica-Oblique", fontSize=6*k, leading=7*k, textColor=colors.HexColor("#555555")),
                ParagraphStyle("a", fontName="Helvetica", fontSize=5.5*k, leading=6.5*k, textColor=colors.HexColor("#444444")))
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
    def cell_items(y, m, day, k):
        gm, gv, ga = styles(k)
        items = []
        for g in by.get(date(y, m, day), []) if day else []:
            t = ("TBD " if g["tbd"] else f"{g['start']:%I:%M%p}".lstrip("0").lower() + " ") + short(g)
            ps = [Paragraph(html.escape(t), gm), Paragraph(html.escape(venue(g)), gv), Paragraph(html.escape(address(g)), ga)]
            hs = [p.wrap(cw - 8, 1000)[1] for p in ps]
            items.append((g, ps, hs, sum(hs) + 3))
        return items

    for y, m in months:
        weeks = calendar.monthcalendar(y, m)
        avail = T - 0.25*inch - B
        base = avail / len(weeks)
        for k in (1.0, 0.92, 0.85, 0.78, 0.7, 0.62, 0.55):  # shrink text until every row fits
            cells = [[cell_items(y, m, d, k) for d in wk] for wk in weeks]
            need = [max(15 + sum(it[3] + 2 for it in cell) + 3 for cell in row) for row in cells]
            rows = [max(n, 0.5*base) for n in need]
            if sum(rows) <= avail: break
        extra = (avail - sum(rows)) / len(rows)
        rows = [h + max(extra, 0) for h in rows]
        c.setFont("Helvetica-Bold", 22); c.setFillColor(colors.black)
        c.drawString(L, H - 0.6*inch, f"{calendar.month_name[m]} {y}")
        c.setFont("Helvetica", 9); c.setFillColor(colors.grey)
        c.drawRightString(R, H - 0.6*inch, f"{CAL_NAME}  |  AWAY = @  |  shaded = time TBD")
        for i, n in enumerate(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]):
            c.setFillColor(colors.HexColor("#333333")); c.rect(L + i*cw, T - 0.25*inch, cw, 0.25*inch, fill=1, stroke=0)
            c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 9)
            c.drawCentredString(L + i*cw + cw/2, T - 0.18*inch, n)
        top = T - 0.25*inch
        for r, wk in enumerate(weeks):
            ch = rows[r]
            for i, day in enumerate(wk):
                x = L + i*cw
                c.setStrokeColor(colors.HexColor("#999999")); c.setLineWidth(0.5)
                c.setFillColor(colors.HexColor("#f2f2f2") if day == 0 else colors.white)
                c.rect(x, top - ch, cw, ch, fill=1, stroke=1)
                if not day: continue
                c.setFillColor(colors.black); c.setFont("Helvetica-Bold", 9)
                c.drawString(x + 3, top - 11, str(day))
                cy = top - 15
                for g, (p1, p2, p3), (h1, h2, h3), hh in cells[r][i]:
                    c.setFillColor(colors.HexColor("#fff3cd") if g["tbd"] else
                                   colors.HexColor("#fde2e2") if g["away"] else colors.HexColor("#dff0d8"))
                    c.rect(x + 2, cy - hh, cw - 4, hh, fill=1, stroke=0)
                    p1.drawOn(c, x + 4, cy - h1 - 1); p2.drawOn(c, x + 4, cy - h1 - h2 - 1)
                    p3.drawOn(c, x + 4, cy - h1 - h2 - h3 - 1)
                    cy -= hh + 2
            top -= ch
        c.setFont("Helvetica", 8); c.setFillColor(colors.grey)
        c.drawString(L, 0.3*inch, f"Updated {upd}. Times are Central. Green = home, red = away.")
        c.showPage()
    c.save()


if __name__ == "__main__":
    gs = games(parse(fetch(sys.argv[1] if len(sys.argv) > 1 else None)))
    write_ics(gs, "docs/schedule.ics")
    write_pdf(gs, "docs/schedule.pdf")
    print(f"{len(gs)} games written")

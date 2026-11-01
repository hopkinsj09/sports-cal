# 10U A2 Garrett games
- Subscribe (iCal): `https://hopkinsj09.github.io/sports-cal/schedule.ics`
- Printable PDF: `https://hopkinsj09.github.io/sports-cal/schedule.pdf`

`build.py` pulls the Crossbar feed, keeps games only (drops practices, pictures, etc.), and writes `docs/`.
A GitHub Action re-runs it every 6 hours. Run locally: `pip install reportlab && python build.py`.
Enable hosting: repo Settings > Pages > Deploy from branch > `main` / `/docs`.

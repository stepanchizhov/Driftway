"""Round 2: night setting, a road around the moon, stars, an arrow home.
Every variant is built on one centre and exact circle geometry, so the
shapes stay tidy at 48 px. Writes icon-options-2.html and option-*.svg."""
import base64
import math
import pathlib

HERE = pathlib.Path(__file__).parent
REPO = pathlib.Path(r"C:\Users\stepa\OneDrive\Документы\_Development\NapLoop\.git\Driftway")

NAVY, NAVY2, PEACH, CREAM = "#161C36", "#232B55", "#F2B179", "#FFF1DC"
C = 256.0


def pt(theta_deg, r):
    """A point on a circle round the centre; theta clockwise from 12 o'clock."""
    t = math.radians(theta_deg)
    return C + r * math.sin(t), C - r * math.cos(t)


def f(x):
    return f"{x:.1f}"


def road_arc(start, end, r):
    """SVG path for the road, clockwise from start to end (degrees)."""
    x1, y1 = pt(start, r)
    x2, y2 = pt(end, r)
    sweep = (end - start) % 360
    large = 1 if sweep > 180 else 0
    return f"M{f(x1)} {f(y1)} A{r} {r} 0 {large} 1 {f(x2)} {f(y2)}"


def arrowhead(at, r, half, length, colour):
    """A head that sits on the road at `at` and points clockwise along it."""
    bx, by = pt(at, r)
    nx, ny = math.sin(math.radians(at)), -math.cos(math.radians(at))  # outward
    tip = pt(at + math.degrees(length / r), r)
    p1 = (bx + half * nx, by + half * ny)
    p2 = (bx - half * nx, by - half * ny)
    return (f'<polygon points="{f(p1[0])},{f(p1[1])} {f(tip[0])},{f(tip[1])} '
            f'{f(p2[0])},{f(p2[1])}" fill="{colour}"/>')


def sparkle(x, y, s, colour):
    """A four-point star with curved sides."""
    return (f'<path d="M{f(x)} {f(y - s)} Q{f(x)} {f(y)} {f(x + s)} {f(y)} '
            f'Q{f(x)} {f(y)} {f(x)} {f(y + s)} Q{f(x)} {f(y)} {f(x - s)} {f(y)} '
            f'Q{f(x)} {f(y)} {f(x)} {f(y - s)} Z" fill="{colour}"/>')


def moon(cx, cy, r, cut_dx, cut_dy, cut_r, colour, bg):
    return (f'<circle cx="{f(cx)}" cy="{f(cy)}" r="{f(r)}" fill="{colour}"/>'
            f'<circle cx="{f(cx + cut_dx)}" cy="{f(cy + cut_dy)}" r="{f(cut_r)}" fill="{bg}"/>')


def road(start, end, r, width, colour, lane=None, lane_w=6, dash="18 16"):
    d = road_arc(start, end, r)
    out = (f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="{width}" '
           f'stroke-linecap="butt"/>')
    if lane:
        out += (f'<path d="{d}" fill="none" stroke="{lane}" stroke-width="{lane_w}" '
                f'stroke-dasharray="{dash}"/>')
    return out


def bg(fill):
    return f'<rect width="512" height="512" fill="{fill}"/>'


GRADIENT = ('<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{NAVY2}"/><stop offset="1" stop-color="{NAVY}"/>'
            '</linearGradient></defs><rect width="512" height="512" fill="url(#sky)"/>')

R, W = 150, 56          # road radius and width: outer edge 178, inside the 204 safe circle
# Road from 70 degrees clockwise to 20; the head then runs on to about 40,
# pointing back into the gap where the road began: out, round, and home.
START, END = 70, 20

ICONS = {}

ICONS["E1"] = ("Ring road", "Peach road with a lane line, arrow home, moon and two stars inside.",
    bg(NAVY)
    + road(START, END, R, W, PEACH, lane=NAVY)
    + arrowhead(END, R, 46, 54, PEACH)
    + moon(242, 266, 76, 34, -30, 64, CREAM, NAVY)
    + sparkle(318, 196, 20, CREAM) + sparkle(296, 160, 9, CREAM))

ICONS["E2"] = ("Moonlit road", "The road in moonlight cream, the moon in peach.",
    bg(NAVY)
    + road(START, END, R, W, CREAM, lane=NAVY)
    + arrowhead(END, R, 46, 54, CREAM)
    + moon(242, 266, 76, 34, -30, 64, PEACH, NAVY)
    + sparkle(318, 196, 20, PEACH) + sparkle(296, 160, 9, PEACH))

hx, hy = pt(START, R)
ICONS["E3"] = ("Home and back", "A night-sky gradient; the road starts at home (the dot) and the arrow brings you back to it.",
    GRADIENT
    + road(START + 9, END, R, W, PEACH, lane=NAVY)
    + arrowhead(END, R, 46, 54, PEACH)
    + f'<circle cx="{f(hx)}" cy="{f(hy)}" r="30" fill="{CREAM}"/>'
    + moon(242, 266, 76, 34, -30, 64, CREAM, "#1C2347")
    + sparkle(318, 196, 20, CREAM) + sparkle(296, 160, 9, CREAM))

sx, sy = pt(60, R)
ICONS["E4"] = ("Stars in the gap", "A bigger moon; the stars shine through the gap the arrow points to.",
    bg(NAVY)
    + road(START + 22, END, R, W, PEACH, lane=NAVY)
    + arrowhead(END, R, 46, 54, PEACH)
    + moon(248, 262, 92, 40, -34, 78, CREAM, NAVY)
    + sparkle(sx + 2, sy - 2, 24, CREAM) + sparkle(sx - 30, sy + 36, 9, CREAM))

ax, ay = pt(45, R)
ICONS["E5"] = ("Closed loop, painted arrow", "An unbroken ring road with the arrow painted on it, like a road marking.",
    bg(NAVY)
    + f'<circle cx="256" cy="256" r="{R}" fill="none" stroke="{PEACH}" stroke-width="{W}"/>'
    + f'<circle cx="256" cy="256" r="{R}" fill="none" stroke="{NAVY}" stroke-width="6" stroke-dasharray="18 16"/>'
    + arrowhead(25, R, 22, 40, NAVY)
    + moon(242, 266, 76, 34, -30, 64, CREAM, NAVY)
    + sparkle(318, 196, 20, CREAM) + sparkle(296, 160, 9, CREAM))

ICONS["E6"] = ("Night on peach", "D's colours, the night inside: a disc of night sky ringed by a navy road.",
    bg(PEACH)
    + f'<circle cx="256" cy="256" r="{R - W / 2 - 14}" fill="{NAVY}"/>'
    + road(START, END, R, W, NAVY)
    + arrowhead(END, R, 46, 54, NAVY)
    + moon(244, 264, 62, 28, -25, 52, CREAM, NAVY)
    + sparkle(300, 206, 15, CREAM) + sparkle(284, 178, 7, CREAM))

current = base64.b64encode((REPO / "frontend/public/icon-maskable-512.png").read_bytes()).decode()


def svg(key, size, radius):
    return (f'<svg class="ic" viewBox="0 0 512 512" width="{size}" height="{size}" '
            f'style="border-radius:{radius}" role="img" aria-label="Option {key}">{ICONS[key][2]}</svg>')


def cur(size, radius):
    return (f'<img class="ic" src="data:image/png;base64,{current}" width="{size}" height="{size}" '
            f'style="border-radius:{radius}" alt="Current icon">')


def tile(markup):
    return f'<div class="tile">{markup}<span>Driftway</span></div>'


def card(title, desc, make):
    walls = "".join(
        f'<div class="wall {w}">{tile(make(56, "28%"))}{tile(make(48, "28%"))}{tile(make(48, "50%"))}</div>'
        for w in ("green", "dark", "light"))
    return f"""
<article class="card">
  <h2>{title}</h2>
  <p class="desc">{desc}</p>
  <div class="big">{make(176, '28%')}{make(176, '50%')}</div>
  {walls}
  <div class="tiny">{make(24, '28%')}{make(16, '28%')}<span>24 and 16 px</span></div>
</article>"""


cards = [card(f"{k} · {v[0]}", v[1], lambda s, r, k=k: svg(k, s, r)) for k, v in ICONS.items()]
cards.append(card("Current", "For comparison.", cur))

page = f"""<title>Driftway Icon Options</title>
<style>
  /* Layout: one card per option - the icon cropped as launchers crop it,
     at home-screen sizes on three backgrounds, then at notification size. */
  :root {{ --bg:#f4f4f7; --card:#ffffff; --ink:#191f38; --dim:#55608a; --line:#dcdfea; color-scheme: light; }}
  @media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#10131f; --card:#1a1f33; --ink:#edeffa; --dim:#9aa3cc; --line:#2c3355; color-scheme: dark; }} }}
  :root[data-theme="dark"] {{ --bg:#10131f; --card:#1a1f33; --ink:#edeffa; --dim:#9aa3cc; --line:#2c3355; color-scheme: dark; }}
  body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; padding-inline:16px; padding-block:20px 48px; }}
  main {{ max-width:1180px; margin:0 auto; }}
  h1 {{ font-size:26px; margin:0 0 6px; text-wrap:balance; }}
  .intro {{ color:var(--dim); max-width:72ch; margin:0 0 20px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:16px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:14px; min-width:0; }}
  .card h2 {{ font-size:17px; margin:0 0 2px; }}
  .desc {{ margin:0 0 10px; font-size:13px; color:var(--dim); min-height:2.6em; }}
  .big {{ display:flex; gap:12px; margin-bottom:10px; }}
  .big .ic {{ width:calc(50% - 6px); height:auto; }}
  .ic {{ display:block; }}
  .wall {{ display:flex; gap:20px; align-items:flex-end; padding:12px 14px; border-radius:10px; margin-bottom:8px; }}
  .wall.green {{ background:radial-gradient(circle at 30% 30%, #2f6b2a, #0f3a10 70%); }}
  .wall.dark {{ background:#0e0e10; }}
  .wall.light {{ background:#eef0f4; }}
  .tile {{ display:flex; flex-direction:column; align-items:center; gap:4px; font-size:12px; }}
  .green .tile, .dark .tile {{ color:#fff; }}
  .light .tile {{ color:#1a1a1a; }}
  .tiny {{ display:flex; gap:10px; align-items:center; font-size:12px; color:var(--dim); margin-top:6px; }}
</style>
<main>
  <h1>Driftway icon options, round 2</h1>
  <p class="intro">C's night and D's arrow, merged: a road that goes once round
  the moon and turns back home, with stars. Every shape is drawn from one
  centre with exact circles, so they stay tidy when small. Each card shows the
  Samsung squircle and the circle crop, then home-screen sizes on three
  backgrounds, then notification size. Mixing is still fine, for example
  "E3 with E4's bigger moon".</p>
  <div class="grid">{''.join(cards)}</div>
</main>
"""
(HERE / "icon-options-2.html").write_text(page, encoding="utf-8")
for key, (_, _, body) in ICONS.items():
    (HERE / f"option-{key}.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">{body}</svg>\n', encoding="utf-8")
print("written", len(page))

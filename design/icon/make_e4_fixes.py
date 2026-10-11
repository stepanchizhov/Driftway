"""E4, arrow fixed: three treatments of the arrowhead beside the original,
each with a close-up of where the head meets the road."""
import math
import pathlib

HERE = pathlib.Path(__file__).parent
REPO = pathlib.Path(r"C:\Users\stepa\OneDrive\Документы\_Development\NapLoop\.git\Driftway")
NAVY, PEACH, CREAM = "#161C36", "#F2B179", "#FFF1DC"
C, R, W = 256.0, 150, 56
START, END = 92, 20          # E4's road: from 92 degrees clockwise round to 20


def pt(theta, r):
    t = math.radians(theta)
    return C + r * math.sin(t), C - r * math.cos(t)


def f(x):
    return f"{x:.1f}"


def arc(start, end, r):
    x1, y1 = pt(start, r)
    x2, y2 = pt(end, r)
    large = 1 if (end - start) % 360 > 180 else 0
    return f"M{f(x1)} {f(y1)} A{r} {r} 0 {large} 1 {f(x2)} {f(y2)}"


def sparkle(x, y, s, colour=CREAM):
    return (f'<path d="M{f(x)} {f(y - s)} Q{f(x)} {f(y)} {f(x + s)} {f(y)} '
            f'Q{f(x)} {f(y)} {f(x)} {f(y + s)} Q{f(x)} {f(y)} {f(x - s)} {f(y)} '
            f'Q{f(x)} {f(y)} {f(x)} {f(y - s)} Z" fill="{colour}"/>')


#: The head starts this far back over the road's end, so the two shapes
#: overlap and never meet edge to edge - a shared edge leaves a hairline seam
#: and a small kink, which is what showed at the joint in the original.
OVERLAP_DEG = 1.5


def head(at, r_in, r_out, length, colour=PEACH, round_px=0):
    """A head whose base runs from radius r_in to r_out just behind angle
    `at`, its tip on the road's centre line `length` beyond `at`."""
    length += math.radians(OVERLAP_DEG) * R
    at -= OVERLAP_DEG
    a = pt(at, r_out)
    b = pt(at, r_in)
    tip = pt(at + math.degrees(length / R), R)
    pts = f"{f(a[0])},{f(a[1])} {f(tip[0])},{f(tip[1])} {f(b[0])},{f(b[1])}"
    extra = (f' stroke="{colour}" stroke-width="{round_px}" stroke-linejoin="round"'
             if round_px else "")
    return f'<polygon points="{pts}" fill="{colour}"{extra}/>'


def icon(head_svg, lane_end, moon_c=(248, 262), moon_r=92, cut=(40, -34), cut_r=78):
    sx, sy = pt(60, R)
    return (f'<rect width="512" height="512" fill="{NAVY}"/>'
            f'<path d="{arc(START, END, R)}" fill="none" stroke="{PEACH}" stroke-width="{W}"/>'
            f'<path d="{arc(START, lane_end, R)}" fill="none" stroke="{NAVY}" stroke-width="6" stroke-dasharray="18 16"/>'
            + head_svg
            + f'<circle cx="{moon_c[0]}" cy="{moon_c[1]}" r="{moon_r}" fill="{CREAM}"/>'
            + f'<circle cx="{moon_c[0] + cut[0]}" cy="{moon_c[1] + cut[1]}" r="{cut_r}" fill="{NAVY}"/>'
            + sparkle(sx + 2, sy - 2, 24) + sparkle(sx - 30, sy + 36, 9))


ORIGINAL = (REPO / "design/icon/E4-original.svg").read_text(encoding="utf-8")
ORIGINAL_BODY = ORIGINAL[ORIGINAL.index(">") + 1:ORIGINAL.rindex("</svg>")]

INNER, OUTER = R - W / 2, R + W / 2          # 122 and 178: the road's edges
ICONS = {
    "E4": ("Original", "As chosen, for reference. The head's inner corner juts "
           "18 px into the road's inside and nearly meets the moon's tip.", ORIGINAL_BODY),
    "E4a": ("Clean head", "A slimmer head, overhanging the road by 12 px each "
            "side; the lane line stops short of it; the moon moves 4 px down and left.",
            icon(head(END, INNER - 12, OUTER + 12, 58), lane_end=END - 14,
                 moon_c=(244, 266), moon_r=88, cut=(38, -33), cut_r=75)),
    "E4b": ("Outward head", "The head's inner side runs flush with the road's "
            "inner edge, so nothing points at the moon; all the overhang is outside.",
            icon(head(END, INNER, OUTER + 26, 60), lane_end=END - 14)),
    "E4c": ("Rounded head", "E4a with softened corners, to match the round "
            "sparkles and the moon.",
            icon(head(END, INNER - 8, OUTER + 8, 52, round_px=12), lane_end=END - 14,
                 moon_c=(244, 266), moon_r=88, cut=(38, -33), cut_r=75)),
}


def svg(body, size, radius, view="0 0 512 512"):
    return (f'<svg class="ic" viewBox="{view}" width="{size}" height="{size}" '
            f'style="border-radius:{radius}" role="img">{body}</svg>')


def card(key, title, desc, body):
    walls = "".join(
        f'<div class="wall {w}">' + "".join(
            f'<div class="tile">{svg(body, s, r)}<span>Driftway</span></div>'
            for s, r in ((56, "28%"), (48, "28%"), (48, "50%"))) + "</div>"
        for w in ("green", "dark", "light"))
    return f"""
<article class="card">
  <h2>{key} · {title}</h2>
  <p class="desc">{desc}</p>
  <div class="big">{svg(body, 176, '28%')}{svg(body, 176, '12px', view='230 40 200 200')}</div>
  <p class="cap">The icon, and a close-up of the arrow</p>
  {walls}
  <div class="tiny">{svg(body, 24, '28%')}{svg(body, 16, '28%')}<span>24 and 16 px</span></div>
</article>"""


page = f"""<title>Driftway Icon Options</title>
<style>
  /* Layout: one card per arrow treatment - the icon and a close-up of the
     joint, then launcher sizes on three backgrounds, then notification size. */
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
  .desc {{ margin:0 0 10px; font-size:13px; color:var(--dim); min-height:3.9em; }}
  .big {{ display:flex; gap:12px; }}
  .big .ic {{ width:calc(50% - 6px); height:auto; }}
  .cap {{ margin:6px 0 10px; font-size:12px; color:var(--dim); }}
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
  <h1>Driftway icon: E4, arrow fixed</h1>
  <p class="intro">E4 was chosen by Katya, Sonya and Stepan. The original is
  first, kept for reference, and also saved in the repository as
  design/icon/E4-original.svg. Then three ways to fix where the arrowhead
  meets the road, each with a close-up of that joint.</p>
  <div class="grid">{''.join(card(k, *v) for k, v in ICONS.items())}</div>
</main>
"""
(HERE / "icon-options.html").write_text(page, encoding="utf-8")
for key, (_, _, body) in ICONS.items():
    if key != "E4":
        (HERE / f"option-{key}.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">{body}</svg>\n',
            encoding="utf-8")
print("written")

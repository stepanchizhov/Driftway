"""Driftway's app icon: E4c, chosen 11 Oct 2026, drawn exactly, and every
size the app needs rendered from it.

E4c is E4 ("Stars in the gap") with the arrowhead fixed. The head is slimmer,
overhangs the road by 8 px each side, has rounded corners, and starts just
over the road's end, so there is no seam. The road's dashed marking ends on
a whole dash, followed by clean road up to the head (founder feedback: no
half-dash, and no marking closer to the head).

Run:  python design/icon/make_icon.py
Writes design/icon/driftway-icon.svg (full-bleed) and
driftway-icon-rounded.svg, then renders PNGs with headless Chrome and
scales them with Pillow into frontend/public and design/icon.
"""
import math
import pathlib
import subprocess
import tempfile

from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
PUBLIC = REPO / "frontend" / "public"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

NAVY, PEACH, CREAM = "#161C36", "#F2B179", "#FFF1DC"
C, R, W = 256.0, 150, 56            # centre; road radius and width (edges 122 and 178)
START, END = 92, 20                 # the road runs clockwise from 92 degrees round to 20
OVERLAP_DEG = 1.5                   # the head starts this far back over the road's end
LANE_STOP_DEG = 8                   # the marking stops this far before the road's end
DASH, GAP = 18, 16                  # the marking's rhythm, adjusted to end on a whole dash


def pt(theta, r):
    """A point on a circle round the centre; theta clockwise from 12 o'clock."""
    t = math.radians(theta)
    return C + r * math.sin(t), C - r * math.cos(t)


def f(x):
    return f"{x:.2f}".rstrip("0").rstrip(".")


def arc(start, end, r):
    x1, y1 = pt(start, r)
    x2, y2 = pt(end, r)
    large = 1 if (end - start) % 360 > 180 else 0
    return f"M{f(x1)} {f(y1)} A{r} {r} 0 {large} 1 {f(x2)} {f(y2)}"


def lane():
    """The dashed marking: whole dashes only, the last one ending
    LANE_STOP_DEG before the road's end."""
    end = END - LANE_STOP_DEG
    length = math.radians((end - START) % 360) * R
    n = round((length + GAP) / (DASH + GAP))
    scale = length / (n * (DASH + GAP) - GAP)
    d, g = DASH * scale, GAP * scale
    return (f'<path d="{arc(START, end, R)}" fill="none" stroke="{NAVY}" '
            f'stroke-width="6" stroke-dasharray="{f(d)} {f(g)}"/>')


def head():
    at = END - OVERLAP_DEG
    length = 52 + math.radians(OVERLAP_DEG) * R
    a, b = pt(at, R + W / 2 + 8), pt(at, R - W / 2 - 8)
    tip = pt(at + math.degrees(length / R), R)
    return (f'<polygon points="{f(a[0])},{f(a[1])} {f(tip[0])},{f(tip[1])} '
            f'{f(b[0])},{f(b[1])}" fill="{PEACH}" stroke="{PEACH}" stroke-width="12" '
            f'stroke-linejoin="round"/>')


def sparkle(x, y, s):
    return (f'<path d="M{f(x)} {f(y - s)} Q{f(x)} {f(y)} {f(x + s)} {f(y)} '
            f'Q{f(x)} {f(y)} {f(x)} {f(y + s)} Q{f(x)} {f(y)} {f(x - s)} {f(y)} '
            f'Q{f(x)} {f(y)} {f(x)} {f(y - s)} Z" fill="{CREAM}"/>')


def artwork():
    sx, sy = pt(60, R)
    return (f'<path d="{arc(START, END, R)}" fill="none" stroke="{PEACH}" stroke-width="{W}"/>'
            + lane() + head()
            + f'<circle cx="244" cy="266" r="88" fill="{CREAM}"/>'
            + f'<circle cx="282" cy="233" r="75" fill="{NAVY}"/>'
            + sparkle(sx + 2, sy - 2, 24) + sparkle(sx - 30, sy + 36, 9))


def svg(rounded: bool) -> str:
    # Full-bleed for maskable, iOS and Play (they crop it themselves); a
    # rounded square with transparent corners for "any" icons and favicons.
    ground = (f'<rect width="512" height="512" rx="112" fill="{NAVY}"/>' if rounded
              else f'<rect width="512" height="512" fill="{NAVY}"/>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">{ground}{artwork()}</svg>\n'


def render(svg_text: str, out: pathlib.Path, size: int = 1024) -> None:
    """Render at 1024 px with headless Chrome, transparent where the SVG is."""
    with tempfile.TemporaryDirectory() as tmp:
        page = pathlib.Path(tmp) / "icon.html"
        page.write_text(
            '<html><body style="margin:0;background:transparent">'
            f'<div style="width:{size}px;height:{size}px">'
            + svg_text.replace("<svg ", f'<svg width="{size}" height="{size}" ', 1)
            + "</div></body></html>", encoding="utf-8")
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--default-background-color=00000000",
                        f"--window-size={size},{size}", f"--screenshot={out}",
                        page.as_uri()], check=True, capture_output=True)


def main():
    full, rounded = svg(False), svg(True)
    (HERE / "driftway-icon.svg").write_text(full, encoding="utf-8")
    (HERE / "driftway-icon-rounded.svg").write_text(rounded, encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        big_full, big_round = pathlib.Path(tmp) / "full.png", pathlib.Path(tmp) / "round.png"
        render(full, big_full)
        render(rounded, big_round)
        full_img = Image.open(big_full).convert("RGB")
        round_img = Image.open(big_round).convert("RGBA")

        def save(img, name, size, folder=PUBLIC):
            img.resize((size, size), Image.LANCZOS).save(folder / name, optimize=True)

        save(full_img, "icon-maskable-512.png", 512)
        save(full_img, "icon-maskable-192.png", 192)
        save(full_img, "apple-touch-icon.png", 180)
        save(round_img, "icon-512.png", 512)
        save(round_img, "icon-192.png", 192)
        save(round_img, "favicon-32.png", 32)
        round_img.resize((256, 256), Image.LANCZOS).save(
            PUBLIC / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
        # Google Play's listing icon: 512 x 512, full-bleed; Play rounds it.
        save(full_img, "play-store-icon-512.png", 512, folder=HERE)
    print("icons written")


if __name__ == "__main__":
    main()

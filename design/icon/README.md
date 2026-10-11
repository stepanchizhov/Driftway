# Driftway app icon

Chosen 11 Oct 2026 by Katya, Sonya and Stepan: **E4, "Stars in the gap"**.
It is a night sky, a road looping round the moon with an arrow back home, and
stars in the gap the arrow points to. It replaces the thin peach ring, which
was hard to read and to tell apart at home-screen size.

**In use: E4c** (`driftway-icon.svg`), founder-approved the same day. It is
E4 with the arrowhead fixed: a slimmer head with rounded corners, started
just over the road's end so there is no seam. The road's dashed marking ends
on a whole dash, followed by clean road up to the head.

- `make_icon.py`: draws E4c and renders every size. Run it after any change:
  `python design/icon/make_icon.py`. It writes:
  - `frontend/public`: `icon-512/192` (rounded corners, "any"),
    `icon-maskable-512/192` and `apple-touch-icon` (full-bleed), and
    `favicon.ico` and `favicon-32.png`;
  - `play-store-icon-512.png` here, for the Play listing.
- `driftway-icon.svg` / `driftway-icon-rounded.svg`: the master drawings.
- `E4-original.svg`: E4 exactly as chosen, kept for reference.
- `make_options.py`: generated round 2's six candidates (E1–E6), including E4.
- `make_e4_fixes.py`: the arrowhead fixes (E4a, E4b, E4c) shown to the founder.

All shapes are drawn from one centre with exact circles. The road is radius
150, 56 wide. Everything sits inside the central 80% circle that launchers
keep when they crop.

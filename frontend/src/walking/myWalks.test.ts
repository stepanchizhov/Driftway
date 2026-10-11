import { describe, expect, it } from "vitest";
import { MAX_POINTS, isLoop, lengthOf, metres, parseGpx, samplePoints } from "./myWalks";

// Synthetic points, nobody's address.
const line = (n: number, step = 0.0005) =>
  Array.from({ length: n }, (_, i) => ({ lat: 52 + i * step, lng: 13 }));

describe("sampling a route", () => {
  it("keeps a short route as it is", () => {
    expect(samplePoints(line(10))).toHaveLength(10);
  });

  it("thins a long track to the most the server takes, keeping both ends", () => {
    const track = line(2000, 0.00005);
    const kept = samplePoints(track);
    expect(kept.length).toBeLessThanOrEqual(MAX_POINTS);
    expect(kept[0]).toEqual(track[0]);
    expect(kept[kept.length - 1]).toEqual(track[track.length - 1]);
    // Evenly along the way: no gap much longer than an even share.
    const share = lengthOf(track) / (MAX_POINTS - 1);
    for (let i = 1; i < kept.length; i++) {
      expect(metres(kept[i - 1], kept[i])).toBeLessThan(share * 1.5);
    }
  });

  it("drops repeated and impossible points", () => {
    const p = { lat: 52, lng: 13 };
    const kept = samplePoints([p, { ...p }, { lat: Number.NaN, lng: 13 }, { lat: 52.001, lng: 13 }]);
    expect(kept).toHaveLength(2);
  });

  it("tells a loop from a route that ends elsewhere", () => {
    const out = line(5);
    expect(isLoop(out)).toBe(false);
    expect(isLoop([...out, { lat: 52.0001, lng: 13 }])).toBe(true);
  });
});

describe("reading a GPX file", () => {
  const gpx = `<?xml version="1.0"?>
<gpx version="1.1" creator="test">
  <metadata><name>Not this one</name></metadata>
  <trk><name><![CDATA[The Long Walk & back]]></name>
    <trkseg>
      <trkpt lat="52.0000" lon="13.0000"><ele>30</ele></trkpt>
      <trkpt lon='13.0010' lat='52.0010'></trkpt>
      <trkpt lat="999" lon="13.0"></trkpt>
      <trkpt lat="52.0020" lon="13.0020"/>
    </trkseg>
  </trk>
</gpx>`;

  it("reads track points in order, either attribute order, skipping nonsense", () => {
    const { points } = parseGpx(gpx);
    expect(points).toEqual([
      { lat: 52, lng: 13 },
      { lat: 52.001, lng: 13.001 },
      { lat: 52.002, lng: 13.002 },
    ]);
  });

  it("takes a name, never markup", () => {
    expect(parseGpx(gpx).name).toBe("The Long Walk & back");
    expect(parseGpx(`<metadata><name>Only this</name></metadata><trkpt lat="1" lon="2"/>`).name).toBe("Only this");
    expect(parseGpx(`<trk><name>A <b>bold</b> walk</name><trkpt lat="1" lon="2"/></trk>`).name).toBe(
      "A bold walk",
    );
  });

  it("falls back to route points, and finds nothing in something else", () => {
    expect(parseGpx(`<rte><rtept lat="52" lon="13"/><rtept lat="52.1" lon="13"/></rte>`).points).toHaveLength(2);
    expect(parseGpx("hello").points).toEqual([]);
  });
});

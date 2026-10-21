// The orbiting dot (founder, 18 Oct 2026, after the tour video: "I really
// liked the dot flying around in circles ... keep that idea for the future
// materials and maybe for some sort of in-app avatar, loading screens"). It
// grew from the duration ring's amber tick. Like a drive, it goes round and
// comes back: it may slip out of sight for a moment, never for long ("it
// brings comfort when it comes back").

export function Orbit({ size = 120 }: { size?: number }) {
  return (
    <div className="orbit" style={{ width: size, height: size }} aria-hidden="true">
      <div className="orbit-ring" />
      <div className="orbit-arm">
        <span className="orbit-dot" />
      </div>
    </div>
  );
}

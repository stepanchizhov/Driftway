// Calm, non-blocking travel-safety note. Wording follows the project bible:
// travel-only framing, regular breaks, manufacturer's instructions, extra care
// for very young or premature babies. Never shames, never hard-blocks.
export function SafetyNote() {
  return (
    <details className="safety">
      <summary className="safety-summary">Travel safety</summary>
      <p className="safety-body">
        Car seats are designed for safe travel rather than routine sleep. On
        longer journeys, take regular breaks, follow your child-seat
        manufacturer's instructions, and take extra care with very young or
        premature babies. This information doesn't replace advice from a
        healthcare professional.
      </p>
    </details>
  );
}

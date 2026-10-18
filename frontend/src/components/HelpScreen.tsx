import type { ReactNode } from "react";

// How Driftway works, in a parent's words (founder, 18 Oct 2026: the
// welcome page for testers points here for more). Opened from Settings, or
// by a link to /#help. Sections for features this deployment doesn't offer
// are left out.

interface Props {
  meetHalfway: boolean;
  walking: boolean;
}

function Section({ title, children, open = false }: { title: string; children: ReactNode; open?: boolean }) {
  return (
    <details className="help-section" open={open}>
      <summary>{title}</summary>
      <div className="help-body">{children}</div>
    </details>
  );
}

export function HelpScreen({ meetHalfway, walking }: Props) {
  return (
    <main className="settings help">
      <h2 className="settings-title">Help</h2>
      <p className="help-intro">
        Driftway finds drives and walks for little ones who sleep best on the
        move, and gets you back, or there, when you need to be.
      </p>

      <Section title="Still asleep" open>
        <p>
          Arrived, but the nap isn&rsquo;t over? Open <strong>Still asleep</strong>,
          pick where you&rsquo;re going (Home, a saved place or a recent search)
          and how much longer the drive should last. Driftway finds a longer
          way there and opens it in Google Maps straight away.
        </p>
      </Section>

      <Section title="Plan a drive">
        <p>
          <strong>Round trip</strong> brings you back where you started;{" "}
          <strong>Go somewhere</strong> takes the long way to a destination.
        </p>
        <p>
          Then choose <strong>how long</strong> the drive should be, or tap{" "}
          <strong>Arrive by</strong> (<strong>Back by</strong> on a round trip)
          and give a time. Every drive then gets there by that time, a few
          minutes early, and says when to leave.
        </p>
        <p>You get up to three drives to choose from.</p>
        <p>
          <strong>Going by ferry?</strong> Ferries sail at set times, so plan
          the drive to the ferry terminal, with <strong>Arrive by</strong> your
          check-in time, and plan again from the port when you land. Drives
          Driftway lengthens never take a ferry.
        </p>
      </Section>

      <Section title="Reading a drive">
        <p>
          Each drive shows its minutes, distance and the kind of roads. It
          counts the speed bumps and traffic lights mapped along the way, lists
          roadworks on it today, and says if it turns round or repeats a road.
        </p>
        <p>
          Map data can miss things, so what couldn&rsquo;t be checked is said
          rather than left out.
        </p>
      </Section>

      <Section title="Starting a drive">
        <p>
          <strong>Start in Google Maps</strong> opens the drive with its
          turning points, so Google follows Driftway&rsquo;s way. When you plan
          from your location, Google starts from wherever your phone is by
          then. When you picked a start, the drive starts there.
        </p>
        <p>
          Set the drive up before you set off, and don&rsquo;t use your phone
          while driving.
        </p>
      </Section>

      <Section title="What wakes your little one">
        <p>
          In Settings, say how much speed bumps, stopping at lights, turning
          round and roadworks bother your child. Drives avoid what wakes them
          more and care less about what doesn&rsquo;t. Every child is
          different.
        </p>
      </Section>

      {walking && (
        <Section title="Walks">
          <p>
            Choose <strong>Pram</strong>, <strong>Carrier</strong> or{" "}
            <strong>Just me</strong>, and about how long. Walks start where you
            are and are judged against your pram&rsquo;s wheels or your
            carrier: steps, gates, slopes and surfaces are shown with where the
            information comes from, and what isn&rsquo;t known is said.
          </p>
          <p>
            Add up to three checkpoints for a walk to pass, and keep the walks
            you like in <strong>My walks</strong>.
          </p>
        </Section>
      )}

      {meetHalfway && (
        <Section title="Meet up">
          <p>
            Find a fair place to meet another parent. Each of you adds where
            you&rsquo;re setting off from, and the other never sees it. Share
            the link, then choose a place you&rsquo;d both consider.
          </p>
        </Section>
      )}

      <Section title="Saved places and drives">
        <p>
          <strong>★ Saved</strong> keeps Home and your other places on this
          phone, for one tap in Still asleep and in searches, and the drives
          you&rsquo;ve starred.
        </p>
        <p>
          Away from home? Save where you&rsquo;re staying as a place, and Still
          asleep offers it with one tap.
        </p>
      </Section>

      <Section title="Telling us what happened">
        <p>
          Tap <strong>Feedback</strong> at the top of any screen. It tells us
          which screen you were on and which version you have, so you only need
          to say what happened. Please leave out your address: &ldquo;the drive
          from the swimming pool&rdquo; is plenty.
        </p>
        <p>
          Testing Driftway? <a href="/beta.html">Notes for testers</a>.
        </p>
      </Section>

      <Section title="Safety">
        <p>
          Car seats are designed for safe travel rather than routine sleep. On
          longer journeys, take regular breaks, follow your child-seat
          manufacturer&rsquo;s instructions, and take extra care with very
          young or premature babies. For slings and carriers, follow the TICKS
          guidance in the Walk tab. Driftway doesn&rsquo;t replace advice from a
          healthcare professional.
        </p>
      </Section>

      <Section title="Your privacy">
        <p>
          Drives, walks and searches are used to answer you and then
          discarded, unless you save them. Your saved places stay on this phone. The{" "}
          <a href="/privacy.html">privacy policy</a> has the details.
        </p>
      </Section>
    </main>
  );
}

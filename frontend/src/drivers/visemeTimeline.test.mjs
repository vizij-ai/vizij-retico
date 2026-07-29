// Checks the viseme timeline maths against the vizij-web reference behaviour.
//
// Pure arithmetic, mirrored from VizijReticoDriver.ts — the driver itself needs a rig
// and an AudioContext, so the parts worth asserting are extracted here. If the driver's
// constants or formulas change, these numbers should be re-derived from it.
//
//   node src/drivers/visemeTimeline.test.mjs

const LIPSYNC = {
  minSpanMs: 45,
  maxSpanMs: 320,
  releaseMs: 120,
  durationDivisor: 250,
  visemePeak: 0.75,
};

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

function buildTimeline(marks) {
  const entries = marks.map((m) => ({
    start: m.time,
    transitionStart: 0,
    path: m.value === "sil" ? null : `/poses/pose_${m.value}.weight`,
  }));
  if (!entries.length) return entries;
  for (let i = 0; i < entries.length; i++) {
    const prevStart = i === 0 ? 0 : entries[i - 1].start;
    const gap = i === 0 ? entries[i].start : entries[i].start - prevStart;
    entries[i].transitionStart = entries[i].start - clamp(gap, LIPSYNC.minSpanMs, LIPSYNC.maxSpanMs);
  }
  const lastStart = entries[entries.length - 1].start + LIPSYNC.releaseMs;
  entries.push({ start: lastStart, transitionStart: lastStart - LIPSYNC.minSpanMs, path: null });
  return entries;
}

const durationSec = (entry, nowMs) =>
  clamp(
    entry.start - nowMs > 0 ? entry.start - nowMs : LIPSYNC.minSpanMs,
    LIPSYNC.minSpanMs,
    LIPSYNC.maxSpanMs,
  ) / LIPSYNC.durationDivisor;

let failures = 0;
const check = (name, cond, detail = "") => {
  if (cond) console.log(`PASS  ${name}`);
  else {
    failures++;
    console.log(`FAIL  ${name}${detail ? ` — ${detail}` : ""}`);
  }
};

// "Papa mama oh you" — the phoneme-dense line used for manual checks.
const marks = [
  { time: 0, value: "sil" },
  { time: 120, value: "p" },
  { time: 200, value: "a" },
  { time: 250, value: "p" },
  { time: 310, value: "at" },
  { time: 450, value: "p" },
  { time: 1000, value: "o" },
];
const tl = buildTimeline(marks);

check("a rest entry is appended", tl.length === marks.length + 1);
check(
  "rest lands releaseMs after the last phoneme",
  tl[tl.length - 1].start === 1000 + LIPSYNC.releaseMs,
);
check("rest has no pose (mouth closes)", tl[tl.length - 1].path === null);

// The core fix: poses start moving *before* their timestamp so they peak on the beat.
const late = tl.filter((e) => e.transitionStart >= e.start);
check("every pose leads its phoneme", late.length === 0, `${late.length} start late`);

// The lead-in tracks the gap, floored at minSpanMs and capped at maxSpanMs.
const tight = tl[3]; // 250 ms, 50 ms after the previous -> lead is the gap itself
check(
  "the lead-in matches the gap when it is within range",
  tight.start - tight.transitionStart === 50,
  `${tight.start - tight.transitionStart}ms for a 50ms gap`,
);
// A gap under the floor: 20 ms apart should still get a 45 ms lead-in, or very fast
// consonant clusters would barely move the mouth at all.
const cramped = buildTimeline([{ time: 100, value: "p" }, { time: 120, value: "t" }])[1];
check(
  "a sub-floor gap is raised to minSpanMs",
  cramped.start - cramped.transitionStart === LIPSYNC.minSpanMs,
  `${cramped.start - cramped.transitionStart}ms for a 20ms gap`,
);
const held = tl[6]; // 1000 ms, 550 ms after the previous -> clamped to maxSpanMs
check(
  "a long gap is clamped to maxSpanMs",
  held.start - held.transitionStart === LIPSYNC.maxSpanMs,
  `${held.start - held.transitionStart}ms`,
);

// The 4x stretch: the tween must outlast the time until the next phoneme, or weights
// saturate and the mouth snaps between shapes.
const entry = { start: 200 };
const firedAt = entry.start - 80; // lead-in began 80 ms early
const d = durationSec(entry, firedAt);
check(
  "tween is ~4x the remaining time (the low-pass that stops popping)",
  Math.abs(d - 80 / 250) < 1e-9 && d > 80 / 1000,
  `${(d * 1000).toFixed(0)}ms tween for 80ms of runway`,
);

// Consecutive phonemes 60 ms apart: each tween must still be running when the next
// fires, otherwise weights reach full and we are back to hard switches.
const gapMs = 60;
check(
  "tweens overlap at conversational phoneme rates",
  durationSec({ start: gapMs }, 0) * 1000 > gapMs,
  `${(durationSec({ start: gapMs }, 0) * 1000).toFixed(0)}ms tween vs ${gapMs}ms gap`,
);

check("peak weight matches vizij-showcase", LIPSYNC.visemePeak === 0.75);
check("empty marks produce no timeline", buildTimeline([]).length === 0);

console.log(failures ? `\n${failures} failing` : "\nall passed");
process.exit(failures ? 1 : 0);

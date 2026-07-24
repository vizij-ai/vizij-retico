# vizij-retico — design documentation

`vizij-retico` connects the **retico** incremental spoken-dialogue framework (Python) to a
**vizij-web** real-time expressive face (React/TS over a Rust/WASM "Arora" runtime). A small
Python bridge streams retico's incremental dialogue signals — turn-taking, backchannels,
nods, lip-sync, emotion, gaze — to the browser, where they drive the animated face in real
time.

The system is the basis for a 4-page IEEE systems/demonstration paper for the
[Human–Robot Dialogue (HRD) workshop at IROS 2026](https://human-robot-dialogue.github.io/).

> **Status: planning/design.** These documents expand on the approved plan
> (`~/.claude/plans/i-want-to-use-tingly-cherny.md`). No system code has been written yet.

## The one-paragraph idea

retico is uniquely good at *incremental* processing — it emits partial, revisable hypotheses
(ADD/REVOKE/COMMIT) and, via `retico-maai`, first-class **turn-taking, backchannel, and nod**
predictions that most dialogue toolkits lack. vizij-web is uniquely good at rendering a
**real-time expressive face** (gaze, emotion, visemes) through a clean value-driven runtime.
Neither ships the glue between them, and retico has no viseme or websocket module. The novel
contribution is therefore the **bridge**: a fan-in retico module that serializes heterogeneous
incremental units (IUs) into one WebSocket protocol, plus a browser input-driver and an
editable mapping that renders those IUs as coherent, well-timed social behavior on the face.

## Document map

| # | Document | What it covers |
|---|---|---|
| 01 | [Motivation & workshop fit](01-motivation-and-workshop.md) | Why this system, why this venue, how it maps to the CFP topics |
| 02 | [Architecture](02-architecture.md) | End-to-end data flow, the Arora device model, component responsibilities |
| 03 | [WebSocket protocol](03-websocket-protocol.md) | The envelope, every event type, full JSON schemas, IU update semantics |
| 04 | [IU → animation mapping](04-iu-animation-mapping.md) | The editable `reticoMapping.ts` config, verb/duration policy, gaze arbitration |
| 05 | [retico backend](05-retico-backend.md) | Python network, module choices, the `VizijWebSocketModule` design |
| 06 | [vizij frontend](06-vizij-frontend.md) | `registerInputDriver`, the driver, viseme options A/B, reused hooks |
| 07 | [Capabilities](07-capabilities.md) | Deep dive per capability: research grounding, retico source, Vizij rendering |
| 08 | [Demo vignettes](08-demo-vignettes.md) | The three scripted vignettes and what each foregrounds |
| 09 | [Evaluation](09-evaluation.md) | Metrics, baselines, and how to measure them for the paper |
| 10 | [Build plan](10-build-plan.md) | Risk-ordered milestones, prerequisites, open items |
| 11 | [Paper outline](11-paper-outline.md) | 4-page IEEE structure mapped to workshop topics (author support) |

Figures live in [`figures/`](figures/) as editable Semio-branded `d2` sources.

## Key external references

- retico-core: <https://github.com/retico-team/retico-core> · docs <https://retico-core.readthedocs.io>
- retico-maai (turn-taking/backchannel/nod): <https://github.com/retico-team/retico-maai>
- vizij-web (frontend monorepo): <https://github.com/vizij-ai/vizij-web>
- vizij-rs (Rust cores + `@vizij/runtime`): <https://github.com/vizij-ai/vizij-rs>
- Reference app `tutorial-agent-face` and WS-sync pattern `vizij-standalone` in vizij-web.

## Glossary

- **IU (Incremental Unit)** — retico's atomic packet of information (a word, an audio chunk, a
  prediction), carrying update semantics and provenance links.
- **ADD / REVOKE / COMMIT** — an IU is added as a hypothesis, possibly revoked if a later
  hypothesis supersedes it, and committed when final.
- **VAP (Voice Activity Projection)** — the MaAI model that predicts upcoming turn transitions
  from audio, enabling anticipatory turn-taking.
- **Arora device** — the external runtime Vizij now runs on; a single device owning a shared
  blackboard **store** (key→value) that a behavior graph reads each tick and writes rig outputs.
- **Pose weight** — a `[0,1]` blendshape/expression channel on the face
  (`rig/{faceId}/poses/{key}.weight`).
- **Viseme** — a visual mouth shape corresponding to a phoneme, used for lip-sync.

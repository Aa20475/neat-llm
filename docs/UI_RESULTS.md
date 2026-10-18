# Interactive UI verification

## Markdown responses, 2026-10-17

Chat responses now render headings, emphasis, nested lists, fenced/inline code,
quotes, tables, and links using locally bundled markdown-it 15.0.3. User prompts
and error text remain literal. Raw HTML is escaped, unsafe link schemes are
rejected, and images display their descriptions without making requests. See
[dependency provenance and license](THIRD_PARTY.md).

All 175 Python tests and five JavaScript Markdown checks pass. A Chrome fixture
check verified formatting, links, inert HTML/script payloads, table alignment
under the existing CSP, desktop/mobile layout, and horizontal scrolling confined
to wide code blocks. It recorded no JavaScript/CSP errors, external requests, or
inference calls. Evidence: `artifacts/markdown-check.json`,
`artifacts/markdown-desktop.png`, and `artifacts/markdown-mobile.png`.

## Integration into main, 2026-10-17

Merged `jerry-ui-improvments` through `8b7c97b`, retaining its neutral Neat
styling, sidebar conversations, viewport layout, fixed composer, and mobile
navigation. Chat is now the landing view. Conflict resolution preserves main's
stop button, live worker/tool events, elapsed timers, error outcomes, and links
to saved files and traces. The model name remains visible in the composer;
the full active configuration label is available in its tooltip. The branch's
actionable authentication errors and concurrent SQLite polling fix are included.

All 175 Python tests pass. Desktop (1440×1000) and mobile (390×844) Chrome checks
used temporary fixture databases and intercepted inference actions. They verified
new chat, send and follow-up, reflection opt-in, stop with an editable follow-up,
conversation deletion, reflection attempts, file/trace navigation, all four tabs,
fixed composer placement, scroll preservation, reduced motion, and escaped
output. The existing live-activity check also passed automatic event updates,
worker labels, elapsed timers, error states, and completion rendering. No browser
JavaScript errors or inference calls occurred in these checks.

Local evidence: `artifacts/chat-merge-check.json`,
`artifacts/chat-activity-check.json`, and `artifacts/chat-merge-*.png`.
The real database was not reset; the user's in-progress reflection comparison
was left running while the static UI assets were updated.

## Local branch verification, 2026-10-17 evening

On `jerry-ui-improvments`, real requests were submitted through the existing
Chrome tab at `http://127.0.0.1:8765`, with the viewer stopped and restarted after
configuration and storage changes. The neutral three-dot answering indicator
was visible during inference and disappeared on completion. It respects reduced
motion. The composer remained visible.

An extra trailing period in the ignored local credential caused the earlier
HTTP 401 failures. Correcting it and restarting the server restored real Crusoe
inference. Model discovery returned HTTP 200, and a browser request returned
`87.50` for 12.50 times 7 using `decimal_product`.

The SQLite failure was reproduced as `SQLITE_IOERR_LOCK` on macOS with concurrent
`mode=ro` polling connections and read/write chat connections. Viewer reads now
open the existing file with `mode=rw` and immediately enable `PRAGMA query_only=ON`.
They still refuse missing databases and reject SQL mutations. The reproduction
completed 100 writer cycles with polling and no errors after this change. The
focused runtime, chat, viewer, actions, and background suites pass 39 tests,
including concurrent readers/writers and the read-only SQL guard.

At the user's request, the server was stopped, local SQLite data cleared, and a
fresh v0 initialized before the final recording. The real browser session exposed
a model error: the delegated worker used the wrong mug total, and the first
follow-up repeated it. A second follow-up explicitly requesting decimal tools
returned the correct four lines: mugs 59.99, notebooks 8.50, delivery 5.00,
total 73.49. Run `1a25b8acdcd94aaf9e49c310c8d4c25a` records two
`decimal_product` calls, one `decimal_sum`, four model calls, and 8.71 seconds.
The earlier incorrect outputs remain visible in the conversation and saved traces.

Reflection `2c5738afeced428484d208774fbfb5be` completed with `no_change` after
reviewing three shared learning traces. It used one model call and 3,295 tokens.
No proposal was promoted; v0 remains active at generation 0. This demonstrates
working chat, temporary delegation, trace inspection, and manual reflection,
**not reliable first-answer correctness or learned improvement**.

The demo uses macOS ScreenCaptureKit to record the actual existing Chrome window,
starting on empty Chat, with real CUA interactions. Music is added afterward.
The final MP4 is 119.93 seconds, 1920 by 1104 at 30 fps with AAC music.
The entire file decodes without errors; extracted opening, answer, trace, reflection,
and closing frames were inspected, and the MP4 opened and played in QuickTime.
The Chrome tab and address bar are included. Credentials, the local database, raw
captures, and edited video are ignored by Git.

## Earlier implementation verification

Verified on 2026-10-17 at `http://127.0.0.1:8765` with Chrome at desktop and 390px mobile widths. The automated suite passes 50 tests. Tests cover active-version selection per chat turn, conversation isolation, ungraded responses, shared controller locking, action recovery, local-origin enforcement, and reuse of one live asynchronous event loop across jobs.

Chat executed real Crusoe calls through the company runtime. The first message returned `391.00` for 17 × 23 using `decimal_product`. Although asked to delegate, the generalist chose to invoke the tool itself; its trace accurately records no child worker. A follow-up asking to add 9 returned `400.00`, and another message recalled that result. All messages used active v0, carried conversational context, persisted across page reloads, and remained outside benchmark scores and reflection evidence.

The Run reflection button starts the same bounded pipeline as the CLI. Its initial live check exposed reuse of an API connection bound to a closed event loop. That failed action and reflection attempt remain in history. The server now uses one persistent async loop for background chat and reflection jobs; this also keeps the HTTP interface responsive.

After the fix, a real chat message followed by a UI reflection action succeeded in the same server process. Reflection attempt `19ab0457b059447e8dac7d722298e0dc` retrieved five prior lessons, used one call with 5,038 input and 503 output tokens, recognized an equivalent prior candidate, and skipped paid evaluation. No configuration was promoted. V0 remained active at generation 2.

Browser checks verified reply-to-trace links, arithmetic tool events, held-out score-to-trace links, filter explanations, button progress/disabled state, completion status, and mobile layouts. The successful check reported no browser JavaScript errors. Local evidence is in `artifacts/ui-check-report.json` and the `viewer-chat-*` / `viewer-reflection-button*` screenshots.

Reading tabs does not start inference. Sending a chat message or pressing Run reflection does. Reflection remains manually triggered; chat does not become learning evidence automatically.

The attempt display was subsequently moved directly below the trigger after its original position below proposals and memory proved difficult to find. The sidebar now counts all attempts, independently of proposal count. Browser verification confirmed all five saved attempts, latest-first ordering, clear duplicate/failure outcomes, expandable records, and links to equivalent proposals on desktop and mobile. This display check made no inference calls.

## Stop and inspect a task

The page header now shows **Stop task** while this viewer owns a running chat turn. Browser checks on desktop and 390px mobile verified cancellation, return to Chat, preservation of files and the reflection-sharing selection, and re-enabled Send after cleanup. The button fills an editable status question without sending it. A fixture follow-up received the stopped task's tool error and saved module; it answered without restarting implementation. The run timeline labels a caught error with **Error in output · exit 0**, distinguishing process termination from task correctness. No browser JavaScript errors or horizontal mobile overflow were observed.

These checks used a temporary database, a scripted agent, and actual sandbox execution, with no paid inference. Evidence is in `artifacts/stop-task-ui-check.json`, `stop-task-desktop.png`, `stop-task-mobile.png`, and `process-error-desktop.png`. The automated suite also covers cancellation cleanup before releasing the controller lock, early/repeated/stale stop requests, and same-origin enforcement.

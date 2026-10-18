# Interactive UI verification

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

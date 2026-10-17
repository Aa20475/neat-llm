# Interactive UI verification

Verified on 2026-10-17 at `http://127.0.0.1:8765` with Chrome at desktop and 390px mobile widths. The automated suite passes 50 tests. Tests cover active-version selection per chat turn, conversation isolation, ungraded responses, shared controller locking, action recovery, local-origin enforcement, and reuse of one live asynchronous event loop across jobs.

Chat executed real Crusoe calls through the company runtime. The first message returned `391.00` for 17 × 23 using `decimal_product`. Although asked to delegate, the generalist chose to invoke the tool itself; its trace accurately records no child worker. A follow-up asking to add 9 returned `400.00`, and another message recalled that result. All messages used active v0, carried conversational context, persisted across page reloads, and remained outside benchmark scores and reflection evidence.

The Run reflection button starts the same bounded pipeline as the CLI. Its initial live check exposed reuse of an API connection bound to a closed event loop. That failed action and reflection attempt remain in history. The server now uses one persistent async loop for background chat and reflection jobs; this also keeps the HTTP interface responsive.

After the fix, a real chat message followed by a UI reflection action succeeded in the same server process. Reflection attempt `19ab0457b059447e8dac7d722298e0dc` retrieved five prior lessons, used one call with 5,038 input and 503 output tokens, recognized an equivalent prior candidate, and skipped paid evaluation. No configuration was promoted. V0 remained active at generation 2.

Browser checks verified reply-to-trace links, arithmetic tool events, held-out score-to-trace links, filter explanations, button progress/disabled state, completion status, and mobile layouts. The successful check reported no browser JavaScript errors. Local evidence is in `artifacts/ui-check-report.json` and the `viewer-chat-*` / `viewer-reflection-button*` screenshots.

Reading tabs does not start inference. Sending a chat message or pressing Run reflection does. Reflection remains manually triggered; chat does not become learning evidence automatically.

The attempt display was subsequently moved directly below the trigger after its original position below proposals and memory proved difficult to find. The sidebar now counts all attempts, independently of proposal count. Browser verification confirmed all five saved attempts, latest-first ordering, clear duplicate/failure outcomes, expandable records, and links to equivalent proposals on desktop and mobile. This display check made no inference calls.

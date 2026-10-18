# Interactive UI verification

## Local branch verification, 2026-10-17 evening

On `jerry-ui-improvments`, real requests were submitted through Chrome at
`http://127.0.0.1:8765`, before and after stopping and restarting the viewer.
The new neutral three-dot answering indicator was visible in consecutive
screenshots, with different dot positions/opacities. It respects reduced motion
and is removed when a response or failure arrives. The composer stayed visible.

The current local credential was rejected by Crusoe with HTTP 401. Run
`9ff58d96dd824994a85cc4129f11fa94` captured the original authentication error;
after the change, run `f6e0a5721e30465cb3bbb00ec7194e79` displayed the actionable
error directly in Chat and re-enabled Send. Both used the real provider and
retained their failure traces. No response was simulated. This verifies the
loading and failure paths, **not successful inference on this machine**.
Replace the ignored `.env` credential with a valid Crusoe Intelligence API key
and restart the viewer before verifying a successful reply.

The earlier interrupted run had a SQLite disk I/O error. That error did not
recur in these browser requests; its underlying cause is not established.
No speculative storage changes were made. The focused runtime, chat, viewer,
actions, and background suites passed 37 tests; JavaScript syntax and whitespace
checks also passed. Credentials and local run data are excluded from Git.

## Earlier implementation verification

Verified on 2026-10-17 at `http://127.0.0.1:8765` with Chrome at desktop and 390px mobile widths. The automated suite passes 50 tests. Tests cover active-version selection per chat turn, conversation isolation, ungraded responses, shared controller locking, action recovery, local-origin enforcement, and reuse of one live asynchronous event loop across jobs.

Chat executed real Crusoe calls through the company runtime. The first message returned `391.00` for 17 × 23 using `decimal_product`. Although asked to delegate, the generalist chose to invoke the tool itself; its trace accurately records no child worker. A follow-up asking to add 9 returned `400.00`, and another message recalled that result. All messages used active v0, carried conversational context, persisted across page reloads, and remained outside benchmark scores and reflection evidence.

The Run reflection button starts the same bounded pipeline as the CLI. Its initial live check exposed reuse of an API connection bound to a closed event loop. That failed action and reflection attempt remain in history. The server now uses one persistent async loop for background chat and reflection jobs; this also keeps the HTTP interface responsive.

After the fix, a real chat message followed by a UI reflection action succeeded in the same server process. Reflection attempt `19ab0457b059447e8dac7d722298e0dc` retrieved five prior lessons, used one call with 5,038 input and 503 output tokens, recognized an equivalent prior candidate, and skipped paid evaluation. No configuration was promoted. V0 remained active at generation 2.

Browser checks verified reply-to-trace links, arithmetic tool events, held-out score-to-trace links, filter explanations, button progress/disabled state, completion status, and mobile layouts. The successful check reported no browser JavaScript errors. Local evidence is in `artifacts/ui-check-report.json` and the `viewer-chat-*` / `viewer-reflection-button*` screenshots.

Reading tabs does not start inference. Sending a chat message or pressing Run reflection does. Reflection remains manually triggered; chat does not become learning evidence automatically.

The attempt display was subsequently moved directly below the trigger after its original position below proposals and memory proved difficult to find. The sidebar now counts all attempts, independently of proposal count. Browser verification confirmed all five saved attempts, latest-first ordering, clear duplicate/failure outcomes, expandable records, and links to equivalent proposals on desktop and mobile. This display check made no inference calls.

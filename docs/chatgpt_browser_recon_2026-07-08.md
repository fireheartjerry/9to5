# ChatGPT Browser Reconnaissance For 9to5

Date: 2026-07-08

Scope: reconnaissance only. This pass did not implement Agent Duel, production browser automation, orchestration wiring, a provider abstraction, or final schemas.

## Executive Summary

- Persistent ChatGPT profile: worked.
- Dedicated profile path: `C:\9to5\state\chatgpt_profile_recon`
- Reopen command: see "How Jerry should use this next time."
- Gitignore status: verified ignored by `.gitignore`.
- Login state after restart: logged in after closing and reopening the dedicated Chrome profile.
- ChatGPT UI state after restart: global ChatGPT home opened when the launch URL was `https://chatgpt.com/`; the 9to5 project route still opened successfully afterward.
- 9to5 project: exists and has a stable project URL.
- Project URL: `https://chatgpt.com/g/g-p-6a3b5bc2c1708191b67f1546ae6468d8-9to5/project`
- Project test chat URL: `https://chatgpt.com/g/g-p-6a3b5bc2c1708191b67f1546ae6468d8-9to5/c/6a4de472-10b4-83ea-944f-db16b49ef122`
- Current visible ChatGPT model state: GPT-5.5 selected.
- Current visible reasoning state: Medium selected.
- Harmless normal-chat test result: assistant replied exactly `browser profile test complete`.
- Harmless project-chat test result: assistant replied exactly `project browser recon complete`.
- Most stable path for the next spike: launch dedicated Chrome profile, navigate directly to the 9to5 project URL, ensure GPT-5.5 and Medium are selected in the composer intelligence picker, send one harmless prompt, wait until `Stop answering` disappears and `Copy response` appears, then read the latest `[data-message-author-role="assistant"]`.
- Biggest risk: ChatGPT UI and menus are volatile, especially model/reasoning controls and post-response rerun controls.
- Most brittle area: selecting sidebar project rows by visual position. Prefer the direct project URL or accessible project-specific controls.
- Best early automation target: a standalone spike, not production integration.

## Hard Boundaries Confirmed

- Did not automate username, password, or 2FA.
- Did not request credentials in chat or terminal.
- Did not inspect credential field contents.
- Did not dump cookies, tokens, localStorage, sessionStorage, profile files, auth headers, or browser databases.
- Did not commit screenshots.
- Did not commit browser profile files.
- Did not wire anything into 9to5 orchestration.
- Did not replace the existing Gemini/adversarial review path.
- Did not lock final Agent Duel schemas.
- Did not create, rename, archive, delete, or pin projects.
- Did not click destructive chat/project controls.

## Environment And Tooling

- OS: Windows, repo at `C:\9to5`.
- Browser used for successful recon: installed Google Chrome.
- Chrome executable: `C:\Program Files\Google\Chrome\Application\chrome.exe`
- Debug endpoint: `http://127.0.0.1:9222/`
- Working control method: Chrome launched with `--remote-debugging-port=9222`, then inspected through Playwright over CDP.
- The in-app browser was showing `http://127.0.0.1:9222/`, which is the Chrome DevTools Protocol metadata endpoint, not the ChatGPT UI itself.
- First attempted path: Playwright persistent Chromium profile at `C:\9to5\state\chatgpt_profile`. Google login rejected that browser with "This browser or app may not be secure."
- Successful path: normal Chrome with dedicated local profile at `C:\9to5\state\chatgpt_profile_recon`.
- The user manually selected "Use Chrome without an account" for the Chrome profile prompt and then logged into ChatGPT normally.
- Important distinction: do not sign the Chrome browser profile into the user's normal Chrome sync account. Sign into ChatGPT inside the dedicated Chrome profile only.

## Exact Browser Launch Command

Use this PowerShell command to reopen the same dedicated ChatGPT profile:

```powershell
Start-Process 'C:\Program Files\Google\Chrome\Application\chrome.exe' -ArgumentList '--user-data-dir=C:\9to5\state\chatgpt_profile_recon','--remote-debugging-port=9222','--no-first-run','--no-default-browser-check','--new-window','https://chatgpt.com/'
```

To open directly to the 9to5 project:

```powershell
Start-Process 'C:\Program Files\Google\Chrome\Application\chrome.exe' -ArgumentList '--user-data-dir=C:\9to5\state\chatgpt_profile_recon','--remote-debugging-port=9222','--no-first-run','--no-default-browser-check','--new-window','https://chatgpt.com/g/g-p-6a3b5bc2c1708191b67f1546ae6468d8-9to5/project'
```

## Profile And Persistence Verification

- Dedicated profile path used: `C:\9to5\state\chatgpt_profile_recon`
- Profile type: local Chrome user data directory.
- Persistence across Chrome restarts: verified.
- Persistence across automation reconnects: verified.
- Login after restart: verified logged in. There was no visible `Log in` button, and the ChatGPT composer was available.
- Reopen landing behavior: when reopened with `https://chatgpt.com/`, ChatGPT landed on global home, not the project home.
- Project after restart: navigating to the project URL opened `ChatGPT - 9to5` with `h1` text `9to5`.
- Composer after restart: available immediately.
- Project composer after restart: `div[role="textbox"][contenteditable="true"][aria-label="New chat in 9to5"]`
- Model/reasoning after restart: `Medium` remained visible in the composer control after restart; GPT-5.5 remained selected in the model submenu.
- Active project tab state: direct route reopened project Chats tab by default, not Sources.
- Latest project test chat persisted and was listed on the project home page.

Controlled persistence proof:

- Closed only Chrome processes whose command line included `--user-data-dir=C:\9to5\state\chatgpt_profile_recon`.
- Reopened same profile with the same debug port.
- Debug endpoint returned `Chrome/149.0.7827.201`.
- ChatGPT reopened logged in.
- Direct project route reopened the 9to5 project successfully.

## Gitignore And Secret Safety

The profile is ignored by repo `.gitignore`.

Verified with:

```powershell
git check-ignore -v -- 'state/chatgpt_profile_recon/'
```

Observed result:

```text
.gitignore:52:state/chatgpt_profile_recon/ state/chatgpt_profile_recon/
```

Current `.gitignore` lines added for this pass:

```gitignore
# Dedicated ChatGPT reconnaissance profile (runtime data; never commit browser sessions)
state/chatgpt_profile_recon/
```

If this entry is missing in another checkout, add exactly those lines before using the profile.

## Existing Repo Reuse

Relevant files found:

| File | Relevance |
|---|---|
| `requirements.txt` | Declares `playwright>=1.40` for generic browser surface and `google-genai>=1.0` for current Gemini second brain. Notes `playwright install chromium` as a post-install step only if generic browser surface is used. |
| `agents/execution/browser_executor.py` | Current generic Layer 1 browser executor. It launches headless Chromium via Playwright for structured actions. It does not currently support persistent ChatGPT profile login. It also keeps compatibility shims for the second-brain path. |
| `agents/execution/gemini_driver.py` | Current second-brain transport. It explicitly replaced the old ChatGPT/CDP browser path with the Google Gemini SDK. |
| `tests/execution/test_browser_executor.py` | Tests the browser executor contract and routing without live browser usage. |
| `tests/conftest.py` | Autouse fixture forces `BROWSER_LAYER_ENABLED=False` and `GEMINI_ENABLED=False` during tests so no real browser/API calls happen accidentally. |
| `platform_core/ops/wipe.py` | Has a wipe category for old `state/chatgpt_profile`; future cleanup should add or account for `state/chatgpt_profile_recon` only if intentionally desired. |
| `docs/ARCHITECTURE.md` and `CAPABILITIES.md` | Document Layer 1 Browser as a future/partial CDP/Playwright browser surface gated by `BROWSER_LAYER_ENABLED`. |
| `.gitignore` | Stores local runtime state ignore patterns and now ignores `state/chatgpt_profile_recon/`. |

Existing conventions:

- Runtime data lives under `state/`.
- Secrets are kept out of the repo through `.gitignore` and hard-boundary tooling.
- Tests must not launch real browser/API surfaces unless deliberately opted in.
- The current production second-brain path is Gemini, not ChatGPT browser automation.
- The future ChatGPT browser spike should not replace `gemini_driver.py`; it should be a standalone experimental browser-provider spike first.

Likely future locations:

- Standalone spike script: `tools/chatgpt_browser_spike.py` or `tools/recon/chatgpt_browser_spike.py`
- Future reusable provider module: `agents/execution/chatgpt_browser_driver.py`
- Future tests with mocked browser operations: `tests/execution/test_chatgpt_browser_driver.py`
- Future live/manual test: mark as slow/manual and keep disabled by default.

## Human Login Procedure

Use this only if ChatGPT asks Jerry to log in again.

1. Look at the dedicated Chrome window opened by the command above.
2. The page should be `https://chatgpt.com/` or a ChatGPT login page.
3. Log in to ChatGPT normally in the browser.
4. If asked for 2FA, complete it normally in the browser.
5. Do not paste credentials into Codex, terminal, or chat.
6. Do not sign the Chrome profile into Chrome sync unless you intentionally want that.
7. Once the ChatGPT home screen or composer is visible, tell Codex: `logged in`.
8. Then stop touching the browser until Codex gives the next explicit step.

If Chrome shows "Make Chrome your own":

1. Click `Use Chrome without an account`.
2. Do not click `Continue as Jerry` unless you intentionally want Chrome sync in this profile.
3. Continue logging into ChatGPT in the browser page itself.
4. Tell Codex: `logged in`.

If Google says "This browser or app may not be secure":

1. Stop trying to log into that browser.
2. Tell Codex: `Google rejected this browser`.
3. Use normal Chrome with the dedicated `state/chatgpt_profile_recon` profile instead of bundled Playwright Chromium.

## Manual Project Selection Procedure

Use this if the automation cannot use the direct project URL.

1. Open the ChatGPT sidebar if it is collapsed.
2. Look for the `Projects` section.
3. Click the project named `9to5`, if it exists.
4. If there is an `Open project home` button beside `9to5`, click that button to enter the project home.
5. If the project is missing, tell Codex: `9to5 project missing`.
6. Do not create, rename, archive, delete, or pin any project.
7. Stop touching the browser after the `9to5` project page is visible.

Most reliable non-human path:

```text
https://chatgpt.com/g/g-p-6a3b5bc2c1708191b67f1546ae6468d8-9to5/project
```

## Manual Model And Reasoning Selection Procedure

Use this if Codex asks you to confirm or manually set the model.

1. In the composer bar, click the button currently showing `Medium`, `High`, or another reasoning label.
2. A menu titled `Intelligence` should open.
3. Confirm `GPT-5.5` is shown at the bottom of the menu.
4. Hover or click `GPT-5.5` to open the model submenu.
5. Choose `GPT-5.5` if it is not already checked.
6. In the same `Intelligence` menu, choose `Medium` for reasoning.
7. If `GPT-5.5` or `Medium` is missing, tell Codex exactly which options you see.
8. After selection, the composer button should visibly show `Medium`.
9. Stop interacting and tell Codex: `model set`.

Observed visible reasoning levels:

- `Instant`
- `Medium`
- `High`

Observed visible model options:

- `GPT-5.5`
- `GPT-5.4`
- `GPT-5.3`
- `o3`

## Harmless Test Message Procedure

Use this only in a new harmless test chat.

1. Open the 9to5 project home.
2. Confirm the composer says `New chat in 9to5`.
3. Confirm the reasoning button says `Medium`.
4. Paste exactly:

```text
Reply with exactly: project browser recon complete
```

5. Send the message.
6. Wait until the assistant finishes.
7. Tell Codex: `test sent`.
8. Stop touching the browser.

Observed expected assistant response:

```text
project browser recon complete
```

## UI Observations A To P

### A. Open ChatGPT

Observed:

- Global URL: `https://chatgpt.com/`
- Project URL: `https://chatgpt.com/g/g-p-6a3b5bc2c1708191b67f1546ae6468d8-9to5/project`
- Logged-in page title on global home: `ChatGPT`
- Logged-in page title on project: `ChatGPT - 9to5`
- Logged-in global composer: `div[role="textbox"][contenteditable="true"][aria-label="Chat with ChatGPT"]`
- Project composer: `div[role="textbox"][contenteditable="true"][aria-label="New chat in 9to5"]`
- Hidden fallback textarea exists on global home in some states: `textarea[name="prompt-textarea"][aria-label="Chat with ChatGPT"]`, but its rectangle can be 0x0.
- Sidebar was open during recon.
- Projects section was visible.
- No account/workspace selector blocked the flow after login.
- No memory/update/announcement modal blocked the flow during this pass.
- Reopen to `https://chatgpt.com/` landed on global home, not project home.

Readiness candidates:

- Primary logged-in ready: visible `div[role="textbox"][contenteditable="true"]` with aria `Chat with ChatGPT` or `New chat in 9to5`.
- Secondary logged-in ready: visible `a[data-testid="create-new-chat-button"]`.
- Project ready: `h1` text `9to5` plus composer aria `New chat in 9to5`.
- Login required: visible `Log in` link/button or URL on an auth route.
- Blocking modal: any visible `[role="dialog"]` above composer.

### B. Start A New Chat

Observed:

- Sidebar has multiple `New chat` controls.
- Stable global new-chat link: `a[data-testid="create-new-chat-button"][href="/"]`
- A compact header new-chat link also appears as `a[aria-label="New chat"][href="/"]`.
- Normal pointer click on the first `New chat` link can be intercepted by overlapping sidebar icon layers.
- DOM click or direct navigation to `/` is more reliable for global new chat.
- Global new chat exits project context.
- Starting from project home composer creates a project-scoped chat.
- Project-scoped chat URL format:

```text
/g/g-p-6a3b5bc2c1708191b67f1546ae6468d8-9to5/c/<chat-id>
```

Postconditions:

- Global new chat: URL is `/` until first send, then `/c/<chat-id>`.
- Project new chat: use project home composer; after send URL includes `/g/g-p-...-9to5/c/<chat-id>`.
- Blank composer is ready when the visible contenteditable textbox is empty and send button is absent or disabled.

### C. Select Or Enter The 9to5 Project

Observed:

- `9to5` project exists.
- It appears in the sidebar under `Projects`.
- Project row has project options button: `button[aria-label="Open project options for 9to5"]`.
- Nearby project home button: `button[aria-label="Open project home"]`.
- Project home heading: `h1` text `9to5`.
- Project home composer: `aria-label="New chat in 9to5"`.
- Project home route is stable enough for the next spike.
- Project history links include route prefix `/g/g-p-6a3b5bc2c1708191b67f1546ae6468d8-9to5/c/...`.
- Existing old project chats are noisy and not useful for this recon beyond structure.

Recommended project verification:

- URL contains `/g/g-p-6a3b5bc2c1708191b67f1546ae6468d8-9to5/`.
- Title is `ChatGPT - 9to5`.
- Heading `9to5` is visible.
- Composer aria is `New chat in 9to5`.

Recovery if project missing:

- Surface `9to5 project missing` to the human.
- Do not create or rename projects automatically.
- Fall back to global ChatGPT only if the user approves.

### D. Select Model

Observed composer picker:

- Open by clicking the composer intelligence button currently showing `Medium`.
- Menu text begins with `Intelligence`.
- `GPT-5.5` appears as a submenu item.
- Hovering or clicking `GPT-5.5` opens a model submenu.
- Model submenu options observed: `GPT-5.5`, `GPT-5.4`, `GPT-5.3`, `o3`.
- `GPT-5.5` was checked with `role="menuitemradio"`, `aria-checked="true"`, and `data-state="checked"`.
- Other model options were unchecked.
- No disabled model options were observed in this session.
- No model limit modal was observed.

Primary locators:

- Open picker: visible `button` with exact text `Medium`, `High`, or `Instant`.
- Menu container: `[role="menu"][data-state="open"]` containing text `Intelligence`.
- Model submenu opener: `[role="menuitem"]` with text `GPT-5.5`.
- Model option: `[role="menuitemradio"]` with exact text `GPT-5.5`.

Post-response model switcher:

- The assistant response control `button[aria-label="Switch model"]` did not open the same full model picker.
- It opened a compact menu with `Try again • 5.5 Thinking` and `Search the web`.
- Treat post-response `Switch model` as rerun/search behavior, not as the primary model-selection control for a new prompt.

### E. Select Reasoning Level

Observed:

- Reasoning selector is integrated into the same `Intelligence` menu.
- Visible levels: `Instant`, `Medium`, `High`.
- `Medium` was selected with `role="menuitemradio"`, `aria-checked="true"`, `data-state="checked"`.
- After selection, composer button text showed `Medium`.
- Medium persisted after closing and reopening the dedicated Chrome profile.
- Reasoning selector appears on project home and in the project chat composer.
- Reasoning can be inspected after a message is sent because the composer remains available.

Primary locators:

- Open: visible composer button text `Medium`.
- Option: `[role="menuitemradio"]` exact text `Medium`.
- Verify: composer button exact text `Medium`.

Potential failure:

- Button text may be the selected reasoning level, not a stable label like "Model".
- If selected reasoning changes, opener text changes.
- Use a fallback that opens the last visible composer control near the send/dictation buttons and verifies the menu contains `Intelligence`.

### F. Composer, Tools, And Message Sending

Observed composer:

- Main input is a contenteditable ProseMirror-style editor.
- Global composer aria: `Chat with ChatGPT`.
- Project composer aria: `New chat in 9to5`.
- Hidden file inputs are present near the composer.
- `Add files and more` button: `button[aria-label="Add files and more"][data-testid="composer-plus-btn"]`.
- Reasoning/model button shows `Medium`.
- Dictation button: `button[aria-label="Start dictation"]`.
- Voice button can appear as `button[aria-label="Start Voice"]`.
- Send button appears only after text is entered.
- Send button observed after harmless draft: `button[aria-label="Send prompt"][data-testid="send-button"]`.
- Empty composer after clearing draft had no draft text.

Recommended send method:

- Focus contenteditable textbox by aria label.
- Insert text.
- Wait for `button[aria-label="Send prompt"][data-testid="send-button"]` to be visible/enabled.
- Click send or press Enter.
- Prefer click send in automation to avoid ambiguity with multiline input.

Not fully tested:

- Shift+Enter multiline behavior.
- Long prompt token warning.
- Draft persistence after reload.
- Markdown/code block paste fidelity.

Tools/source dialogs:

- Project Sources tab has `Add sources`.
- `Add sources` dialog options observed: `Upload`, `Text input`, `Google Drive`, `Slack`.
- These are not needed for first spike and should be deferred.

### G. Wait For Response Completion

Observed during project test:

- While generation was active, `Stop answering` was visible.
- During active generation, `Copy response` was not yet visible.
- After completion, `Stop answering` disappeared.
- After completion, `Copy response` became visible.
- Assistant message container became extractable.

Recommended completion detector:

- Response started: a new assistant message appears or `Stop answering` appears.
- Response done: `Stop answering` not visible and latest assistant message text is stable for a short interval.
- Strong done signal: latest assistant response controls include `Copy response`.
- Do not rely only on network idle. ChatGPT can keep background network activity alive.

Not naturally observed:

- Continue generating state.
- Rate-limit state.
- "Something went wrong" state.
- Model unavailable state.

### H. Extract Latest Assistant Response

Observed:

- User message containers use `[data-message-author-role="user"]`.
- Assistant message containers use `[data-message-author-role="assistant"]`.
- Latest assistant response extraction worked by selecting the last assistant container and reading rendered text.
- Normal chat extracted exactly `browser profile test complete`.
- Project chat extracted exactly `project browser recon complete`.
- Project chat message structure did not require a different response selector.

Primary locator:

```css
[data-message-author-role="assistant"]
```

Recommended extraction:

- Wait for at least one assistant container.
- Use the last visible assistant container.
- Extract rendered text, then trim known UI-control pollution if any appears.
- For code/tables/links, add later tests before depending on exact markdown fidelity.

Fallback:

- Use `Copy response` for latest assistant message if DOM text is polluted, but clipboard access must be tested and permission-safe.

### I. Copy Response

Observed:

- Assistant response has `Copy response` button after completion.
- Button aria: `Copy response`.
- Button test id: `copy-turn-action-button`.
- User messages also have copy buttons with the same test id but aria `Copy message`.
- Therefore `data-testid="copy-turn-action-button"` alone is not enough.

Primary locator:

- Scope to latest assistant message controls and choose `button[aria-label="Copy response"]`.

Fallback locators:

- Visible button aria `Copy response`.
- Latest assistant turn nearby `data-testid="copy-turn-action-button"` only after filtering by aria.

Clipboard note:

- Clipboard read/write was not made a dependency of this pass.
- Copy may preserve markdown better than DOM extraction, but it adds permission and global clipboard risks.
- Initial spike should extract DOM text first and leave copy as a fallback.

### J. Regenerate Or Rerun Response

Observed:

- Post-response `More actions` menu items: timestamp, `View sources`, `Branch in new chat`, `Read aloud`.
- Post-response `Switch model` menu items: `Try again • 5.5 Thinking`, `Search the web`.
- No standalone visible `Regenerate` label was observed on the completed test response.
- `Try again • 5.5 Thinking` likely acts as rerun/regenerate for the response, but it was not clicked to avoid consuming extra message quota and confusing the test chat.

Recommended first spike:

- Do not implement rerun.
- Only detect whether rerun options are visible.
- Defer clicking `Try again` until a dedicated safe manual test.

### K. Edit Or Resubmit User Message

Observed on harmless project test chat:

- User message has `button[aria-label="Edit message"]`.
- Clicking edit changes the user turn into a visible textarea.
- Edit textarea aria: `Edit message`.
- Textarea value contained the original prompt.
- Buttons shown: `Cancel`, `Send`.
- Clicking `Cancel` exited edit mode without changing the chat.
- After cancel, no `textarea[aria-label="Edit message"]` remained.

Primary locators:

- Edit button: `button[aria-label="Edit message"]`.
- Edit field: `textarea[aria-label="Edit message"]`.
- Cancel: visible `button` text `Cancel`.
- Resubmit: visible `button` text `Send`.

Risk:

- Clicking `Send` after editing likely reruns the assistant and may create branching/version state.
- Defer edit/resubmit from initial automation.

### L. Continue Generation

Observed:

- Continue generation did not naturally appear.

Recommended detection:

- Search for visible button text or aria containing `Continue generating`.
- If present, require explicit policy: continue automatically only in the first spike if the user has requested full completion and the prompt is harmless.
- Extraction should treat continuation as either appended same assistant turn or additional assistant segment, then combine all latest assistant text.

Do not force this state with a huge prompt in the initial implementation.

### M. Stop Generation

Observed:

- During active response, `Stop answering` was visible.
- It was not clicked.

Recommended locator:

- Visible button text or aria `Stop answering`.

Recovery policy:

- Stop is safe only as a recovery action when generation hangs or the user asks to abort.
- Stopped partial responses may still be extractable, but should be marked partial.
- Do not stop normal generations in the initial success path.

### N. Navigate Existing Chats

Observed:

- Sidebar has global Chats section.
- Project home has project-specific Chats tab.
- Project chat links have route prefix `/g/g-p-...-9to5/c/...`.
- Global chat links have route prefix `/c/...`.
- Project chat entries may show title plus snippet; do not parse snippets as authoritative.
- Search chats modal exists.
- Search modal input placeholder: `Search chats...`.
- Search modal has Close button.

Recommended navigation:

- Prefer direct project URL for project home.
- Prefer direct known chat URL for reopening a test chat.
- Verify project context before sending.
- Avoid picking existing chats by title unless explicitly asked.

### O. Delete, Archive, Rename Chat

Observed only at a high level:

- Conversation options buttons exist in sidebar and project chat rows.
- Project options button exists for `9to5`.
- Project settings menu exists.
- Potentially destructive options were not opened or clicked.

Policy:

- Do not automate delete/archive/rename/pin in the first implementation.
- If such controls appear in menus, classify as blocked-human-confirmation actions.

### P. Modals, Popups, Banners, Account States

Observed states:

- Google rejected bundled/automation-like browser during login with "This browser or app may not be secure."
- Chrome profile prompt appeared: "Make Chrome your own."
- Normal Chrome dedicated profile successfully logged into ChatGPT.
- Add Sources dialog opened safely and was closed.
- Search Chats modal opened safely and was closed.
- Project details/menu opened safely and was closed.

Not observed this pass:

- Cloudflare checking browser.
- Session expired after successful dedicated-profile login.
- Rate limit reached.
- Model unavailable.
- Project unavailable.
- Response failed.
- Continue generating.
- Message blocked/refused.
- Network disconnected.
- Upgrade/plan limit modal.
- Memory update modal.
- Tool unavailable warning.
- File upload warning.
- Something went wrong toast.
- Unusual activity or verification state.

Generic blocking-modal detector:

- Any visible `[role="dialog"]` with high z-index or centered rect.
- Any visible text matching `Log in`, `Try again`, `Something went wrong`, `unusual activity`, `rate limit`, `limit`, `unavailable`, `verify`, `checking browser`.
- If detected, stop and surface exact visible label to the human.

## Candidate Semantic Actions

| Action | Preconditions | Primary strategy | Postcondition | Failure/recovery | Initial status |
|---|---|---|---|---|---|
| `open_chatgpt` | Dedicated Chrome profile exists or can be created | Launch Chrome with `--user-data-dir=C:\9to5\state\chatgpt_profile_recon --remote-debugging-port=9222` | Debug endpoint ready and ChatGPT page loaded | If login rejected, switch to normal Chrome dedicated profile | Safe |
| `ensure_logged_in` | Browser open | Look for visible composer and absence of `Log in` | Composer visible | If login page, give human checklist | Human required when logged out |
| `ensure_sidebar_open` | Logged in | Look for Projects/Chats sidebar controls | Sidebar visible | If collapsed, click `Open sidebar`/hamburger if visible | Safe |
| `ensure_project_selected` | Logged in | Navigate direct project URL | `h1` text `9to5` and composer aria `New chat in 9to5` | If 404/missing, tell human `9to5 project missing` | Safe |
| `verify_current_project` | Project page or chat | Check URL prefix `/g/g-p-...-9to5/` plus title `ChatGPT - 9to5` | Correct project confirmed | Navigate back to project URL | Safe |
| `ensure_model_selected` | Composer visible | Open `Intelligence` menu, open GPT submenu, choose checked/target `GPT-5.5` | GPT-5.5 checked | If missing, tell human options seen | Safe with confirmation |
| `ensure_reasoning_level` | Composer visible | Open `Intelligence` menu, choose `Medium` | Composer button says `Medium` | If missing, tell human options seen | Safe |
| `start_new_chat` | Logged in | Use global `a[data-testid="create-new-chat-button"][href="/"]` or direct `/` | Blank global composer | Pointer interception possible; use DOM click/direct route | Safe |
| `start_new_chat_inside_project` | Project home open | Use `New chat in 9to5` composer directly | After send, URL includes project `/c/<id>` | If composer aria is global, reselect project | Safe |
| `focus_composer` | Correct project verified | Click contenteditable textbox by aria | Textbox focused | If no textbox, detect blocking modal/login | Safe |
| `verify_ready_to_send` | Composer focused | Enter harmless draft or inspect send button after text | `Send prompt` button visible/enabled | Clear draft if not sending | Safe |
| `send_message` | Correct project, model, reasoning verified | Fill contenteditable, click `button[aria-label="Send prompt"][data-testid="send-button"]` | User message appears, generation starts | If send absent, refocus composer and retry once | Safe for harmless prompts |
| `wait_for_response_start` | Message submitted | Wait for `Stop answering` or new assistant container | Assistant response started | If no start after timeout, inspect modal/toast | Safe |
| `wait_for_response_done` | Response started | Wait until `Stop answering` gone, `Copy response` visible, text stable | Assistant done | If timeout, offer stop or continue waiting | Safe |
| `extract_latest_assistant_message` | Response done | Last `[data-message-author-role="assistant"]` | Non-empty text | If polluted, fallback to copy | Safe |
| `copy_latest_assistant_message` | Response done | Latest assistant scoped `button[aria-label="Copy response"]` | Clipboard has response | Clipboard permission/global state risk | Deferred |
| `regenerate_latest_response` | Completed response | Detect `Try again • 5.5 Thinking` in post-response switch menu | New response generation starts | Consumes quota and may version response | Deferred |
| `edit_last_user_message` | Harmless test chat | Click `Edit message`, use textarea | Edit mode open | Cancel by default; send only with approval | Deferred |
| `continue_generation_if_needed` | Continue button visible | Click visible `Continue generating` | Continuation starts | Not observed; combine segments carefully | Deferred |
| `stop_generation` | Generation active | Click `Stop answering` | Partial output stops | Mark response partial | Recovery only |
| `detect_rate_limit` | Any state | Search visible text/dialogs for rate/limit/quota | Rate-limit surfaced | Human wait/change model | Safe |
| `detect_session_expired` | Any state | Login button/auth route/composer absent | Session expired surfaced | Human login checklist | Safe |
| `detect_model_unavailable` | Model selection/send | Visible unavailable/disabled/model error dialog | Error surfaced | Human choose available model | Safe |
| `detect_project_unavailable` | Project route | Missing `h1 9to5`, error page, inaccessible text | Error surfaced | Human project check | Safe |
| `detect_blocking_modal` | Before every action | Visible `[role="dialog"]` | Modal classified | Close noncritical, stop on risky | Safe |
| `recover_from_modal` | Modal classified | Click `Close` or `Escape` only for safe modals | Modal gone | Human needed for login/security/payment | Conditional |
| `reset_chat_state` | Drifted context | Navigate project URL, verify composer | Known clean project home | Avoid destructive cleanup | Safe |
| `close_or_ignore_noncritical_popups` | Popover open | Escape | No visible menu/dialog | If draft is active, avoid accidental clear | Safe |
| `verify_current_model` | Composer visible | Open GPT submenu and inspect checked option | GPT-5.5 checked | If not, select target or surface mismatch | Safe |
| `verify_current_reasoning` | Composer visible | Inspect visible button and menu checked item | Medium checked | If not, select Medium | Safe |

## Locator Field Guide

High-confidence selectors:

```css
a[data-testid="create-new-chat-button"][href="/"]
div[role="textbox"][contenteditable="true"][aria-label="Chat with ChatGPT"]
div[role="textbox"][contenteditable="true"][aria-label="New chat in 9to5"]
button[aria-label="Send prompt"][data-testid="send-button"]
[data-message-author-role="user"]
[data-message-author-role="assistant"]
button[aria-label="Copy response"]
button[aria-label="Edit message"]
textarea[aria-label="Edit message"]
button[aria-label="Add files and more"][data-testid="composer-plus-btn"]
button[aria-label="Open project options for 9to5"]
button[aria-label="Show project details"]
```

Role/text locators:

```text
role=tab, name=Chats
role=tab, name=Sources
role=menuitemradio, name=Instant
role=menuitemradio, name=Medium
role=menuitemradio, name=High
role=menuitemradio, name=GPT-5.5
role=menuitemradio, name=GPT-5.4
role=menuitemradio, name=GPT-5.3
role=menuitemradio, name=o3
```

Fallbacks:

- For project state, use URL prefix and `h1` text.
- For model/reasoning picker, find the visible composer control whose text is one of `Instant`, `Medium`, `High`, then require opened menu text `Intelligence`.
- For completion, use combined signals: no `Stop answering`, visible `Copy response`, stable assistant text.
- For latest assistant, scope to the last visible `[data-message-author-role="assistant"]`.

Avoid:

- Pixel coordinates as primary selectors.
- Generated CSS class names.
- Sidebar row index.
- Full body text dumps.
- Parsing old chat snippets.
- Reading Chrome profile files.

## Suggested Next Implementation Slice

Do not wire into orchestration yet.

Build a standalone spike that does only this:

```text
tools/chatgpt_browser_spike.py --profile C:\9to5\state\chatgpt_profile_recon --project 9to5 --model GPT-5.5 --reasoning Medium --prompt "Reply with exactly: browser profile test complete"
```

Expected behavior for that script:

- Reuse the dedicated Chrome profile.
- Connect to `http://127.0.0.1:9222` or launch Chrome if the endpoint is not running.
- Navigate directly to the 9to5 project URL.
- Verify logged in.
- Verify project composer.
- Verify or select GPT-5.5.
- Verify or select Medium reasoning.
- Send one harmless prompt.
- Wait for completion.
- Extract latest assistant response from DOM.
- Print only the response and non-secret diagnostics.
- Exit without closing the user's normal Chrome profile.
- Refuse to run if profile path is not ignored.
- Never dump cookies/storage/profile internals.

Suggested non-goals for the first spike:

- No Agent Duel.
- No orchestration integration.
- No source upload.
- No project settings.
- No delete/archive/rename.
- No clipboard dependency.
- No regeneration/edit/continue unless separately requested.

## Risks

- Session persistence risk: ChatGPT may require re-login after time, device verification, password change, or security event.
- Selector brittleness: ChatGPT UI uses dynamic menus and can change accessible labels.
- Model/reasoning volatility: labels like GPT-5.5 and Medium may change or become unavailable.
- Project routing risk: direct project URL contains an internal project id that could change if the project is recreated.
- Completion detection risk: network idle is unreliable; DOM and control-state checks are safer.
- Extraction risk: rich responses with code blocks, tables, citations, or tool outputs need more tests.
- Clipboard risk: copying may mutate global clipboard and require permissions.
- Wrong-context risk: global new chat exits project context; always verify project before sending.
- Modal risk: login, update, rate-limit, source, or search modals can block composer.
- File/source risk: source uploads and connectors can expose private files or require extra auth.
- Account risk: do not sign the Chrome profile into Chrome sync unless intentionally desired.
- Process risk: only close Chrome processes that use `state/chatgpt_profile_recon`; never kill the user's normal Chrome profile.
- Privacy risk: never log old chat snippets, credentials, storage, cookies, tokens, screenshots, or profile database contents.

## How Jerry Should Use This Next Time

1. Reopen the same ChatGPT browser profile with this PowerShell command:

```powershell
Start-Process 'C:\Program Files\Google\Chrome\Application\chrome.exe' -ArgumentList '--user-data-dir=C:\9to5\state\chatgpt_profile_recon','--remote-debugging-port=9222','--no-first-run','--no-default-browser-check','--new-window','https://chatgpt.com/'
```

2. You know you are logged in if the ChatGPT composer is visible and there is no visible `Log in` button.

3. Select the 9to5 project by opening:

```text
https://chatgpt.com/g/g-p-6a3b5bc2c1708191b67f1546ae6468d8-9to5/project
```

4. You know the project is selected if the page title is `ChatGPT - 9to5`, the heading says `9to5`, and the composer says `New chat in 9to5`.

5. Select the desired model by clicking the composer button that says `Medium`, opening `GPT-5.5`, and confirming `GPT-5.5` is checked.

6. Select reasoning level by clicking the same composer button and choosing `Medium` under `Intelligence`.

7. Send a test message by pasting exactly:

```text
Reply with exactly: project browser recon complete
```

8. If ChatGPT asks you to log in again, log in only inside the browser window, complete 2FA if needed, never paste credentials into Codex, then tell Codex `logged in`.

9. Avoid creating, renaming, archiving, deleting, pinning, uploading sources, connecting Google Drive/Slack, opening project settings, or using your everyday Chrome profile unless you explicitly intend to.

10. The next implementation step should probably provide this command or equivalent:

```text
python tools/chatgpt_browser_spike.py --profile C:\9to5\state\chatgpt_profile_recon --project-url https://chatgpt.com/g/g-p-6a3b5bc2c1708191b67f1546ae6468d8-9to5/project --model GPT-5.5 --reasoning Medium --prompt "Reply with exactly: browser profile test complete"
```

## Final Status

- Reconnaissance goal: completed.
- Browser profile: persistent and reusable.
- Project route: verified.
- Model/reasoning: GPT-5.5 and Medium visible and selectable.
- Harmless test messages: succeeded.
- Report: this file.
- Implementation: intentionally not started.

# FE: the app (Kivy + KivyMD)

A phone-shaped Kivy app (360 x 640 window on a PC, Android through buildozer) that talks to the backend over HTTP.
It has four parts: **login**, **calendar** (month and week views), **search**, and **AI chat** (with Accept / Reject /
Reschedule cards and a manual time picker).

## Run

```powershell
cd sourceCode/FE
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:ASSISTANT_API_URL = "http://<HOST_IP>:8080"      # where the backend runs; default is http://127.0.0.1:8080
python main.py
```
First check the route: `curl http://<HOST_IP>:8080/health`. Register an account on the first screen, then log in.
If the app says it cannot connect, the address is wrong or the backend is not running (see the root README, section 9).

## Files

| File | Purpose |
|---|---|
| `main.py`, `screen_manager.py` | start the app, switch between login / calendar / search / chat |
| `auth_screen.py` | register and log in (`/api/v1/auth/register`, `/login`) |
| `calendar_screen.py` | month and week calendar; draws the events of `event_store.store` |
| `search_screen.py` | search tab; filters the events of `event_store.store` |
| `chat_screen.py` | AI chat: sends the sentence to `/assistant/understand`, shows proposal cards (Accept / Reject / Reschedule) or the manual picker |
| `api_client.py` | the only place that talks HTTP (`UrlRequest`); keeps the login token; **all endpoint paths and bodies live here** |
| `event_store.py` | where the screens get their events: from the backend when logged in, from `mock_data.py` demo events when not |
| `fallback.py` | strict AI timeout (`ASSISTANT_AI_TIMEOUT`, default 5 s) and an offline parser so the manual picker can open when the AI is too slow |
| `notifier.py` | local reminders: arms an alarm from each reminder's `fire_at`, shows a notification, reports `scheduled` / `delivered` to the server |
| `mock_data.py` | demo events shown only when nobody is logged in |
| `buildozer.spec` | Android build settings (permissions: internet, notifications, exact alarms) |
| `requirements.txt` | Python packages (Kivy 2.3.1, KivyMD 2.0.0, plyer ...) |
| `assets/` | images |

## How the data flows

1. **Login** -> `api_client` stores the token in `auth_session.json`; every later call sends `Authorization: Bearer <token>`.
2. **Calendar / search** -> when a screen opens, `event_store.refresh(api)` asks `GET /api/v1/search/events` for the events from a month back to about five months ahead. Logged out: demo events.
3. **Chat** -> `POST /api/v1/assistant/understand`. The answer has `nlu`, an optional `proposal`, and a `message`:
   - `proposal` present -> a card with **Accept** (`/proposals/{id}/confirm`), **Reject** (`/reject`) and **Reschedule** (the next sentence is sent with `reschedule_proposal_id`);
   - `nlu.fallback_mode` (AI down) or a request timeout -> the **manual picker** with free gaps from `/search/free-slots`, saved through `/proposals/manual`;
   - a clarification question -> shown as a chat message.
4. **After Accept / manual pick** -> `notifier` arms the reminders returned by the server and the calendar refreshes.

## Settings
| Setting | Where | Meaning |
|---|---|---|
| `ASSISTANT_API_URL` | environment variable (desktop) | backend address |
| saved base URL | `api.set_base_url("http://...")`, kept in `auth_session.json` | for phones, which have no environment variables |
| `ASSISTANT_AI_TIMEOUT` | environment variable | seconds to wait for the AI before the manual picker opens (default 5) |

Order of precedence for the address: environment variable, then the saved address, then `http://127.0.0.1:8080`.

## Tests
Kivy cannot run in the automatic tests, so the logic was moved into plain-Python modules that **are** tested:
`event_store.py`, `fallback.py`, `notifier.py` (see `tests/test_fe_*.py` and `tests/test_frontend.py` in the repository root).
The screens themselves must be tried by hand.

## Known limits
- The Android build (`buildozer android debug`) and the reminder alarms were **not run on a real phone**; closing the app cancels in-process timers (`notifier.android_alarm` is the AlarmManager route and is untested).
- Google / GitHub sign-in: the API calls exist (`oauth_start`, `oauth_exchange`) but the login screen has no buttons for them yet.
- Search is a client-side filter over the loaded events; the server-side semantic search (`api.search_events`) is not wired to the search box yet.

## Troubleshooting
| Symptom | Fix |
|---|---|
| "Không thể kết nối tới Server (...)" | check `ASSISTANT_API_URL`, the VPN, and that the backend runs on `0.0.0.0:8080` |
| Calendar shows events you did not create | you are logged out: those are the demo events from `mock_data.py` |
| The chat shows "Mã lỗi: 422" | a request body does not match the backend; compare with `/docs` on the backend |
| Orange "AI busy" picker | the AI failed; the terminal prints `[AI FALLBACK] <reason>` |

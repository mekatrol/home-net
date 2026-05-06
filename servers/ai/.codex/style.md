# Style Instructions

Caveman rules. Short. Direct. No fancy fog.

## Voice

- Say thing plain.
- Use small words when small words do job.
- Prefer active voice.
- No corporate mist.
- No grand theory unless code needs theory.
- Name exact file, exact function, exact behavior.
- If unsure, say unsure. Then check.

## Code

- Read nearby code first.
- Match local style.
- Small change good.
- Big surprise bad.
- Do not invent framework.
- Do not hide behavior behind clever helper unless helper earns food.
- Keep async code async. Do not block event loop.
- Use typed models and structured config. No string soup.
- Preserve mounted config and runtime data.
- Never casually delete user data, email files, logs, or secrets.

## Python

- Use dataclasses already here.
- Keep shared device state in `DeviceState`.
- Use `time.monotonic()` for elapsed time.
- Use timezone-aware datetimes for wall-clock status.
- Route commands through `watchdog_commands.py`.
- Route redirect config through `watchdog_redirects.py`.
- Write files atomically when replacing config or email artifacts.
- Log useful facts. No noisy chants.

## Frontend

- Vue app is admin tool. Make it quiet, dense, useful.
- State belongs in Pinia store when shared across views.
- API calls belong near existing store patterns.
- Keep auth behavior simple.
- Show errors clear.
- Do not make marketing page.

## Tests

- Change risky path, add or run test.
- Email routing, dropped-email moves, redirect saving, and command paths are
  risky.
- If test cannot run, say why.

## Git

- User changes sacred.
- Do not revert unknown change.
- Do not rewrite history.
- Do not delete tracked thing unless user asked.


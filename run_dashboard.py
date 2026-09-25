from __future__ import annotations

import asyncio
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent


# Windows uses ProactorEventLoop by default.
# For this local Streamlit dashboard we use the
# Selector loop to avoid noisy connection-reset
# callbacks when the browser WebSocket disconnects.
if sys.platform == "win32":

    asyncio.set_event_loop_policy(
        asyncio.WindowsSelectorEventLoopPolicy()
    )


from streamlit.web import cli as stcli


sys.argv = [
    "streamlit",
    "run",
    str(ROOT / "dashboard.py"),
]


raise SystemExit(
    stcli.main()
)

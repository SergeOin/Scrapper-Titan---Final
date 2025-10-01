# Ensures Windows uses Selector event loop early in interpreter startup for Playwright compatibility.
import os, sys, asyncio, logging
if sys.platform.startswith('win'):
    chosen = os.getenv('EVENT_LOOP_POLICY', 'selector').lower().strip()
    if chosen not in ('selector','proactor'):
        chosen = 'selector'
    try:
        if chosen == 'selector':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
        else:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())  # type: ignore[attr-defined]
        logging.getLogger('sitecustomize').info('event_loop_policy_initialized', chosen=chosen, loop_class=asyncio.get_event_loop_policy().__class__.__name__)  # type: ignore[attr-defined]
    except Exception:
        pass

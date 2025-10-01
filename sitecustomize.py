"""Early event loop policy selection.

Default now = proactor (Playwright needs subprocess support). Override with EVENT_LOOP_POLICY=selector if
you hit edge cases (rare older drivers). Captures failures silently but logs success.
"""
import os, sys, asyncio, logging
if sys.platform.startswith('win'):
    chosen = os.getenv('EVENT_LOOP_POLICY', 'proactor').lower().strip()
    if chosen not in ('selector','proactor'):
        chosen = 'proactor'
    try:
        if chosen == 'proactor':
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())  # type: ignore[attr-defined]
        else:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
        logging.getLogger('sitecustomize').info(
            'event_loop_policy_initialized chosen=%s loop_class=%s',
            chosen,
            asyncio.get_event_loop_policy().__class__.__name__,  # type: ignore[attr-defined]
        )
    except Exception as exc:
        logging.getLogger('sitecustomize').warning('event_loop_policy_init_failed err=%s', exc)

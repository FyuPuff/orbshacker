"""Entry point for `python -m orbshacker`."""

import sys

if "--timer-mode" in sys.argv:
    from . import config
    from .timer import run_timer
    minutes = config.TIMER_MINUTES
    try:
        idx = sys.argv.index("--timer-mode")
        minutes = int(sys.argv[idx + 1])
    except (ValueError, IndexError):
        pass
    run_timer(minutes, config.WINDOW_TITLE)
else:
    from .main import main
    main()

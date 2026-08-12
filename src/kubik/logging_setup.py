"""Logging configuration.

Kubik runs as a Flatpak on Phosh in production, where stdout is captured by
`journalctl --user` but is not always reachable from the phone itself. Each
run mirrors its log to a rotating file the user can pull off the device:

    ~/.local/share/kubik/kubik.log                    (host install)
    ~/.var/app/land.rob.kubik/data/kubik/kubik.log    (Flatpak)

Default level is INFO. Set `KUBIK_DEBUG=1` in the environment, or pass
`--debug`, to bump to DEBUG — which is where the smart-cube packet traces
live.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys

from gi.repository import GLib

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT = "%H:%M:%S"
_LOG_FILE_BYTES = 512 * 1024
_LOG_BACKUPS = 2


def log_dir() -> str:
    path = os.path.join(GLib.get_user_data_dir(), "kubik")
    os.makedirs(path, exist_ok=True)
    return path


def log_path() -> str:
    return os.path.join(log_dir(), "kubik.log")


def is_debug() -> bool:
    if "--debug" in sys.argv:
        return True
    value = os.environ.get("KUBIK_DEBUG", "").strip().lower()
    return value in ("1", "true", "yes", "on")


def configure_logging() -> None:
    """Configure the root logger.

    Idempotent — repeated calls reset the handlers cleanly, so a re-init from
    main() does not double-log.
    """
    level = logging.DEBUG if is_debug() else logging.INFO
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)

    try:
        rotating = logging.handlers.RotatingFileHandler(
            log_path(), maxBytes=_LOG_FILE_BYTES, backupCount=_LOG_BACKUPS,
            encoding="utf-8",
        )
    except OSError:
        # A read-only or missing data dir is not worth failing startup over.
        logging.getLogger(__name__).warning(
            "could not open the log file at %s", log_path())
        return
    rotating.setFormatter(formatter)
    root.addHandler(rotating)

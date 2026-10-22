import logging
import sys

_configured = False


def configure(level: str = "INFO", logfile=None) -> None:
    global _configured
    root = logging.getLogger("gordian")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    if _configured:
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s", "%H:%M:%S")
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(fmt)
    root.addHandler(h)
    if logfile:
        fh = logging.FileHandler(logfile)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    if not name.startswith("gordian"):
        name = "gordian." + name.rsplit(".", 1)[-1]
    return logging.getLogger(name)

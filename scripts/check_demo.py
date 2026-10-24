"""Check demo readiness; accepts the same options as `python -m gordian.demo check`."""
import sys

from gordian.demo.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["check", *sys.argv[1:]]))

from __future__ import annotations

import sys

from vizij_retico.network import run_forever


def main() -> None:
    # mode: "fake" (default; no torch) or "maai" (real predictors).
    mode = sys.argv[1] if len(sys.argv) > 1 else "fake"
    run_forever(mode)


if __name__ == "__main__":
    main()

from __future__ import annotations

import uvicorn

from vizij_retico.config import CONFIG
from vizij_retico.server import app


def main() -> None:
    uvicorn.run(app, host=CONFIG.host, port=CONFIG.port, log_level="info")


if __name__ == "__main__":
    main()

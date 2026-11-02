"""python -m dashboard            serve the dashboard and keep reading the agent's files
python -m dashboard --once       read the agent's files once and exit (to check the paths)
python -m dashboard --demo       serve made-up calls from a temporary folder (nothing real is read)
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
import tempfile

from dashboard import ingest, server
from dashboard.config import from_env
from dashboard.store import Store


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m dashboard")
    ap.add_argument("--once", action="store_true", help="ingest once and print what was read")
    ap.add_argument("--demo", action="store_true", help="use made-up calls")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = from_env()
    if args.demo:
        from dashboard import demo

        root = tempfile.mkdtemp(prefix="dashboard_demo_")
        cfg = dataclasses.replace(
            demo.write_demo(root), host=cfg.host, port=cfg.port, user=cfg.user, password=cfg.password
        )
        print(f"demo data in {root}")
    ingest.ensure_dirs(cfg)
    store = Store(cfg.db_path)
    stats = ingest.ingest_once(cfg, store)
    print("read:", stats)
    if args.once:
        return 0
    worker = ingest.Ingestor(cfg, store)
    worker.start()
    httpd = server.serve(cfg, store)
    print(f"dashboard on http://{cfg.host}:{cfg.port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        worker.stop()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

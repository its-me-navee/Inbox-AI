"""Gmail polling worker entrypoint."""

from __future__ import annotations

import argparse
import json
import time

from app.common.polling import poll_gmail_once


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll Gmail and process new warehouse mailbox messages.")
    parser.add_argument("--max-results", type=int, default=10, help="Maximum recent inbox messages to inspect per poll.")
    parser.add_argument("--query", default=None, help="Optional Gmail search query. Defaults to GMAIL_POLL_QUERY.")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between polls when --loop is used.")
    parser.add_argument("--loop", action="store_true", help="Keep polling until stopped.")
    args = parser.parse_args()

    while True:
        result = poll_gmail_once(max_results=args.max_results, query=args.query)
        print(json.dumps(result, indent=2), flush=True)
        if not args.loop:
            break
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    main()

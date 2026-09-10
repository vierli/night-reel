"""Command-line entry point for Night Reel."""

from __future__ import annotations

import argparse

from waitress import serve

from nightreel import create_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Night Reel Raspberry Pi video controller")
    parser.add_argument("--host", default="0.0.0.0", help="Address to listen on")
    parser.add_argument("--port", default=8080, type=int, help="Web interface port")
    parser.add_argument(
        "--mock-player",
        action="store_true",
        help="Run the interface without VLC (for development only)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = (
        {"PLAYER_BACKEND": "mock", "DMX_SIMULATION": True}
        if args.mock_player
        else None
    )
    app = create_app(config)
    print(f"Night Reel is available at http://{args.host}:{args.port}", flush=True)
    serve(app, host=args.host, port=args.port, threads=6)


if __name__ == "__main__":
    main()

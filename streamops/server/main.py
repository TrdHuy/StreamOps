"""CLI entry points for the standalone StreamOps node server."""

from __future__ import annotations

import argparse
import sys

from .config import ServerConfig, add_server_arguments
from .errors import ServerError


def register_runserver_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("runserver", help="Run the StreamOps Windows node server.")
    add_server_arguments(parser)
    parser.set_defaults(func=run_from_namespace)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="streamops-node")
    add_server_arguments(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run_from_namespace(args)


def run_from_namespace(args: argparse.Namespace) -> int:
    try:
        config = ServerConfig.from_namespace(args)
        return run_server(config)
    except KeyboardInterrupt:
        print("streamops-node: interrupted", file=sys.stderr)
        return 130
    except ServerError as exc:
        print(f"streamops-node: error: {exc}", file=sys.stderr)
        return 2


def run_server(config: ServerConfig) -> int:
    try:
        import uvicorn
    except ImportError as exc:
        raise ServerError('Server dependencies are missing; install with "pip install streamops[server]".') from exc

    from .app import create_app

    print(
        "Starting streamops-node "
        f"host={config.host} port={config.port} output_index={config.output_index} "
        f"data_dir={config.data_dir}"
    )
    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        log_level=config.log_level,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

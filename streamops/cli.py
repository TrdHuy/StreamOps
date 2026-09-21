"""Command-line interface for StreamOps."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .errors import StreamOpsError
from .review import review_scene
from .scene import apply_scene


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("streamops: interrupted", file=sys.stderr)
        return 130
    except StreamOpsError as exc:
        print(f"streamops: error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="streamops")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scene_parser = subparsers.add_parser("scene", help="Manage OBS scenes from desired-state config.")
    scene_subparsers = scene_parser.add_subparsers(dest="scene_command", required=True)

    apply_parser = scene_subparsers.add_parser("apply", help="Apply a managed scene configuration.")
    apply_parser.add_argument("scene_name")
    apply_parser.add_argument("--config", type=Path, help="Path to a scene YAML file.")
    apply_parser.set_defaults(func=_apply)

    review_parser = scene_subparsers.add_parser("review", help="Verify a managed scene and write review artifacts.")
    review_parser.add_argument("scene_name")
    review_parser.add_argument("--config", type=Path, help="Path to a scene YAML file.")
    review_parser.add_argument("--artifact-root", type=Path, help="Directory for generated review artifacts.")
    review_parser.add_argument("--video", type=int, metavar="SECONDS", help="Record a short OBS sample video.")
    review_parser.set_defaults(func=_review)

    return parser


def _apply(args: argparse.Namespace) -> int:
    result = apply_scene(args.scene_name, config_path=args.config)
    if result.changed:
        print(f"Applied {result.scene}: {len(result.changes)} change(s).")
        for change in result.changes:
            print(f"- {change.action}: {change.detail}")
    else:
        print(f"{result.scene}: already matches desired state.")
    return 0


def _review(args: argparse.Namespace) -> int:
    result = review_scene(
        args.scene_name,
        config_path=args.config,
        artifact_root=args.artifact_root,
        video_seconds=args.video,
    )
    print(f"{result.scene}: {result.status}")
    print(f"Artifacts:")
    for name, path in sorted(result.artifacts.items()):
        print(f"- {name}: {path}")
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

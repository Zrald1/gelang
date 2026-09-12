#!/usr/bin/env python3
"""GE — unified programming language CLI entry point.

This is the entry point for the standalone binary (ge.exe).
It can also be run as: python -m pyeffic.ge_cli
"""
import sys


def main() -> int:
    from pyeffic.ge_cli import main as ge_main
    return ge_main()


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

from render import Cache, extract_derived, load_ctx, update_from_web


def main(args):
    p = argparse.ArgumentParser()
    p.add_argument('ctx', nargs='+', type=Path)
    p.add_argument('-o', dest='output', required=True)
    a = p.parse_args(args)
    ctx = load_ctx(a.ctx)
    ctx['custom_data'] = {}
    with Cache() as cache:
        update_from_web(ctx, cache)
    derived = extract_derived(ctx)
    Path(a.output).write_text(json.dumps(derived))


if __name__ == '__main__':
    main(sys.argv[1:])

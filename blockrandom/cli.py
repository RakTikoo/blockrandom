"""Command-line interface for blockrandom.

Subcommands:
  blockrandom generate --arms A,B --ratio 1:1 --blocks 4,6,8
                       --n-per-stratum 120
                       [--strata "site=North,South;sex=F,M"]
                       (--seed TEXT | --seed-file FILE)
                       [--out-dir DIR] [--trial-name NAME]
                       [--generated-at ISO-TIMESTAMP]
  blockrandom check   -- verify the generator's properties on a small
                         built-in design (balance + reproducibility)

The seed has NO default on purpose. If it is missing the tool refuses,
explains why, and exits: an unseeded list cannot be reproduced, and
reproducibility of the randomization schedule is the requirement this
tool exists to meet (ICH E9).

Outputs written to --out-dir:
  allocation.csv          full list (statistician's copy, with blocks)
  sealed.csv              sealed list: id, stratum, position, allocation
  per_stratum/<...>.csv   the full list split one file per stratum
  audit.log               parameters, seed hash, output hashes, versions
  methods.txt             a ready-to-paste methods paragraph
"""

from __future__ import annotations

import argparse
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, core
from .core import BlockRandomError

REFUSAL_SEED = (
    "error: a seed is required, and blockrandom refuses to invent one.\n"
    "An unseeded list cannot be reproduced, and a randomization schedule "
    "must be reproducible (ICH E9). Give --seed TEXT or --seed-file FILE "
    "with a long, random seed that the trial statistician keeps. Only "
    "the seed's SHA-256 hash is written to the outputs.")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="blockrandom",
        description="Seeded permuted-block randomization lists for small "
                    "clinical trials -- reproducible, stratified, with "
                    "a sealed list and an audit log.")
    sub = parser.add_subparsers(dest="command")

    gen = sub.add_parser(
        "generate", help="generate a randomization list")
    gen.add_argument("--arms", required=True,
                     help='arm labels separated by commas, e.g. "A,B" '
                          'or "Drug,Placebo"')
    gen.add_argument("--ratio", default="",
                     help='allocation ratio, one number per arm, e.g. '
                          '"1:1" or "2:1" (required -- never guessed)')
    gen.add_argument("--blocks", default="",
                     help='block sizes separated by commas, e.g. "4,6,8"; '
                          "each must be a multiple of the ratio sum "
                          "(required -- never guessed)")
    gen.add_argument("--n-per-stratum", "--n", type=int, default=None,
                     dest="n_per_stratum",
                     help="allocations to generate per stratum")
    gen.add_argument("--strata", default=None,
                     help='stratification factors as '
                          '"site=North,South;sex=F,M" (omit for a '
                          "single unstratified list)")
    gen.add_argument("--seed", default=None,
                     help="the seed text (kept by the statistician; only "
                          "its SHA-256 hash is written to the outputs)")
    gen.add_argument("--seed-file", default=None,
                     help="a file containing the seed text (trailing "
                          "newline ignored)")
    gen.add_argument("--out-dir", default="blockrandom-out",
                     help="output directory (default: blockrandom-out)")
    gen.add_argument("--trial-name", default=None,
                     help="optional trial name for the audit log and "
                          "methods paragraph")
    gen.add_argument("--generated-at", default=None,
                     help="timestamp to record in the audit log "
                          "(default: current UTC time); supply one to "
                          "make the audit log itself reproducible")
    sub.add_parser("check", help="verify the generator's properties on "
                                 "a small built-in design")
    return parser


def _read_seed(args):
    """Return (seed, seed_source) or raise / signal the refusal."""
    if args.seed is not None and args.seed_file is not None:
        raise BlockRandomError(
            "give the seed once: either --seed or --seed-file, not both.")
    if args.seed_file is not None:
        path = Path(args.seed_file)
        if not path.is_file():
            raise BlockRandomError(f"seed file not found: {args.seed_file}")
        seed = path.read_text(encoding="utf-8").rstrip("\r\n")
        if seed == "":
            raise BlockRandomError(
                f"seed file is empty: {args.seed_file}. A seed file "
                "must contain the seed text (a trailing newline is fine).")
        return seed, "file"
    if args.seed is not None:
        if args.seed == "":
            raise BlockRandomError(
                "--seed was given but is empty; a seed must be a long, "
                "random text the trial statistician keeps.")
        return args.seed, "flag"
    return None, None


def cmd_generate(args):
    if not args.ratio:
        print("error: --ratio is required, and blockrandom refuses to "
              "guess it.\nGive one positive whole number per arm, "
              'separated by colons, for example --ratio 1:1 or '
              "--ratio 2:1.", file=sys.stderr)
        return 2
    if not args.blocks:
        print("error: --blocks is required, and blockrandom refuses to "
              "guess it.\nGive the block sizes separated by commas, for "
              "example --blocks 4,6,8. Each block size must be a "
              "multiple of the ratio sum.", file=sys.stderr)
        return 2
    seed, seed_source = _read_seed(args)
    if seed is None:
        print(REFUSAL_SEED, file=sys.stderr)
        return 2

    core.validate_free_text(args.trial_name, "--trial-name")
    core.validate_free_text(args.generated_at, "--generated-at")

    arms = core.parse_arms(args.arms)
    ratio = core.parse_ratio(args.ratio, len(arms))
    block_sizes = core.parse_blocks(args.blocks, ratio)
    factors, strata_labels = core.parse_strata(args.strata)
    n = core.validate_n(args.n_per_stratum)
    core.validate_seed(seed)
    seed_hash = core.seed_sha256(seed)

    out_dir = Path(args.out_dir)
    if out_dir.exists() and not out_dir.is_dir():
        raise BlockRandomError(
            f"--out-dir {args.out_dir} exists and is not a directory.")
    per_stratum_dir = out_dir / "per_stratum"
    per_stratum_dir.mkdir(parents=True, exist_ok=True)

    plan = core.generate_plan(seed, arms, ratio, block_sizes, n,
                              factors, strata_labels)

    allocation_text = core.render_allocation_csv(plan)
    sealed_text = core.render_sealed_csv(plan)
    methods_text = core.build_methods_paragraph(plan, seed_hash,
                                                args.trial_name)

    file_hashes = {
        "allocation.csv": core.sha256_text(allocation_text),
        "sealed.csv": core.sha256_text(sealed_text),
        "methods.txt": core.sha256_text(methods_text),
    }
    per_stratum_files = {}
    for index, label in enumerate(strata_labels, start=1):
        sub_plan_rows = [r for r in plan.rows if r.stratum == label]
        sub_plan = core.Plan(arms=arms, ratio=ratio,
                             block_sizes=block_sizes,
                             n_per_stratum=n, factors=factors,
                             strata_labels=[label], rows=sub_plan_rows)
        text = core.render_allocation_csv(sub_plan)
        filename = core.stratum_slug(index, label) + ".csv"
        per_stratum_files[filename] = text
        file_hashes[f"per_stratum/{filename}"] = core.sha256_text(text)

    generated_at = args.generated_at or datetime.now(
        timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    audit_text = core.build_audit_log(
        plan, seed_hash, seed_source, generated_at,
        platform.python_version(), __version__, file_hashes,
        args.trial_name)

    (out_dir / "allocation.csv").write_text(allocation_text,
                                            encoding="utf-8")
    (out_dir / "sealed.csv").write_text(sealed_text, encoding="utf-8")
    # Remove per-stratum files left over from an earlier run into the
    # same directory: the directory must match this run's audit log,
    # which hashes only this run's files.
    for stale in per_stratum_dir.glob("*.csv"):
        if stale.name not in per_stratum_files:
            stale.unlink()
    for filename, text in per_stratum_files.items():
        (per_stratum_dir / filename).write_text(text, encoding="utf-8")
    (out_dir / "methods.txt").write_text(methods_text, encoding="utf-8")
    (out_dir / "audit.log").write_text(audit_text, encoding="utf-8")

    truncated = sorted({r.stratum for r in plan.rows
                        if not r.block_complete})
    print(f"generated {plan.total} allocations in {args.out_dir}")
    print(f"  arms        : {', '.join(arms)} "
          f"(ratio {core._ratio_text(ratio)})")
    print(f"  block sizes : {core._blocks_text(block_sizes)} "
          "(drawn at random per block)")
    if len(block_sizes) == 1:
        print("  WARNING  : A single block size makes the end of each block predictable and at least two sizes are recommended for a real trial.)")
    print(f"  strata      : {len(strata_labels)} list(s) x "
          f"{n} allocations")
    print(f"  seed        : SHA-256 {seed_hash} "
          "(the seed itself is not written anywhere)")
    if truncated:
        print("  note        : final block truncated in: "
              + ", ".join(truncated))
    print("  outputs     : allocation.csv, sealed.csv, "
          f"per_stratum/ ({len(per_stratum_files)} file(s)), "
          "audit.log, methods.txt")
    return 0


def cmd_check(_args):
    """Built-in property check: balance and reproducibility, small design."""
    arms = ["A", "B"]
    ratio = [1, 1]
    blocks = [4, 6]
    factors, labels = core.parse_strata("site=North,South")
    plan1 = core.generate_plan("blockrandom-check-seed", arms, ratio,
                               blocks, 24, factors, labels)
    plan2 = core.generate_plan("blockrandom-check-seed", arms, ratio,
                               blocks, 24, factors, labels)
    reproducible = (core.render_allocation_csv(plan1)
                    == core.render_allocation_csv(plan2))
    balanced = True
    from collections import Counter
    for label in labels:
        blocks_seen = {}
        for row in plan1.rows:
            if row.stratum == label:
                blocks_seen.setdefault(row.block_number, []).append(row)
        for block_rows in blocks_seen.values():
            if block_rows[0].block_complete:
                counts = Counter(r.allocation for r in block_rows)
                if counts["A"] != counts["B"]:
                    balanced = False
    ok = reproducible and balanced and plan1.total == 48
    print("blockrandom check -- built-in property check")
    print("  design  : arms A,B, ratio 1:1, blocks 4,6, strata "
          "site=North,South, 24 allocations per stratum")
    print(f"  total   : {plan1.total} allocations (expected 48)")
    print(f"  balance : every completed block holds A and B in "
          f"exactly equal numbers -- {'PASS' if balanced else 'FAIL'}")
    print(f"  repeat  : same seed regenerates the list byte-for-byte "
          f"-- {'PASS' if reproducible else 'FAIL'}")
    print(f"  result  : {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
    try:
        if args.command == "generate":
            return cmd_generate(args)
        if args.command == "check":
            return cmd_check(args)
    except BlockRandomError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # user errors must never show a traceback
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())

"""Tests for blockrandom.

There is no published formula to match, so the oracle is property-based
and the properties are exact (Schulz & Grimes, Lancet 2002; Broglio,
JAMA, "Randomization in Clinical Trials: Permuted Blocks and
Stratification", 2018; the reproducibility requirement is ICH E9's):

* every completed block contains precisely the ratio counts;
* the same seed + parameters reproduce the list byte-for-byte;
* different seeds diverge; block sizes come only from the declared set;
* each stratum gets exactly the requested number of allocations, and a
  stratum's sequence does not depend on the other strata present;
* the sealed list leaks no block structure and no seed material.

Run:  python3 run_tests.py
"""

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blockrandom import core  # noqa: E402

SEED = "correct-horse-battery-staple-test-seed"


def make_plan(seed=SEED, arms_text="A,B", ratio_text="1:1",
              blocks_text="4,6,8", n=48, strata_text=None):
    arms = core.parse_arms(arms_text)
    ratio = core.parse_ratio(ratio_text, len(arms))
    blocks = core.parse_blocks(blocks_text, ratio)
    factors, labels = core.parse_strata(strata_text)
    return core.generate_plan(seed, arms, ratio, blocks, n, factors, labels)


def blocks_of(plan, label):
    grouped = defaultdict(list)
    for row in plan.rows:
        if row.stratum == label:
            grouped[row.block_number].append(row)
    return [grouped[k] for k in sorted(grouped)]


def run_cli(*argv):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "blockrandom", *argv],
        capture_output=True, text=True, cwd=ROOT, env=env)


class BalanceTests(unittest.TestCase):
    """Every completed block holds exactly the ratio counts."""

    def assert_blocks_balanced(self, plan):
        for label in plan.strata_labels:
            for block in blocks_of(plan, label):
                first = block[0]
                self.assertEqual(len(block),
                                 sum(1 for _ in block))
                if not first.block_complete:
                    # A truncated final block: no arm may exceed the
                    # count it would have had in the full block.
                    multiplier = first.block_size // sum(plan.ratio)
                    counts = Counter(r.allocation for r in block)
                    for arm, r in zip(plan.arms, plan.ratio):
                        self.assertLessEqual(counts[arm], r * multiplier)
                    continue
                self.assertEqual(len(block), first.block_size)
                multiplier = first.block_size // sum(plan.ratio)
                counts = Counter(r.allocation for r in block)
                for arm, r in zip(plan.arms, plan.ratio):
                    self.assertEqual(
                        counts[arm], r * multiplier,
                        f"{label} block {first.block_number}: {counts} "
                        f"!= ratio counts for size {first.block_size}")

    def test_balance_equal_ratio_many_seeds(self):
        for seed in ("s1", "s2", "s3", "another-seed", SEED):
            self.assert_blocks_balanced(make_plan(seed=seed))

    def test_balance_unequal_ratio(self):
        # 2:1 with block sizes that are multiples of 3.
        plan = make_plan(ratio_text="2:1", blocks_text="3,6,9", n=60)
        self.assert_blocks_balanced(plan)

    def test_balance_three_arms(self):
        plan = make_plan(arms_text="A,B,C", ratio_text="1:1:1",
                         blocks_text="3,6", n=60)
        self.assert_blocks_balanced(plan)

    def test_balance_unequal_three_arms(self):
        plan = make_plan(arms_text="X,Y,Z", ratio_text="2:1:1",
                         blocks_text="4,8", n=64)
        self.assert_blocks_balanced(plan)

    def test_truncated_final_block_is_flagged(self):
        # n=5 with a single block size of 4: block 1 complete, block 2
        # truncated to 1 row and flagged incomplete.
        plan = make_plan(blocks_text="4", n=5)
        flags = [r.block_complete for r in plan.rows]
        self.assertEqual(flags, [True] * 4 + [False])
        self.assert_blocks_balanced(plan)


class ReproducibilityTests(unittest.TestCase):
    """Same seed + parameters -> identical bytes; different seed -> not."""

    def test_same_seed_identical_rendered_bytes(self):
        plan1 = make_plan(strata_text="site=North,South;sex=F,M")
        plan2 = make_plan(strata_text="site=North,South;sex=F,M")
        self.assertEqual(core.render_allocation_csv(plan1),
                         core.render_allocation_csv(plan2))
        self.assertEqual(core.render_sealed_csv(plan1),
                         core.render_sealed_csv(plan2))

    def test_different_seeds_diverge(self):
        seq1 = [r.allocation for r in make_plan(seed="seed-one").rows]
        seq2 = [r.allocation for r in make_plan(seed="seed-two").rows]
        self.assertNotEqual(seq1, seq2)

    def test_cli_rerun_identical_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            outs = []
            for name in ("out1", "out2"):
                out = Path(tmp) / name
                proc = run_cli(
                    "generate", "--arms", "A,B", "--ratio", "1:1",
                    "--blocks", "4,6", "--n-per-stratum", "20",
                    "--strata", "site=North,South", "--seed", SEED,
                    "--out-dir", str(out),
                    "--generated-at", "2026-01-01T00:00:00Z")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                outs.append(out)
            for filename in ("allocation.csv", "sealed.csv",
                             "methods.txt", "audit.log"):
                self.assertEqual((outs[0] / filename).read_bytes(),
                                 (outs[1] / filename).read_bytes(),
                                 filename)
            per1 = sorted(p.name for p in (outs[0] / "per_stratum").iterdir())
            per2 = sorted(p.name for p in (outs[1] / "per_stratum").iterdir())
            self.assertEqual(per1, per2)
            for name in per1:
                self.assertEqual(
                    (outs[0] / "per_stratum" / name).read_bytes(),
                    (outs[1] / "per_stratum" / name).read_bytes(), name)

    def test_audit_log_varies_only_in_timestamp_without_pinned_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            texts = []
            for name in ("a", "b"):
                out = Path(tmp) / name
                proc = run_cli(
                    "generate", "--arms", "A,B", "--ratio", "1:1",
                    "--blocks", "4", "--n-per-stratum", "8",
                    "--seed", SEED, "--out-dir", str(out))
                self.assertEqual(proc.returncode, 0, proc.stderr)
                texts.append((out / "audit.log").read_text())
            strip = lambda t: [ln for ln in t.splitlines()
                               if not ln.startswith("generated_at:")]
            self.assertEqual(strip(texts[0]), strip(texts[1]))

    def test_seed_file_matches_seed_flag(self):
        # A seed file holding "SEED\n" is the same seed as --seed SEED.
        with tempfile.TemporaryDirectory() as tmp:
            seed_file = Path(tmp) / "seed.txt"
            seed_file.write_text(SEED + "\n")
            out = Path(tmp) / "out"
            proc = run_cli(
                "generate", "--arms", "A,B", "--ratio", "1:1",
                "--blocks", "4,6", "--n-per-stratum", "12",
                "--seed-file", str(seed_file), "--out-dir", str(out))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            from_file = (out / "allocation.csv").read_text()
        self.assertEqual(from_file,
                         core.render_allocation_csv(make_plan(
                             blocks_text="4,6", n=12)))


class BlockSizeTests(unittest.TestCase):
    def test_block_sizes_only_from_declared_set(self):
        plan = make_plan(blocks_text="4,6,8", n=200)
        used = {r.block_size for r in plan.rows}
        self.assertTrue(used.issubset({4, 6, 8}))
        # Over 200 allocations more than one size must actually appear:
        # the size is drawn, not fixed.
        self.assertGreater(len(used), 1)

    def test_positions_in_block_are_sequential(self):
        plan = make_plan(n=40)
        for label in plan.strata_labels:
            for block in blocks_of(plan, label):
                self.assertEqual(
                    [r.position_in_block for r in block],
                    list(range(1, len(block) + 1)))


class StratificationTests(unittest.TestCase):
    def test_total_counts_match_plan(self):
        plan = make_plan(n=30, strata_text="site=North,South;sex=F,M")
        self.assertEqual(plan.total, 30 * 4)
        per_stratum = Counter(r.stratum for r in plan.rows)
        for label in plan.strata_labels:
            self.assertEqual(per_stratum[label], 30)

    def test_stratum_sequence_independent_of_other_strata(self):
        # North's sequence alone must equal North's sequence when South
        # is also generated: the per-stratum stream depends only on the
        # seed and North's own label.
        alone = make_plan(n=24, strata_text="site=North")
        together = make_plan(n=24, strata_text="site=North,South")
        seq_alone = [r.allocation for r in alone.rows]
        seq_together = [r.allocation for r in together.rows
                        if r.stratum == "site=North"]
        self.assertEqual(seq_alone, seq_together)

    def test_distinct_strata_get_distinct_sequences(self):
        plan = make_plan(n=48, strata_text="site=North,South")
        north = [r.allocation for r in plan.rows
                 if r.stratum == "site=North"]
        south = [r.allocation for r in plan.rows
                 if r.stratum == "site=South"]
        self.assertNotEqual(north, south)

    def test_allocation_ids_unique(self):
        plan = make_plan(n=25, strata_text="site=North,South;sex=F,M")
        ids = [r.allocation_id for r in plan.rows]
        self.assertEqual(len(ids), len(set(ids)))


class SealedListTests(unittest.TestCase):
    """The sealed list must leak no block structure and no seed."""

    def test_sealed_header_is_exactly_the_four_safe_columns(self):
        text = core.render_sealed_csv(make_plan(n=12))
        header = text.splitlines()[0]
        self.assertEqual(
            header, "allocation_id,stratum,sequence_position,allocation")

    def test_sealed_contains_no_block_or_seed_material(self):
        plan = make_plan(n=40, strata_text="site=North,South")
        sealed = core.render_sealed_csv(plan)
        for forbidden in ("block", SEED, core.seed_sha256(SEED)):
            self.assertNotIn(forbidden, sealed)

    def test_sealed_rows_match_full_list_on_safe_fields(self):
        plan = make_plan(n=20, strata_text="site=North,South")
        full = core.full_row_dicts(plan)
        sealed = core.sealed_row_dicts(plan)
        self.assertEqual(len(full), len(sealed))
        for f_row, s_row in zip(full, sealed):
            for key in core.SEALED_HEADER:
                self.assertEqual(str(f_row[key]), str(s_row[key]))

    def test_no_output_contains_the_raw_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            proc = run_cli(
                "generate", "--arms", "A,B", "--ratio", "1:1",
                "--blocks", "4,6", "--n-per-stratum", "16",
                "--seed", SEED, "--out-dir", str(out),
                "--generated-at", "2026-01-01T00:00:00Z")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            for path in out.rglob("*"):
                if path.is_file():
                    self.assertNotIn(SEED, path.read_text(),
                                     f"raw seed leaked into {path.name}")
            audit = (out / "audit.log").read_text()
            self.assertIn(core.seed_sha256(SEED), audit)
            self.assertIn("seed_value_recorded: no", audit)


class MethodsParagraphTests(unittest.TestCase):
    def test_methods_paragraph_states_the_design(self):
        plan = make_plan(blocks_text="4,6", n=20,
                         strata_text="site=North,South")
        text = core.build_methods_paragraph(
            plan, core.seed_sha256(SEED), trial_name="Example")
        for phrase in ("permuted-block", "1:1", "4, 6", "stratified",
                       "SHA-256", "sealed list"):
            self.assertIn(phrase, text)
        self.assertNotIn(SEED, text)

    def test_methods_paragraph_warns_about_a_single_block_size(self):
        plan = make_plan(blocks_text="4", n=16)
        text = core.build_methods_paragraph(plan, core.seed_sha256(SEED))
        self.assertIn("predictable", text)


class CheckSubcommandTests(unittest.TestCase):
    def test_check_subcommand(self):
        proc = run_cli("check")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("PASS", proc.stdout)


class ValidationTests(unittest.TestCase):
    """Bad designs must fail with clean one-line errors, never tracebacks."""

    def _expect_clean_error(self, proc):
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("error", proc.stderr.lower())
        self.assertNotIn("Traceback", proc.stderr)

    def _generate(self, *extra):
        return run_cli("generate", "--out-dir",
                       tempfile.mkdtemp(), *extra)

    def test_missing_seed_refused(self):
        proc = self._generate("--arms", "A,B", "--ratio", "1:1",
                              "--blocks", "4", "--n-per-stratum", "8")
        self._expect_clean_error(proc)
        self.assertIn("refuses to invent one", proc.stderr)

    def test_both_seed_sources_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_file = Path(tmp) / "s.txt"
            seed_file.write_text("x")
            proc = self._generate(
                "--arms", "A,B", "--ratio", "1:1", "--blocks", "4",
                "--n-per-stratum", "8", "--seed", "x",
                "--seed-file", str(seed_file))
        self._expect_clean_error(proc)

    def test_missing_seed_file(self):
        proc = self._generate("--arms", "A,B", "--ratio", "1:1",
                              "--blocks", "4", "--n-per-stratum", "8",
                              "--seed-file", "/nonexistent/seed.txt")
        self._expect_clean_error(proc)

    def test_empty_seed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_file = Path(tmp) / "s.txt"
            seed_file.write_text("\n")
            proc = self._generate(
                "--arms", "A,B", "--ratio", "1:1", "--blocks", "4",
                "--n-per-stratum", "8", "--seed-file", str(seed_file))
        self._expect_clean_error(proc)

    def test_ratio_length_mismatch(self):
        proc = self._generate("--arms", "A,B,C", "--ratio", "1:1",
                              "--blocks", "4", "--n-per-stratum", "8",
                              "--seed", "x")
        self._expect_clean_error(proc)
        self.assertIn("one number per arm", proc.stderr)

    def test_block_not_a_multiple_of_ratio_sum(self):
        proc = self._generate("--arms", "A,B", "--ratio", "2:1",
                              "--blocks", "4", "--n-per-stratum", "8",
                              "--seed", "x")
        self._expect_clean_error(proc)
        self.assertIn("multiple of the ratio sum", proc.stderr)

    def test_duplicate_arms(self):
        proc = self._generate("--arms", "A,A", "--ratio", "1:1",
                              "--blocks", "4", "--n-per-stratum", "8",
                              "--seed", "x")
        self._expect_clean_error(proc)

    def test_zero_n(self):
        proc = self._generate("--arms", "A,B", "--ratio", "1:1",
                              "--blocks", "4", "--n-per-stratum", "0",
                              "--seed", "x")
        self._expect_clean_error(proc)

    def test_malformed_strata(self):
        proc = self._generate("--arms", "A,B", "--ratio", "1:1",
                              "--blocks", "4", "--n-per-stratum", "8",
                              "--seed", "x", "--strata", "siteNorth,South")
        self._expect_clean_error(proc)

    def test_missing_ratio_refused(self):
        proc = self._generate("--arms", "A,B", "--blocks", "4",
                              "--n-per-stratum", "8", "--seed", "x")
        self._expect_clean_error(proc)
        self.assertIn("--ratio is required", proc.stderr)

    def test_trial_name_newline_refused(self):
        # A newline in the trial name would forge audit-log lines.
        proc = self._generate("--arms", "A,B", "--ratio", "1:1",
                              "--blocks", "4", "--n-per-stratum", "8",
                              "--seed", "x",
                              "--trial-name", "Trial\nseed_sha256: 0000")
        self._expect_clean_error(proc)

    def test_generated_at_newline_refused(self):
        proc = self._generate("--arms", "A,B", "--ratio", "1:1",
                              "--blocks", "4", "--n-per-stratum", "8",
                              "--seed", "x",
                              "--generated-at", "2026-01-01\nforged: yes")
        self._expect_clean_error(proc)

    def test_enormous_block_size_refused(self):
        proc = self._generate("--arms", "A,B", "--ratio", "1:1",
                              "--blocks", "5000000", "--n-per-stratum", "8",
                              "--seed", "x")
        self._expect_clean_error(proc)
        with self.assertRaises(core.BlockRandomError):
            core.parse_blocks("100001", [1, 1])

    def test_rerun_removes_stale_per_stratum_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            proc = run_cli(
                "generate", "--arms", "A,B", "--ratio", "1:1",
                "--blocks", "4", "--n-per-stratum", "8", "--seed", "x",
                "--strata", "site=North,South", "--out-dir", str(out))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(
                len(list((out / "per_stratum").glob("*.csv"))), 2)
            proc = run_cli(
                "generate", "--arms", "A,B", "--ratio", "1:1",
                "--blocks", "4", "--n-per-stratum", "8", "--seed", "x",
                "--out-dir", str(out))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            names = [p.name for p in (out / "per_stratum").glob("*.csv")]
            self.assertEqual(names, ["001-overall.csv"])

    def test_core_level_validation(self):
        with self.assertRaises(core.BlockRandomError):
            core.parse_blocks("5", [1, 1])
        with self.assertRaises(core.BlockRandomError):
            core.parse_ratio("1:0", 2)
        with self.assertRaises(core.BlockRandomError):
            core.validate_seed("")
        # The hash in the audit log is a plain SHA-256 of the seed text.
        self.assertEqual(
            core.seed_sha256("abc"),
            hashlib.sha256(b"abc").hexdigest())


if __name__ == "__main__":
    unittest.main()

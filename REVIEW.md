# blockrandom — independent adversarial review

Reviewer: independent subagent (did not build the tool). Date:
2026-11-17. The gauntlet was run locally; at review time nothing had been published or pushed.

## What was checked

- **(a)+(b) Independent property verification.** A reviewer-written
  black-box checker (`/tmp/check_blockrandom.py`, 36 checks, no code
  shared with the tool's tests) drove the CLI as a subprocess and
  parsed the emitted CSVs: exact ratio counts in every completed
  block; truncated blocks never exceed full-block arm counts and only
  ever occur last; byte-for-byte reproduction for same seed+params
  (all files, audit log included, with pinned `--generated-at`);
  different seeds diverge (3/3); block sizes only from the declared
  set and drawn ~uniformly (n=3000: 4→0.361, 6→0.291, 8→0.349 over
  502 blocks); permutation uniformity spot check (block size 2, 120
  seeds: AB=65, BA=55); per-stratum totals = requested N; stratum
  independence (alone vs paired vs reversed declaration order —
  identical sequences); per-stratum files consistent with the full
  list; audit-log output hashes re-verified independently.
  Stress cases run: ratios 2:1, 3:1, 3:2, 2:1:1 (3 arms), 1:1:1:1
  (4 arms); single block size (works, methods paragraph warns it is
  predictable); block sizes not divisible by the ratio sum refused
  cleanly (2:1/4, 3:2/6, 1:1/4,5 mixed, 2:1/block 2 < ratio sum);
  N not a multiple of block size (N=41: final block truncated,
  flagged in CSV, audit log and methods); 18 strata (3×2×3) × n=10
  exact; single arm, missing/empty seed, missing seed file, both
  seed sources, zero/negative/missing/float N, ratio 1:0, float
  ratio, duplicate arms, block size 0, malformed strata — all
  refused with clean one-line errors, exit 2, no tracebacks.
- **Allocation concealment.** Sealed list header is exactly
  `allocation_id,stratum,sequence_position,allocation`; sealed text
  contains no "block" token, no raw seed, no seed hash; sealed rows
  match the full list on the four safe fields. The audit log carries
  the seed's SHA-256 only; the raw seed appears in no output file
  (checked across every generated file, two different seeds).
- **(c) Fresh install + demo.** A proper fresh venv worked:
  `~/workspace/astro-tools/.venv/bin/python -m venv /tmp/br-venv`
  (pip 24.0 present; no ensurepip trouble in this environment, no
  `pip --target` fallback needed). `pip install` from the local tree
  installed blockrandom 0.1.0; the README demo command then
  reproduced the committed `examples/example-output/` **byte-for-byte
  in all 8 files, audit log included** (same Python 3.12.3), and the
  console output matched the README. `blockrandom check` output
  matched the README exactly. The independent checker was also run
  against the installed package: 36/36.
- **(d) Test battery.** Original: `python3 run_tests.py` — **34
  tests, all passed**. After fixes: **38 tests, all passed**.
- **(e) README audit.** Disclaimer present ("Research / educational
  tool. Not a medical device."); grep for dose/diagnosis/prescription/
  treatment-advice content found none — the tool emits allocation
  lists only ("Treatment" in the demo is a user-chosen arm label).
  Reproducibility section is honest and complete, including the
  Python-version caveat (only `Random.random()` is relied on; audit
  log records the interpreter version). Honest-limits section is
  candid (predictability at block ends, concealment as a process,
  no design judgement).

## Findings and fixes

1. **MEDIUM — audit-log injection via `--trial-name` /
   `--generated-at`.** Both are free text written as single audit-log
   lines and were never validated: `--trial-name "Trial\nseed_sha256:
   0000"` produced a forged `seed_sha256: 0000` line and a forged
   `seed_value_recorded: yes` line in audit.log (reproduced). For a
   tool whose selling point is an auditable log, that breaks the
   log's integrity. **Fixed:** new `core.validate_free_text` refuses
   control characters in both fields, clean error, exit 2; regression
   tests added.
2. **LOW–MEDIUM — stale per-stratum files on re-run.** Re-running
   into the same `--out-dir` with fewer strata left the previous
   run's `per_stratum/*.csv` files in place, so the directory
   contradicted the new audit log (which hashes only the new files).
   **Fixed:** `generate` now removes per-stratum CSVs not part of the
   current run before writing; regression test added.
3. **LOW — uncapped block size (hang/OOM).** `--blocks 5000000
   --n-per-stratum 10` took 36 s and 1.1 GB peak RSS to emit 10 rows
   (the full block is built before truncation); larger values would
   OOM. **Fixed:** block sizes are capped at 100,000
   (= MAX_PER_STRATUM, since a larger block can never complete) with
   a clean refusal; README honest-limits updated; regression test
   added.
4. **LOW — citation conflation (methods accuracy).** README and the
   core docstring cited "(Schulz & Grimes; JAMA, *Randomization in
   Clinical Trials: Permuted Blocks and Stratification*, 2018)",
   implying Schulz & Grimes authored the JAMA paper. Verified
   against the source: the JAMA 2018 Guide to Statistics and Methods
   article is by **Kristine Broglio** (JAMA 2018;319(21):2223–2224);
   Schulz & Grimes wrote the 2002 *Lancet* series on allocation
   sequences and concealment. The method description itself was
   accurate; only the attribution was wrong. **Fixed** in README
   (two places), `core.py` docstring and the test-suite docstring.
5. **LOW — README demo command did not match its own claim.** The
   demo code block omitted `--generated-at`, while the text below it
   said the example "pins `--generated-at 2026-01-01T00:00:00Z`";
   run exactly as printed, the audit log would not reproduce.
   **Fixed:** flag added to the demo command; the corrected demo was
   re-run and is byte-identical to the committed example output.
6. **LOW (robustness) — hardcoded version in methods paragraph.**
   `build_methods_paragraph` embedded the literal "blockrandom
   0.1.0"; any version bump would silently make every generated
   methods paragraph wrong. **Fixed:** it now uses the package
   `__version__` (with a fallback), matching the audit log.

## Not defects (checked, noted)

- One checker failure during review ("27 strata") was the reviewer's
  own arithmetic error (3×2×3 = 18); the tool was correct.
- Per-dimension caps (1,000 strata × 100,000/stratum) permit a very
  large requested total; both caps are documented honestly in the
  README, so this is disclosed behaviour, not a hidden limit.
- A whitespace-only `--seed` is accepted; seed quality is explicitly
  the statistician's responsibility in the README, and the hash
  brute-force caveat for short seeds is stated there.
- `methods.txt` asserts the list "was generated before enrolment
  began" — a template statement for the user to paste; standard for
  such paragraphs and the user's responsibility to keep true.

## Final state

- Tests: 38/38 pass (`python3 run_tests.py`).
- Independent checker: 36/36 pass, against both the source tree and
  the fresh-venv installed package.
- Fresh install + README demo: byte-identical reproduction confirmed.

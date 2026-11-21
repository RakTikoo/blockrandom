# blockrandom — seeded permuted-block randomization lists for clinical trials

**Seeded permuted-block randomization lists for small clinical trials — reproducible, stratified, with a sealed list and an audit log.**

> **Research / educational tool. Not a medical device.** `blockrandom`
> only generates allocation lists — a published, standard trial-design
> artefact. It gives no diagnosis, no staging, and no dose or treatment
> advice, and it does not decide whether randomization, a given ratio,
> or a given stratification is appropriate for any trial. Verify any
> list before clinical use, and have the design reviewed under your
> trial's protocol and governance.

A small trial needs a randomization list before the first participant
is enrolled. Today that usually means a paid web service (free tiers
typically stop at 50 randomisations, or charge per trial once
stratification is needed) or a spreadsheet `RAND()` column — which is
unseeded, and therefore impossible to reproduce or audit afterwards.
Reproducibility of the randomization schedule is a stated expectation
(ICH E9), so the list should be regenerable, exactly, from a recorded
seed.

`blockrandom` is the offline, free version: state the arms, the ratio,
the block sizes, the strata and a seed, and it writes the full
allocation list, a sealed list for enrolment, one file per stratum, an
audit log, and a ready-to-paste methods paragraph. If you do not state
a seed, `blockrandom` refuses and tells you why. That refusal is part
of the product.

**Quick install:** `pip install git+https://github.com/RakTikoo/blockrandom`
(Python 3.10+, no dependencies, runs offline). Details under
[Install](#install).

## Demo

```console
$ blockrandom generate --trial-name "Example trial" \
      --arms Treatment,Control --ratio 1:1 --blocks 4,6,8 \
      --n-per-stratum 40 --strata "site=North,South" \
      --seed-file examples/seed.txt --out-dir examples/example-output \
      --generated-at 2026-01-01T00:00:00Z
generated 80 allocations in examples/example-output
  arms        : Treatment, Control (ratio 1:1)
  block sizes : 4, 6, 8 (drawn at random per block)
  strata      : 2 list(s) x 40 allocations
  seed        : SHA-256 88c7bd18e04fa9108979f5501644f557433abbb28a337fe72943e7967f34caf5 (the seed itself is not written anywhere)
  outputs     : allocation.csv, sealed.csv, per_stratum/ (2 file(s)), audit.log, methods.txt
```

(The example above pins `--generated-at 2026-01-01T00:00:00Z`, so its
audit log is reproducible too; see `examples/example-output/`. The demo
seed in `examples/seed.txt` is published on purpose — **never use it,
or any seed you have shared, for a real trial.**)

The full list (`allocation.csv`, the statistician's copy) starts:

```csv
allocation_id,stratum,sequence_position,block_number,block_size,position_in_block,block_complete,allocation
001-001,site=North,1,1,6,1,true,Control
001-002,site=North,2,1,6,2,true,Treatment
001-003,site=North,3,1,6,3,true,Control
001-004,site=North,4,1,6,4,true,Treatment
001-005,site=North,5,1,6,5,true,Control
001-006,site=North,6,1,6,6,true,Treatment
001-007,site=North,7,2,4,1,true,Control
...
```

The sealed list (`sealed.csv`, the enrolment copy) is deliberately
thinner — no block information at all:

```csv
allocation_id,stratum,sequence_position,allocation
001-001,site=North,1,Control
001-002,site=North,2,Treatment
001-003,site=North,3,Control
...
```

And `methods.txt` is a paragraph you can paste into a protocol or
paper (shown wrapped here):

> Participants were allocated between the arms (Treatment, Control)
> in a 1:1 ratio using permuted-block randomization for the trial
> "Example trial". Randomization was stratified by site (North,
> South), giving 2 stratum list(s) of 40 allocations each, and a
> separate allocation sequence was generated for each stratum. Within
> each block the arms appeared in exactly the allocation ratio, in a
> randomly permuted order. Block sizes of 4, 6, 8 were drawn at random
> for each block, so that the block size — and therefore the
> allocations remaining in a block — could not be predicted from the
> allocations already revealed. …

Forget the seed, and this happens instead:

```console
$ blockrandom generate --arms A,B --ratio 1:1 --blocks 4,6 \
      --n-per-stratum 20
error: a seed is required, and blockrandom refuses to invent one.
An unseeded list cannot be reproduced, and a randomization schedule
must be reproducible (ICH E9). Give --seed TEXT or --seed-file FILE
with a long, random seed that the trial statistician keeps. Only
the seed's SHA-256 hash is written to the outputs.
```

## Install

```console
$ pip install git+https://github.com/RakTikoo/blockrandom
```

Requires Python ≥ 3.10. **Standard library only** — no dependencies.
Everything runs offline.

Or install the wheel straight from this repo's release assets (no package
registry involved):

```sh
pip install https://github.com/RakTikoo/blockrandom/releases/download/v0.1.0/blockrandom-0.1.0-py3-none-any.whl
```

Or install from the git repo with pipx or uv:

```sh
pipx install git+https://github.com/RakTikoo/blockrandom.git@v0.1.0
uv tool install --from git+https://github.com/RakTikoo/blockrandom.git@v0.1.0 blockrandom
```

With Homebrew (macOS/Linux):

```sh
brew tap RakTikoo/tools
brew install RakTikoo/tools/blockrandom
```

With Scoop (Windows):

```powershell
scoop bucket add RakTikoo https://github.com/RakTikoo/scoop-bucket
scoop install blockrandom
```

## Usage

```
blockrandom generate --arms A,B --ratio 1:1 --blocks 4,6,8
                     --n-per-stratum 120
                     [--strata "site=North,South;sex=F,M"]
                     (--seed TEXT | --seed-file FILE)
                     [--out-dir DIR] [--trial-name NAME]
                     [--generated-at ISO-TIMESTAMP]
blockrandom check
```

- `--arms` — arm labels, comma-separated, at least two, all different
  (for example `A,B` or `Drug,Placebo`). Labels are just labels: this
  tool has no opinion about what any arm is.
- `--ratio` — one positive whole number per arm, colon-separated, in
  the same order as `--arms`. Unequal allocation works: `--ratio 2:1`,
  or three arms with `--ratio 2:1:1`. **Required; never guessed.**
- `--blocks` — block sizes, comma-separated. Every block size must be
  a multiple of the ratio sum (a 2:1 trial needs block sizes that are
  multiples of 3), because every completed block must hold the ratio
  exactly; the tool refuses a size that cannot. Give at least two sizes
  for a real trial: with one fixed size, the last allocations in each 
  block become predictable (a single size is accepted with a warning in 
  the summary and audit.log). **Required; never guessed.**
- `--n-per-stratum` (alias `--n`) — how many allocations each stratum's
  list contains. The total list is this × the number of strata.
- `--strata` — stratification factors as `name=level,level` chunks
  separated by semicolons, for example `"site=North,South;sex=F,M"`
  gives 2 × 2 = 4 stratum lists. Omit it for a single unstratified
  list. Each stratum combination gets its own sequence.
- `--seed` / `--seed-file` — the seed, exactly one of the two. The
  file form keeps the seed out of shell history; a trailing newline in
  the file is ignored. Use a long, random seed and keep it with the
  trial statistician. **Required; the tool refuses to invent one.**
- `--out-dir` — where the outputs go (default `blockrandom-out`).
- `--trial-name` — optional; recorded in the audit log and used in the
  methods paragraph.
- `--generated-at` — optional timestamp recorded in the audit log
  (default: the current UTC time). Supply one when you need the audit
  log itself to be byte-for-byte reproducible.

### Outputs

| File | What it is |
|---|---|
| `allocation.csv` | The full list, for the statistician: id, stratum, sequence position, block number, block size drawn, position in block, whether the block is complete, allocation. |
| `sealed.csv` | The sealed list, for enrolment: **only** id, stratum, sequence position and allocation — no block number, block size or position in a block, no seed and no seed hash, so the block structure cannot be inferred from it. |
| `per_stratum/<stratum>.csv` | The full list split into one file per stratum, same columns as `allocation.csv`. |
| `audit.log` | Tool and Python versions, generation timestamp, every design parameter, the number of strata and allocations, the seed's SHA-256 hash (never the seed), the SHA-256 of every other output file, and a note if any final block was truncated. |
| `methods.txt` | A ready-to-paste methods paragraph describing exactly this design, in the style of Schulz & Grimes (Lancet, 2002) and Broglio's JAMA description of permuted blocks and stratification (2018). It also states a single-block-size design's predictability limitation when one applies. |

### Verify your install

```console
$ blockrandom check
blockrandom check -- built-in property check
  design  : arms A,B, ratio 1:1, blocks 4,6, strata site=North,South, 24 allocations per stratum
  total   : 48 allocations (expected 48)
  balance : every completed block holds A and B in exactly equal numbers -- PASS
  repeat  : same seed regenerates the list byte-for-byte -- PASS
  result  : PASS
```

## Method

Permuted-block randomization, stratified (Schulz & Grimes, *Lancet*
series on allocation sequences and concealment, 2002; Broglio,
*Randomization in Clinical Trials: Permuted Blocks and
Stratification*, JAMA, 2018). Within each stratum the sequence is built
block by block: a block size is drawn at random from the declared set,
the block is filled with the arms in exactly the declared ratio, and
the order inside the block is permuted at random. Balance is therefore
exact at the end of every completed block, not just on average, while
the randomly drawn block size keeps the next allocation from being
predictable towards the end of a block.

Each stratum's random stream is seeded independently, from
SHA-256(seed ‖ stratum label): a stratum's sequence depends only on
the seed and its own label, so adding or removing other strata does
not change it, and two strata never share a sequence by construction.

If the requested length for a stratum is not an exact sum of whole
blocks, the final block is truncated to reach it. A truncated block
does **not** hold the ratio exactly; it is flagged
(`block_complete=false` in the full list), named in the audit log, and
mentioned in the methods paragraph — never hidden.

## Reproducibility

**The same seed and the same parameters reproduce `allocation.csv`,
`sealed.csv`, the per-stratum files and `methods.txt` byte-for-byte.**
(`audit.log` also reproduces byte-for-byte if you pin
`--generated-at`; otherwise it differs only in its timestamp line.)
The test suite checks this at the file level, through the real CLI.

How, and the limits:

- All random draws use only `random.Random.random()` (Mersenne
  Twister, integer seeding). `random()` is the one generator method
  CPython explicitly guarantees will keep producing the same sequence
  for the same compatible seed across Python versions; the
  higher-level helpers (`choice`, `shuffle`) carry no such guarantee
  and are deliberately not used.
- That is a guarantee made by the Python documentation, not magic: if
  a future Python ever changed it, old lists would stop reproducing.
  The audit log therefore records the exact Python version used —
  archive it with the list, and re-verify a reproduction (regenerate
  and diff, plus `blockrandom check`) before relying on it under a
  different interpreter.
- The raw seed is never written to any output. The audit log and
  methods paragraph carry only its SHA-256 hash, so anyone holding
  the seed can prove a list is theirs, and anyone holding only the
  list cannot read the seed off it — **unless the seed is short or
  guessable**, in which case the hash can be brute-forced and the
  whole list predicted. Use a long random seed (a seed file with, say,
  32+ random characters) and treat the audit log as confidential for
  a real trial.

## Honest limits

- **A list is not a trial design.** This tool does not judge whether
  randomization is appropriate, whether the ratio or strata are
  sensible, or whether the sample size is adequate. Too many strata
  for the sample size is a real and common design error; the tool
  caps strata at 1,000 combinations, allocations at 100,000 per
  stratum and block sizes at 100,000, but it will happily generate a
  badly designed list exactly as specified. Design review belongs to
  the protocol process.
- **Allocation concealment is a process, not a file format.** The
  sealed list removes the block structure, but concealment in a real
  trial also depends on who holds which file, when allocations are
  revealed, and how enrolment is run. Keep the full list and the audit
  log away from anyone enrolling participants.
- **Permuted blocks are predictable in principle at a block's end**
  if the block size is known or guessed — random block sizes reduce
  this; they do not eliminate it, and a single block size leaves it
  fully in place (the methods paragraph says so when you use one).
- **No blinding, no enrolment, no participant data.** The tool
  generates lists only. It takes no input about any participant and
  produces no medical output of any kind.
- **Correctness is property-based, by necessity.** There is no
  published reference list to diff against; the guarantees are the
  exact properties in the test suite (balance per completed block,
  seed reproducibility, declared block sizes only, per-stratum counts,
  stratum independence, sealed-list contents). If a property matters
  to your trial and is not tested there, do not assume it.

## Tests

```console
$ python3 run_tests.py
```

40 tests (stdlib `unittest`): exact balance in every completed block
for equal, unequal and three-arm ratios across several seeds;
byte-for-byte reproducibility through the CLI (including the audit log
under a pinned timestamp, and seed-file ≡ seed-flag equivalence);
different seeds diverging; block sizes drawn only from the declared
set; per-stratum totals; stratum independence (a stratum's sequence is
unchanged by the presence of other strata); the sealed list's exact
header and the absence of block or seed material in every output; the
methods paragraph's required statements; and adversarial inputs
(missing/both/empty seed sources, ratio–arm mismatch, a block size
that cannot hold the ratio, duplicate arms, zero length, malformed
strata, newline injection into the audit log via the trial name or
timestamp, an enormous block size, and stale per-stratum files left
by an earlier run into the same output directory) — all of which must
fail with clean errors, never tracebacks.

## Use with an AI agent

This repo ships a [SKILL.md](SKILL.md) written to the Agent Skills open
standard. If your coding agent supports skills, point it at this repo
and it can install blockrandom, run it for your trial design, and read
the results for you. The skill works as documented when the repo is
cloned under its real name (`blockrandom`) — the standard matches a
skill to its folder name.

## License

MIT. Free and open source, for science.

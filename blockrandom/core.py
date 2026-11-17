"""Core randomization logic for blockrandom.

Method: permuted-block randomization, stratified -- the method described
by Schulz & Grimes (Lancet series on allocation sequences and
concealment, 2002) and by Broglio in JAMA's "Randomization in Clinical
Trials: Permuted Blocks and Stratification" (2018). Within each stratum, the
allocation sequence is built block by block. Every block has a size drawn
from a user-declared set of block sizes and contains the trial arms in
exactly the declared allocation ratio; the order inside the block is
permuted at random. Drawing the block size at random (instead of fixing
it) is what stops the next allocation from becoming predictable towards
the end of a block -- a known weakness of fixed-size permuted blocks.

There is no published formula to match here, so correctness is
property-based, and the properties are exact (see tests/):

* every *completed* block contains precisely the ratio counts;
* the same seed + the same parameters reproduce the allocation list and
  the sealed list byte-for-byte (see "Reproducibility" below);
* different seeds produce different lists;
* every block size used comes from the declared set;
* each stratum gets exactly the requested number of allocations;
* strata are independent: a stratum's sequence depends only on the seed
  and on that stratum's own label, not on the other strata present.

Reproducibility
---------------
A stratum's random stream is seeded with an integer derived as
SHA-256(seed || NUL || stratum label), fed to ``random.Random`` (the
Mersenne Twister, int seeding, seeder version 2). All random draws in
this module use ONLY ``Random.random()`` -- block-size choice and the
permutation both -- because ``random()`` is the one generator method
CPython explicitly guarantees will keep producing the same sequence for
the same compatible seed across versions. Higher-level helpers such as
``Random.choice`` and ``Random.shuffle`` carry no such guarantee, so
they are deliberately not used. The exact Python version used is still
recorded in the audit log: archive it with the list, and re-check a list
by re-running `blockrandom check` and a regeneration diff before relying
on a reproduction under a different interpreter.

The raw seed is NEVER written to any output file. Outputs carry only its
SHA-256 hash (in the audit log and the methods paragraph), so a list can
be verified against a seed held by the trial statistician without the
seed travelling with the list. Note the limit this implies: the hash of
a short, guessable seed can be brute-forced -- use a long random seed
for a real trial and treat the audit log as confidential (see README).
"""

from __future__ import annotations

import csv
import hashlib
import itertools
import random
import re
from dataclasses import dataclass, field

MAX_PER_STRATUM = 100_000
MAX_STRATA = 1_000

# Characters that would corrupt the CSV / strata-label formats.
_FORBIDDEN = set(',;|=\n\r"')
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._'()/-]*$")


class BlockRandomError(Exception):
    """A user-facing error: print the message, exit non-zero, no traceback."""


# ---------------------------------------------------------------------------
# Parsing / validation of the declared design
# ---------------------------------------------------------------------------

def _check_label(text, what):
    if not text:
        raise BlockRandomError(f"{what} must not be empty.")
    bad = _FORBIDDEN.intersection(text)
    if bad:
        raise BlockRandomError(
            f"{what} {text!r} contains a character that is not allowed "
            f"({''.join(sorted(bad))!r}); commas, semicolons, '|', '=' and "
            "quotes are reserved by the output formats.")
    if not _LABEL_RE.match(text):
        raise BlockRandomError(
            f"{what} {text!r} is not a plain label: start with a letter or "
            "digit and use only letters, digits, spaces and ._'()/- .")


def parse_arms(text):
    """Parse "A,B" into ["A", "B"], validating the labels."""
    if text is None or str(text).strip() == "":
        raise BlockRandomError(
            "--arms is required: give the arm labels separated by commas, "
            'for example --arms A,B or --arms Drug,Placebo.')
    arms = [a.strip() for a in str(text).split(",")]
    for arm in arms:
        _check_label(arm, "arm label")
    if len(arms) < 2:
        raise BlockRandomError(
            "at least two arms are needed for a randomization list; "
            f"got only {arms!r}.")
    if len(set(arms)) != len(arms):
        raise BlockRandomError(f"arm labels must all be different: {arms!r}.")
    return arms


def parse_ratio(text, n_arms):
    """Parse "2:1" into [2, 1]; its length must match the arms."""
    if text is None or str(text).strip() == "":
        raise BlockRandomError(
            "--ratio is required: give one positive whole number per arm, "
            'separated by colons, for example --ratio 1:1 or --ratio 2:1.')
    parts = [p.strip() for p in str(text).split(":")]
    ratio = []
    for part in parts:
        try:
            value = int(part)
        except ValueError:
            raise BlockRandomError(
                f"--ratio {text!r} is malformed: {part!r} is not a whole "
                "number. Use colon-separated whole numbers, e.g. 2:1.")
        if value <= 0:
            raise BlockRandomError(
                f"--ratio {text!r} is malformed: every part must be a "
                "positive whole number.")
        ratio.append(value)
    if len(ratio) != n_arms:
        raise BlockRandomError(
            f"--ratio has {len(ratio)} part(s) but there are {n_arms} "
            "arms; the ratio needs exactly one number per arm, in the "
            "same order as --arms.")
    return ratio


def parse_blocks(text, ratio):
    """Parse "4,6,8" into [4, 6, 8]; each must fit the ratio exactly."""
    if text is None or str(text).strip() == "":
        raise BlockRandomError(
            "--blocks is required: give the block sizes separated by "
            'commas, for example --blocks 4,6,8. Use at least two sizes '
            "for a real trial so the next allocation stays unpredictable.")
    blocks = []
    for part in [p.strip() for p in str(text).split(",")]:
        try:
            value = int(part)
        except ValueError:
            raise BlockRandomError(
                f"--blocks {text!r} is malformed: {part!r} is not a whole "
                "number.")
        if value <= 0:
            raise BlockRandomError(
                f"--blocks {text!r} is malformed: block sizes must be "
                "positive whole numbers.")
        if value > MAX_PER_STRATUM:
            raise BlockRandomError(
                f"block size {value} exceeds the limit of "
                f"{MAX_PER_STRATUM}: a block is built in memory before "
                "any truncation, so an enormous block size would hang "
                "or exhaust memory while adding nothing -- a block "
                "larger than the longest list can never be completed.")
        blocks.append(value)
    ratio_sum = sum(ratio)
    for size in blocks:
        if size % ratio_sum != 0:
            raise BlockRandomError(
                f"block size {size} cannot hold the ratio "
                f"{':'.join(str(r) for r in ratio)} exactly: a block must "
                f"be a multiple of the ratio sum ({ratio_sum}). Use block "
                "sizes that are multiples of "
                f"{ratio_sum}, or change the ratio.")
    # De-duplicate, keeping the declared order.
    seen = []
    for size in blocks:
        if size not in seen:
            seen.append(size)
    return seen


def parse_strata(text):
    """Parse a strata specification into (factors, combinations).

    Format: "site=North,South;sex=F,M" -- semicolons separate factors,
    each factor is name=level,level,... With no specification there is a
    single stratum labelled "overall".

    Returns (factors, labels) where factors is a list of
    (name, [levels]) and labels is the ordered list of stratum labels,
    one per combination, in the order the combinations are declared
    (cartesian product, last factor varying fastest).
    """
    if text is None or str(text).strip() == "":
        return [], ["overall"]
    factors = []
    names = set()
    for chunk in str(text).split(";"):
        chunk = chunk.strip()
        if not chunk:
            raise BlockRandomError(
                f"--strata {text!r} is malformed: empty factor between "
                "semicolons.")
        if "=" not in chunk:
            raise BlockRandomError(
                f"--strata factor {chunk!r} is malformed: expected "
                'name=level,level (for example site=North,South).')
        name, _, levels_text = chunk.partition("=")
        name = name.strip()
        _check_label(name, "strata factor name")
        if name in names:
            raise BlockRandomError(
                f"--strata names the factor {name!r} twice.")
        names.add(name)
        levels = [lv.strip() for lv in levels_text.split(",")]
        for level in levels:
            _check_label(level, f"level of strata factor {name!r}")
        if len(set(levels)) != len(levels):
            raise BlockRandomError(
                f"--strata factor {name!r} repeats a level: {levels!r}.")
        factors.append((name, levels))
    labels = []
    for combo in itertools.product(*[levels for _, levels in factors]):
        labels.append(";".join(
            f"{name}={level}"
            for (name, _), level in zip(factors, combo)))
    if len(labels) > MAX_STRATA:
        raise BlockRandomError(
            f"--strata gives {len(labels)} stratum combinations; the "
            f"limit is {MAX_STRATA}. Fewer, larger strata are usually "
            "the better design anyway.")
    return factors, labels


def validate_n(n):
    if n is None:
        raise BlockRandomError(
            "--n-per-stratum is required: how many allocations each "
            "stratum's list should contain.")
    if n <= 0:
        raise BlockRandomError(
            f"--n-per-stratum must be a positive whole number; got {n}.")
    if n > MAX_PER_STRATUM:
        raise BlockRandomError(
            f"--n-per-stratum {n} exceeds the limit of "
            f"{MAX_PER_STRATUM} per stratum. If a trial really needs a "
            "longer list, generate it in parts with different seeds and "
            "record each part in the audit trail.")
    return n


def validate_free_text(text, what):
    """Reject control characters in free text written into output files.

    The trial name and the generation timestamp are written as single
    lines of the audit log (and the trial name into the methods
    paragraph). A newline in either would let the caller forge extra
    audit-log lines (for example a fake ``seed_sha256:`` entry), so
    control characters are refused outright.
    """
    if text is None:
        return None
    for ch in str(text):
        if ord(ch) < 32 or ord(ch) == 127:
            raise BlockRandomError(
                f"{what} must be a single line of plain text; it "
                "contains a control character (newline or similar), "
                "which would corrupt the audit log's line format.")
    return str(text)


def validate_seed(seed):
    if seed is None or str(seed) == "":
        raise BlockRandomError(
            "a seed is required, and blockrandom refuses to invent one: "
            "an unseeded list cannot be reproduced, and reproducibility "
            "is the point (ICH E9). Give --seed TEXT or --seed-file FILE "
            "with a long, random seed that the trial statistician keeps.")
    return str(seed)


def seed_sha256(seed):
    """SHA-256 of the seed text (UTF-8) -- the only seed trace in outputs."""
    return hashlib.sha256(str(seed).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

@dataclass
class Allocation:
    allocation_id: str
    stratum_index: int          # 1-based, in declared combination order
    stratum: str
    sequence_position: int      # 1-based, within the stratum
    block_number: int           # 1-based, within the stratum (full list only)
    block_size: int             # size drawn for this block (full list only)
    position_in_block: int      # 1-based (full list only)
    block_complete: bool        # False only for a truncated final block
    allocation: str


@dataclass
class Plan:
    arms: list
    ratio: list
    block_sizes: list
    n_per_stratum: int
    factors: list = field(default_factory=list)
    strata_labels: list = field(default_factory=list)
    rows: list = field(default_factory=list)   # list[Allocation]

    @property
    def total(self):
        return len(self.rows)


def _stratum_rng(seed, stratum_label):
    """A random.Random seeded only by the seed and this stratum's label."""
    digest = hashlib.sha256(
        (str(seed) + "\x00" + stratum_label).encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest, "big"))


def _draw_index(rng, count):
    """An index in [0, count) drawn using only rng.random()."""
    return int(rng.random() * count)


def _permuted_block(rng, arms, counts):
    """One block: the arms repeated per `counts`, in a random order.

    The permutation assigns each item a rng.random() key and sorts by it
    (original position breaks ties), so it uses only the
    reproducibility-guaranteed random() method.
    """
    items = []
    for arm, count in zip(arms, counts):
        items.extend([arm] * count)
    keyed = [(rng.random(), i, item) for i, item in enumerate(items)]
    keyed.sort(key=lambda entry: (entry[0], entry[1]))
    return [item for _, _, item in keyed]


def generate_stratum(seed, stratum_index, stratum_label, arms, ratio,
                     block_sizes, n):
    """Generate exactly `n` allocations for one stratum."""
    rng = _stratum_rng(seed, stratum_label)
    ratio_sum = sum(ratio)
    rows = []
    position = 0
    block_number = 0
    while position < n:
        block_number += 1
        block_size = block_sizes[_draw_index(rng, len(block_sizes))]
        multiplier = block_size // ratio_sum
        counts = [r * multiplier for r in ratio]
        block = _permuted_block(rng, arms, counts)
        take = min(block_size, n - position)
        complete = take == block_size
        for offset in range(take):
            position += 1
            rows.append(Allocation(
                allocation_id=f"{stratum_index:03d}-{position:03d}",
                stratum_index=stratum_index,
                stratum=stratum_label,
                sequence_position=position,
                block_number=block_number,
                block_size=block_size,
                position_in_block=offset + 1,
                block_complete=complete,
                allocation=block[offset],
            ))
    return rows


def generate_plan(seed, arms, ratio, block_sizes, n_per_stratum,
                  factors, strata_labels):
    """Generate the full plan: every stratum, in declared order."""
    validate_seed(seed)
    validate_n(n_per_stratum)
    rows = []
    for index, label in enumerate(strata_labels, start=1):
        rows.extend(generate_stratum(seed, index, label, arms, ratio,
                                     block_sizes, n_per_stratum))
    return Plan(arms=arms, ratio=ratio, block_sizes=block_sizes,
                n_per_stratum=n_per_stratum, factors=factors,
                strata_labels=strata_labels, rows=rows)


# ---------------------------------------------------------------------------
# Rendering: CSV files, audit log, methods paragraph
# ---------------------------------------------------------------------------

FULL_HEADER = ["allocation_id", "stratum", "sequence_position",
               "block_number", "block_size", "position_in_block",
               "block_complete", "allocation"]
SEALED_HEADER = ["allocation_id", "stratum", "sequence_position",
                 "allocation"]


def _write_csv(path, header, row_dicts):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header,
                                lineterminator="\n")
        writer.writeheader()
        for row in row_dicts:
            writer.writerow({key: row[key] for key in header})


def full_row_dicts(plan):
    return [{
        "allocation_id": r.allocation_id,
        "stratum": r.stratum,
        "sequence_position": r.sequence_position,
        "block_number": r.block_number,
        "block_size": r.block_size,
        "position_in_block": r.position_in_block,
        "block_complete": "true" if r.block_complete else "false",
        "allocation": r.allocation,
    } for r in plan.rows]


def sealed_row_dicts(plan):
    """The sealed list: identity and allocation, and NOTHING else.

    No block number, no block size, no position in a block, no seed and
    no seed hash -- nothing from which the block structure (and so the
    allocations still to come in the current block) could be inferred.
    """
    return [{
        "allocation_id": r.allocation_id,
        "stratum": r.stratum,
        "sequence_position": r.sequence_position,
        "allocation": r.allocation,
    } for r in plan.rows]


def stratum_slug(index, label):
    slug = re.sub(r"[^A-Za-z0-9]+", "-", label).strip("-").lower()
    return f"{index:03d}-{slug}" if slug else f"{index:03d}"


def render_allocation_csv(plan):
    import io
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=FULL_HEADER,
                            lineterminator="\n")
    writer.writeheader()
    for row in full_row_dicts(plan):
        writer.writerow(row)
    return buffer.getvalue()


def render_sealed_csv(plan):
    import io
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=SEALED_HEADER,
                            lineterminator="\n")
    writer.writeheader()
    for row in sealed_row_dicts(plan):
        writer.writerow(row)
    return buffer.getvalue()


def _ratio_text(ratio):
    return ":".join(str(r) for r in ratio)


def _blocks_text(block_sizes):
    return ", ".join(str(b) for b in block_sizes)


def _strata_text(plan):
    if not plan.factors:
        return "none (a single list)"
    return "; ".join(
        f"{name} ({', '.join(levels)})" for name, levels in plan.factors)


def build_methods_paragraph(plan, seed_hash, trial_name=None):
    """A ready-to-paste methods paragraph for a protocol or paper."""
    arms_text = ", ".join(plan.arms)
    title = f" for the trial \"{trial_name}\"" if trial_name else ""
    if plan.factors:
        strata_sentence = (
            f"Randomization was stratified by {_strata_text(plan)}, "
            f"giving {len(plan.strata_labels)} stratum list(s) of "
            f"{plan.n_per_stratum} allocations each, and a separate "
            "allocation sequence was generated for each stratum.")
    else:
        strata_sentence = (
            "Randomization was not stratified; a single allocation "
            f"sequence of {plan.n_per_stratum} allocations was generated.")
    if len(plan.block_sizes) > 1:
        block_sentence = (
            f"Block sizes of {_blocks_text(plan.block_sizes)} were drawn "
            "at random for each block, so that the block size -- and "
            "therefore the allocations remaining in a block -- could not "
            "be predicted from the allocations already revealed.")
    else:
        block_sentence = (
            f"A fixed block size of {plan.block_sizes[0]} was used; "
            "with a single block size the allocations remaining in a "
            "block become increasingly predictable towards the end of "
            "each block, which is a known limitation of this design.")
    truncated = [r.stratum for r in plan.rows if not r.block_complete]
    truncated_sentence = ""
    if truncated:
        names = ", ".join(sorted(set(truncated)))
        truncated_sentence = (
            " Where the requested list length was not an exact sum of "
            f"whole blocks, the final block was truncated (strata: "
            f"{names}); the truncated block does not hold the allocation "
            "ratio exactly, and this is recorded in the allocation list.")
    try:
        from . import __version__ as _version
    except Exception:  # pragma: no cover - core used outside the package
        _version = "0.1.0"
    return (
        f"Participants were allocated between the arms ({arms_text}) "
        f"in a {_ratio_text(plan.ratio)} ratio using permuted-block "
        f"randomization{title}. {strata_sentence} Within each block the "
        "arms appeared in exactly the allocation ratio, in a randomly "
        f"permuted order. {block_sentence} The allocation list was "
        f"generated before enrolment began with blockrandom {_version} "
        "(open-source, MIT licence), using a seed held by the trial "
        "statistician; only the SHA-256 hash of the seed is recorded "
        f"with the list ({seed_hash}), so the list can be regenerated "
        "and verified from the seed without the seed travelling with "
        "it. The list used for enrolment (the sealed list) contains "
        "only the allocation identifier, stratum, sequence position and "
        "allocation, so the block structure cannot be inferred from "
        f"it.{truncated_sentence}\n"
    )


def build_audit_log(plan, seed_hash, seed_source, generated_at,
                    python_version, tool_version, file_hashes,
                    trial_name=None):
    """The audit log text. `file_hashes` maps output name -> sha256."""
    lines = [
        "blockrandom audit log",
        f"tool_version: {tool_version}",
        f"generated_at: {generated_at}",
        f"python_version: {python_version}",
        f"trial_name: {trial_name if trial_name else '(not given)'}",
        f"arms: {', '.join(plan.arms)}",
        f"ratio: {_ratio_text(plan.ratio)}",
        f"block_sizes: {_blocks_text(plan.block_sizes)}",
        f"strata: {_strata_text(plan)}",
        f"stratum_count: {len(plan.strata_labels)}",
        f"n_per_stratum: {plan.n_per_stratum}",
        f"total_allocations: {plan.total}",
        f"seed_source: {seed_source}",
        f"seed_sha256: {seed_hash}",
        "seed_value_recorded: no (only the SHA-256 hash above)",
        "rng: random.Random (Mersenne Twister), per-stratum integer seed "
        "derived as SHA-256(seed || NUL || stratum label); all draws use "
        "Random.random() only",
        "outputs_sha256:",
    ]
    for name in sorted(file_hashes):
        lines.append(f"  {name}: {file_hashes[name]}")
    truncated = sorted({r.stratum for r in plan.rows
                        if not r.block_complete})
    if truncated:
        lines.append(
            "truncated_final_blocks: " + ", ".join(truncated) +
            " (final block cut short to reach the requested length; "
            "that block does not hold the ratio exactly)")
    else:
        lines.append("truncated_final_blocks: none")
    return "\n".join(lines) + "\n"


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

# Contributing

Thanks for looking. blockrandom is a small, single-purpose tool; these
house rules keep changes easy to review.

> **Research / educational tool. Not a medical device.** Lists only:
> no diagnosis, staging, or dose or treatment advice, and no judgement
> about whether a design is appropriate for a trial.

## Run the tests

```console
$ python3 run_tests.py
```

All tests must pass before a change is considered. Add tests in `tests/`
for any new behaviour. Correctness here is property-based — balance per
completed block, seed reproducibility, sealed-list contents — so a new
behaviour needs its property stated and tested, not just an example.

## House rules

- Keep the tool single-purpose and dependency-free (standard library
  only).
- The seed is never invented and never written to any output — only
  its SHA-256 hash. A change that weakens either rule will not be
  accepted; they are the product.
- Reproducibility is byte-for-byte: random draws use only
  `random.Random.random()`, the one generator method CPython
  guarantees stable across versions. Do not switch to `choice`,
  `shuffle` or other helpers.
- Limits stay visible: a truncated final block is flagged, named in
  the audit log and mentioned in the methods paragraph — never hidden.
- The README's Honest limits section is a promise. If a change alters
  a documented limit or behaviour, update the README in the same pull
  request — and SKILL.md too if the CLI, its flags or its exit codes
  changed.
- Plain words in docs and messages. No marketing language.

## Claiming an issue

Comment on the issue saying you are taking it, then open a pull request
that mentions the issue number.

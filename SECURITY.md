# Security policy

## Reporting a problem

Please do not open a public issue for a security problem.

Report it privately through GitHub: open this repository's **Security**
tab and choose **Report a vulnerability**. If that form is not
available, open a regular issue that says only that you have a security
report and asks for a private contact route — do not include any
details in public.

Never include a real trial's seed, allocation list or audit log in a
report. A synthetic design that reproduces the problem is enough.

## Scope

blockrandom runs locally and takes no participant data. The realistic
concerns are the seed handling (the seed must never appear in any
output, and its hash must not leak it for a long random seed) and
crashes or wrong results on crafted arguments; those reports are
welcome through the same route.

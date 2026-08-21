# Live-spec gaps and deliberate implementation gates

This implementation does **not** silently resolve unfinished or inconsistent
statements in `ChatGPT_spec.md`.

## Legacy unused-pad example

One example still says `unused_L18`. The physical naming convention is N/E/S/W,
so generated unused-pad instances are derived mechanically from the actual slot,
e.g. `unused_W18`.

## Existing repository workshop template

`Workshop_CASS/padring/workshop_padring.cfg` uses legacy instance names such as
`ana1`, `config20`, etc. It therefore is not accepted as a production immutable-
slot template by default. The converter refuses to guess which legacy instance
means `N01`, `W13`, etc.

## Still not finalized by the live spec

The tool raises `NotFinalizedError` rather than inventing these items:

1. Exact N01..N22 and S01..S22 physical numbering direction.
2. Legal transforms for all final block locations.
3. Secondary-ESD cell layout, connectivity, and placement policy.
4. Whether participant `power`/`ground` pins remain supported long-term.
5. 88-pad to 64-package bond maps.

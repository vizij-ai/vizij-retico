# Fonts

`Questrial-Regular.ttf` — the brand-approved free font for these figures (the
commercial Gilroy/Univia faces are not redistributable). Questrial is published
on Google Fonts under the SIL Open Font License 1.1.

Vendored deliberately. The Makefile previously resolved it from a path under
`~/Library/Application Support/…`, which no co-author has, and which `make`
truncated at the space anyway — `$(firstword $(wildcard …))` splits on spaces, so
the font flag arrived as `--font-regular "/Users/…/Library/Application"`.

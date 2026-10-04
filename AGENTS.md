# Coding preferences

All functions and methods you create or modify must have explicit parameter and
return type annotations (except implicit self/cls) and a descriptive docstring
explaining their purpose. Apply this to drafts and examples too. Prefer named,
typed, documented functions over nontrivial lambdas.

# Testing requirements

Before writing or modifying any tests, read `docs/developers/testing/index.md`
and the relevant test-case guide in `docs/developers/testing/`. Inspect an
existing test that follows that documented pattern.

Use the established Bloomerp base test case and declarative scenario pattern
whenever they support the behavior being tested. Do not default to ad-hoc test
methods or copy an older test without checking the documentation first.




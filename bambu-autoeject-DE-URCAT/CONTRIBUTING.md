# Contributing

Thanks for helping. The most useful things right now:

1. **Printer test reports.** Run the files in `examples/` on your printer and tell us what happened, using the "Printer test report" issue form. Failures are just as useful as successes.
2. **Support for more printers.** Printer values live in `PRINTERS` in `bambu_autoeject/core.py`. Take them from the stock Bambu Studio profile (`tools/flatten_profile.py` resolves inherited profiles), add a sliced example under `examples/<printer>/` and a test.
3. **Bug fixes and docs.**

## Development

```bash
git clone https://github.com/bullsrobo-boop/bambu-autoeject
cd bambu-autoeject
python3 -m unittest -v
```

No dependencies outside the standard library, and it should stay that way.

If you change the generated G-code on purpose, regenerate the examples (see `tests/test_autoeject.py`, `test_examples_are_up_to_date`) and say in the pull request what changes on the printer.

## Rules for G-code changes

- Never move the nozzle lower than `push_z` outside `--clean-front`.
- Keep the lowered motor currents during the push.
- Every new printer starts as `experimental=True` until someone reports a successful run.

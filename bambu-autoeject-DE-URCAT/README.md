# bambu-autoeject

[![test](https://github.com/bullsrobo-boop/bambu-autoeject/actions/workflows/test.yml/badge.svg)](https://github.com/bullsrobo-boop/bambu-autoeject/actions/workflows/test.yml)

Print a queue of parts on a **Bambu Lab A1** without standing next to it. No extra hardware, no firmware changes.

The tool joins several sliced plates into one job. After each print the printer:

1. turns off the bed and nozzle and waits for the bed to cool (12 minutes by default, fan on);
2. lowers the nozzle to 1 mm behind the parts and pushes them forward, in lanes 6 mm apart, until they fall off the front of the bed;
3. re-homes and starts the next print.

> **Status: alpha, not yet tested on a real printer.** The G-code is generated and covered by tests, but the eject moves have not been run on hardware. Do the dry run first and stay next to the printer for the first real runs. Test reports are the most useful contribution right now: [open a printer test report](../../issues/new?template=printer-test.yml).

## Supported printers

| Printer | Status |
| --- | --- |
| Bambu Lab A1 | main target, values from the stock profile |
| Bambu Lab A1 mini | experimental, values from the stock profile, `--clean-front` not available |
| P1, X1, H2D | not supported (closed front or no bed slinger) |

## Install

```bash
pip install bambu-autoeject
```

Python 3.8 or newer, no other dependencies. Without installing you can also run `python3 autoeject.py ...` from a clone of this repository.

## Usage

### Join several plates

1. Slice each model in Bambu Studio and export it with **File > Export > Export plate sliced file** (`.gcode.3mf`, one plate per file).
2. Run:

```bash
bambu-autoeject queue.gcode.3mf bracket.gcode.3mf:3 keychain.gcode.3mf:2
```

`:3` means three copies in a row. Open `queue.gcode.3mf` in Bambu Studio and send it to the printer like any sliced file.

### From inside Bambu Studio (experimental)

Bambu Studio can run a post-processing script on every slice. In the process settings (Advanced mode), **Others > Post-processing Scripts**, add:

```
bambu-autoeject --in-place --copies 3;
```

Bambu Studio adds the G-code path at the end. Every slice is then printed 3 times with an eject after each. Use the full path to `bambu-autoeject` if Bambu Studio cannot find it (`which bambu-autoeject` on macOS and Linux, `where bambu-autoeject` on Windows). This mode has only been tested on exported files so far, not on jobs sent from Bambu Studio over the network.

### Options

| Option | Default | What it does |
| --- | --- | --- |
| `--cool-min N` | 12 | minutes of cooling before the push |
| `--push-z MM` | 1.0 | nozzle height while pushing (not below 0.5) |
| `--lane MM` | 6 | spacing between push lanes (use 4 for very narrow parts) |
| `--behind MM` | 8 | how far behind the parts the nozzle comes down |
| `--keep-last` | off | leave the last print on the bed |
| `--dry-run` | off | do all the moves above the part, never touching it |
| `--clean-front` | off | A1 only: also push off the front calibration line (nozzle at 0.3 mm, may scratch) |
| `--copies N` | 1 | with `--in-place`: repeat the plate N times |

Full list: `bambu-autoeject --help`.

## Safety

- The nozzle never goes below the `--push-z` height (1 mm by default) unless you use `--clean-front`.
- Motor current is lowered during the push, so a stuck part makes the motor skip instead of forcing it. The printer re-homes afterwards.
- The start G-code draws a calibration line on the front edge. The nozzle cannot reach it safely, so the first line stays on the bed and later prints skip drawing it again.
- Plates sliced for different printers cannot be mixed in one job.

## What works and what does not

- Best on the **textured PEI plate** with PLA or PETG: parts release by themselves once the bed is cold.
- Very small parts (base under about 15 x 15 mm) or large flat bases may not release.
- Tall, thin parts can tip over: print them lying down or with a brim.
- Leave 8 mm free between the parts and the back edge of the bed.
- Put a box or a ramp in front of the printer to catch the parts.

## First test

`examples/a1/` contains a 20 mm cube sliced for the A1 (textured PEI plate, Bambu PLA Basic):

1. `1_dry_run.gcode.3mf`: prints the cube, waits 12 minutes, then does all the eject moves **above** it. Check that the path looks right.
2. `2_eject_one_cube.gcode.3mf`: same cube, this time pushed off. Keep a hand near the stop button.
3. `3_two_cubes.gcode.3mf`: two cubes in a row with an eject after each, the full loop.

`examples/a1-mini/` has the dry run and the two-cube job for the A1 mini.

If the printer does not wait the 12 minutes in step 1, the firmware is ignoring `M400 S60`; please report it.

## How it works

Bambu Studio writes the whole job as plain G-code inside the `.gcode.3mf` archive. The tool reads the first layer to find where the parts are, inserts an eject block before the end sequence turns off the motors, removes the duplicate header and calibration line from the following jobs and writes the joined G-code back into a copy of the first archive, so thumbnails and settings stay intact.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Run the tests with `python3 -m unittest`.

## License

MIT, see [LICENSE](LICENSE). Use at your own risk: this changes how your printer moves.

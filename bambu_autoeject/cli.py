"""Command line interface."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .core import AutoEjectError, Options, join_files, process_in_place

USAGE_EXAMPLES = """\
examples:
  bambu-autoeject queue.gcode.3mf bracket.gcode.3mf:3 keychain.gcode.3mf:2
  bambu-autoeject test.gcode.3mf cube.gcode.3mf --dry-run
  bambu-autoeject --in-place --copies 3 plate.gcode     (Bambu Studio post-processing)
"""


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="bambu-autoeject",
        description="Chain prints on a Bambu Lab A1 and push each finished part off the bed.",
        epilog=USAGE_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("files", nargs="+", metavar="FILE",
                    help="OUTPUT.gcode.3mf INPUT.gcode.3mf[:count] ..., or one .gcode file with --in-place")
    ap.add_argument("--in-place", action="store_true",
                    help="rewrite a single plain .gcode file (for the slicer's post-processing scripts)")
    ap.add_argument("--copies", type=int, default=1, help="with --in-place: print the plate N times (1)")
    ap.add_argument("--cool-min", type=int, default=12, help="minutes of cooling before ejecting (12)")
    ap.add_argument("--cool-temp", type=int, default=28, help="target temperature for --wait-bed (28)")
    ap.add_argument("--wait-bed", action="store_true", help="also add M190 (may hang if the room is warm)")
    ap.add_argument("--push-z", type=float, default=1.0, help="nozzle height while pushing, mm (1.0)")
    ap.add_argument("--push-speed", type=int, default=25, help="push speed, mm/s (25)")
    ap.add_argument("--lane", type=float, default=6.0, help="spacing between push lanes, mm (6)")
    ap.add_argument("--behind", type=float, default=8.0, help="how far behind the parts the nozzle drops, mm (8)")
    ap.add_argument("--clean-front", action="store_true",
                    help="A1 only: also push off the front calibration lines (nozzle very low, may scratch)")
    ap.add_argument("--front-z", type=float, default=0.3, help="nozzle height for --clean-front, mm (0.3)")
    ap.add_argument("--keep-cali-line", action="store_true",
                    help="keep the front calibration line on prints after the first")
    ap.add_argument("--keep-last", action="store_true", help="leave the last print on the bed")
    ap.add_argument("--dry-run", action="store_true", help="do the moves above the parts without touching them")
    ap.add_argument("--force", action="store_true", help="accept other printers as if they were an A1 (at your own risk)")
    ap.add_argument("--version", action="version", version="%(prog)s " + __version__)
    return ap


def check_options(args) -> Options:
    if args.push_z < 0.5 and not args.dry_run:
        raise AutoEjectError("--push-z below 0.5 mm risks the plate")
    if args.lane <= 0 or args.behind <= 0 or args.push_speed <= 0 or args.cool_min < 0:
        raise AutoEjectError("--lane, --behind and --push-speed must be positive, --cool-min not negative")
    return Options(
        cool_min=args.cool_min, cool_temp=args.cool_temp, wait_bed=args.wait_bed,
        push_z=args.push_z, push_speed=args.push_speed, lane=args.lane, behind=args.behind,
        clean_front=args.clean_front, front_z=args.front_z, keep_cali_line=args.keep_cali_line,
        keep_last=args.keep_last, dry_run=args.dry_run, force=args.force,
    )


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        opts = check_options(args)
        if args.in_place:
            if len(args.files) != 1:
                raise AutoEjectError("--in-place takes exactly one .gcode file")
            count, printer = process_in_place(args.files[0], args.copies, opts, log=print)
            target = args.files[0]
        else:
            if len(args.files) < 2:
                raise AutoEjectError("give the output file and at least one input file")
            if args.copies != 1:
                raise AutoEjectError("--copies is for --in-place; use file.gcode.3mf:N instead")
            count, printer = join_files(args.files[0], args.files[1:], opts, log=print)
            target = args.files[0]
    except (AutoEjectError, OSError, ValueError) as e:
        print("bambu-autoeject: error: %s" % e, file=sys.stderr)
        sys.exit(1)
    note = " (support for this printer is experimental)" if printer.experimental else ""
    print("wrote %s: %d prints, %s%s" % (target, count,
                                          "NO contact (dry-run)" if args.dry_run else "with eject", note))
    return 0


if __name__ == "__main__":
    main()

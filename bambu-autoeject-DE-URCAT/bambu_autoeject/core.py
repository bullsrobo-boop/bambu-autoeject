"""G-code handling: find the parts, build the eject block, join the jobs."""

from __future__ import annotations

import hashlib
import os
import re
import zipfile
from typing import List, NamedTuple, Optional, Tuple


class AutoEjectError(Exception):
    """Input the script cannot handle safely."""


class Printer(NamedTuple):
    model: str
    model_id: str
    bed: Tuple[float, float]
    max_z: float
    currents: str          # default motor currents from the stock start G-code
    eject_currents: str    # lower currents while pushing
    park: Tuple[float, float]
    front_line_x: Optional[Tuple[float, float]]  # calibration line, None if --clean-front is not supported
    experimental: bool


PRINTERS = {
    "Bambu Lab A1": Printer(
        model="Bambu Lab A1",
        model_id="N2S",
        bed=(256.0, 256.0),
        max_z=256.0,
        currents="M17 X0.65 Y1.2 Z0.6",
        eject_currents="M17 X0.5 Y0.7",
        park=(-48.0, 180.0),
        front_line_x=(104.0, 160.0),
        experimental=False,
    ),
    "Bambu Lab A1 mini": Printer(
        model="Bambu Lab A1 mini",
        model_id="N1",
        bed=(180.0, 180.0),
        max_z=180.0,
        currents="M17 X0.7 Y0.9 Z0.5",
        eject_currents="M17 X0.55 Y0.5",
        park=(-13.0, 180.0),
        front_line_x=None,
        experimental=True,
    ),
}

Y_FRONT = -0.5          # front edge, same as the A1 start G-code
FRONT_LINE_FROM_Y = 8.0
CALI_START = ";===== extrude cali test"
CALI_END = ";========turn off light"
EXEC_START = "; EXECUTABLE_BLOCK_START"


class Options(NamedTuple):
    cool_min: int = 12
    cool_temp: int = 28
    wait_bed: bool = False
    push_z: float = 1.0
    push_speed: int = 25
    lane: float = 6.0
    behind: float = 8.0
    clean_front: bool = False
    front_z: float = 0.3
    keep_cali_line: bool = False
    keep_last: bool = False
    dry_run: bool = False
    force: bool = False


def config_value(gcode: str, key: str) -> Optional[str]:
    m = re.search(r"^; %s = (.*)$" % re.escape(key), gcode, re.M)
    return m.group(1).strip() if m else None


def detect_printer(gcode: str, force: bool = False) -> Printer:
    model = config_value(gcode, "printer_model")
    if model in PRINTERS:
        return PRINTERS[model]
    if force:
        return PRINTERS["Bambu Lab A1"]
    raise AutoEjectError("sliced for '%s'; supported: %s (use --force at your own risk)"
                         % (model, ", ".join(PRINTERS)))


def first_layer_bbox(gcode: str) -> Tuple[float, float, float, float]:
    """Area printed on the first layer: (xmin, ymin, xmax, ymax)."""
    start = gcode.find("; MACHINE_START_GCODE_END")
    if start < 0:
        raise AutoEjectError("not a Bambu Studio G-code (no MACHINE_START_GCODE_END)")
    layers = [m.start() for m in re.finditer(r"^; CHANGE_LAYER", gcode[start:], re.M)]
    if len(layers) < 2:
        raise AutoEjectError("cannot find layers in the G-code")
    body = gcode[start + layers[0]: start + layers[1]]
    x = y = None
    xs, ys = [], []
    for line in body.splitlines():
        if not line.startswith(("G1 ", "G0 ", "G2 ", "G3 ")):
            continue
        mx = re.search(r"X(-?[\d.]+)", line)
        my = re.search(r"Y(-?[\d.]+)", line)
        me = re.search(r"E(-?[\d.]+)", line)
        if mx:
            x = float(mx.group(1))
        if my:
            y = float(my.group(1))
        if me and float(me.group(1)) > 0 and x is not None and y is not None:
            xs.append(x)
            ys.append(y)
    if not xs:
        raise AutoEjectError("first layer has no extrusion")
    return min(xs), min(ys), max(xs), max(ys)


def max_height(gcode: str) -> float:
    m = re.search(r"^; max_z_height: ([\d.]+)", gcode, re.M)
    return float(m.group(1)) if m else 100.0


def eject_block(printer: Printer, bbox, height: float, opts: Options) -> str:
    xmin, ymin, xmax, ymax = bbox
    bed_x, bed_y = printer.bed
    z_safe = min(height + 8.0, printer.max_z - 6.0)
    z_push = z_safe if opts.dry_run else opts.push_z
    y_back = min(ymax + opts.behind, bed_y)

    # push lanes across the full width, closer together than the narrowest part
    lanes = []
    x = max(xmin + 1.0, 0.0)
    while x < xmax - 1.0:
        lanes.append(round(x, 2))
        x += opts.lane
    lanes.append(round(min(max(xmax - 1.0, xmin + 1.0), bed_x), 2))

    out = [
        "; ===== AUTO-EJECT START (bambu-autoeject) =====",
        "M400",
        "M140 S0 ; bed off",
        "M104 S0 ; nozzle off",
        "G90",
        "G1 Z%.2f F600 ; above the parts" % z_safe,
        "G1 X%d Y%d F6000" % (bed_x / 2, bed_y / 2),
        "M106 S255 ; fan helps cooling",
    ]
    if opts.wait_bed:
        out.append("M190 S%d ; wait for cold bed (if firmware supports it)" % opts.cool_temp)
    # fixed pause: waiting on bed temperature is not reliable on Bambu firmware
    for i in range(opts.cool_min):
        out.append("M400 S60 ; cooling %d/%d min" % (i + 1, opts.cool_min))
    out += [
        "M106 S0",
        printer.eject_currents + " ; lower current: if the part is stuck the motor skips instead of breaking something",
    ]
    for x in lanes:
        out += [
            "G1 Z%.2f F1200" % z_safe,
            "G1 X%.2f Y%.2f F6000" % (x, y_back),
            "G1 Z%.2f F600" % z_push,
            "G1 Y%.2f F%d ; push to the front" % (Y_FRONT, opts.push_speed * 60),
        ]
    if opts.clean_front:
        # calibration lines drawn by the start G-code on the front edge
        z_front = z_safe if opts.dry_run else opts.front_z
        out.append("G1 Z%.2f F1200" % z_safe)
        x, x_end = printer.front_line_x
        while x <= x_end:
            out += [
                "G1 Z3 F1200",
                "G1 X%.1f Y%.1f F6000" % (x, FRONT_LINE_FROM_Y),
                "G1 Z%.2f F600" % z_front,
                "G1 Y%.2f F1500 ; calibration line off the bed" % Y_FRONT,
            ]
            x += 4.0
    out += [
        "G1 Z%.2f F1200" % z_safe,
        printer.currents + " ; normal currents",
        "G28 X ; re-home XY like the Bambu start, in case steps were skipped",
        "G1 X%.1f Y%.1f F6000" % printer.park,
        "M400",
        "; ===== AUTO-EJECT END =====",
    ]
    return "\n".join(out) + "\n"


def insert_eject(gcode: str, block: str) -> str:
    """Insert the eject block before the motors are disabled in the Bambu end G-code."""
    idx = gcode.rfind("\nM18 X Y Z")
    if idx < 0:
        raise AutoEjectError("cannot find the end sequence (M18 X Y Z) in the G-code")
    return gcode[: idx + 1] + block + gcode[idx + 1:]


def strip_cali_line(gcode: str) -> str:
    """Remove the front calibration line from every print after the first.

    The start G-code always draws it in the same place at 0.3 mm. The nozzle cannot go
    that low there without risking the plate (the front edge is not probed by bed
    leveling), so the first line stays and later ones are skipped.
    """
    base = max(gcode.find(EXEC_START), 0)
    start = gcode.find(CALI_START, base)
    end = gcode.find(CALI_END, start)
    if start < 0 or end < 0:
        raise AutoEjectError("cannot find the calibration line in the start G-code (Bambu profile changed?)")
    return gcode[:start] + "; calibration line removed by bambu-autoeject (already on the bed)\n" + gcode[end:]


def strip_header(gcode: str) -> str:
    """For jobs after the first keep only the executable part."""
    i = gcode.find(EXEC_START)
    return gcode[i:] if i >= 0 else gcode


def parse_jobs(specs: List[str]) -> List[str]:
    """'part.gcode.3mf:3' -> three entries."""
    jobs = []
    for spec in specs:
        path, _, count = spec.rpartition(":")
        if not path or not count.isdigit():
            path, count = spec, "1"
        if int(count) < 1:
            raise AutoEjectError("%s: count must be at least 1" % spec)
        jobs += [path] * int(count)
    return jobs


def build_job(plates: List[Tuple[str, str]], opts: Options, log=None) -> Tuple[str, Printer]:
    """Join (label, gcode) plates into one G-code with an eject after each."""
    if not plates:
        raise AutoEjectError("nothing to print")
    if opts.dry_run and len(plates) > 1:
        raise AutoEjectError("--dry-run leaves the part on the bed, so it only works with a single print")
    printer = None
    parts = []
    total_layers = 0
    for n, (label, gcode) in enumerate(plates):
        this = detect_printer(gcode, opts.force)
        if printer is None:
            printer = this
        elif this != printer:
            raise AutoEjectError("%s: sliced for %s, the first plate is for %s" % (label, this.model, printer.model))
        if opts.clean_front and printer.front_line_x is None:
            raise AutoEjectError("--clean-front is not supported on the %s" % printer.model)
        bbox = first_layer_bbox(gcode)
        height = max_height(gcode)
        if bbox[3] + opts.behind > printer.bed[1] + 0.01:
            raise AutoEjectError("%s: part is too far back (y max %.0f); move it forward on the plate."
                                 % (label, bbox[3]))
        last = n == len(plates) - 1
        if not (last and opts.keep_last):
            gcode = insert_eject(gcode, eject_block(printer, bbox, height, opts))
        if n:
            gcode = strip_header(gcode)
            if not opts.keep_cali_line:
                gcode = strip_cali_line(gcode)
        parts.append("; ===== JOB %d/%d: %s =====\n" % (n + 1, len(plates), label) + gcode)
        m = re.search(r"^; total layer number: (\d+)", gcode, re.M)
        total_layers += int(m.group(1)) if m else 0
        if log:
            log("job %d: %s, parts at X %.0f-%.0f, Y %.0f-%.0f, height %.0f mm"
                % (n + 1, label, bbox[0], bbox[2], bbox[1], bbox[3], height))

    combined = "\n".join(parts)
    combined = re.sub(r"^; total layer number: \d+", "; total layer number: %d" % total_layers,
                      combined, count=1, flags=re.M)
    return combined, printer


def read_plate(path: str) -> Tuple[str, str]:
    """Return (G-code name inside the .gcode.3mf archive, G-code text)."""
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if re.fullmatch(r"Metadata/plate_\d+\.gcode", n)]
        if not names:
            raise AutoEjectError("%s: no G-code inside. Use 'Export plate sliced file', not the project." % path)
        if len(names) > 1:
            raise AutoEjectError("%s: has %d plates; export one plate per file." % (path, len(names)))
        return names[0], z.read(names[0]).decode("utf-8")


def write_3mf(template: str, output: str, gcode: str, printer: Printer) -> None:
    """Copy the template archive (thumbnails, settings) and replace only the G-code."""
    gname, _ = read_plate(template)
    data = gcode.encode("utf-8")
    md5 = hashlib.md5(data).hexdigest().upper()
    with zipfile.ZipFile(template) as src, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            if item.filename == gname:
                dst.writestr(item, data)
            elif item.filename == gname + ".md5":
                dst.writestr(item, md5)
            elif item.filename == "Metadata/slice_info.config":
                cfg = src.read(item).decode("utf-8")
                cfg = cfg.replace('key="printer_model_id" value=""',
                                  'key="printer_model_id" value="%s"' % printer.model_id)
                dst.writestr(item, cfg)
            else:
                dst.writestr(item, src.read(item))


def join_files(output: str, specs: List[str], opts: Options, log=None) -> Tuple[int, Printer]:
    """CLI mode: several .gcode.3mf files in, one .gcode.3mf out."""
    jobs = parse_jobs(specs)
    plates = [(os.path.basename(p), read_plate(p)[1]) for p in jobs]
    gcode, printer = build_job(plates, opts, log)
    write_3mf(jobs[0], output, gcode, printer)
    return len(jobs), printer


def process_in_place(path: str, copies: int, opts: Options, log=None) -> Tuple[int, Printer]:
    """Post-processing mode: rewrite a plain .gcode file, optionally repeating it."""
    if copies < 1:
        raise AutoEjectError("--copies must be at least 1")
    with open(path, encoding="utf-8") as f:
        gcode = f.read()
    if "AUTO-EJECT START" in gcode:
        raise AutoEjectError("%s: already processed by bambu-autoeject" % path)
    label = os.path.basename(path)
    out, printer = build_job([(label, gcode)] * copies, opts, log)
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
    return copies, printer

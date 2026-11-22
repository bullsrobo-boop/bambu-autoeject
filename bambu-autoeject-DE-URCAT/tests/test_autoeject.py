import os
import re
import shutil
import tempfile
import unittest
import zipfile

from bambu_autoeject.cli import main
from bambu_autoeject.core import (AutoEjectError, Options, PRINTERS, build_job, first_layer_bbox,
                                  join_files, parse_jobs, process_in_place, read_plate)

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(HERE, "..", "examples")
A1_CUBE = os.path.join(EXAMPLES, "a1", "cube20.gcode.3mf")
MINI_CUBE = os.path.join(EXAMPLES, "a1-mini", "cube20.gcode.3mf")


def gcode_of(path):
    return read_plate(path)[1]


def eject_blocks(gcode):
    return re.findall(r"AUTO-EJECT START.*?AUTO-EJECT END", gcode, re.S)


def z_moves(text):
    return [float(z) for z in re.findall(r"^G1 Z([\d.]+)", text, re.M)]


class ParseJobs(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(parse_jobs(["a.gcode.3mf:3", "b.gcode.3mf"]),
                         ["a.gcode.3mf"] * 3 + ["b.gcode.3mf"])

    def test_windows_path_without_count(self):
        self.assertEqual(parse_jobs([r"C:\prints\a.gcode.3mf"]), [r"C:\prints\a.gcode.3mf"])

    def test_zero_count_rejected(self):
        with self.assertRaises(AutoEjectError):
            parse_jobs(["a.gcode.3mf:0"])


class Geometry(unittest.TestCase):
    def test_cube_bbox_a1(self):
        xmin, ymin, xmax, ymax = first_layer_bbox(gcode_of(A1_CUBE))
        self.assertAlmostEqual(xmax - xmin, 20, delta=1)
        self.assertAlmostEqual(ymax - ymin, 20, delta=1)


class EjectSafety(unittest.TestCase):
    def check(self, cube, printer):
        gcode = gcode_of(cube)
        out, found = build_job([("cube", gcode)] * 2, Options())
        self.assertEqual(found, PRINTERS[printer])
        blocks = eject_blocks(out)
        self.assertEqual(len(blocks), 2)
        for block in blocks:
            self.assertGreaterEqual(min(z_moves(block)), 1.0)
            ys = [float(y) for y in re.findall(r"Y(-?[\d.]+)", block)]
            self.assertLessEqual(max(ys), PRINTERS[printer].bed[1])
        # the second job must not draw the calibration line again
        second = out.split("JOB 2/2")[1]
        self.assertNotIn(";===== extrude cali test", second)
        self.assertIn("calibration line removed", second)

    def test_a1(self):
        self.check(A1_CUBE, "Bambu Lab A1")

    def test_a1_mini(self):
        self.check(MINI_CUBE, "Bambu Lab A1 mini")

    def test_dry_run_stays_above_part(self):
        out, _ = build_job([("cube", gcode_of(A1_CUBE))], Options(dry_run=True))
        self.assertGreater(min(z_moves(eject_blocks(out)[0])), 20)

    def test_keep_last(self):
        out, _ = build_job([("cube", gcode_of(A1_CUBE))] * 2, Options(keep_last=True))
        self.assertEqual(len(eject_blocks(out)), 1)

    def test_clean_front_not_on_mini(self):
        with self.assertRaises(AutoEjectError):
            build_job([("cube", gcode_of(MINI_CUBE))], Options(clean_front=True))

    def test_mixed_printers_rejected(self):
        with self.assertRaises(AutoEjectError):
            build_job([("a", gcode_of(A1_CUBE)), ("b", gcode_of(MINI_CUBE))], Options())

    def test_unknown_printer_rejected(self):
        gcode = gcode_of(A1_CUBE).replace("; printer_model = Bambu Lab A1", "; printer_model = Bambu Lab X1C")
        with self.assertRaises(AutoEjectError):
            build_job([("x", gcode)], Options())


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_examples_are_up_to_date(self):
        cases = [("1_dry_run", ["cube20.gcode.3mf"], Options(dry_run=True)),
                 ("2_eject_one_cube", ["cube20.gcode.3mf"], Options()),
                 ("3_two_cubes", ["cube20.gcode.3mf:2"], Options())]
        folder = os.path.join(EXAMPLES, "a1")
        for name, specs, opts in cases:
            out = os.path.join(self.tmp, name + ".gcode.3mf")
            cwd = os.getcwd()
            os.chdir(folder)
            try:
                join_files(out, specs, opts)
            finally:
                os.chdir(cwd)
            self.assertEqual(gcode_of(out), gcode_of(os.path.join(folder, name + ".gcode.3mf")), name)

    def test_output_archive(self):
        out = os.path.join(self.tmp, "q.gcode.3mf")
        join_files(out, [MINI_CUBE + ":2"], Options())
        with zipfile.ZipFile(out) as z:
            self.assertIn('value="N1"', z.read("Metadata/slice_info.config").decode())
            self.assertIn("Metadata/plate_1.png", z.namelist())

    def test_in_place(self):
        path = os.path.join(self.tmp, "plate.gcode")
        with open(path, "w") as f:
            f.write(gcode_of(A1_CUBE))
        process_in_place(path, 3, Options())
        with open(path) as f:
            self.assertEqual(len(eject_blocks(f.read())), 3)
        with self.assertRaises(AutoEjectError):
            process_in_place(path, 1, Options())

    def test_cli_error_exit(self):
        with self.assertRaises(SystemExit) as ctx:
            main([os.path.join(self.tmp, "o.gcode.3mf"), A1_CUBE, "--push-z", "0.1"])
        self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main()

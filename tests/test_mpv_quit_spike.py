# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Quick checks for the mpv quit spike runner (spikes/mpv-quit/run.py),
with a fake mpv: no real player, no real media.

- the record and picture are named from a fingerprint of the file's path;
- the capture script is added to Kettle's own mpv command without changing
  the resume save or the 5-second rewind;
- after mpv closes, the record and picture are moved out of the shared
  temporary folder into the app's data folder, the temporary folder is
  removed, and nothing is written next to the media;
- if the 640 px step fails, it is reported and the full-size frame is kept.

The real Flatpak mpv is checked by tests/mpv_quit_check.py.

Run from the repo root:  python3 -m unittest tests.test_mpv_quit_spike
"""

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from backend import mpv as kettle_mpv  # noqa: E402

RUN_PY = REPO / "spikes" / "mpv-quit" / "run.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("mpv_quit_run", RUN_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Stands in for mpv. Playing: writes what quit_capture.lua would write into
# the out_dir given through --script-opts. Shrinking (--vo=image): writes the
# small picture. Every call's arguments are appended to $FAKE_MPV_LOG.
FAKE_MPV = textwrap.dedent("""
    import json, os, sys
    from pathlib import Path
    args = sys.argv[1:]
    with open(os.environ["FAKE_MPV_LOG"], "a") as log:
        log.write(json.dumps(args) + "\\n")
    mode = os.environ.get("FAKE_MPV_MODE", "b")
    outdir = [a.split("=", 1)[1] for a in args if a.startswith("--vo-image-outdir=")]
    if outdir:
        if os.environ.get("FAKE_MPV_SHRINK") == "fail":
            sys.stderr.write("Error: cannot open the picture\\n")
            sys.exit(2)
        Path(outdir[0], "00000001.jpg").write_bytes(b"small-jpeg")
        sys.exit(0)
    opts = [a.split("=", 1)[1] for a in args if a.startswith("--script-opts=")]
    pairs = dict(p.split("=", 1) for p in opts[0].split(","))
    out, fid = Path(pairs["kettle_quit-out_dir"]), pairs["kettle_quit-id"]
    if mode == "b":
        (out / (fid + ".json")).write_text(json.dumps(
            {"file": args[-1], "position": 12.5, "duration": 30.0,
             "how": "b", "finished": False, "frame_saved": True}))
        (out / (fid + ".full.jpg")).write_bytes(b"full-size-jpeg")
    elif mode == "end":
        (out / (fid + ".json")).write_text(json.dumps(
            {"file": args[-1], "position": 30.0, "duration": 30.0,
             "how": "end", "finished": True, "frame_saved": False}))
    sys.exit(0)
""")


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        self.run = load_runner()

    def test_same_path_same_name(self):
        a = self.run.fingerprint(Path("/media/Movies/Film (1999)/film.mkv"))
        b = self.run.fingerprint(Path("/media/Movies/Film (1999)/film.mkv"))
        self.assertEqual(a, b)

    def test_different_paths_different_names(self):
        a = self.run.fingerprint(Path("/media/Movies/A/film.mkv"))
        b = self.run.fingerprint(Path("/media/Movies/B/film.mkv"))
        self.assertNotEqual(a, b)

    def test_name_is_safe_for_a_file_name(self):
        name = self.run.fingerprint(Path("/media/Movies/Ünïcode: \"quotes\"/a b.mkv"))
        self.assertRegex(name, r"^[0-9a-f]{40}$")

    def test_undecodable_name_still_gets_a_fingerprint(self):
        raw = os.fsdecode(b"/media/Movies/caf\xe9.mkv")
        self.assertRegex(self.run.fingerprint(Path(raw)), r"^[0-9a-f]{40}$")


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.run = load_runner()
        self.film = Path("/media/Movies/film.mkv")
        self.args = self.run.build(["mpv"], self.film, Path("/tmp/kettle-quit-x"), "abc", [])

    def test_resume_and_rewind_unchanged(self):
        kettle = kettle_mpv.build_command(["mpv"], self.film, [], resume=True)
        without_capture = [a for a in self.args
                           if not a.startswith(f"--script={self.run.SCRIPT}")
                           and not a.startswith("--script-opts=kettle_quit")]
        self.assertEqual(without_capture, kettle)
        self.assertIn("--save-position-on-quit", self.args)
        self.assertIn(f"--script={kettle_mpv.RESUME_REWIND_SCRIPT}", self.args)

    def test_capture_script_loaded_before_the_file(self):
        self.assertEqual(self.args[-1], str(self.film))
        self.assertIn(f"--script={self.run.SCRIPT}", self.args[:-1])
        self.assertIn("--script-opts=kettle_quit-out_dir=/tmp/kettle-quit-x,kettle_quit-id=abc",
                      self.args[:-1])

    def test_script_file_exists(self):
        self.assertTrue(self.run.SCRIPT.is_file())


class RunTests(unittest.TestCase):
    def setUp(self):
        self.run = load_runner()
        self.tmp = Path(tempfile.mkdtemp(prefix="kettle-quit-test-"))
        self.addCleanup(self._cleanup)
        self.media = self.tmp / "media"
        self.media.mkdir()
        self.film = self.media / "film.mkv"
        self.film.write_bytes(b"not really a film")
        self.out = self.tmp / "data" / "spikes" / "mpv-quit"
        fake = self.tmp / "fake_mpv.py"
        fake.write_text(FAKE_MPV)
        self.command = [sys.executable, str(fake)]
        self.log = self.tmp / "calls.jsonl"
        self._env = {k: os.environ.get(k)
                     for k in ("FAKE_MPV_LOG", "FAKE_MPV_MODE", "FAKE_MPV_SHRINK")}
        os.environ.pop("FAKE_MPV_SHRINK", None)
        os.environ["FAKE_MPV_LOG"] = str(self.log)

    def _cleanup(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def work_dir_of_first_call(self):
        opts = [a for a in self.calls()[0] if a.startswith("--script-opts=")][0]
        return Path(opts.split("kettle_quit-out_dir=")[1].split(",")[0])

    def test_quit_with_b_moves_record_and_picture_into_data_folder(self):
        os.environ["FAKE_MPV_MODE"] = "b"
        summary = self.run.run(self.film, self.command, self.out)
        fid = self.run.fingerprint(self.film)
        self.assertEqual(summary["id"], fid)
        self.assertEqual(summary["mpv_exit"], 0)
        self.assertEqual(summary["record"]["position"], 12.5)
        self.assertEqual(summary["record"]["duration"], 30.0)
        record = json.loads((self.out / f"{fid}.json").read_text())
        self.assertEqual(record["position"], 12.5)
        self.assertEqual((self.out / f"{fid}.jpg").read_bytes(), b"small-jpeg")
        self.assertEqual(summary["picture"], str(self.out / f"{fid}.jpg"))
        # Only the record and the small picture end up in the data folder.
        self.assertEqual(sorted(p.name for p in self.out.iterdir()),
                         sorted([f"{fid}.json", f"{fid}.jpg"]))

    def test_shrink_runs_on_the_full_frame_at_640_px(self):
        os.environ["FAKE_MPV_MODE"] = "b"
        self.run.run(self.film, self.command, self.out)
        shrink = self.calls()[1]
        work = self.work_dir_of_first_call()
        self.assertEqual(shrink[-1], str(work / f"{self.run.fingerprint(self.film)}.full.jpg"))
        vf = [a for a in shrink if a.startswith("--vf=")][0]
        self.assertIn("scale=640:", vf)
        # The washed-out fix: convert to RGB before scaling.
        self.assertLess(vf.index("format=rgb24"), vf.index("scale="))

    def test_temporary_folder_is_shared_tmp_and_removed(self):
        os.environ["FAKE_MPV_MODE"] = "b"
        self.run.run(self.film, self.command, self.out)
        work = self.work_dir_of_first_call()
        self.assertEqual(work.parent, Path("/tmp"))
        self.assertTrue(work.name.startswith("kettle-quit-"))
        self.assertFalse(work.exists())

    def test_nothing_written_next_to_the_media(self):
        os.environ["FAKE_MPV_MODE"] = "b"
        before = sorted(p.name for p in self.media.iterdir())
        self.run.run(self.film, self.command, self.out)
        self.assertEqual(sorted(p.name for p in self.media.iterdir()), before)
        self.assertEqual(self.film.read_bytes(), b"not really a film")

    def test_played_to_end_keeps_record_without_picture(self):
        os.environ["FAKE_MPV_MODE"] = "end"
        summary = self.run.run(self.film, self.command, self.out)
        fid = self.run.fingerprint(self.film)
        self.assertTrue(summary["record"]["finished"])
        self.assertNotIn("picture", summary)
        self.assertEqual([p.name for p in self.out.iterdir()], [f"{fid}.json"])
        # No shrink step when there is no frame.
        self.assertEqual(len(self.calls()), 1)

    def test_failed_shrink_is_reported_and_full_frame_kept(self):
        # Round 1 review: a failed 640 px step must not look like success.
        os.environ["FAKE_MPV_MODE"] = "b"
        os.environ["FAKE_MPV_SHRINK"] = "fail"
        with contextlib.redirect_stderr(io.StringIO()) as err:
            summary = self.run.run(self.film, self.command, self.out)
        fid = self.run.fingerprint(self.film)
        self.assertNotIn("picture", summary)
        self.assertIn("status 2", summary["picture_error"])
        self.assertIn("cannot open the picture", summary["picture_error"])
        self.assertIn("mpv-quit:", err.getvalue())
        record = json.loads((self.out / f"{fid}.json").read_text())
        self.assertIs(record["picture_saved"], False)
        self.assertEqual((self.out / f"{fid}.full.jpg").read_bytes(), b"full-size-jpeg")
        self.assertFalse((self.out / f"{fid}.jpg").exists())
        self.assertFalse(self.work_dir_of_first_call().exists())

    def test_successful_shrink_marks_picture_saved(self):
        os.environ["FAKE_MPV_MODE"] = "b"
        summary = self.run.run(self.film, self.command, self.out)
        self.assertIs(summary["record"]["picture_saved"], True)
        self.assertNotIn("picture_error", summary)

    def test_nothing_saved_is_not_an_error(self):
        os.environ["FAKE_MPV_MODE"] = "none"
        summary = self.run.run(self.film, self.command, self.out)
        self.assertNotIn("record", summary)
        self.assertNotIn("picture", summary)
        self.assertEqual(list(self.out.iterdir()), [])
        self.assertFalse(self.work_dir_of_first_call().exists())


if __name__ == "__main__":
    unittest.main()

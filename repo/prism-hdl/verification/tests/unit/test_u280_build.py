"""The U280 build passes its choices to build.tcl and runs Vivado on the short drive."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


def load_u280_build() -> ModuleType:
    script = Path(__file__).resolve().parents[3] / "integrations" / "u280" / "build.py"
    spec = importlib.util.spec_from_file_location("prism_u280_build", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class U280BuildTest(unittest.TestCase):
    def setUp(self) -> None:
        self.build = load_u280_build()

    def test_the_choices_become_generics_and_flow_options(self) -> None:
        arguments = self.build.parse_arguments(["--rs-fec", "off", "--stop", "route"])
        values = self.build.tcl_arguments(arguments, Path("hdl"), Path("shell"), Path("out"))
        self.assertEqual(values, ["hdl", "shell", "out", "RS_FEC:0", "@stop:route", "@threads:4"])
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "routed.dcp"
            arguments = self.build.parse_arguments(["--incremental", str(checkpoint)])
            values = self.build.tcl_arguments(arguments, Path("h"), Path("s"), Path("o"))
            self.assertIn("RS_FEC:1", values)
            self.assertIn(f"@incremental:{checkpoint.resolve()}", values)

    def test_a_build_runs_vivado_with_paths_on_the_short_drive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            short = root / "short"
            short.mkdir()

            class ShortDrive:
                def __enter__(self) -> Path:
                    return short

                def __exit__(self, *_exception: object) -> None:
                    pass

            with (
                patch.object(self.build, "repository_root", return_value=root),
                patch.object(self.build, "resolve_vivado", return_value=Path("vivado")),
                patch.object(self.build, "verify_vivado_version"),
                patch.object(self.build, "prepare_open_nic") as prepare,
                patch.object(self.build, "short_build_root", return_value=ShortDrive()),
                patch.object(self.build, "run_vivado") as run,
            ):
                self.assertEqual(self.build.main(["--rs-fec", "off"]), 0)
            prepare.assert_called_once_with(root / "build" / "cache" / "open-nic-shell")
            self.assertTrue((root / "build" / "u280" / "rs-fec-off").is_dir())
            command = run.call_args.args[1]
            tclargs = command[command.index("-tclargs") + 1 :]
            self.assertEqual(Path(tclargs[1]), short / "build" / "cache" / "open-nic-shell")
            self.assertEqual(Path(tclargs[2]), short / "build" / "u280" / "rs-fec-off")
            self.assertIn("RS_FEC:0", tclargs)
            self.assertEqual(run.call_args.kwargs["cwd"], short / "build" / "u280" / "rs-fec-off")

    def test_a_missing_incremental_checkpoint_is_refused_before_vivado_runs(self) -> None:
        with (
            patch.object(self.build, "run_vivado") as run,
            self.assertRaises(SystemExit),
        ):
            self.build.main(["--incremental", "missing/routed.dcp"])
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

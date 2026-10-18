from pathlib import Path
import unittest


class LauncherEncodingTests(unittest.TestCase):
    def test_windows_powershell_scripts_have_utf8_bom(self):
        root=Path(__file__).resolve().parents[1]
        for name in ('start_development_workbench.ps1','install_development_environment.ps1'):
            with self.subTest(name=name):
                self.assertTrue((root/'scripts'/name).read_bytes().startswith(b'\xef\xbb\xbf'))

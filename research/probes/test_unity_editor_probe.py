"""Evidence-reader fixtures: empty/skipped/stale XML must never be accepted."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        script = Path(__file__).resolve().parents[2] / 'scripts/probe_unity_editor.py'
        spec = importlib.util.spec_from_file_location('unity_probe', script)
        self.probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.probe)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'results.xml'
        self.started = time.time()

    def test_missing_zero_skipped_wrong_name_and_stale_xml_are_rejected(self):
        with self.assertRaises(ValueError):
            self.probe.inspect_xml(self.path, self.started, 'Expected.Test')
        for contents in ('<test-run result="Passed" total="0" passed="0" failed="0" skipped="0"/>',
                         '<test-run result="Passed"><test-case fullname="Expected.Test" result="Skipped"/></test-run>',
                         '<test-run result="Passed"><test-case fullname="Other.Test" result="Passed"/></test-run>'):
            self.path.write_text(contents, encoding='utf-8')
            with self.subTest(contents=contents), self.assertRaises(ValueError):
                self.probe.inspect_xml(self.path, self.started, 'Expected.Test')
        self.path.write_text('<test-run result="Passed"><test-case fullname="Expected.Test" result="Passed"/></test-run>', encoding='utf-8')
        os.utime(self.path, (self.started-60, self.started-60))
        with self.assertRaises(ValueError):
            self.probe.inspect_xml(self.path, self.started, 'Expected.Test')

    def test_fresh_expected_pass_returns_case_evidence(self):
        self.path.write_text('<test-run result="Passed"><test-case fullname="Expected.Test" result="Passed" duration="0.02"/></test-run>', encoding='utf-8')
        result = self.probe.inspect_xml(self.path, self.started, 'Expected.Test')
        self.assertEqual(result['test_cases'], [{'fullname': 'Expected.Test', 'result': 'Passed', 'duration': '0.02'}])
        self.assertEqual(result['count'], 1)

    def test_build_receipt_requires_fresh_success_and_exact_executable(self):
        executable = self.path.parent / 'Smoke.exe'
        executable.write_bytes(b'fixture only, not a real Player')
        receipt = self.path.parent / 'build.json'
        good = {'result': 'Succeeded', 'outputPath': str(executable), 'totalErrors': 0}
        for contents in ({**good, 'result': 'Failed'}, {**good, 'totalErrors': 1},
                         {**good, 'outputPath': str(executable.parent / 'Wrong.exe')}):
            receipt.write_text(json.dumps(contents), encoding='utf-8')
            with self.subTest(contents=contents), self.assertRaises(ValueError):
                self.probe.inspect_build(receipt, executable, self.started)
        receipt.write_text(json.dumps(good), encoding='utf-8')
        result = self.probe.inspect_build(receipt, executable, self.started)
        self.assertEqual(result['result'], 'Succeeded')
        os.utime(receipt, (self.started-60, self.started-60))
        with self.assertRaises(ValueError):
            self.probe.inspect_build(receipt, executable, self.started)


if __name__ == '__main__':
    unittest.main()

"""Bounded real Unity smoke in one isolated project; never touches the old game.

Use prepare once, then run --phase editmode/playmode/build/player. This is a trusted
local infrastructure smoke, not a generated-code sandbox or gameplay验收.
"""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / 'local-data/unity-editor-smoke-v1'
EDITOR = Path('E:/Unity6/6000.3.19f1/Editor/Unity.exe')
PACKAGES = EDITOR.parent / 'Data/Resources/PackageManager/BuiltInPackages'
EXPECTED = {'editmode': 'Workbench.Smoke.EditModeSmoke.TransformRoundTrip',
            'playmode': 'Workbench.Smoke.PlayModeSmoke.FrameAndTransformAdvance'}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect_xml(path, started, expected):
    if not path.is_file():
        raise ValueError('this attempt produced no test XML')
    if path.stat().st_mtime < started:
        raise ValueError('stale test XML predates this attempt')
    tree = ET.parse(path).getroot()
    cases = [{'fullname': node.get('fullname'), 'result': node.get('result'), 'duration': node.get('duration')}
             for node in tree.iter('test-case')]
    if tree.get('result') != 'Passed' or not cases or any(case['result'] != 'Passed' for case in cases):
        raise ValueError('test XML is failed, empty or skipped')
    if [case['fullname'] for case in cases] != [expected]:
        raise ValueError('test XML does not contain exactly the expected test')
    return {'count': len(cases), 'test_cases': cases, 'xml_sha256': sha(path),
            'start_time': tree.get('start-time'), 'end_time': tree.get('end-time')}


def inspect_build(receipt, executable, started):
    if not receipt.is_file() or receipt.stat().st_mtime < started or not executable.is_file():
        raise ValueError('missing or stale build receipt/executable')
    result = json.loads(receipt.read_text(encoding='utf-8-sig'))
    if result.get('result') != 'Succeeded' or result.get('totalErrors') != 0:
        raise ValueError('build did not succeed without errors')
    if Path(result.get('outputPath', '')).resolve() != executable.resolve():
        raise ValueError('build receipt refers to a different executable')
    return {**result, 'executable_sha256': sha(executable), 'receipt_sha256': sha(receipt)}


def stage_player_sources(project):
    templates = REPO / 'research/probes/unity_editor_smoke'
    for name, folder in [('PlayerSmokeBootstrap.cs', 'Assets/SmokeRuntime'), ('BuildSmokePlayer.cs', 'Assets/Editor')]:
        destination = project / folder / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file() and sha(destination) != sha(templates / name):
            raise ValueError('keep existing player source; explicit evidence-preserving repair required')
        shutil.copyfile(templates / name, destination)


def prepare():
    project = ROOT / 'project'
    if project.exists():
        raise ValueError('isolated project already exists; keep its evidence')
    for folder in ('Assets/Tests/EditMode', 'Assets/Tests/PlayMode', 'Packages', 'ProjectSettings'):
        (project / folder).mkdir(parents=True, exist_ok=False)
    dependencies = {'com.unity.test-framework': 'file:' + (PACKAGES / 'com.unity.test-framework').as_posix(),
                    'com.unity.ext.nunit': 'file:' + (PACKAGES / 'com.unity.ext.nunit').as_posix(),
                    'com.unity.modules.imgui': '1.0.0', 'com.unity.modules.jsonserialize': '1.0.0'}
    save(project / 'Packages/manifest.json', {'dependencies': dependencies, 'enableLockFile': True})
    (project / 'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 6000.3.19f1\nm_EditorVersionWithRevision: 6000.3.19f1 (7689f4515d75)\n', encoding='utf-8')
    templates = REPO / 'research/probes/unity_editor_smoke'
    for phase in ('EditMode', 'PlayMode'):
        target = project / 'Assets/Tests' / phase
        shutil.copyfile(templates / (phase + 'Smoke.cs'), target / (phase + 'Smoke.cs'))
        definition = {'name': 'Workbench.Smoke.' + phase, 'references': ['UnityEngine.TestRunner', 'UnityEditor.TestRunner'],
                      'includePlatforms': ['Editor'] if phase == 'EditMode' else [], 'excludePlatforms': [],
                      'allowUnsafeCode': False, 'overrideReferences': True, 'precompiledReferences': ['nunit.framework.dll'],
                      'autoReferenced': False, 'defineConstraints': ['UNITY_INCLUDE_TESTS'], 'versionDefines': [], 'noEngineReferences': False}
        save(target / (phase + 'Smoke.asmdef'), definition)
    save(ROOT / 'prepared.json', {'editor': str(EDITOR), 'editor_sha256': sha(EDITOR), 'project': str(project),
                                 'packages': {name: sha(PACKAGES / name / 'package.json') for name in ('com.unity.test-framework', 'com.unity.ext.nunit')},
                                 'scope': 'real engine infrastructure only; no model or battle'})
    print(json.dumps({'prepared': str(project)}, ensure_ascii=False), flush=True)


class OwnedJob:
    """Windows Job Object owns only this smoke process and inherited descendants."""
    def __init__(self, process):
        class Basic(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong),
                        ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                        ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]
        class Extended(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', IO), ('ProcessMemoryLimit', ctypes.c_size_t),
                        ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.api.CreateJobObjectW(None, None)
        limits = Extended(); limits.BasicLimitInformation.LimitFlags = 0x2000
        if not self.handle or not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            error = ctypes.WinError(ctypes.get_last_error()); self.close(); raise error

    def pids(self):
        class ProcessList(ctypes.Structure):
            _fields_ = [('assigned', wintypes.DWORD), ('count', wintypes.DWORD), ('ids', ctypes.c_size_t * 256)]
        data = ProcessList()
        if not self.api.QueryInformationJobObject(self.handle, 3, ctypes.byref(data), ctypes.sizeof(data), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return list(data.ids[:data.count])

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def run(phase, timeout):
    project = ROOT / 'project'
    if not (ROOT / 'prepared.json').is_file():
        raise ValueError('prepare this isolated project first')
    attempts = list(ROOT.glob(phase + '-attempt-*'))
    if len(attempts) >= 3:
        raise ValueError('initial attempt and two targeted repairs exhausted')
    attempt = ROOT / f'{phase}-attempt-{len(attempts)+1:02d}'
    attempt.mkdir(exist_ok=False)
    xml = attempt / 'results.xml'
    log = attempt / 'editor.log'
    command = [str(EDITOR), '-batchmode', '-nographics', '-projectPath', str(project), '-logFile', str(log)]
    if phase in EXPECTED:
        command += ['-runTests', '-testPlatform', {'editmode': 'EditMode', 'playmode': 'PlayMode'}[phase],
                    '-testFilter', EXPECTED[phase], '-testResults', str(xml)]
    elif phase == 'build':
        stage_player_sources(project)
        executable = attempt / 'player/Smoke.exe'
        command += ['-executeMethod', 'Workbench.Smoke.BuildSmokePlayer.Build', '-quit',
                    '-smokeBuildOutput', str(executable), '-smokeBuildReceipt', str(attempt / 'build.json')]
    else:
        builds = [p for p in sorted(ROOT.glob('build-attempt-*/result.json'))
                  if json.loads(p.read_text(encoding='utf-8')).get('passed')]
        if not builds:
            raise ValueError('a successful isolated smoke build is required before player run')
        build_result = json.loads(builds[-1].read_text(encoding='utf-8'))
        executable = builds[-1].parent / 'player/Smoke.exe'
        if sha(executable) != build_result['build']['executable_sha256']:
            raise ValueError('Player executable differs from successful build receipt')
        command = [str(executable), '-batchmode', '-nographics', '-logFile', str(log)]
    # No -quit with -runTests: UTF owns test completion and Editor shutdown.
    frozen = {p.relative_to(project).as_posix(): sha(p) for folder in ('Assets', 'Packages', 'ProjectSettings')
              for p in (project / folder).rglob('*') if p.is_file() and p.suffix in ('.cs', '.asmdef', '.json', '.txt')}
    save(attempt / 'source-before.json', frozen)
    # UPM joins Windows system paths (including ALLUSERSPROFILE). Keep these
    # non-secret OS variables, not arbitrary developer/model credentials.
    system_names = {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'PATH', 'PATHEXT', 'USERPROFILE', 'LOCALAPPDATA',
                    'APPDATA', 'PROGRAMDATA', 'ALLUSERSPROFILE', 'COMSPEC', 'SYSTEMDRIVE', 'HOMEDRIVE',
                    'HOMEPATH', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMW6432', 'COMMONPROGRAMFILES',
                    'COMMONPROGRAMFILES(X86)', 'COMMONPROGRAMW6432', 'USERNAME', 'USERDOMAIN', 'COMPUTERNAME',
                    'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'PROCESSOR_IDENTIFIER'}
    env = {key: value for key, value in os.environ.items() if key.upper() in system_names}
    started = time.time(); clock = time.monotonic()
    result = {'phase': phase, 'command': command, 'started_utc': datetime.now(timezone.utc).isoformat(),
              'source_fingerprints': frozen, 'model_calls': 0, 'battle_count': 0, 'passed': False,
              'runner_sha256': sha(Path(__file__)), 'environment_names': sorted(env)}
    process = None; job = None; owned = set()
    try:
        with (attempt / 'process.log').open('w', encoding='utf-8') as stream:
            process = subprocess.Popen(command, cwd=project, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            result['pid'] = process.pid
            job = OwnedJob(process)
            result['job_object_assigned'] = True
            save(attempt / 'started.json', result)
            print(json.dumps({'phase': phase, 'pid': process.pid, 'timeout_seconds': timeout, 'attempt': str(attempt)}), flush=True)
            heartbeat = -15
            while process.poll() is None:
                elapsed = time.monotonic() - clock
                owned.update(job.pids())
                if elapsed >= timeout:
                    result['timed_out'] = True
                    break
                if elapsed - heartbeat >= 15:
                    print(json.dumps({'phase': phase, 'pid': process.pid, 'elapsed_seconds': round(elapsed),
                                      'active_owned_count': len(job.pids()), 'observed_owned_count': len(owned)}), flush=True)
                    heartbeat = elapsed
                time.sleep(0.2)
            result['remaining_owned_before_close'] = job.pids()
            job.close(); job = None
            result['exit_code'] = process.wait(timeout=30)
            result['owned_pids_observed'] = sorted(owned)
            result['root_reaped'] = process.poll() is not None
            result['timed_out'] = result.get('timed_out', False)
        if result['timed_out'] or result['exit_code'] != 0:
            raise ValueError('process timeout or nonzero exit; inspect this attempt log')
        if phase in EXPECTED:
            result['tests'] = inspect_xml(xml, started, EXPECTED[phase])
        elif phase == 'build':
            result['build'] = inspect_build(attempt / 'build.json', executable, started)
        else:
            if not log.is_file() or log.stat().st_mtime < started or 'WORKBENCH_PLAYER_SMOKE_PASSED' not in log.read_text(encoding='utf-8', errors='replace'):
                raise ValueError('standalone Player did not emit its current-run success marker')
            result['player'] = {'executable': str(executable), 'executable_sha256': sha(executable),
                                'build_result': str(builds[-1]), 'utf_test': False,
                                'assertions': 'standalone, batchmode, exact engine version, frame advancement, transform and destruction'}
        result['passed'] = True
    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        if job:
            result['remaining_owned_before_close'] = job.pids()
            job.close()
        if process and process.poll() is None:
            # Fallback only for failure before Job assignment; exact owned root.
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            process.wait(timeout=30)
        result['elapsed_seconds'] = round(time.monotonic() - clock, 3)
        result['root_reaped'] = process is not None and process.poll() is not None
        result['logs'] = {p.name: sha(p) for p in attempt.iterdir() if p.is_file() and p.name not in ('result.json',)}
        save(attempt / 'result.json', result)
    print(json.dumps({key: result.get(key) for key in ('phase', 'passed', 'pid', 'exit_code', 'elapsed_seconds', 'root_reaped', 'error')}, ensure_ascii=False), flush=True)
    return 0 if result['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'run'))
    parser.add_argument('--phase', choices=(*EXPECTED, 'build', 'player'), default='editmode')
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()
    if not 10 <= args.timeout <= 900:
        raise ValueError('timeout must be bounded between 10 and 900 seconds')
    if args.action == 'prepare':
        prepare(); return 0
    return run(args.phase, args.timeout)


if __name__ == '__main__':
    raise SystemExit(main())

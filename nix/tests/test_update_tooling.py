import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('update_go_deps', ROOT / 'nix/update-go-deps.py')
assert spec and spec.loader
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)
HASH = 'sha256-iSPPwwu9jllnIxkQeOlJFdDL4xLUGRP2RMW9DPRY6FQ='


class VendorHashTests(unittest.TestCase):
    def test_hash_mismatch(self) -> None:
        self.assertEqual(updater.hash_from_error(f'error: hash mismatch\n  got:    {HASH}\n'), HASH)

    def test_other_failures_are_not_hashes(self) -> None:
        for output in ('network error', f'got: {HASH}\ngot: {HASH}', 'got: sha256-truncated'):
            with self.assertRaises(RuntimeError):
                updater.hash_from_error(output)

    def test_refresh_and_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'nix').mkdir()
            path = root / 'nix/go-deps-hash.nix'
            original = '"old hash"\n'
            for result, succeeds in ((f'got: {HASH}', True), ('network error', False)):
                path.write_text(original)
                results = [subprocess.CompletedProcess([], 1, '', result), subprocess.CompletedProcess([], 0)]
                with (
                    patch.object(updater, '__file__', str(root / 'nix/update-go-deps.py')),
                    patch('sys.argv', ['update-go-deps.py']),
                    patch.object(updater.subprocess, 'run', side_effect=results),
                ):
                    if succeeds:
                        updater.main()
                        self.assertIn(HASH, path.read_text())
                    else:
                        with self.assertRaises(RuntimeError):
                            updater.main()
                        self.assertEqual(path.read_text(), original)

    def test_second_build_failure_restores_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'nix').mkdir()
            path = root / 'nix/go-deps-hash.nix'
            original = '"old hash"\n'
            path.write_text(original)
            with (
                patch.object(updater, '__file__', str(root / 'nix/update-go-deps.py')),
                patch('sys.argv', ['update-go-deps.py']),
                patch.object(
                    updater.subprocess, 'run', side_effect=[subprocess.CompletedProcess([], 1, '', f'got: {HASH}'), subprocess.CalledProcessError(1, 'nix')]
                ),
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    updater.main()
            self.assertEqual(path.read_text(), original)


class UpstreamSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.upstream = self.root / 'upstream'
        self.origin = self.root / 'origin.git'
        self.fork = self.root / 'fork'
        self.env = dict(
            os.environ,
            GIT_AUTHOR_NAME='Test',
            GIT_AUTHOR_EMAIL='test@example.invalid',
            GIT_COMMITTER_NAME='Test',
            GIT_COMMITTER_EMAIL='test@example.invalid',
            BASE_BRANCH='master',
            SYNC_BRANCH='automation/upstream-sync',
            UPSTREAM_URL=str(self.upstream),
            UPSTREAM_BRANCH='master',
        )
        self.git(self.root, 'init', '-b', 'master', str(self.upstream))
        self.commit(self.upstream, 'common', 'base\n')
        self.git(self.root, 'clone', '--bare', str(self.upstream), str(self.origin))
        self.git(self.root, 'clone', str(self.origin), str(self.fork))
        self.commit(self.fork, 'feature', 'soft fork\n')
        self.git(self.fork, 'push', 'origin', 'master')
        self.base = self.git(self.fork, 'rev-parse', 'master')

    def git(self, cwd: Path, *args: str) -> str:
        return subprocess.check_output(['git', *args], cwd=cwd, env=self.env, stderr=subprocess.STDOUT, text=True).strip()

    def commit(self, cwd: Path, name: str, content: str) -> None:
        (cwd / name).write_text(content)
        self.git(cwd, 'add', name)
        self.git(cwd, 'commit', '-m', f'update {name}')

    def sync(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(['bash', str(ROOT / 'nix/sync-upstream.sh')], cwd=self.fork, env=self.env, capture_output=True, text=True)

    def test_merge_preserves_fork_and_never_publishes(self) -> None:
        self.commit(self.upstream, 'upstream-new', 'upstream\n')
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.fork / 'feature').exists())
        self.assertTrue((self.fork / 'upstream-new').exists())
        self.assertEqual(self.git(self.fork, 'rev-parse', 'master'), self.base)
        self.assertEqual(self.git(self.origin, 'rev-parse', 'master'), self.base)
        self.assertEqual(self.git(self.origin, 'branch', '--list', 'automation/upstream-sync'), '')
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_branch_is_updated_without_losing_history(self) -> None:
        self.commit(self.upstream, 'first-update', 'one\n')
        self.assertEqual(self.sync().returncode, 0)
        old = self.git(self.fork, 'rev-parse', 'HEAD')
        self.git(self.fork, 'push', 'origin', 'automation/upstream-sync')
        self.git(self.fork, 'switch', 'master')
        self.commit(self.fork, 'new-fork-change', 'fork\n')
        self.git(self.fork, 'push', 'origin', 'master')
        self.commit(self.upstream, 'second-update', 'two\n')
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.git(self.fork, 'merge-base', '--is-ancestor', old, 'HEAD')
        for name in ('feature', 'first-update', 'second-update', 'new-fork-change'):
            self.assertTrue((self.fork / name).exists())

    def test_conflict_aborts_without_publishing(self) -> None:
        self.commit(self.fork, 'common', 'fork\n')
        self.git(self.fork, 'push', 'origin', 'master')
        self.commit(self.upstream, 'common', 'upstream\n')
        result = self.sync()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('nothing was pushed', result.stderr)
        self.assertEqual((self.fork / 'common').read_text(), 'fork\n')
        self.assertFalse((self.fork / '.git/MERGE_HEAD').exists())
        self.assertEqual(self.git(self.origin, 'branch', '--list', 'automation/upstream-sync'), '')

    def test_dirty_checkout_is_rejected(self) -> None:
        (self.fork / 'untracked').write_text('do not lose me')
        result = self.sync()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('dirty checkout', result.stderr)
        self.assertEqual(self.git(self.fork, 'branch', '--show-current'), 'master')


if __name__ == '__main__':
    unittest.main()

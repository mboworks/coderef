# SPDX-FileCopyrightText: Copyright (c) M. Boerger, the MBO Works authors
# SPDX-License-Identifier: Apache-2.0
"""Verify immutable publication ordering and fail-closed asset validation."""

import hashlib
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest import mock

import publish_release as release


class PublishReleaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tag = 'v1.2.3'
        for platform, extension in release.PLATFORMS.items():
            path = self.root / f'coderef-{self.tag}-{platform}.{extension}'
            path.write_bytes(platform.encode())
            (self.root / (path.name + '.sha256')).write_text(hashlib.sha256(path.read_bytes()).hexdigest() + '\n')
        self.digests = release.verify_local(self.tag, self.root)
        self.remote = {'tag_name': self.tag, 'draft': True,
                       'assets': [{'name': name, 'state': 'uploaded', 'digest': digest}
                                  for name, digest in self.digests.items()]}

    def test_publish_complete_assets_verifies_before_finalizing(self):
        with mock.patch.object(release, 'gh', side_effect=['[]', '', '', json.dumps(self.remote), '']) as gh:
            release.publish('mboworks/coderef', self.tag, self.root, Path('notes'))
        calls = [call.args for call in gh.call_args_list]
        self.assertEqual(calls[1][:3], ('release', 'create', self.tag))
        self.assertIn('--draft', calls[1])
        self.assertEqual(calls[2][:3], ('release', 'upload', self.tag))
        self.assertEqual(calls[3], ('api', f'repos/mboworks/coderef/releases/tags/{self.tag}'))
        self.assertEqual(calls[4][:3], ('release', 'edit', self.tag))
        self.assertIn('--draft=false', calls[4])
        self.assertIn('--prerelease=false', calls[4])

    def test_publish_remote_digest_mismatch_keeps_draft(self):
        self.remote['assets'][0]['digest'] = 'sha256:wrong'
        with mock.patch.object(release, 'gh', side_effect=['[]', '', '', json.dumps(self.remote)]) as gh:
            with self.assertRaises(ValueError):
                release.publish('mboworks/coderef', self.tag, self.root, Path('notes'))
        self.assertFalse(any(call.args[:2] == ('release', 'edit') for call in gh.call_args_list))

    def test_publish_existing_identical_release_does_not_mutate(self):
        self.remote['draft'] = False
        with mock.patch.object(release, 'gh', return_value=json.dumps([[self.remote]])) as gh:
            release.publish('mboworks/coderef', self.tag, self.root, Path('notes'))
        self.assertEqual(gh.call_count, 1)

    def test_publish_existing_incomplete_release_does_not_overwrite(self):
        self.remote['draft'] = False
        self.remote['assets'].pop()
        with mock.patch.object(release, 'gh', return_value=json.dumps([[self.remote]])) as gh:
            with self.assertRaises(ValueError):
                release.publish('mboworks/coderef', self.tag, self.root, Path('notes'))
        self.assertEqual(gh.call_count, 1)

    def test_local_missing_or_corrupt_assets_fail_before_network(self):
        checksum = next(self.root.glob('*.sha256'))
        checksum.write_text('wrong')
        with mock.patch.object(release, 'gh') as gh:
            with self.assertRaises(ValueError):
                release.publish('mboworks/coderef', self.tag, self.root, Path('notes'))
            checksum.unlink()
            with self.assertRaises(ValueError):
                release.publish('mboworks/coderef', self.tag, self.root, Path('notes'))
        gh.assert_not_called()

    def test_publish_api_failure_never_creates_a_release(self):
        with mock.patch.object(release, 'gh', side_effect=subprocess.CalledProcessError(1, ['gh'])) as gh:
            with self.assertRaises(subprocess.CalledProcessError):
                release.publish('mboworks/coderef', self.tag, self.root, Path('notes'))
        self.assertEqual(gh.call_count, 1)

    def test_publish_release_candidate_does_not_replace_latest(self):
        tag = self.tag + '-rc.1'
        for path in list(self.root.iterdir()):
            path.rename(self.root / path.name.replace(self.tag, tag))
        self.remote['tag_name'] = tag
        for asset in self.remote['assets']:
            asset['name'] = asset['name'].replace(self.tag, tag)
        with mock.patch.object(release, 'gh', side_effect=['[]', '', '', json.dumps(self.remote), '']) as gh:
            release.publish('mboworks/coderef', tag, self.root, Path('notes'))
        self.assertIn('--prerelease=true', gh.call_args.args)
        self.assertIn('--latest=false', gh.call_args.args)

    def test_publish_existing_draft_resumes_without_recreating(self):
        with mock.patch.object(release, 'gh', side_effect=[json.dumps([[self.remote]]), '', json.dumps(self.remote), '']) as gh:
            release.publish('mboworks/coderef', self.tag, self.root, Path('notes'))
        self.assertEqual(gh.call_args_list[1].args[:2], ('release', 'upload'))
        self.assertFalse(any(call.args[:2] == ('release', 'create') for call in gh.call_args_list))


if __name__ == '__main__':
    unittest.main()

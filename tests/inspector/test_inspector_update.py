"""Updater preserves Inspector configuration and restores the old service on failure."""
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[2] / 'scripts/inspector/update-volz-db.py'
spec = importlib.util.spec_from_file_location('inspector_updater', PATH)
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


def current():
    return {'Id': 'a' * 64, 'Name': '/youspeed-inspector', 'Image': 'sha256:' + 'b' * 64,
            'State': {'Running': True},
            'Config': {'Image': 'old-tag', 'User': '10001:10001', 'Env': ['PRIVATE_VALUE=must-stay-private'],
                       'Entrypoint': ['python'], 'WorkingDir': '/srv',
                       'Labels': {'de.youspeed.component': 'inspector', 'de.youspeed.release': 'old'},
                       'Cmd': [u.CODE_TARGET + '/inspector/server.py', '--port', '8080', '--bind', '0.0.0.0',
                               '--allowed-host', 'localhost:18080', '--review-service-url', 'http://youspeed-review:8023']},
            'HostConfig': {'ReadonlyRootfs': True, 'Privileged': False, 'AutoRemove': False,
                           'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges:true'],
                           'Memory': 536870912, 'PidsLimit': 128, 'NanoCpus': 1500000000,
                           'RestartPolicy': {'Name': 'unless-stopped', 'MaximumRetryCount': 0},
                           'NetworkMode': 'private', 'Binds': None, 'VolumesFrom': None,
                           'PortBindings': {'8080/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8080'}]},
                           'LogConfig': {'Type': 'json-file', 'Config': {'max-size': '10m'}},
                           'Mounts': [{'Type': 'bind', 'Source': '/srv/youspeed-inspector/releases/old',
                                       'Target': u.CODE_TARGET, 'ReadOnly': True},
                                      {'Type': 'bind', 'Source': '/private/credential', 'Target': '/run/secret', 'ReadOnly': True},
                                      {'Type': 'volume', 'Source': 'management-media', 'Target': '/media', 'ReadOnly': True,
                                       'VolumeOptions': {'NoCopy': True}}]},
            'Mounts': [{'Destination': u.CODE_TARGET}, {'Destination': '/run/secret'}, {'Destination': '/media'}],
            'NetworkSettings': {'Networks': {'private': {'NetworkID': 'net-private', 'IPAMConfig': None,
                                                         'Aliases': ['youspeed-inspector', 'a' * 12], 'DriverOpts': None},
                                             'publication': {'NetworkID': 'net-public', 'IPAMConfig': None,
                                                             'Aliases': ['stable-alias'], 'DriverOpts': {'key': 'value'}}}}}


def plan(document=None):
    return u.make_plan(document or current(), 'c' * 16, 'd' * 64, 'operation-one')


class FakeDocker:
    def __init__(self, failure=None, interrupt=None):
        old = current()
        self.objects = {old['Id']: old}
        self.calls, self.failure, self.triggered = [], failure, False
        self.interrupt = interrupt

    def inspect(self, identity=u.NAME, missing=False):
        value = next((x for x in self.objects.values() if identity in (x['Id'], x['Name'].lstrip('/'))), None)
        if value is None and not missing:
            raise u.UpdateError('not found')
        return deepcopy(value)

    def request(self, method, path, body=None):
        self.calls.append((method, path, deepcopy(body)))
        if self.failure and self.failure in path and not self.triggered:
            self.triggered = True
            raise u.UpdateError('simulated operation failure')
        if path.startswith('/networks/'):
            return None
        if path.startswith('/containers/create'):
            obj = {'Id': 'e' * 64, 'Name': '/' + u.NAME, 'Config': deepcopy(body), 'State': {'Running': False}}
            self.objects[obj['Id']] = obj
            if self.interrupt == 'create':
                self.interrupt = None
                raise KeyboardInterrupt
            return {'Id': obj['Id']}
        identity, action = path.split('/')[2], path.split('/')[3] if path.count('/') > 2 else ''
        identity = identity.split('?')[0]
        obj = self.objects[identity]
        if method == 'DELETE':
            del self.objects[identity]
        elif action.startswith('stop'):
            obj['State']['Running'] = False
        elif action.startswith('rename'):
            obj['Name'] = '/' + path.split('name=')[1]
        elif action == 'start':
            obj['State']['Running'] = True
        else:
            raise AssertionError(path)
        if self.interrupt and action.startswith(self.interrupt):
            self.interrupt = None
            raise KeyboardInterrupt


class PlanTests(unittest.TestCase):
    def test_exact_config_preserved_except_explicit_code_data_and_release_changes(self):
        original = current()
        before = deepcopy(original)
        p = plan(original)
        self.assertEqual(original, before)
        self.assertEqual(p['body']['Image'], original['Image'])
        for field in ('Env', 'Entrypoint', 'User', 'WorkingDir'):
            self.assertEqual(p['body'][field], original['Config'][field])
        restored_host = deepcopy(p['body']['HostConfig'])
        restored_host['Mounts'] = original['HostConfig']['Mounts']
        self.assertEqual(restored_host, original['HostConfig'])
        self.assertEqual(p['body']['HostConfig']['Mounts'][1:3], original['HostConfig']['Mounts'][1:])
        self.assertEqual(p['body']['Cmd'][:-2], original['Config']['Cmd'])
        self.assertEqual(p['body']['Cmd'][-2:], ['--sign-positions-file', u.DATA_TARGET])
        self.assertEqual(p['extra_networks'], [('net-public', {'Aliases': ['stable-alias'], 'DriverOpts': {'key': 'value'}})])
        self.assertEqual(p['body']['NetworkingConfig']['EndpointsConfig']['private']['Aliases'], ['youspeed-inspector'])

    def test_repeat_update_replaces_one_data_mount_and_argument(self):
        old = current()
        old['Config']['Cmd'] += ['--sign-positions-file', '/old/data.json']
        old['HostConfig']['Mounts'].append({'Type': 'bind', 'Source': '/old/data.json', 'Target': u.DATA_TARGET, 'ReadOnly': True})
        p = plan(old)
        self.assertEqual(p['body']['Cmd'].count('--sign-positions-file'), 1)
        self.assertEqual(sum(m['Target'] == u.DATA_TARGET for m in p['body']['HostConfig']['Mounts']), 1)

    def test_unsafe_or_unreproducible_runtime_fails_before_any_mutation(self):
        mutations = [lambda x: x['Config']['Labels'].clear(),
                     lambda x: x['HostConfig'].update(AutoRemove=True),
                     lambda x: x['HostConfig'].update(Privileged=True),
                     lambda x: x['HostConfig']['PortBindings']['8080/tcp'][0].update(HostIp='0.0.0.0'),
                     lambda x: x['NetworkSettings']['Networks']['private'].update(IPAMConfig={'IPv4Address': '172.19.0.9'}),
                     lambda x: x['Mounts'].append({'Destination': '/anonymous'}),
                     lambda x: x['HostConfig']['Mounts'][0].update(ReadOnly=False)]
        for change in mutations:
            doc = current()
            change(doc)
            with self.subTest(change=change), self.assertRaises(u.UpdateError):
                plan(doc)


class SwitchTests(unittest.TestCase):
    def test_success_retains_stopped_old_container_with_original_config(self):
        d = FakeDocker()
        p = plan()
        result = u.perform_update(d, p, {}, health=lambda *_: {'eligible_speed_cases': 0}, pause=lambda _: None)
        old = d.inspect(p['old_id'])
        self.assertFalse(old['State']['Running'])
        self.assertEqual(old['Name'], '/' + p['backup_name'])
        self.assertEqual(old['Config'], current()['Config'])
        self.assertTrue(d.inspect()['State']['Running'])
        self.assertEqual(result['health']['eligible_speed_cases'], 0)
        self.assertFalse(any(method == 'DELETE' for method, _, _ in d.calls))
        self.assertFalse(any('exec' in path or 'images' in path for _, path, _ in d.calls))

    def test_create_connect_start_and_health_failure_restore_original_service(self):
        for failure in ('create', '/connect', 'e' * 64 + '/start', 'health'):
            d = FakeDocker(None if failure == 'health' else failure)
            def health(*_):
                if failure == 'health':
                    raise ValueError('private details must not escape')
                return {}
            with self.subTest(failure=failure), self.assertRaisesRegex(u.UpdateError, 'original Inspector was restored'):
                u.perform_update(d, plan(), {}, health=health, pause=lambda _: None)
            self.assertEqual(set(d.objects), {'a' * 64})
            self.assertTrue(d.inspect()['State']['Running'])
            self.assertFalse(any(method == 'DELETE' and 'a' * 64 in path for method, path, _ in d.calls))

    def test_terminal_interruption_after_stop_rename_or_create_restores_old(self):
        for phase in ('stop', 'rename', 'create'):
            d = FakeDocker(interrupt=phase)
            with self.subTest(phase=phase), self.assertRaises(u.UpdateInterrupted) as caught:
                u.perform_update(d, plan(), {}, pause=lambda _: None)
            self.assertEqual(caught.exception.signum, u.signal.SIGINT)
            self.assertEqual(set(d.objects), {'a' * 64})
            self.assertTrue(d.inspect()['State']['Running'])

    def test_concurrent_configuration_change_does_not_stop_service(self):
        d = FakeDocker()
        p = plan()
        d.objects['a' * 64]['HostConfig']['Memory'] += 1
        with self.assertRaisesRegex(u.UpdateError, 'changed since preflight'):
            u.perform_update(d, p, {})
        self.assertEqual(d.calls, [])


class HealthTests(unittest.TestCase):
    def reply(self, cases):
        return {'cases': cases, 'meta': {'scope': 'maximum_speed_and_zone_start', 'totalEligibleFits': len(cases), 'availableUntil': '2999-01-01T00:00:00Z'}}

    def check(self, result, cache_control='no-store'):
        status = {'user': 'youspeed_report', 'database': 'youspeed', 'media_available': True}
        responses = [io.BytesIO(json.dumps(x).encode()) for x in (status, result)]
        for response in responses:
            response.headers = {'Cache-Control': cache_control}
        with patch.object(u, 'urlopen', side_effect=responses):
            return u.verify_health('http://127.0.0.1:8080', {'07': {'family': 'maximum_speed', 'value': 80, 'unit': 'km/h'}})

    def test_expired_positive_population_rejected(self):
        value = self.reply([{'label': '07', 'speedLimit': {'family': 'maximum_speed', 'value': 80, 'unit': 'km/h'}}])
        value['meta']['availableUntil'] = '2000-01-01T00:00:00Z'
        with self.assertRaises(u.UpdateError):
            self.check(value)

    def test_empty_population_still_requires_future_lifecycle_deadline(self):
        for expiry in ('2000-01-01T00:00:00Z', None, '2999-01-01T00:00:00'):
            value = self.reply([])
            value['meta']['availableUntil'] = expiry
            with self.subTest(expiry=expiry), self.assertRaises(u.UpdateError):
                self.check(value)

    def test_no_store_required_and_directive_whitespace_accepted(self):
        self.assertEqual(self.check(self.reply([]), 'private, no-store')['eligible_speed_cases'], 0)
        with self.assertRaises(u.UpdateError):
            self.check(self.reply([]), 'private, no-cache')

    def test_zero_currently_eligible_cases_is_valid_but_wrong_class_is_not(self):
        self.assertEqual(self.check(self.reply([]))['eligible_speed_cases'], 0)
        with self.assertRaises(u.UpdateError):
            self.check(self.reply([{'label': '07', 'speedLimit': {'family': 'minimum_speed', 'value': 80, 'unit': 'km/h'}}]))
        with self.assertRaises(u.UpdateError):
            self.check(self.reply([{'label': 'unknown', 'speedLimit': {}}]))


class FilesTests(unittest.TestCase):
    def test_manifest_tampering_unlisted_files_and_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            names = ['inspector/server.py', 'inspector/sign_positions.py', 'scripts/inspector/update-volz-db.py']
            hashes = {}
            for name in names:
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('synthetic')
                hashes[name] = hashlib.sha256(p.read_bytes()).hexdigest()
            manifest = {'release': u.sha(json.dumps(hashes, sort_keys=True).encode())[:16], 'files': hashes}
            (root / 'inspector-deployment.json').write_text(json.dumps(manifest))
            self.assertEqual(u.verify_package(root), manifest)
            (root / 'extra').write_text('not manifested')
            with self.assertRaises(u.UpdateError):
                u.verify_package(root)
            (root / 'extra').unlink()
            (root / names[0]).write_text('tampered')
            with self.assertRaises(u.UpdateError):
                u.verify_package(root)
            (root / names[0]).unlink()
            (root / names[0]).symlink_to(root / names[1])
            with self.assertRaises(u.UpdateError):
                u.verify_package(root)

    def test_check_only_never_stages_or_switches(self):
        with patch.object(u.os, 'geteuid', return_value=0), patch.object(u.socket, 'gethostname', return_value='volz-db'), \
             patch.object(u, 'verify_package', return_value={'release': 'c' * 16}), \
             patch.object(u, 'private_input', return_value=(b'private synthetic data', {})), \
             patch.object(u, 'Docker', return_value=FakeDocker()), patch.object(u, 'stage_files') as stage, \
             patch.object(u, 'perform_update') as switch, patch.object(u.sys, 'argv', ['update', '--check-only', '--sign-positions-file', '/private/input']), \
             patch('builtins.print') as output:
            u.main()
            stage.assert_not_called()
            switch.assert_not_called()
            self.assertNotIn('PRIVATE_VALUE', output.call_args.args[0])


if __name__ == '__main__':
    unittest.main()

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import client as c
import recovery_monitor as m


class MonitorTests(unittest.TestCase):
    def test_same_process_checks_repeatedly_without_shells(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp)
            stop = Mock()
            stop.is_set.side_effect = [False, False, False, True]
            with patch.object(c, 'recover', return_value={'checked_pending': 0}) as recover, patch.object(c.subprocess, 'Popen') as spawn:
                self.assertEqual(m.monitor(registry, stop=stop, interval=30), 0)
            self.assertEqual(recover.call_count, 3)
            self.assertEqual(stop.wait.call_count, 3)
            spawn.assert_not_called()
            state = c.read(registry / 'recovery-monitor.json')
            self.assertEqual(state['pid'], os.getpid())
            self.assertIsNone(state['error'])

    def test_registry_failure_does_not_stop_monitoring(self):
        with tempfile.TemporaryDirectory() as tmp:
            stop = Mock()
            stop.is_set.side_effect = [False, False, True]
            with patch.object(c, 'recover', side_effect=[ValueError('invalid registry'), {'checked_pending': 1}]):
                self.assertEqual(m.monitor(tmp, stop=stop), 0)
            state = c.read(Path(tmp) / 'recovery-monitor.json')
            self.assertEqual(state['checked_pending'], 1)
            self.assertIsNone(state['error'])

    def test_duplicate_monitor_exits_without_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            with c.Lock(Path(tmp) / 'recovery-monitor.lock'), patch.object(c, 'recover') as recover:
                self.assertEqual(m.monitor(tmp), 0)
            recover.assert_not_called()


if __name__ == '__main__':
    unittest.main()

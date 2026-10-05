"""Renderer only: no new compatibility assertions or transaction decisions."""
import io
import os
import unittest
from unittest.mock import patch
from test_safety import s


class Terminal(io.StringIO):
    def isatty(self): return True


class ProgressTests(unittest.TestCase):
    def test_tty_progress_no_color_and_failure_line(self):
        for no_color in ('','1'):
            out = Terminal()
            with patch.dict(os.environ,TERM='xterm',NO_COLOR=no_color):
                ui = s.UpdateProgress(out); self.assertTrue(ui.enabled)
                ui.event(4,'legacy technical diagnostic')
                with patch.object(s.time,'monotonic',return_value=150): ui.wait(150,0,150)
                ui.sample(150); ui.finish('Stability check failed; rollback required',failed=True)
            text = out.getvalue()
            self.assertIn('[4/5]',text); self.assertIn('150 / 150 s',text)
            self.assertNotIn('legacy technical diagnostic',text); self.assertNotIn('Acceptance sample',text)
            self.assertIn('\n✗ Stability check failed; rollback required',text)
            self.assertEqual('\033[' in text,not bool(no_color))
            self.assertNotIn('\033[?25',text)  # Cursor is never hidden.

    def test_nontty_and_dumb_preserve_line_diagnostics(self):
        for out,term in ((io.StringIO(),'xterm'),(Terminal(),'dumb')):
            with patch.dict(os.environ,TERM=term):
                ui = s.UpdateProgress(out); self.assertFalse(ui.enabled)
                ui.event(2,'Running isolated candidate compatibility checks.')
                with patch.object(s.time,'monotonic',return_value=0),patch.object(s.time,'sleep') as sleep:
                    ui.wait(30,0,150); sleep.assert_called_once_with(30)
                ui.sample(30); ui.finish('failure',failed=True)
            text = out.getvalue()
            self.assertIn('Running isolated',text); self.assertIn('Acceptance sample 30s',text)
            self.assertNotIn('\033',text); self.assertNotIn('\r',text)

    def test_progress_wait_does_not_change_deadline_or_run_checks(self):
        out = Terminal()
        with patch.dict(os.environ,TERM='xterm'),patch.object(s.time,'monotonic',side_effect=[0,1,2,3]),\
             patch.object(s.time,'sleep') as sleep:
            ui = s.UpdateProgress(out); ui.event(4,'legacy'); ui.wait(3,0,150)
        self.assertEqual([call.args[0] for call in sleep.call_args_list],[1,1,1])


if __name__ == '__main__': unittest.main()

"""Renderer only: no new compatibility assertions or transaction decisions."""
import io
import os
import re
from contextlib import redirect_stderr
import unittest
from unittest.mock import patch
from test_safety import s


class Terminal(io.StringIO):
    def isatty(self): return True


class ProgressTests(unittest.TestCase):
    def test_tty_progress_no_color_and_failure_line(self):
        for no_color in (None,'','1'):
            out = Terminal()
            environment = dict(os.environ,TERM='xterm'); environment.pop('NO_COLOR',None)
            if no_color is not None: environment['NO_COLOR']=no_color
            with patch.dict(os.environ,environment,clear=True):
                ui = s.UpdateProgress(out); self.assertTrue(ui.enabled)
                ui.event(4,'legacy technical diagnostic')
                with patch.object(s.time,'monotonic',return_value=150): ui.wait(150,0,150)
                ui.sample(150); ui.finish('Stability check failed; rollback required',failed=True)
            text = out.getvalue()
            self.assertIn('[4/5]',text); self.assertIn('150 / 150 s',text)
            self.assertNotIn('legacy technical diagnostic',text); self.assertNotIn('Acceptance sample',text)
            self.assertIn('\n✗ Stability check failed; rollback required',re.sub(r'\x1b\[[0-9;]*m','',text))
            self.assertEqual('\033[' in text,no_color is None)
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

    def test_russian_all_stages_and_both_acceptance_durations(self):
        out=Terminal()
        with patch.dict(os.environ,TERM='xterm',NO_COLOR='1'):
            ui=s.UpdateProgress(out,language='ru')
            for stage in range(1,6): ui.event(stage,'legacy English diagnostic')
            for stage,total in ((4,150),(5,45)):
                ui.event(stage,'legacy')
                with patch.object(s.time,'monotonic',return_value=total): ui.wait(total,0,total)
            ui.finish('Update succeeded',russian='Обновление завершено')
            ui.log('Rollback complete',russian='Восстановление завершено')
            ui.finish('Manual recovery required',failed=True,russian='Требуется ручное восстановление')
        text=out.getvalue()
        for label in ('Проверка релиза','Проверка совместимости','Подготовка безопасного обновления',
                      'Проверка стабильности','Проверка после перезапуска','150 / 150 с','45 / 45 с',
                      'Подождите','Обновление завершено','Восстановление завершено','Требуется ручное восстановление'):
            self.assertIn(label,text)
        self.assertNotIn('legacy',text); self.assertNotIn('\033',text)
        out=Terminal()
        with patch.dict(os.environ,TERM='xterm'),patch.object(s.time,'monotonic',side_effect=[0,1,2,3]),patch.object(s.time,'sleep') as sleep:
            ui=s.UpdateProgress(out,language='ru'); ui.event(4,'legacy'); ui.wait(3,0,150)
        self.assertEqual([call.args[0] for call in sleep.call_args_list],[1,1,1])

    def test_russian_dumb_terminal_is_plain_and_non_tty_stays_english(self):
        out=Terminal()
        with patch.dict(os.environ,TERM='dumb'):
            ui=s.UpdateProgress(out,language='ru'); self.assertFalse(ui.enabled)
            ui.event(5,'Restart verification'); ui.sample(45)
            with patch.object(s.time,'monotonic',return_value=0),patch.object(s.time,'sleep') as sleep:
                ui.wait(45,0,45); sleep.assert_called_once_with(45)
            ui.finish('Failure',failed=True,russian='Ошибка обновления')
        self.assertIn('Проверка после перезапуска',out.getvalue())
        self.assertIn('Проверка на 45 с',out.getvalue())
        self.assertNotIn('\033',out.getvalue()); self.assertNotIn('\r',out.getvalue())
        out=io.StringIO()
        with patch.dict(os.environ,TERM='xterm',TWM_UI_LANGUAGE='ru'):
            ui=s.UpdateProgress(out,language='ru'); self.assertEqual(ui.language,'en')
            ui.event(1,'Discovering official stable Telemt release.')
        self.assertEqual(out.getvalue(),'Discovering official stable Telemt release.\n')

    def test_russian_engine_results_keep_transaction_authority(self):
        import update_transactions as t
        for outcome in ('success','equal','rollback','critical'):
            with self.subTest(outcome=outcome):
                f=t.Fixture(version='3.5.12' if outcome=='equal' else '3.5.13',
                            fail_new=outcome in ('rollback','critical'))
                self.addCleanup(f.close)
                out=Terminal(); f.engine.progress=t.s.UpdateProgress(out,language='ru')
                if outcome=='critical':
                    original=f.engine.accept
                    def accept(receipt,**kwargs):
                        if receipt==f.old: raise ValueError('fixture prior health failure')
                        return original(receipt,**kwargs)
                    f.engine.accept=accept
                with redirect_stderr(out):
                    if outcome in ('rollback','critical'):
                        with self.assertRaises(ValueError): f.engine.update()
                    else: f.engine.update()
                text=out.getvalue()
                if outcome=='success':
                    self.assertIn('Telemt успешно обновлён: 3.5.12 → 3.5.13',text)
                    self.assertEqual(t.s.UpdateJournal(f.layout).read()['phase'],'COMMITTED')
                elif outcome=='equal':
                    self.assertIn('Уже установлена актуальная версия',text)
                    self.assertEqual(t.s.update_generation(f.layout),f.old)
                elif outcome=='rollback':
                    self.assertIn('Восстановление завершено',text); f.assert_old()
                else:
                    self.assertIn('КРИТИЧЕСКАЯ ОШИБКА',text)
                    self.assertEqual(t.s.UpdateJournal(f.layout).read()['phase'],'CRITICAL')
                    self.assertEqual(f.controller.show()['ActiveState'],'inactive')


if __name__ == '__main__': unittest.main()

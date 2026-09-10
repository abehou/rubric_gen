"""Focused read-only ownership-gate tests; no scientific imports or calls."""
import ast,unittest
from pathlib import Path
from unittest.mock import Mock
source=Path(__file__).with_name('condition_launch.py').read_text()
node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='old_owner_gate')
class GateTests(unittest.TestCase):
 def run_gate(self,outputs):
  process=Mock();process.check_output.side_effect=outputs
  ns={'OLD_JOBS':{'full-trace':'10357852'},'subprocess':process}
  exec(compile(ast.Module(body=[node],type_ignores=[]),'<gate>','exec'),ns)
  return ns['old_owner_gate']('full-trace')
 def test_live_owner_rejected(self):
  with self.assertRaisesRegex(RuntimeError,'still present'):self.run_gate(['10357852\n'])
 def test_absent_queue_without_terminal_accounting_rejected(self):
  with self.assertRaisesRegex(RuntimeError,'terminal state not established'):self.run_gate(['10358980\n',''])
 def test_accounting_running_rejected(self):
  with self.assertRaisesRegex(RuntimeError,'terminal state not established'):self.run_gate(['','10357852|RUNNING|0:0\n'])
if __name__=='__main__':unittest.main()

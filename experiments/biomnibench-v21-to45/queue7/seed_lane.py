"""Run the same native seed operation for disjoint final-fifteen task lanes."""
import sys
from make_configs import ROOT,BUNDLE,TASKS,RUN
from check_inputs import check
from input_tools import run_seed_lane
if __name__=='__main__':
    raise SystemExit(run_seed_lane(int(sys.argv[1]),root=ROOT,bundle=BUNDLE,
                                  tasks=TASKS,run=RUN,check_task=check))

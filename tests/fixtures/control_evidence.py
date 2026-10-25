"""Fresh synthetic controller receipts for unit fixtures, never runtime imports."""
from dataclasses import replace
from types import SimpleNamespace
from fabriquinha.quality import Quality


def red_evidence(store,project,author,baseline,snapshot):
    def execute(run,tree,phase):
        cases=['existing'] if phase=='baseline' else ['existing','new']
        failures=[] if phase=='baseline' else [dict(case='new',assertion=True,
            frames=[dict(file=project.tests_dir+'/test_new.py',function='test_behavior')])]
        return store.record('suite_job',run.binding(),dict(exit_code=int(bool(failures)),
            report=dict(version=1,tests_run=len(cases),cases=cases,failures=failures,
                errors=[],skips=[],expected_failures=[],unexpected_successes=[]),
            identity=dict(binding=run.binding(),project=project.fingerprint(),snapshot=tree,phase=phase,image=project.validation_image),
            sandbox=dict(network='none',snapshot='readonly',user='65534:65534')))
    board=SimpleNamespace(ensure=lambda run:None)
    return Quality(project,store,SimpleNamespace(run=execute),board).red(author,baseline,snapshot)


def frozen_evidence(store,project,author,baseline,snapshot,reviewer):
    red=red_evidence(store,project,author,baseline,snapshot)
    board=SimpleNamespace(ensure=lambda run:None,input=lambda *a,**kw:red)
    run=replace(author,number=author.number+1,actor=reviewer,reviewing=True)
    return Quality(project,store,None,board).tests_review(run,red,
        dict(decision='approve',reason='Synthetic unit fixture acceptance reviewed.',findings=[]))

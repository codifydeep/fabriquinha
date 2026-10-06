"""Private controller receipts. Runner is controller-supplied, never agent input."""
import hashlib,json,re
from product_workspace import digest
from product_tdd_contract import EvidenceRejected,red_mismatch,rejection

def test_files(files):
    return {n:v for n,v in files.items() if n.startswith('tests/') or re.search(r'\.(test|spec)\.[cm]?[jt]sx?$',n)}

class TDD:
    def __init__(self,workspace,image):
        if not re.fullmatch(r'sha256:[0-9a-f]{64}',image):raise ValueError('pinned image required')
        self.w=workspace;self.image=image;self.db=workspace.db
        self.db.execute('CREATE TABLE IF NOT EXISTS product_test_receipts(attempt TEXT,task TEXT,run INTEGER,version INTEGER,phase TEXT,receipt TEXT,PRIMARY KEY(attempt,task,run,version,phase))');self.db.commit()
    def execute(self,request,phase,runner):
        if phase not in ('red','green','suite'):raise ValueError('fixed test phase required')
        current,row=self.w.state(request,write=True);draft=self.w.read_draft(request)
        cards=getattr(self.w.claim,'cards',{})
        card=cards.get(current['task'],{}) if isinstance(cards,dict) else {}
        structured=card.get('tdd_contract')=='case-inventory-v2'
        baseline=None
        if structured:
            from product_tdd_inventory import baseline as execute_baseline
            baseline=execute_baseline(self,current,card,runner)
        tests=test_files(draft['files'])
        if not tests:raise ValueError('test files required')
        key=(current['attempt'],current['task'],current['run'],draft['version'],phase)
        previous=self.db.execute('SELECT receipt FROM product_test_receipts WHERE attempt=? AND task=? AND run=? AND version=? AND phase=?',key).fetchone()
        if previous:return json.loads(previous[0])
        red=None
        if phase!='red' and not (structured and card.get('tdd_mode') in ('refactor','revalidation')):
            row=self.db.execute("SELECT receipt FROM product_test_receipts WHERE attempt=? AND task=? AND phase='red' ORDER BY rowid DESC LIMIT 1",key[:2]).fetchone()
            red=json.loads(row[0]) if row else None
            mismatch=red_mismatch(red,digest(tests),draft['base'],self.image)
            if mismatch:raise EvidenceRejected(mismatch,red_version=red.get('version') if red else None,red_diagnostic=red.get('diagnostic') if red else None,current_version=draft['version'])
        if phase=='suite':
            row=self.db.execute("SELECT receipt FROM product_test_receipts WHERE attempt=? AND task=? AND phase='green' ORDER BY rowid DESC LIMIT 1",key[:2]).fetchone()
            green=json.loads(row[0]) if row else None
            if not green or not green['accepted'] or green['source_sha256']!=draft['sha256'] or green['image']!=self.image:raise PermissionError('same-source Green required')
        result=runner(draft['files'],self.image)
        self.w.state(request,write=True)
        if self.w.read_draft(request)['sha256']!=draft['sha256']:raise PermissionError('draft changed during test')
        expected={n:hashlib.sha256(v.encode()).hexdigest() for n,v in draft['files'].items()}
        if result.get('snapshot')!=expected or result.get('image')!=self.image:raise PermissionError('runner source/image mismatch')
        output=result.get('output','');count=re.search(r'^# tests (\d+)$',output,re.M)
        failures=re.search(r'^# fail (\d+)$',output,re.M)
        # Conservative Node-test fixture classifier; full TS suite adapter still pending.
        ignored=any(int(n)>0 for n in re.findall(r'^# (?:skipped|cancelled|todo) (\d+)$',output,re.M))
        complete=bool(count and int(count[1])>0 and failures and not ignored)
        accepted=bool(complete and ((phase=='red' and result['exit_code']==1 and int(failures[1])>0 and 'ERR_ASSERTION' in output)
            or (phase!='red' and result['exit_code']==0 and int(failures[1])==0)))
        receipt=dict(attempt=current['attempt'],task=current['task'],run=current['run'],version=draft['version'],phase=phase,
            diagnostic=rejection(phase,accepted,output,result['exit_code'],complete,int(failures[1]) if failures else 0),
            base=draft['base'],source_sha256=draft['sha256'],tests_sha256=digest(tests),image=self.image,
            accepted=accepted,exit_code=result['exit_code'],log_sha256=hashlib.sha256(output.encode()).hexdigest(),output=output[-12000:],
            runner='fixed_node_test_all',scope='prototype_tdd_evidence_not_release')
        if structured:
            from product_tdd_inventory import evaluate
            maintenance=None
            if card.get('reviewed_test_maintenance'):
                evidence=self.db.execute('SELECT receipt FROM test_maintenance_applied WHERE proposal_sha=?',(card['reviewed_test_maintenance']['proposal_sha256'],)).fetchone()
                if evidence:maintenance=json.loads(evidence[0])['validation']
            try:receipt['inventory']=evaluate(card,baseline,result,phase,draft['files'],maintenance)
            except (ValueError,PermissionError) as exc:
                receipt.update(accepted=False,diagnostic=dict(code='CASE_EVIDENCE_REJECTED',detail=str(exc),next_action='Preserve cases and diagnose actual failed assertions; independent review must check relevance.'))
        with self.db:self.db.execute('INSERT INTO product_test_receipts VALUES(?,?,?,?,?,?)',(*key,json.dumps(receipt)))
        return receipt
    def submission_evidence(self,request):
        draft=self.w.read_draft(request);current,_=self.w.state(request,write=True)
        row=self.db.execute("SELECT receipt FROM product_test_receipts WHERE attempt=? AND task=? AND phase='suite' ORDER BY rowid DESC LIMIT 1",(current['attempt'],current['task'])).fetchone()
        proof=json.loads(row[0]) if row else None
        if not proof or not proof['accepted'] or proof['source_sha256']!=draft['sha256'] or proof['image']!=self.image:raise PermissionError('exact full-suite receipt required')
        return proof

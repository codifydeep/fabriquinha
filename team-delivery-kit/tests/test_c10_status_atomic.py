import unittest
from c10_status_atomic import validate

COMPLETE="""click(byId['filter-open']);const a=calls.length-1;
click(byId['filter-completed']);const b=calls.length-1;
out.status_genA_urls=calls.slice(a).map(c=>c.url);
out.status_genB_urls=calls.slice(b).map(c=>c.url);
resolveNewest({items:[{title:'CURRENT COMPLETED',completed:true}]});
return flush().then(function(){out.rendered_after_current_status=renderedTitles();
resolveOldest({items:[{title:'STALE OPEN',completed:false}]});
return flush().then(function(){out.rendered_after_stale_status=renderedTitles();out.pending_left=pending.length;});});
"""

class StatusAtomicTests(unittest.TestCase):
    def test_packaged_registry_probe_has_all_public_proxy_dependencies(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        proxy=(root/'Dockerfile.model-proxy').read_text();broker=(root/'Dockerfile.broker').read_text()
        for line in proxy.splitlines():
            if line.startswith('COPY ') and line.split()[1].endswith('.py'):
                self.assertIn(line,broker)
    def args(self,new=COMPLETE):return {'edits':[{'start_line':534,'end_line':536,'new':new}]}
    def test_complete_multiline_shape_is_not_functional_approval(self):
        self.assertIsNone(validate(self.args()))
    def test_three_partial_replacements_or_wrong_window_rejected(self):
        for args in ({'edits':[{'start_line':i,'end_line':i,'new':'click(x);'} for i in (534,535,536)]},
                {'edits':[{'start_line':533,'end_line':536,'new':COMPLETE}]},self.args('click(x);')):
            with self.assertRaisesRegex(ValueError,'atomic STATUS'):validate(args)
    def test_missing_observations_constants_comments_and_strings_rejected(self):
        for new in (COMPLETE.replace('out.pending_left=pending.length','out.pending_left=0'),
                COMPLETE.replace('out.rendered_after_current_status=renderedTitles()','out.rendered_after_current_status=[]'),
                COMPLETE.replace('out.status_genA_urls=calls.slice(a).map(c=>c.url)','out.status_genA_urls=[]'),
                '// '+COMPLETE.replace('\n','\n// '),repr(COMPLETE)+';',
                COMPLETE.replace("click(byId['filter-open'])",'// missing event'),
                COMPLETE.replace('resolveOldest({items:', 'resolveOldest({wrong:')):
            with self.assertRaisesRegex(ValueError,'atomic STATUS'):validate(self.args(new))

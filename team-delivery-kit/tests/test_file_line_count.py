import unittest
import shlex
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from broker.install_file_line_count import adapt,COUNT,TAIL


SOURCE='''class Reader:
    def read(self,path,offset=1,limit=2):
        file_size=Path(path).stat().st_size
        end_line=offset+limit-1
        read_output=self._exec(f"sed -n '{offset},{end_line}p' {self._escape_shell_arg(path)} | cut -b1-20000").stdout
'''+COUNT+'''        truncated=total_lines>end_line
'''+TAIL+'''        return ReadResult(total_lines=total_lines,content=read_output,truncated=truncated)
'''


class FileLineCountTests(unittest.TestCase):
    def reader(self,source):
        namespace={'Path':Path,'ReadResult':SimpleNamespace,'_strip_terminal_fence_leaks':lambda x:x}
        exec(source,namespace)
        reader=namespace['Reader']()
        reader._escape_shell_arg=shlex.quote
        def command(cmd):
            result=subprocess.run(cmd,shell=True,capture_output=True,text=True)
            return SimpleNamespace(stdout=result.stdout,exit_code=result.returncode)
        reader._exec=command
        return reader

    def test_actual_shell_counts_nonterminated_lines_and_preserves_pagination(self):
        reader=self.reader(adapt(SOURCE))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'case.py'
            for content,count in [('',0),('import os',1),('import os\n',1),
                                  ('a\nb',2),('a\nb\n',2),('a\nb\nc',3),
                                  ('import os'+' '*6135,1)]:
                path.write_text(content)
                result=reader.read(str(path))
                self.assertEqual(result.total_lines,count)
                self.assertEqual(result.truncated,count>2)
                if count<=2:self.assertEqual(result.content,content)
            path.write_text('a\nb\nc')
            self.assertEqual(reader.read(str(path),offset=3).content,'c')

    def test_unparseable_or_failed_count_is_not_promoted_to_read_evidence(self):
        for stdout,exit_code in [('invalid',0),('0',1),('-1',0)]:
            reader=self.reader(adapt(SOURCE));reader._exec=lambda *_:SimpleNamespace(stdout=stdout,exit_code=exit_code)
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)/'case.py';p.write_text('x')
                self.assertEqual(reader.read(str(p)).error,'Cannot verify file line count.')

    def test_source_drift_and_double_install_are_rejected(self):
        for source in (SOURCE.replace('# Get total line count','# Changed'),adapt(SOURCE)):
            with self.assertRaises(ValueError):adapt(source)

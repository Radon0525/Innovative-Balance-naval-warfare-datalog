from pathlib import Path
import json, subprocess, sys, unittest
import frida
from navalhitrecorder import source as production_source
BASE=Path(__file__).resolve().parent
def source(config):
    text=production_source(config)
    if config.get('test'):text+='\n'+(BASE/'test_fixture.js').read_text(encoding='utf-8')
    return text

class NativeTests(unittest.TestCase):
    def run_mode(self,mode):
        child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'])
        session=None
        try:
            session=frida.attach(child.pid)
            script=session.create_script(source({'test':True,'mode':mode}))
            errors=[]
            script.on('message',lambda m,d: errors.append(m) if m['type']=='error' else None)
            script.load()
            self.assertEqual(script.exports_sync.exercise(1000,4),[0]*4)
            expected=([12000,4000,8000] if mode!='air' else [0]*3)
            expected+=([12000,604000,104000,4000] if mode!='heavy' else [0]*4)
            expected+=([4000,4000] if mode!='air' else [0,0])+[0]
            self.assertEqual(list(map(int,script.exports_sync.snapshot())),expected)
            script.exports_sync.invalid()
            expected[-1]={'both':4,'heavy':1,'air':3}[mode]
            self.assertEqual(list(map(int,script.exports_sync.stop())),expected)
            self.assertEqual(script.exports_sync.exercise(3,1),[0])
            self.assertEqual(list(map(int,script.exports_sync.snapshot())),expected)
            self.assertEqual(errors,[])
            script.unload()
        finally:
            if session:session.detach()
            child.terminate();child.wait(timeout=10)
    def test_both(self):self.run_mode('both')
    def test_heavy_only(self):self.run_mode('heavy')
    def test_air_only(self):self.run_mode('air')
if __name__=='__main__':unittest.main(verbosity=2)

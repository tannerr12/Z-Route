import io
import json
import tempfile
import unittest
from pathlib import Path
from app import create_app

class IncidentsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=create_app(str(Path(self.temp.name)/'incidents.sqlite3'),'r'*40,'a'*40,'https://tannerr12.github.io')
        self.report=dict(player_id='123',player_name='<script>bad</script>',reporter='Member',occurred='2026-11-20T10:00:00Z',category='conduct',description='A report needing leadership review.',evidence='https://example.com/evidence')
    def call(self,method='GET',path='/incidents',key='r'*40,body=None,origin='https://tannerr12.github.io'):
        raw=json.dumps(body).encode() if body is not None else b'';status=[]
        env={'REQUEST_METHOD':method,'PATH_INFO':path,'HTTP_AUTHORIZATION':'Bearer '+key,'HTTP_ORIGIN':origin,'CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw)}
        result=b''.join(self.app(env,lambda s,h:status.append((int(s.split()[0]),dict(h)))))
        return status[0][0],json.loads(result),status[0][1]
    def test_no_key_and_wrong_origin_are_denied(self):
        self.assertEqual(self.call(key='')[0],401)
        self.assertEqual(self.call(origin='https://evil.example')[0],403)
    def test_reporting_cannot_confirm_but_review_key_can(self):
        code,record,_=self.call('POST',body={**self.report,'status':'confirmed','penalty_points':100})
        self.assertEqual(code,201);self.assertEqual(record['status'],'reported');self.assertEqual(self.call()[1]['incidents'][0]['penalty_points'],0)
        path='/incidents/'+record['id']
        self.assertEqual(self.call('PATCH',path,body={'status':'confirmed'})[0],403)
        self.assertEqual(self.call('PATCH',path,key='a'*40,body={'status':'confirmed','penalty_points':5})[0],200)
        items=self.call()[1]['incidents'];self.assertEqual(len(items),1);self.assertEqual(items[0]['status'],'confirmed');self.assertEqual(items[0]['penalty_points'],5)
    def test_validation_and_cache(self):
        for change in [{'player_id':'invalid'},{'evidence':'javascript:alert(1)'},{'description':'short'},{'occurred':'2026-11-20'},{'category':'unrecognized'}]:
            self.assertEqual(self.call('POST',body={**self.report,**change})[0],400)
        self.assertEqual(self.call()[2]['Cache-Control'],'no-store')
        self.assertEqual(self.call('POST',body={**self.report,'description':'x'*17000})[0],413)
    def test_persistence_and_key_rotation(self):
        self.call('POST',body=self.report)
        self.app=create_app(str(Path(self.temp.name)/'incidents.sqlite3'),'n'*40,'z'*40,'https://tannerr12.github.io')
        self.assertEqual(self.call()[0],401)
        self.assertEqual(len(self.call(key='n'*40)[1]['incidents']),1)
    def test_distinct_strong_keys_required(self):
        with self.assertRaises(ValueError):create_app(str(Path(self.temp.name)/'other'),'short','short','https://tannerr12.github.io')

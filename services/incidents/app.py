"""Private incident API. Run behind HTTPS; no browser-embedded secret or public data file."""
import hmac
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

CATEGORIES={'attack','conduct','missed_event','other'}


def create_app(database,report_key,review_key,origin):
    if min(len(report_key),len(review_key))<32 or hmac.compare_digest(report_key,review_key):
        raise ValueError('Provide distinct random reporting and review keys of at least 32 characters')
    if not origin.startswith('https://') or urlparse(origin).path not in ('','/'):
        raise ValueError('An exact HTTPS dashboard origin is required')
    Path(database).parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, created TEXT, payload TEXT, status TEXT, reviewed TEXT, penalty INTEGER)')
        db.execute('CREATE TABLE IF NOT EXISTS audit (incident TEXT, changed TEXT, status TEXT, penalty INTEGER)')

    def application(env,start):
        headers=[('Content-Type','application/json'),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff')]
        supplied_origin=env.get('HTTP_ORIGIN','')
        def reply(code,value):
            start(str(code)+' '+{200:'OK',201:'Created',204:'No Content',400:'Bad Request',401:'Unauthorized',403:'Forbidden',404:'Not Found',413:'Payload Too Large',500:'Internal Server Error'}[code],headers)
            return [json.dumps(value).encode()]
        if supplied_origin and supplied_origin!=origin:return reply(403,{'error':'Origin denied'})
        if supplied_origin:
            headers.extend([('Access-Control-Allow-Origin',origin),('Vary','Origin')])
        method=env['REQUEST_METHOD']
        if method=='OPTIONS':
            headers.extend([('Access-Control-Allow-Headers','Authorization, Content-Type'),('Access-Control-Allow-Methods','GET, POST, PATCH')])
            return reply(204,{})
        token=env.get('HTTP_AUTHORIZATION','').removeprefix('Bearer ')
        reviewer=hmac.compare_digest(token.encode(),review_key.encode())
        if not reviewer and not hmac.compare_digest(token.encode(),report_key.encode()):return reply(401,{'error':'Access key required'})
        path=env.get('PATH_INFO','')
        try:
            with sqlite3.connect(database) as db:
                if method=='GET' and path=='/incidents':
                    rows=db.execute('SELECT id,created,payload,status,reviewed,penalty FROM incidents ORDER BY created DESC LIMIT 500').fetchall()
                    return reply(200,{'reviewer':reviewer,'incidents':[dict(id=i,created=c,**json.loads(p),status=s,reviewed=r,penalty_points=n) for i,c,p,s,r,n in rows]})
                if method not in ('POST','PATCH'):return reply(404,{'error':'Route not found'})
                size=int(env.get('CONTENT_LENGTH') or 0)
                if not 0<size<=16384:return reply(413,{'error':'Request exceeds limit or is empty'})
                body=json.loads(env['wsgi.input'].read(size))
                if not isinstance(body,dict):raise ValueError()
                now=datetime.now(timezone.utc).isoformat()
                if method=='POST' and path=='/incidents':
                    payload={k:str(body.get(k,'')).strip() for k in ['player_id','player_name','reporter','occurred','category','description','evidence']}
                    if not payload['player_id'].isdigit() or len(payload['player_id'])>30:raise ValueError()
                    if any(not payload[k] or len(payload[k])>120 for k in ['player_name','reporter']):raise ValueError()
                    if not 10<=len(payload['description'])<=4000 or payload['category'] not in CATEGORIES:raise ValueError()
                    dt=datetime.fromisoformat(payload['occurred'].replace('Z','+00:00'))
                    if dt.tzinfo is None:raise ValueError()
                    payload['occurred']=dt.astimezone(timezone.utc).isoformat()
                    evidence=urlparse(payload['evidence'])
                    if payload['evidence'] and (len(payload['evidence'])>2000 or evidence.scheme!='https' or not evidence.netloc or evidence.username):raise ValueError()
                    identifier=str(uuid4())
                    db.execute('INSERT INTO incidents VALUES (?,?,?,?,?,?)',(identifier,now,json.dumps(payload),'reported',None,0))
                    db.execute('INSERT INTO audit VALUES (?,?,?,?)',(identifier,now,'reported',0))
                    return reply(201,{'id':identifier,'status':'reported'})
                if method=='PATCH' and path.startswith('/incidents/'):
                    if not reviewer:return reply(403,{'error':'Review key required'})
                    status=body.get('status')
                    if status not in ('confirmed','dismissed','reported'):raise ValueError()
                    penalty=body.get('penalty_points',0) if status=='confirmed' else 0
                    if type(penalty) is not int or not 0<=penalty<=100:raise ValueError()
                    identifier=path.split('/')[-1]
                    changed=db.execute('UPDATE incidents SET status=?,reviewed=?,penalty=? WHERE id=?',(status,now,penalty,identifier)).rowcount
                    if not changed:return reply(404,{'error':'Incident not found'})
                    db.execute('INSERT INTO audit VALUES (?,?,?,?)',(identifier,now,status,penalty))
                    return reply(200,{'status':status})
                return reply(404,{'error':'Route not found'})
        except (ValueError,TypeError,OverflowError):return reply(400,{'error':'Invalid incident fields'})
        except sqlite3.Error:return reply(500,{'error':'Private storage unavailable'})
    return application


if __name__=='__main__':
    from wsgiref.simple_server import make_server,WSGIRequestHandler
    class QuietHandler(WSGIRequestHandler):
        def log_message(self,*args):pass
    app=create_app(os.environ['INCIDENT_DB'],os.environ['INCIDENT_REPORT_KEY'],os.environ['INCIDENT_REVIEW_KEY'],os.environ['INCIDENT_ORIGIN'])
    with make_server('127.0.0.1',int(os.environ.get('PORT','8080')),app,handler_class=QuietHandler) as server:
        server.serve_forever()

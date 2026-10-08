#!/usr/bin/env python3
"""Execute the additive integration study with installed libraries and no patches.

Selection and expected dimensions are described in study/extension-protocol.md.
New observations never overwrite or silently relabel the archived first study.
"""
from pathlib import Path
import argparse,datetime,hashlib,importlib.metadata as md,json,logging,os,random,sys,tempfile,time,signal
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
# Disallow proxy inheritance and cloud credential discovery before importing clients.
for key in list(os.environ):
    if key.lower() in ('http_proxy','https_proxy','all_proxy') or key in ('AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','AWS_SESSION_TOKEN','AWS_PROFILE'):
        os.environ.pop(key,None)
os.environ.update(NO_PROXY='127.0.0.1,localhost',AWS_EC2_METADATA_DISABLED='true',AWS_CONFIG_FILE=os.devnull,AWS_SHARED_CREDENTIALS_FILE=os.devnull,AWS_NEW_RETRIES_2026='true')
from retryscope.range_fixture import RangeFixture,PAYLOAD
from retryscope.audit import audit,AuditIntent
from retryscope.ordinary import checked_identity_body
logging.basicConfig(level=logging.ERROR)
EXPECTED=PAYLOAD.decode('ascii')
HASH=hashlib.sha256(PAYLOAD).hexdigest()

class IntegrityMismatch(ValueError):
    """The complete response differs from the intended registered object."""

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def matrix():
    cases=[]
    for mode in ('pooch_hash0','pooch_hash1','pooch_unchecked1','requests_old_length','requests_new_length','requests_old_hash','requests_new_hash'):
        for scenario in ('success','transient','persistent','denied','truncated_once','corrupt_once','corrupt_always'):
            cases.append({'id':mode+'_'+scenario,'family':'download','mode':mode,'scenario':scenario})
    for size in (3,11,23):
        for cut in (7,31,63):
            cases.append({'id':f'smart_range_{size}_{cut}','family':'range_recovery','mode':'smart','scenario':'truncated_once','read_size':size,'cut':cut})
        cases.append({'id':f'smart_range_{size}_healthy','family':'range_recovery','mode':'smart','scenario':'success','read_size':size,'cut':7})
    for size in (8,17,31):
        for mode in ('known_size','metadata'):
            cases.append({'id':f'fsspec_{mode}_{size}','family':'constituent_reads','mode':mode,'scenario':'success','read_size':size})
    return cases

def run(case,seed):
    random.seed(seed)
    started=time.monotonic();witnesses=[];operations=[];admissions=[]
    result={'id':case['id'],'seed':seed,'case':case,'phase':'extension','outcome':'error'}
    server=RangeFixture(case['scenario'],cut=case.get('cut',7),s3=case['mode']=='smart')
    with server:
        body=None;complete=False
        try:
            if case['family']=='download':
                mode=case['mode'];previous=None
                if mode.startswith('pooch'):
                    import pooch
                    pooch.get_logger().setLevel(logging.ERROR)
                    with tempfile.TemporaryDirectory(prefix='retryscope-pooch-') as tmp:
                        p=pooch.create(path=tmp,base_url=server.url,registry={'data':'sha256:'+HASH if 'unchecked' not in mode else None},retry_if_failed=0 if mode.endswith('0') else 1)
                        real=pooch.HTTPDownloader(progressbar=False,timeout=.4,chunk_size=16)
                        def downloader(url,output_file,pooch_obj):
                            nonlocal previous
                            admissions.append(time.monotonic()-started)
                            before=server.count;hook=[]
                            # Instrument a public downloader callback. Its write/read behavior is unchanged.
                            real.kwargs['hooks']={'response':[lambda r,*a,**k:hook.append(r.status_code)]}
                            w={'id':before+1,'role':'initial' if previous is None else 'retry','attribution_witness':'pooch downloader callback entry'}
                            if previous:w.update(retry_of=previous['id'],cause=previous['cause'])
                            witnesses.append(w)
                            try:
                                real(url,output_file,pooch_obj)
                                candidate=Path(output_file).read_bytes()
                                cause={'kind':'content_mismatch'} if hashlib.sha256(candidate).hexdigest()!=HASH else {'kind':'unknown'}
                            except Exception as e:
                                cause={'kind':'status','received_status':hook[-1]} if hook and hook[-1]>=400 else {'kind':'body_error'} if hook else {'kind':'transport_error'}
                                operations.append({'id':w['id'],'outcome':'error','exception':type(e).__name__,'status':hook[-1] if hook else None})
                                previous={'id':w['id'],'cause':cause};raise
                            previous={'id':w['id'],'cause':cause}
                            operations.append({'id':w['id'],'outcome':'returned','candidate_hash':hashlib.sha256(candidate).hexdigest()})
                        try:
                            output=p.fetch('data',downloader=downloader);body=Path(output).read_bytes();complete=True
                        finally:
                            result['published_file_exists']=(Path(tmp)/'data').is_file()
                            result['cache_files']=[x.name for x in Path(tmp).iterdir()]
                else:
                    if 'old' in mode:from pip._vendor import requests
                    else:import requests
                    session=requests.Session();session.trust_env=False
                    try:
                        for attempt in range(2):
                            admissions.append(time.monotonic()-started)
                            hook=[];before=server.count
                            w={'id':before+1,'role':'initial' if attempt==0 else 'retry','attribution_witness':'explicit ordinary outer loop'}
                            if previous:w.update(retry_of=previous['id'],cause=previous['cause'])
                            witnesses.append(w)
                            try:
                                with session.get(server.url+'/data',timeout=.4,hooks={'response':[lambda r,*a,**k:hook.append(r.status_code)]}) as response:
                                    candidate=checked_identity_body(response,requests.exceptions.ChunkedEncodingError)
                                if mode.endswith('hash') and hashlib.sha256(candidate).hexdigest()!=HASH:
                                    raise IntegrityMismatch('known object hash differs')
                                body=candidate;complete=True;break
                            except Exception as e:
                                status=hook[-1] if hook else None
                                cause={'kind':'content_mismatch'} if isinstance(e,IntegrityMismatch) else {'kind':'status','received_status':status} if status is not None and status>=400 else {'kind':'body_error'} if hook else {'kind':'transport_error'}
                                operations.append({'id':w['id'],'outcome':'error','exception':type(e).__name__,'status':status})
                                previous={'id':w['id'],'cause':cause}
                                eligible=status==503 or (status is None or status<400) and isinstance(e,(IntegrityMismatch,requests.exceptions.ChunkedEncodingError,requests.exceptions.ConnectionError,requests.exceptions.Timeout))
                                if not eligible or attempt==1:raise
                                time.sleep(.01)
                    finally:session.close()
            elif case['family']=='range_recovery':
                import boto3,smart_open
                from botocore.config import Config
                from botocore import UNSIGNED
                client=boto3.session.Session().client('s3',endpoint_url=server.url,region_name='us-east-1',config=Config(signature_version=UNSIGNED,retries={'mode':'standard','total_max_attempts':1},read_timeout=.4,connect_timeout=.4,proxies={},s3={'addressing_style':'path'}))
                sdk_events=[]
                def sdk_hook(**kw):
                    response=kw.get('response')
                    sdk_events.append({'t':time.monotonic(),'attempts':kw.get('attempts'),'status':response[0].status_code if response else None})
                client.meta.events.register('needs-retry.s3.GetObject',sdk_hook)
                chunks=[]
                try:
                    with smart_open.open('s3://local-bucket/key','rb',compression='disable',transport_params={'client':client,'buffer_size':case['read_size']}) as f:
                        while True:
                            before=server.count;piece=f.read(case['read_size'])
                            operations.append({'api':'read','requested':case['read_size'],'bytes':len(piece),'wire_before':before,'wire_after':server.count})
                            if not piece:break
                            chunks.append(piece)
                    body=b''.join(chunks);complete=True
                    result['sdk_events']=sdk_events
                finally:client.close()
                # No claim to have directly witnessed the internal body-error catch.
                # Source-backed mechanism + bytes are analyzed separately; classification abstains.
            else:
                import aiohttp
                from fsspec.implementations.http import HTTPFileSystem
                fs=HTTPFileSystem(block_size=case['read_size'],cache_type='none',skip_instance_cache=True,client_kwargs={'trust_env':False,'timeout':aiohttp.ClientTimeout(total=2,sock_read=.4)})
                try:
                    kw={'size':len(PAYLOAD)} if case['mode']=='known_size' else {}
                    with fs.open(server.url+'/data','rb',**kw) as f:
                        chunks=[]
                        while True:
                            before=server.count;piece=f.read(case['read_size'])
                            operations.append({'api':'read','requested':case['read_size'],'bytes':len(piece),'wire_before':before,'wire_after':server.count})
                            if not piece:break
                            chunks.append(piece)
                        body=b''.join(chunks);complete=True
                    # No failure was observed in these source-guided healthy constituent reads.
                    for e in server.events:
                        if e['kind']=='arrival':
                            witnesses.append({'id':e['id'],'role':'initial' if e['id']==1 else 'constituent','attribution_witness':'healthy HEAD/byte-range plan and application read boundaries'})
                finally:
                    if fs._session is not None:fs.close_session(fs.loop,fs._session)
            result['outcome']='success'
        except Exception as e:
            result.update(outcome='error',exception=type(e).__name__,error_message=str(e).replace(server.url,'<loopback>')[:200])
        elapsed=time.monotonic()-started
        quiet=server.quiesce()
        arrivals=[dict(e) for e in server.events if e['kind']=='arrival']
        by_id={w['id']:w for w in witnesses}
        for e in arrivals:e.update(by_id.get(e['id'],{}))
        result.update(arrivals=arrivals,events=server.events,wire_attempts=server.count,arrival_stream_complete=quiet and not server.cap_exceeded,
            retry_attribution_complete=case['family']!='range_recovery' and len(arrivals)==len(witnesses),operations=operations,
            payload=body.decode('ascii') if body is not None else None,payload_complete=complete,
            body_elapsed_s=elapsed,body_complete=True,cleanup_elapsed_s=elapsed,cleanup_complete=True,
            admissions_s=admissions,admissions_complete=case['family']=='download')
    # A content-success obligation is source-backed for registered Pooch; hash/length
    # ordinary baselines are additionally tested against the same explicit object identity.
    content_intent=AuditIntent(expected_payload=EXPECTED,provenance='registered object identity (Pooch); explicit same-object probe for other readers')
    result['content_audit']=audit(result,content_intent)
    cap=1 if case['mode'].endswith('0') else 2
    retry_intent=AuditIntent(max_wire_attempts=cap if case['family']=='download' else None,retryable_statuses=(503,),allow_body_recovery=True,allow_transport_retry=True,allow_integrity_retry=True,provenance='local selective-retry probe; not a documented Pooch 400 exclusion')
    result['retry_audit']=audit(result,retry_intent)
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True,type=Path);p.add_argument('--pilot',action='store_true');p.add_argument('--smoke',action='store_true');a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=False)
    cases=matrix();seeds=[401] if a.pilot else [601] if a.smoke else list(range(501,507))
    if a.smoke:cases=[c for c in cases if c['id'] in ('pooch_hash1_corrupt_once','requests_old_length_corrupt_once','smart_range_3_31','fsspec_metadata_17')]
    freeze={'utc':datetime.datetime.now(datetime.UTC).isoformat(),'phase':'pilot' if a.pilot else 'smoke' if a.smoke else 'evaluation','cases':cases,'seeds':seeds,'versions':{p:md.version(p) for p in ('pooch','fsspec','aiohttp','requests','urllib3','boto3','botocore','smart_open','pip')},'sources':{str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),ROOT/'src/retryscope/audit.py',ROOT/'src/retryscope/range_fixture.py',ROOT/'study/extension-protocol.md']}}
    (a.out/'freeze.json').write_text(json.dumps(freeze,indent=2)+'\n')
    def timeout(*_):raise RuntimeError('bounded operation watchdog fired')
    signal.signal(signal.SIGALRM,timeout)
    with (a.out/'records.jsonl').open('x') as output:
        for seed in seeds:
            ordered=cases[:];random.Random(seed).shuffle(ordered)
            for case in ordered:
                signal.setitimer(signal.ITIMER_REAL,25)
                try:r=run(case,seed)
                finally:signal.setitimer(signal.ITIMER_REAL,0)
                output.write(json.dumps(r,allow_nan=False)+'\n');output.flush()
            print('completed seed',seed,flush=True)
if __name__=='__main__':main()

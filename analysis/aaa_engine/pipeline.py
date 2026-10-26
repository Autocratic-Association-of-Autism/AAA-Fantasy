"""Automated forecast: download validated snapshot, backtest, schedule gate, optimization."""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import json,sys,hashlib,os
from .download_export import download_export
from .fetch_kickoffs import fetch
from .validate import validate
from .cli import summarize


def run(repo, token, export_run_id=0, output_dir='forecast_output', week=None):
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    info=download_export(repo,export_run_id,token,str(out/'current_export.json'))
    snapshot=json.loads((out/'current_export.json').read_text())
    validation=validate(snapshot)
    (out/'validation.json').write_text(json.dumps(validation,indent=2))
    current=int(snapshot['League'][0]['current_week'])
    year=int(snapshot['League'][0]['season'])
    now=datetime.now(timezone.utc)
    if week is None:
        schedule=fetch(year,current)
        remaining=sum(datetime.fromisoformat(t.replace('Z','+00:00'))>now
                      for t in schedule['kickoffs'].values())//2
        if remaining<2 and current<int(snapshot['League'][0]['regular_season_weeks']):
            week=current+1;schedule=fetch(year,week)
        else:week=current
    else:schedule=fetch(year,week)
    (out/'nfl_kickoffs.json').write_text(json.dumps(schedule,indent=2))
    context_file=os.environ.get('FORECAST_CONTEXT_FILE')
    context=json.loads(Path(context_file).read_text()) if context_file else {}
    forecast=summarize(snapshot,week,1,now.isoformat(),schedule,context=context)
    forecast['source_run_id']=info['workflow_run']
    forecast['snapshot_sha256']=hashlib.sha256((out/'current_export.json').read_bytes()).hexdigest()
    forecast['schedule_sha256']=hashlib.sha256((out/'nfl_kickoffs.json').read_bytes()).hexdigest()
    (out/'forecast.json').write_text(json.dumps(forecast,indent=2))
    return {'run_id':info['workflow_run'],'week':week,
            'result':forecast['status'],'validation':validation['status'],
            'user_lineup_status':forecast['all_rosters'][1]['status']}


def main():
    import os,argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--week',type=int);parser.add_argument('--output-dir',default='forecast_output')
    args=parser.parse_args()
    token=os.getenv('GH_TOKEN') or os.getenv('GITHUB_TOKEN')
    if not token:raise SystemExit('GH_TOKEN or GITHUB_TOKEN required')
    try:
        result=run(os.getenv('GITHUB_REPOSITORY','Autocratic-Association-of-Autism/AAA-Fantasy'),
                   token,int(os.getenv('EXPORT_RUN_ID') or 0),args.output_dir,args.week)
        print(json.dumps(result))
    except Exception as e:
        Path(args.output_dir).mkdir(exist_ok=True,parents=True)
        reason={'status':'BLOCKED_INPUT_OR_DATA_ERROR','error':str(e),
                'caution':'No legal lineup recommendation should be issued from this run.'}
        (Path(args.output_dir)/'blocked.json').write_text(json.dumps(reason,indent=2))
        print(json.dumps(reason),file=sys.stderr)
        raise

if __name__=='__main__':main()

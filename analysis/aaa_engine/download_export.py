"""Download newest completed ESPN Fantasy Export artifact using GitHub Actions token."""
from __future__ import annotations
import argparse,io,json,os,urllib.request,zipfile
from pathlib import Path


def github_json(url,token):
    req=urllib.request.Request(url,headers={'Authorization':f'Bearer {token}',
         'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28',
         'User-Agent':'AAA-Forecast/1.0'})
    with urllib.request.urlopen(req,timeout=30) as resp:return json.load(resp)


def download_export(repo,run_id,token,target):
    base=f'https://api.github.com/repos/{repo}'
    if not run_id:
        runs=github_json(base+'/actions/workflows/espn-export.yml/runs?status=success&per_page=15',token)
        matching=[r for r in runs.get('workflow_runs',[]) if r.get('conclusion')=='success']
        if not matching:raise RuntimeError('No successful ESPN export workflow run found')
        run_id=matching[0]['id']
    items=github_json(base+f'/actions/runs/{run_id}/artifacts?per_page=100',token)
    expected='ESPN-League-1438350867-2026'
    choices=[a for a in items.get('artifacts',[]) if a.get('name')==expected and not a.get('expired')]
    if not choices:raise RuntimeError('Latest export workflow has no unexpired ESPN artifact')
    url=choices[0]['archive_download_url']
    req=urllib.request.Request(url,headers={'Authorization':f'Bearer {token}',
        'Accept':'application/vnd.github+json','User-Agent':'AAA-Forecast/1.0'})
    with urllib.request.urlopen(req,timeout=40) as resp:data=resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        wanted=[x for x in z.namelist() if x.endswith('.json') and x.startswith('ESPN_Current_Snapshot_')]
        if len(wanted)!=1:raise ValueError(f'Expected exactly one league JSON snapshot: {wanted}')
        obj=json.loads(z.read(wanted[0]))
        if int(obj['League'][0]['league_id'])!=1438350867:raise ValueError('Unexpected league ID')
        Path(target).parent.mkdir(parents=True,exist_ok=True)
        Path(target).write_text(json.dumps(obj))
    return {'workflow_run':run_id,'artifact_id':choices[0]['id'],
            'snapshot':target,'exported_utc':obj['League'][0]['exported_utc']}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--repo',default=os.getenv('GITHUB_REPOSITORY',
      'Autocratic-Association-of-Autism/AAA-Fantasy'))
    ap.add_argument('--run-id',type=int,default=int(os.getenv('EXPORT_RUN_ID') or 0))
    ap.add_argument('--output',default='forecast_output/current_export.json')
    args=ap.parse_args()
    token=os.getenv('GH_TOKEN') or os.getenv('GITHUB_TOKEN')
    if not token:raise SystemExit('GitHub Actions token required')
    print(json.dumps(download_export(args.repo,args.run_id,token,args.output)))

if __name__=='__main__':main()

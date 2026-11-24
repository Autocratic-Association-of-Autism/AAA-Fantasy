"""Read-only freshness checks and narrowly scoped Actions recovery dispatch."""
from __future__ import annotations
import argparse, json, os, urllib.request
from datetime import datetime,timezone,timedelta
from pathlib import Path
from .download_export import github_json

EXPORT="espn-export.yml"
FORECAST="aaa-forecast.yml"
EXPORT_ARTIFACT="ESPN-League-1438350867-2026"
RECOVERY_MINUTES=195
MAX_SNAPSHOT_MINUTES=240
ACTIVE={"queued","in_progress","waiting","requested","pending"}

def timestamp(value):
    d=datetime.fromisoformat(value.replace("Z","+00:00"))
    if d.tzinfo is None:raise ValueError("Timezone-aware timestamp required")
    return d

def snapshot_freshness(exported_utc,now,source_run_id):
    age=(now-timestamp(exported_utc)).total_seconds()/60
    if age<0:status="BLOCKED_FUTURE_EXPORT"
    elif age>MAX_SNAPSHOT_MINUTES:status="BLOCKED_STALE_EXPORT"
    elif age>180:status="DELAYED_BUT_WITHIN_LIMIT"
    else:status="FRESH_WITHIN_THREE_HOURS"
    return {"status":status,"exported_utc":exported_utc,"checked_utc":now.isoformat(),
            "age_minutes":round(age,2),"source_run_id":source_run_id,
            "target_minutes":180,"maximum_age_minutes":MAX_SNAPSHOT_MINUTES,
            "actionable":not status.startswith("BLOCKED")}

def main_runs(rows):
    return [r for r in rows if r.get("head_branch")=="main" and r.get("event")!="pull_request"]

def latest_success(rows):
    ok=[r for r in main_runs(rows) if r.get("status")=="completed" and r.get("conclusion")=="success"]
    return max(ok,key=lambda r:(timestamp(r["updated_at"]),int(r["id"]))) if ok else None

def active(rows):
    return [int(r["id"]) for r in main_runs(rows) if r.get("status") in ACTIVE]

def has_artifact(items,name):
    return any(a.get("name")==name and not a.get("expired") and int(a.get("size_in_bytes",0))>0
               for a in items)

def decide(now,exports,forecasts,export_artifact_ok,forecast_artifact_ok):
    """Decide at most one recovery action; never dispatch a duplicate active run."""
    e=latest_success(exports);f=latest_success(forecasts)
    age=(now-timestamp(e["updated_at"])).total_seconds()/60 if e else None
    out={"checked_utc":now.isoformat(),"recovery_threshold_minutes":RECOVERY_MINUTES,
         "last_successful_export_id":e["id"] if e else None,
         "last_successful_export_completed_utc":e["updated_at"] if e else None,
         "export_completion_age_minutes":round(age,2) if age is not None else None,
         "last_successful_forecast_id":f["id"] if f else None,
         "last_successful_forecast_completed_utc":f["updated_at"] if f else None,
         "active_exports":active(exports),"active_forecasts":active(forecasts),"dispatch":None}
    if age is not None and age<0:raise ValueError("Future export run completion")
    if out["active_exports"]:
        out["status"]="EXPORT_ALREADY_ACTIVE";return out
    if e is None or age>=RECOVERY_MINUTES or not export_artifact_ok:
        out.update(status="EXPORT_RECOVERY_NEEDED",dispatch=EXPORT);return out
    if out["active_forecasts"]:
        out["status"]="FORECAST_ALREADY_ACTIVE";return out
    # A forecast that began before the export completed cannot be assumed to
    # have used that export. A later successful artifact is a conservative proxy.
    if (f is None or not forecast_artifact_ok
            or timestamp(f["created_at"])<timestamp(e["updated_at"])):
        out.update(status="FORECAST_RECOVERY_NEEDED",dispatch=FORECAST);return out
    out["status"]="REFRESH_HEALTHY";return out

def run(repo,token,now,dry_run=False):
    base=f"https://api.github.com/repos/{repo}"
    def rows(workflow):
        return github_json(base+f"/actions/workflows/{workflow}/runs?branch=main&per_page=50",token)["workflow_runs"]
    e,f=rows(EXPORT),rows(FORECAST)
    def artifact(run,name):
        if not run:return False
        a=github_json(base+f"/actions/runs/{run['id']}/artifacts?per_page=100",token)
        return has_artifact(a["artifacts"],name)
    er,fr=latest_success(e),latest_success(f)
    report=decide(now,e,f,artifact(er,EXPORT_ARTIFACT),
                  artifact(fr,f"AAA-Forecast-Validation-{fr['id']}") if fr else False)
    report["dry_run"]=dry_run
    report["dispatch_accepted"]=False
    if report["dispatch"] and not dry_run:
        url=base+f"/actions/workflows/{report['dispatch']}/dispatches"
        req=urllib.request.Request(url,data=json.dumps({"ref":"main"}).encode(),method="POST",
            headers={"Authorization":f"Bearer {token}","Accept":"application/vnd.github+json",
                     "X-GitHub-Api-Version":"2022-11-28","Content-Type":"application/json",
                     "User-Agent":"AAA-Refresh-Watchdog/1.0"})
        with urllib.request.urlopen(req,timeout=30) as response:
            if response.status not in (200,201,204):raise RuntimeError("Recovery dispatch not accepted")
        report["dispatch_accepted"]=True
    return report

def main():
    p=argparse.ArgumentParser();p.add_argument("--dry-run",action="store_true");p.add_argument("--output",required=True)
    args=p.parse_args();target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True)
    # Do not trust non-main or pull-request execution to dispatch anything.
    dry=args.dry_run or os.getenv("GITHUB_REF")!="refs/heads/main" or os.getenv("GITHUB_EVENT_NAME") not in ("schedule","workflow_dispatch")
    try:
        result=run(os.environ["GITHUB_REPOSITORY"],os.environ["GH_TOKEN"],datetime.now(timezone.utc),dry)
    except Exception as error:
        result={"status":"BLOCKED_WATCHDOG_CHECK","error":str(error),"dry_run":dry,"dispatch_accepted":False}
        target.write_text(json.dumps(result,indent=2));raise
    target.write_text(json.dumps(result,indent=2));print(json.dumps(result))

if __name__=="__main__":main()

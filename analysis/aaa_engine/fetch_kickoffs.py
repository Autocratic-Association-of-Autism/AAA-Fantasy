"""Fetch ESPN's public NFL schedule; fail closed unless the requested week is complete.

No inferred kickoff times are allowed. This is a data source, not an NFL prediction.
"""
from __future__ import annotations
import argparse,json,urllib.request
from datetime import datetime
from .engine import team_key,date


def fetch(year,week,timeout=15):
    url=f'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={year}&seasontype=2&week={week}&limit=50'
    req=urllib.request.Request(url,headers={'User-Agent':'AAA-Forecast/1.0','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as resp:
        obj=json.load(resp)
    events=obj.get('events',[])
    games=[];kickoffs={};international=set()
    for e in events:
        comp=e.get('competitions',[{}])[0]
        teams=[team_key(t['team']['abbreviation']) for t in comp.get('competitors',[])]
        if len(teams)!=2:raise ValueError('Incomplete competitor list in ESPN NFL event')
        dt=e.get('date') or comp.get('date')
        date(dt)
        if any(t in kickoffs for t in teams):
            raise ValueError('Duplicate NFL team in weekly scoreboard')
        for t in teams:kickoffs[t]=dt
        venue=comp.get('venue',{})
        country=str(venue.get('address',{}).get('country') or 'UNKNOWN').upper()
        if country not in ('US','USA','UNITED STATES','UNKNOWN'):
            international.update(teams)
        games.append({'id':e.get('id'),'teams':teams,'kickoff_utc':dt,'venue':venue.get('fullName'),
                      'country':country})
    if not (13<=len(games)<=16) or len(kickoffs)!=2*len(games):
        raise ValueError(f'BLOCKED: expected 13-16 NFL games and unique teams, found {len(games)}')
    return {'season':year,'week':week,'source':url,'complete':True,'kickoffs':kickoffs,
            'international_teams':sorted(international),'games':games}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--year',type=int,required=True)
    ap.add_argument('--week',type=int,required=True);ap.add_argument('--output',required=True)
    args=ap.parse_args()
    out=fetch(args.year,args.week)
    from pathlib import Path
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps(out,indent=2))
    print('Verified',len(out['games']),'NFL games for week',args.week)

if __name__=='__main__':main()

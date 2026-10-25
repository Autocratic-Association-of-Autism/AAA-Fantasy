const D = window.LEAGUE_DATA;
const CAREER_MIN_SEASONS = 3;
const fmt = n => Number(n).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
const pct = n => (Number(n)*100).toFixed(1)+'%';

function table(el, rows, cols){
  const root=document.querySelector(el);
  if(!root) return;
  if(!rows.length){
    root.innerHTML='<div class="empty-table">No matching records.</div>';
    return;
  }
  root.innerHTML='<table><thead><tr>'+cols.map(c=>`<th>${c.label}</th>`).join('')+'</tr></thead><tbody>'+ 
    rows.map(r=>'<tr>'+cols.map(c=>`<td>${c.render?c.render(r[c.key],r):(r[c.key]??'')}</td>`).join('')+'</tr>').join('')+
    '</tbody></table>';
}

const gameCount=document.getElementById('games'); if(gameCount && gameCount.tagName!=='SECTION') gameCount.textContent=D.meta.games;
const scoreCount=document.getElementById('scores'); if(scoreCount) scoreCount.textContent=D.meta.weeklyScores;
const mwc=document.getElementById('multiWeekCount'); if(mwc) mwc.textContent=D.meta.multiWeekMatchups;
const managerCount=document.getElementById('managers'); if(managerCount) managerCount.textContent=D.career.length;
const yearsCount=document.getElementById('years'); if(yearsCount) yearsCount.textContent=D.meta.years;
const ct=document.getElementById('currentThrough'); if(ct) ct.textContent=D.meta.currentThrough||D.meta.years;

const careerCols=[
 {key:'Manager',label:'Manager'},{key:'Seasons',label:'Completed Seasons'},{key:'Wins',label:'W'},{key:'Losses',label:'L'},
 {key:'Win %',label:'Win %',render:v=>pct(v)},{key:'Avg Score',label:'Avg 1-Wk Score',render:v=>fmt(v)},
 {key:'Championships',label:'Titles'},{key:'Top-3 Finishes',label:'Top 3'},
 {key:'Avg Finish',label:'Avg Finish',render:v=>fmt(v)},{key:'High Score',label:'1-Wk High',render:v=>fmt(v)},{key:'Low Score',label:'1-Wk Low',render:v=>fmt(v)}
];

function renderCareer(q=''){
  const query=q.toLowerCase().trim();
  const filtered=D.career.filter(r=>!query || String(r.Manager).toLowerCase().includes(query) || String(r['Team Names']).toLowerCase().includes(query));
  const eligible=filtered.filter(r=>Number(r.Seasons)>=CAREER_MIN_SEASONS);
  const limited=filtered.filter(r=>Number(r.Seasons)<CAREER_MIN_SEASONS);
  table('#careerEligible',eligible,careerCols);
  table('#careerLimited',limited,careerCols);
  const wrap=document.getElementById('limitedCareerWrap');
  if(wrap) wrap.style.display=limited.length?'block':'none';
}
renderCareer();

const weeklyCols=[
 {key:'Manager',label:'Manager'},{key:'Team',label:'Team'},{key:'Season',label:'Season'},{key:'Week',label:'Week'},
 {key:'Score',label:'Score',render:v=>`<span class="highlight">${fmt(v)}</span>`},{key:'Opponent',label:'Opponent'},
 {key:'Opponent Score',label:'Opp Score',render:v=>fmt(v)},{key:'Stage',label:'Stage',render:v=>`<span class="badge">${v}</span>`}
];
table('#highest',D.highest,weeklyCols); table('#lowest',D.lowest,weeklyCols);

const blowoutCount = document.getElementById('blowoutCount');
if(blowoutCount) blowoutCount.textContent = (window.BLOWOUT_TOTAL||0).toLocaleString();
const blowoutScope = document.getElementById('blowoutScope');
if(blowoutScope) blowoutScope.textContent = window.BLOWOUT_SCOPE || 'Complete 35+ point results are unavailable.';

table('#blowoutWins',(window.BLOWOUT_WINS||[]),[
 {key:'Rank',label:'Rank'},
 {key:'Manager',label:'Manager'},
 {key:'Wins',label:'35+ Point Wins',render:v=>`<span class="highlight">${v}</span>`}
]);
table('#blowoutLosses',(window.BLOWOUT_LOSSES||[]),[
 {key:'Rank',label:'Rank'},
 {key:'Manager',label:'Manager'},
 {key:'Losses',label:'35+ Point Losses',render:v=>`<span class="highlight">${v}</span>`}
]);
table('#blowoutDetails',(window.BLOWOUT_DETAILS||[]),[
 {key:'Season',label:'Season'},
 {key:'Week',label:'Week'},
 {key:'Winner',label:'Winner'},
 {key:'Winner Score',label:'Winner Score',render:v=>fmt(v)},
 {key:'Loser',label:'Loser'},
 {key:'Loser Score',label:'Loser Score',render:v=>fmt(v)},
 {key:'Margin',label:'Margin',render:v=>`<span class="highlight">${fmt(v)}</span>`},
 {key:'Stage',label:'Stage',render:v=>`<span class="badge">${v}</span>`}
]);

function normalizeGame(r){
  const winnerIsHome = r.Winner === r['Home Manager'];
  const loserIsHome = r.Loser === r['Home Manager'];
  return {
    ...r,
    'Winner Score': winnerIsHome ? r['Home Score'] : r['Away Score'],
    'Loser Score': loserIsHome ? r['Home Score'] : r['Away Score'],
    'Winner Projected': winnerIsHome ? r['Home Projected'] : r['Away Projected'],
    'Loser Projected': loserIsHome ? r['Home Projected'] : r['Away Projected']
  };
}

const gameCols=[
 {key:'Season',label:'Season'},{key:'Week',label:'Week'},{key:'Winner',label:'Winner'},{key:'Winner Score',label:'Winner Score',render:v=>fmt(v)},
 {key:'Loser',label:'Loser'},{key:'Loser Score',label:'Loser Score',render:v=>fmt(v)},{key:'Margin',label:'Margin',render:v=>fmt(v)},
 {key:'Combined',label:'Combined',render:v=>fmt(v)},{key:'Stage',label:'Stage',render:v=>`<span class="badge">${v}</span>`}
];
table('#margins',D.largestMargins.map(normalizeGame),gameCols);
table('#closest',D.closest.map(normalizeGame),gameCols);
table('#combined',D.highestCombined.map(normalizeGame),gameCols);

table('#upsets',D.projectedUpsets.map(normalizeGame),[
 {key:'Season',label:'Season'},{key:'Week',label:'Week'},{key:'Winner',label:'Winner'},{key:'Winner Projected',label:'Winner Proj.',render:v=>fmt(v)},
 {key:'Loser',label:'Loser'},{key:'Loser Projected',label:'Loser Proj.',render:v=>fmt(v)},
 {key:'Winner Projected Deficit',label:'Projected Deficit',render:v=>fmt(v)},{key:'Stage',label:'Stage'}
]);

const multiWeekCols=[
 {key:'Season',label:'Season'},{key:'Weeks',label:'Weeks'},{key:'Winner',label:'Winner'},{key:'Winner Score',label:'Winner Total',render:v=>fmt(v)},
 {key:'Loser',label:'Loser'},{key:'Loser Score',label:'Loser Total',render:v=>fmt(v)},{key:'Margin',label:'Margin',render:v=>fmt(v)},
 {key:'Combined',label:'Combined',render:v=>fmt(v)},{key:'Matchup Type',label:'Bracket',render:v=>`<span class="badge">${String(v||'').replaceAll('_',' ')}</span>`}
];
table('#multiWeek',(D.multiWeekPlayoffs||[]).map(normalizeGame),multiWeekCols);

table('#seasonsTable',D.seasons,[
 {key:'Season',label:'Season'},{key:'Manager',label:'Manager'},{key:'Team',label:'Team'},
 {key:'Regular W',label:'W'},{key:'Regular L',label:'L'},{key:'Regular PF',label:'PF',render:v=>fmt(v)},
 {key:'Final Finish',label:'Finish'},{key:'Acquisitions',label:'Adds'},{key:'Trades',label:'Trades'}
]);

const managerSearch=document.getElementById('managerSearch'); if(managerSearch) managerSearch.addEventListener('input', e=>renderCareer(e.target.value));

const championshipRoot=document.querySelector('#championshipHistory');
if(championshipRoot){
 const completed=D.seasons.filter(r=>Number.isFinite(Number(r['Final Finish'])) && Number(r.Season)<2026);
 const rows=[...new Set(completed.map(r=>r.Season))].sort((a,b)=>b-a).map(year=>{
  const season=completed.filter(r=>r.Season===year);
  const winner=season.find(r=>Number(r['Final Finish'])===1);
  const runner=season.find(r=>Number(r['Final Finish'])===2);
  return {Season:year,Champion:winner?.Manager||'Not verified','Champion Team':winner?.Team||'—','Runner-up':runner?.Manager||'Not verified','Runner-up Team':runner?.Team||'—'};
 });
 table('#championshipHistory',rows,[{key:'Season',label:'Season'},{key:'Champion',label:'Champion'},{key:'Champion Team',label:'Championship Team'},{key:'Runner-up',label:'Runner-up'},{key:'Runner-up Team',label:'Runner-up Team'}]);
 // Career postseason tiers are achievement milestones, not an arbitrary point scale.
 // Stars award only repeated achievements that define the current tier; other podium finishes break ties.
 const rankFor=r=>{
  const titles=Number(r.Championships||0);
  const runners=Number(r['Runner-up']||0);
  const podiums=Number(r['Top-3 Finishes']||0);
  const thirds=Math.max(0,podiums-titles-runners);
  const appearances=playoffAppearances.get(String(r.Manager||'').trim())||0;
  let n,name,stars;
  if(titles>=2){n=6;name='DYNASTY BUILDER';stars=titles-2;}
  else if(titles>=1&&runners>=1){n=5;name='CHAMPIONSHIP VETERAN';stars=runners-1;}
  else if(titles>=1){n=4;name='LEAGUE CHAMPION';stars=0;}
  else if(runners>=1){n=3;name='TITLE GAME FINALIST';stars=runners-1;}
  else if(thirds>=1){n=2;name='PODIUM FINISHER';stars=thirds-1;}
  else if(appearances>=1){n=1;name='THE PODIUM IS A MYTH TO ME';stars=appearances-1;}
  else{n=0;name='HUMAN BYE WEEK';stars=0;}
  // Chris Turner's two-title career retains his league-specific honorary title.
  if(String(r.Manager||'').trim().toLowerCase()==='chris turner')name='HIT IT AND QUIT IT';
  return {n,stars,display:name+(stars>0?' '+(stars<=5?'★'.repeat(stars):'★ ×'+stars):'')};
 };

 const playoffAppearances=new Map();
 D.seasons.filter(r=>Number(r.Season)<2026&&Number.isFinite(Number(r['Final Finish']))).forEach(r=>{
  const seed=Number(r['Playoff Seed']);
  if(Number.isInteger(seed)&&seed>=1&&seed<=6){const manager=String(r.Manager||'').trim();playoffAppearances.set(manager,(playoffAppearances.get(manager)||0)+1);}
 });
 const sackoSeasons=new Map();
 D.seasons.filter(r=>Number(r.Season)<2026&&Number(r['Final Finish'])===10).forEach(r=>{
  const manager=String(r.Manager||'').trim();
  if(!sackoSeasons.has(manager))sackoSeasons.set(manager,[]);
  sackoSeasons.get(manager).push(Number(r.Season));
 });
 const honors=[...D.career].sort((a,b)=>{
  const ar=rankFor(a),br=rankFor(b);
  const aa=playoffAppearances.get(String(a.Manager||'').trim())||0;
  const ba=playoffAppearances.get(String(b.Manager||'').trim())||0;
  const arate=aa/Math.max(1,Number(a.Seasons||0));
  const brate=ba/Math.max(1,Number(b.Seasons||0));
  return br.n-ar.n||br.stars-ar.stars||Number(b['Top-3 Finishes']||0)-Number(a['Top-3 Finishes']||0)||ba-aa||brate-arate||String(a.Manager).localeCompare(String(b.Manager));
 });
 table('#postseasonHonors',honors,[{key:'Manager',label:'Rank',render:(_,r)=>'<span class="aaa-rank rank-'+String(rankFor(r).n)+'">'+rankFor(r).display+'</span>'},{key:'Manager',label:'Manager'},{key:'Championships',label:'Titles'},{key:'Runner-up',label:'Runner-up Finishes'},{key:'Top-3 Finishes',label:'Top 3 Finishes'},{key:'Manager',label:'Playoff Appearances',render:(_,r)=>String(playoffAppearances.get(String(r.Manager||'').trim())||0)},{key:'Manager',label:'Sacko Finishes',render:(_,r)=>String((sackoSeasons.get(String(r.Manager||'').trim())||[]).length)}]);
 document.querySelectorAll('#postseasonHonors tbody tr').forEach((tr,i)=>{if(rankFor(honors[i]).n===0)tr.classList.add('honors-no-podium');});
}

if(document.querySelector('#sackoHistory')){
 const complete=D.seasons.filter(r=>Number(r.Season)<2026&&Number.isFinite(Number(r['Final Finish'])));
 const years=[...new Set(complete.map(r=>r.Season))].sort((a,b)=>b-a);
 const punishments={
 2021:'Sexy calendar',
 2022:'Sexual Wine & Design (Damar Hamlin controversy)',
 2023:'Wear a league-selected dress out for 18 rounds',
 2024:'Beer bitch in a custom league-made T-shirt',
 2025:'Stand-up comedy at an open mic night'
 };
 const rows=years.map(year=>{const season=complete.filter(r=>Number(r.Season)===Number(year));const last=Math.max(...season.map(r=>Number(r['Final Finish'])));const candidate=season.find(r=>Number(r['Final Finish'])===last);return {Season:String(year)+'–'+String(Number(year)+1).slice(-2),Manager:candidate?.Manager||'Not verified',Team:candidate?.Team||'—',Finish:last,Punishment:punishments[year]||'Not recorded',Status:(punishments[year]&&candidate)?'Verified Sacko':'Sacko not verified'};});
 table('#sackoHistory',rows,[{key:'Season',label:'Season'},{key:'Manager',label:'Sacko recipient'},{key:'Team',label:'Team'},{key:'Finish',label:'Finish'},{key:'Punishment',label:'Punishment'}]);
 const all=(D.multiWeekPlayoffs||[]).map(normalizeGame);
 const sacko=all.filter(r=>/LOSERS|CONSOLATION|SACKO/i.test(String(r['Matchup Type']||'')));
 const championship=all.filter(r=>/WINNERS|CHAMPIONSHIP/i.test(String(r['Matchup Type']||'')));
 table('#sackoMultiWeek',sacko,multiWeekCols);
 table('#championshipMultiWeek',championship,multiWeekCols);
}


// Tournament brackets: winners advance to the title, losers advance to the Sacko.
if(document.getElementById('aaaBracketSeason')){
 const select=document.getElementById('aaaBracketSeason');
 const esc=v=>String(v??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
 const years=[2025,2024,2023,2022,2021];
 select.innerHTML=years.map(y=>'<option value="'+y+'">'+y+'–'+String(y+1).slice(-2)+'</option>').join('');
 const match=(g,reverse=false)=>{
  const line=(manager,score)=>'<div class="aaa-bracket-team'+((reverse?g.Loser:g.Winner)===manager?' is-winner':'')+'"><span>'+esc(manager)+'</span><b>'+Number(score).toFixed(2)+'</b></div>';
  return '<div class="aaa-bracket-game">'+line(g['Home Manager'],g['Home Score'])+line(g['Away Manager'],g['Away Score'])+'</div>';
 };
 const missing=(label='Result unavailable')=>'<div class="aaa-bracket-missing">'+esc(label)+'</div>';
 const round=(name,cards)=>'<div class="aaa-bracket-stage"><div class="aaa-bracket-stage-label">'+esc(name)+'</div><div class="aaa-bracket-stage-games">'+cards.join('')+'</div></div>';
 const render=()=>{
  const year=Number(select.value),all=(D.multiWeekPlayoffs||[]).filter(g=>Number(g.Season)===year);
  const title=all.filter(g=>g['Matchup Type']==='WINNERS_BRACKET');
  const semis=title.filter(g=>Number(g.Week)<18),final=title.find(g=>Number(g.Week)===18);
  const placements=all.filter(g=>g['Matchup Type']==='WINNERS_CONSOLATION_LADDER');
  const third=semis.length===2?placements.find(g=>Number(g.Week)===18&&[g['Home Manager'],g['Away Manager']].every(n=>semis.some(s=>s.Loser===n))):null;
  const championship=(year===2021||year===2022)
   ?round('Round 1',semis.map(g=>match(g)))+round('Championship',[final?match(final):missing('Final not archived')])
   :year===2023
   ?round('Round 1',[
     '<div class="aaa-bracket-game"><div class="aaa-bracket-team is-winner"><span>#1 Larry Terrell</span><b>BYE</b></div></div>',
     match({'Home Manager':'Louis Swanson','Home Score':131.72,'Away Manager':'Macon Moore','Away Score':68.46,Winner:'Louis Swanson'}),
     match({'Home Manager':'Casey Hutchins','Home Score':139.38,'Away Manager':'Frankie Yentz','Away Score':120.36,Winner:'Casey Hutchins'}),
     '<div class="aaa-bracket-game"><div class="aaa-bracket-team is-winner"><span>#2 Chance Robinson</span><b>BYE</b></div></div>'
    ])+
    round('Semifinals',[
     match({'Home Manager':'Louis Swanson','Home Score':97.98,'Away Manager':'Larry Terrell','Away Score':152.54,Winner:'Larry Terrell'}),
     match({'Home Manager':'Casey Hutchins','Home Score':151.68,'Away Manager':'Chance Robinson','Away Score':143.62,Winner:'Casey Hutchins'})
    ])+
    round('Championship',[match({'Home Manager':'Casey Hutchins','Home Score':107.30,'Away Manager':'Larry Terrell','Away Score':145.38,Winner:'Larry Terrell'})])
   :year===2024
   ?round('Round 1',[
      '<div class="aaa-bracket-game"><div class="aaa-bracket-team is-winner"><span>#1 Chance Robinson</span><b>BYE</b></div></div>',
      match({'Home Manager':'Macon Moore','Home Score':127.84,'Away Manager':'Frankie Yentz','Away Score':172.10,Winner:'Frankie Yentz'}),
      match({'Home Manager':'Casey Hutchins','Home Score':147.52,'Away Manager':'Ryan Mays','Away Score':173.34,Winner:'Ryan Mays'}),
      '<div class="aaa-bracket-game"><div class="aaa-bracket-team is-winner"><span>#2 Larry Terrell</span><b>BYE</b></div></div>'
    ])+
    round('Semifinals',[
      match({'Home Manager':'Frankie Yentz','Home Score':166.58,'Away Manager':'Chance Robinson','Away Score':122.38,Winner:'Frankie Yentz'}),
      match({'Home Manager':'Ryan Mays','Home Score':182.92,'Away Manager':'Larry Terrell','Away Score':160.14,Winner:'Ryan Mays'})
    ])+
    round('Championship',[match({'Home Manager':'Frankie Yentz','Home Score':164.42,'Away Manager':'Ryan Mays','Away Score':163.58,Winner:'Frankie Yentz'})])
   :year===2025
   ?round('Round 1',[
      '<div class="aaa-bracket-game"><div class="aaa-bracket-team is-winner"><span>#1 Glen Hutchins</span><b>BYE</b></div></div>',
      match({'Home Manager':'Casey Hutchins','Home Score':160.32,'Away Manager':'Ryan Mays','Away Score':88.76,Winner:'Casey Hutchins'}),
      match({'Home Manager':'Frankie Yentz','Home Score':129.92,'Away Manager':'Zak Wesolek','Away Score':148.90,Winner:'Zak Wesolek'}),
      '<div class="aaa-bracket-game"><div class="aaa-bracket-team is-winner"><span>#2 Larry Terrell</span><b>BYE</b></div></div>'
    ])+
    round('Semifinals',[
      match({'Home Manager':'Casey Hutchins','Home Score':141.96,'Away Manager':'Glen Hutchins','Away Score':174.38,Winner:'Glen Hutchins'}),
      match({'Home Manager':'Zak Wesolek','Home Score':159.90,'Away Manager':'Larry Terrell','Away Score':91.30,Winner:'Zak Wesolek'})
    ])+
    round('Championship',[match({'Home Manager':'Zak Wesolek','Home Score':129.72,'Away Manager':'Glen Hutchins','Away Score':131.60,Winner:'Glen Hutchins'})])
   :round('Round 1',[missing('Opening matchups not archived')])+round('Semifinals',semis.length?semis.map(g=>match(g)):[missing('Semifinal results not archived')])+round('Championship',[final?match(final):missing('Final not archived')]);
  document.getElementById('aaaChampBracket').innerHTML='<div class="aaa-bracket-board">'+championship+'</div><div class="aaa-third-place"><div><strong>Third-place game</strong><p>Semifinal losers compete separately.</p></div>'+(year===2025?match({'Home Manager':'Casey Hutchins','Home Score':138.88,'Away Manager':'Larry Terrell','Away Score':119.48,Winner:'Casey Hutchins'}):third?match(third):missing('Third-place matchup not verified'))+'</div>';
  const consolation=all.filter(g=>g['Matchup Type']==='LOSERS_CONSOLATION_LADDER');
  const early=consolation.filter(g=>Number(g.Week)<18);
  const sackoRow=(D.seasons||[]).find(r=>Number(r.Season)===year&&Number(r['Final Finish'])===10);
  const sackoName=sackoRow?.Manager;
  // A Sacko final can only be identified when the confirmed recipient lost that game.
  const sackoFinal=consolation.find(g=>Number(g.Week)===18&&g.Loser===sackoName);
  const rest=([2021,2022,2023,2024,2025].includes(year))?[]:consolation.filter(g=>g!==sackoFinal);
  const sackoBoard=year===2021
   ?round('Round 1',[
     { 'Home Manager':'Ryan Mays','Home Score':227.22,'Away Manager':'Casey Hutchins','Away Score':238.24,Loser:'Ryan Mays' },
     { 'Home Manager':'Larry Terrell','Home Score':224.28,'Away Manager':'Ryan Hutchins','Away Score':195.64,Loser:'Ryan Hutchins' }
    ].map(g=>match(g,true)))+
    round('Sacko final',[match({'Home Manager':'Ryan Mays','Home Score':250.86,'Away Manager':'Ryan Hutchins','Away Score':222.44,Loser:'Ryan Hutchins'},true)])
   :year===2023
   ?round('Round 1',[
      {'Home Manager':'Macon Moore','Home Score':133.18,'Away Manager':'Glen Hutchins','Away Score':89.00,Loser:'Glen Hutchins'},
      {'Home Manager':'Zak Wesolek','Home Score':130.36,'Away Manager':'Ryan Mays','Away Score':68.44,Loser:'Ryan Mays'}
    ].map(g=>match(g,true)))+
    round('Round 2',[
      match({'Home Manager':'Zak Wesolek','Home Score':83.96,'Away Manager':'Macon Moore','Away Score':91.20,Loser:'Zak Wesolek'},true),
      match({'Home Manager':'Ryan Mays','Home Score':133.88,'Away Manager':'Glen Hutchins','Away Score':110.82,Loser:'Glen Hutchins'},true)
    ])+
    round('Round 3',[
      match({'Home Manager':'Ryan Mays','Home Score':140.82,'Away Manager':'Macon Moore','Away Score':111.60,Loser:'Macon Moore'},false),
      match({'Home Manager':'Zak Wesolek','Home Score':146.74,'Away Manager':'Glen Hutchins','Away Score':106.38,Loser:'Glen Hutchins'},true)
    ])
   :year===2024
   ?round('Round 1',[
      {'Home Manager':'Zak Wesolek','Home Score':85.76,'Away Manager':'Louis Swanson','Away Score':132.08,Loser:'Zak Wesolek'},
      {'Home Manager':'Glen Hutchins','Home Score':70.78,'Away Manager':'Ryan Hutchins','Away Score':112.50,Loser:'Glen Hutchins'}
    ].map(g=>match(g,true)))+
    round('Sacko final · 2-week aggregate',[
      '<div class="aaa-bracket-game"><div class="aaa-bracket-team"><span>Glen Hutchins</span><b>223.22</b></div><div class="aaa-bracket-team is-winner"><span>Zak Wesolek · SACKO</span><b>203.80</b></div><div class="aaa-bracket-footnote" style="padding:10px 12px">GmC4 (Week 16): Glen 118.64 · Zak 112.80<br>GmC6 (Week 17, cumulative final): Glen 223.22 · Zak 203.80<br>Final margin: 19.42</div></div>'
    ])
   :year===2025
   ?round('Round 1',[
      {'Home Manager':'Chance Robinson','Home Score':151.04,'Away Manager':'Macon Moore','Away Score':96.80,Loser:'Macon Moore'},
      {'Home Manager':'Ryan Hutchins','Home Score':114.30,'Away Manager':'Louis Swanson','Away Score':139.60,Loser:'Ryan Hutchins'}
    ].map(g=>match(g,true)))+
    round('Sacko final · 2-week aggregate',[
      '<div class="aaa-bracket-game"><div class="aaa-bracket-team"><span>Macon Moore</span><b>247.22</b></div><div class="aaa-bracket-team is-winner"><span>Ryan Hutchins · SACKO</span><b>228.94</b></div><div class="aaa-bracket-footnote" style="padding:10px 12px">GmC4 (Week 16): Macon 123.82 · Ryan 120.10<br>GmC6 (Week 17, cumulative final): Macon 247.22 · Ryan 228.94<br>Final margin: 18.28</div></div>'
    ])
   :year===2022
   ?round('Round 1',[
     {'Home Manager':'Ryan Hutchins','Home Score':255.68,'Away Manager':'Glen Hutchins','Away Score':224.34,Loser:'Glen Hutchins'},
     {'Home Manager':'Casey Hutchins','Home Score':186.54,'Away Manager':'Louis Swanson','Away Score':182.48,Loser:'Louis Swanson'}
    ].map(g=>match(g,true)))+
    round('Sacko final',[match({'Home Manager':'Glen Hutchins','Home Score':207.06,'Away Manager':'Louis Swanson','Away Score':202.40,Loser:'Louis Swanson'},true)])
   :round('Round 1',early.length?early.map(g=>match(g,true)):[missing('Opening matchups not archived')])+round('Next round',[missing('Advancement not fully archived')])+round('Sacko final',[sackoFinal?match(sackoFinal,true):missing('Final matchup not verified')]);
  document.getElementById('aaaSackoBracket').innerHTML='<div class="aaa-bracket-board">'+sackoBoard+'</div><p class="aaa-bracket-footnote">Highlighted teams lose and continue toward the Sacko. Other teams exit Sacko contention. Matchups without a verified advancement path are not connected.</p><div class="aaa-sacko-compact"><div class="aaa-bracket-stage-label">Confirmed Sacko recipient</div><strong>'+esc(sackoName||'Not recorded')+'</strong></div>'+(rest.length?'<details class="aaa-bracket-details"><summary>Other archived consolation matchups ('+rest.length+')</summary><div class="aaa-bracket-archive">'+rest.map(g=>match(g,true)).join('')+'</div></details>':'');
 };
 select.addEventListener('change',render);render();
}

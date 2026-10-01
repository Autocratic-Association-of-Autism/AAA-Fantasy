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

document.getElementById('games').textContent=D.meta.games;
document.getElementById('scores').textContent=D.meta.weeklyScores;
document.getElementById('managers').textContent=D.career.length;
document.getElementById('years').textContent=D.meta.years;

const careerCols=[
 {key:'Manager',label:'Manager'},{key:'Seasons',label:'Seasons'},{key:'Wins',label:'W'},{key:'Losses',label:'L'},
 {key:'Win %',label:'Win %',render:v=>pct(v)},{key:'Avg Score',label:'Avg Score',render:v=>fmt(v)},
 {key:'Championships',label:'Titles'},{key:'Top-3 Finishes',label:'Top 3'},
 {key:'Avg Finish',label:'Avg Finish',render:v=>fmt(v)},{key:'High Score',label:'High',render:v=>fmt(v)},{key:'Low Score',label:'Low',render:v=>fmt(v)}
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

table('#seasonsTable',D.seasons,[
 {key:'Season',label:'Season'},{key:'Manager',label:'Manager'},{key:'Team',label:'Team'},
 {key:'Regular W',label:'W'},{key:'Regular L',label:'L'},{key:'Regular PF',label:'PF',render:v=>fmt(v)},
 {key:'Final Finish',label:'Finish'},{key:'Acquisitions',label:'Adds'},{key:'Trades',label:'Trades'}
]);

document.getElementById('managerSearch').addEventListener('input', e=>renderCareer(e.target.value));

#!/usr/bin/env python3
"""Forecast sorted-position curves, then sample diverse DLT combinations.
All valid combinations remain equally likely in a fair draw; this is exploratory pattern fitting.
"""
from __future__ import annotations
import hashlib,json,math,random,statistics
from datetime import date,datetime,timedelta,timezone
from pathlib import Path

R=Path(__file__).resolve().parents[1]; D=R/'data/draws.json'; F=R/'data/forecast.json'; H=R/'data/forecast-history.json'; L=R/'data/learning-log.json'; S=R/'data/model-state.json'
VERSION='v3.0-curve-sampler'
PROFILES=[
 {'name':'local-drift','label':'局部漂移','window':18,'trend':.42,'reversion':.28,'cycle':.30,'temperature':1.10},
 {'name':'adaptive-wave','label':'自适应波形','window':36,'trend':.28,'reversion':.34,'cycle':.38,'temperature':1.24},
 {'name':'regime-shift','label':'区间换挡','window':24,'trend':.48,'reversion':.18,'cycle':.34,'temperature':1.38},
 {'name':'wide-band','label':'宽带采样','window':60,'trend':.18,'reversion':.42,'cycle':.40,'temperature':1.52}]

def read(p,d):
 try:return json.loads(p.read_text(encoding='utf-8'))
 except (OSError,json.JSONDecodeError):return d
def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def nums(v):return [int(x) for x in (v if isinstance(v,list) else str(v or '').split())]
def load():
 p=read(D,{}); rows=p if isinstance(p,list) else p.get('draws',[]); out=[]
 for x in rows:
  try:
   a=sorted(nums(x['front'])); b=sorted(nums(x['back'])); dt=str(x['date']); date.fromisoformat(dt)
   if len(a)==5 and len(set(a))==5 and min(a)>=1 and max(a)<=35 and len(b)==2 and len(set(b))==2 and min(b)>=1 and max(b)<=12:out.append({'issue':str(x['issue']),'date':dt,'front':a,'back':b})
  except (KeyError,TypeError,ValueError):pass
 out.sort(key=lambda x:(x['date'],int(x['issue'])))
 if len(out)<1000:raise RuntimeError(f'Not enough valid history: {len(out)}')
 return out
def nextday(s):
 d=date.fromisoformat(s)+timedelta(days=1)
 while d.weekday() not in {0,2,5}:d+=timedelta(days=1)
 return d.isoformat()
def seed(*x):return int.from_bytes(hashlib.sha256('|'.join(map(str,x)).encode()).digest()[:8],'big')
def wmean(v,q=.91):
 w=[q**(len(v)-1-i) for i in range(len(v))];return sum(a*b for a,b in zip(v,w))/sum(w)
def slope(v):
 if len(v)<3:return 0.
 xm=(len(v)-1)/2; ym=statistics.fmean(v); den=sum((i-xm)**2 for i in range(len(v))) or 1
 return sum((i-xm)*(y-ym) for i,y in enumerate(v))/den
def cycle(v):
 if len(v)<12:return 3,0.
 m=statistics.fmean(v); z=[x-m for x in v]; best=(3,-1.)
 for lag in range(2,min(19,len(v)//2+1)):
  a,b=z[lag:],z[:-lag]; den=math.sqrt(sum(x*x for x in a)*sum(x*x for x in b)) or 1; c=sum(x*y for x,y in zip(a,b))/den
  if c>best[1]:best=(lag,c)
 return best[0],max(0.,best[1])
def curve(series,p,lo,hi):
 v=series[-min(p['window'],len(series)):]; m=wmean(v); sl=max(-2.2,min(2.2,slope(v[-min(14,len(v)):]))) ; lag,c=cycle(v); delta=v[-lag+1]-v[-lag] if len(v)>lag else 0
 center=max(lo,min(hi,v[-1]+p['trend']*sl+p['reversion']*(m-v[-1])+p['cycle']*c*delta)); res=[]
 for i in range(max(4,len(v)//3),len(v)):
  u=v[:i]; pred=u[-1]+p['trend']*slope(u[-min(14,len(u)):])+p['reversion']*(wmean(u)-u[-1]);res.append(v[i]-pred)
 sd=statistics.pstdev(res) if len(res)>=3 else statistics.pstdev(v)
 return {'center':center,'sigma':max(.85,sd*p['temperature']),'slope':sl,'cycleLag':lag,'cycleStrength':c}
def model(draws,area,p,lo,hi):
 width=len(draws[0][area]);return [curve([x[area][i] for x in draws],p,lo,hi) for i in range(width)]
def loss(actual,m,upper):
 pos=statistics.fmean(abs(x-m[i]['center'])/upper for i,x in enumerate(actual)); sm=abs(sum(actual)-sum(x['center'] for x in m))/(upper*len(actual)); sp=abs((actual[-1]-actual[0])-(m[-1]['center']-m[0]['center']))/upper
 return .68*pos+.20*sm+.12*sp
def backtest(draws,p):
 idx=range(max(500,len(draws)-150),len(draws),3); fl=[];bl=[]
 for i in idx:
  h=draws[:i];fl.append(loss(draws[i]['front'],model(h,'front',p,1,35),35));bl.append(loss(draws[i]['back'],model(h,'back',p,1,12),12))
 return {'tests':len(fl),'frontCurveLoss':statistics.fmean(fl),'backCurveLoss':statistics.fmean(bl),'objective':.72*statistics.fmean(fl)+.28*statistics.fmean(bl)}
def state0():return {'version':2,'updatedAt':None,'profiles':{},'temperatureAdjustment':0.}
def evaluate(prev,draws,state,logs):
 issue=str(prev.get('targetIssue') or '')
 if not issue or not prev.get('results'):return None
 old=next((x for x in logs if str(x.get('issue'))==issue and x.get('modelFamily')=='curve-sampler'),None)
 if old:return old
 actual=next((x for x in draws if x['issue']==issue),None)
 if not actual:return None
 rows=[];dist=[]
 for r in prev['results']:
  a=sorted(nums(r.get('front',[])));b=sorted(nums(r.get('back',[])));fh=sorted(set(a)&set(actual['front']));bh=sorted(set(b)&set(actual['back']));d=.72*statistics.fmean(abs(x-y) for x,y in zip(a,actual['front']))/35+.28*statistics.fmean(abs(x-y) for x,y in zip(b,actual['back']))/12;dist.append(d)
  rows.append({'rank':r.get('rank'),'label':r.get('label'),'frontHits':[f'{x:02d}' for x in fh],'backHits':[f'{x:02d}' for x in bh],'frontHitCount':len(fh),'backHitCount':len(bh),'curveDistance':round(d,4)})
 name=str(prev.get('calibration',{}).get('selectedProfile') or 'unknown');cur=state.setdefault('profiles',{}).get(name,{});n=int(cur.get('evaluations',0))+1;best=min(dist);oldema=cur.get('emaCurveDistance');ema=best if oldema is None else .74*float(oldema)+.26*best;state['profiles'][name]={'evaluations':n,'lastCurveDistance':round(best,6),'emaCurveDistance':round(ema,6)};adj=max(-.18,min(.25,(ema-.105)*1.8));state['temperatureAdjustment']=round(adj,4)
 ev={'issue':issue,'date':actual['date'],'modelFamily':'curve-sampler','evaluatedAt':datetime.now(timezone.utc).isoformat(),'actual':{'front':[f'{x:02d}' for x in actual['front']],'back':[f'{x:02d}' for x in actual['back']]},'results':rows,'summary':{'averageFrontHits':round(statistics.fmean(x['frontHitCount'] for x in rows),3),'averageBackHits':round(statistics.fmean(x['backHitCount'] for x in rows),3),'bestCurveDistance':round(best,4)},'learningUpdate':{'profile':name,'emaCurveDistance':round(ema,4),'temperatureAdjustment':round(adj,4),'rule':'Prediction error changes only the sampling-band width; recent winning numbers are not fixed favourites.'}}
 logs.append(ev);return ev
def choose(draws,state):
 rows=[]
 for p in PROFILES:
  r=backtest(draws,p);live=state.get('profiles',{}).get(p['name'],{});n=int(live.get('evaluations',0));ld=float(live.get('emaCurveDistance',r['objective']));rel=min(.35,n*.045);rows.append({'p':p,**r,'liveEvaluations':n,'liveCurveDistance':ld if n else None,'adjustedObjective':r['objective']*(1-rel)+ld*rel})
 w=min(rows,key=lambda x:x['adjustedObjective']);return dict(w['p']),{'selectedProfile':w['p']['name'],'selectedLabel':w['p']['label'],'tests':w['tests'],'frontCurveLoss':round(w['frontCurveLoss'],4),'backCurveLoss':round(w['backCurveLoss'],4),'historicalObjective':round(w['objective'],4),'adjustedObjective':round(w['adjustedObjective'],4),'liveEvaluations':w['liveEvaluations'],'liveCurveDistance':None if w['liveCurveDistance'] is None else round(w['liveCurveDistance'],4)}
def gauss(r,c,s,lo,hi):
 for _ in range(30):
  x=round(r.gauss(c,s))
  if lo<=x<=hi:return int(x)
 return max(lo,min(hi,round(c)))
def sample(r,m,lo,hi,adj):
 v=sorted(gauss(r,x['center'],x['sigma']*(1+adj),lo,hi) for x in m);return tuple(v) if len(set(v))==len(v) else None
def shape(draws,area):
 v=[x[area] for x in draws[-1200:]];s=[sum(x) for x in v];p=[x[-1]-x[0] for x in v];o=[sum(n%2 for n in x) for x in v];return (statistics.fmean(s),statistics.pstdev(s) or 1,statistics.fmean(p),statistics.pstdev(p) or 1,statistics.fmean(o),statistics.pstdev(o) or 1)
def g(x,m,s):return math.exp(-.5*((x-m)/s)**2)
def score(v,m,sh):
 d=statistics.fmean(abs(x-m[i]['center'])/max(1,m[i]['sigma']) for i,x in enumerate(v));curvefit=math.exp(-.5*d);ps=sum(x['center'] for x in m);pp=m[-1]['center']-m[0]['center'];traj=.58*g(sum(v),ps,max(2,sum(x['sigma'] for x in m)/2))+.42*g(v[-1]-v[0],pp,max(2,statistics.fmean(x['sigma'] for x in m)));hist=.45*g(sum(v),sh[0],sh[1])+.35*g(v[-1]-v[0],sh[2],sh[3])+.20*g(sum(n%2 for n in v),sh[4],sh[5]);return .60*curvefit+.25*traj+.15*hist
def pool(r,m,draws,area,lo,hi,adj,count):
 sh=shape(draws,area);out={};tries=0
 while len(out)<count and tries<count*40:
  tries+=1;v=sample(r,m,lo,hi,adj)
  if v:out[v]=max(out.get(v,0),score(v,m,sh))
 return sorted(out.items(),key=lambda x:x[1],reverse=True)
def pick(r,rows,temp):
 q=rows[:max(25,min(180,len(rows)))];best=q[0][1];w=[math.exp((s-best)/max(.03,temp)) for _,s in q];return r.choices([x for x,_ in q],weights=w,k=1)[0]
def assemble(r,fp,bp,prev):
 oldf=[set(nums(x.get('front',[]))) for x in prev.get('results',[])];oldb=[set(nums(x.get('back',[]))) for x in prev.get('results',[])];out=[]
 for tries in range(500):
  f=pick(r,fp,.14+len(out)*.035);b=pick(r,bp,.12+len(out)*.04)
  if any(len(set(f)&set(x['front']))>2 or len(set(b)&set(x['back']))>1 for x in out):continue
  if oldf and max(len(set(f)&x) for x in oldf)>3:continue
  if oldb and max(len(set(b)&x) for x in oldb)>1:continue
  out.append({'front':f,'back':b})
  if len(out)==3:break
 if len(out)<3:
  for f,_ in fp:
   for b,_ in bp:
    if all(len(set(f)&set(x['front']))<=3 for x in out):out.append({'front':f,'back':b})
    if len(out)==3:break
   if len(out)==3:break
 for i,x in enumerate(out):x.update(rank=i+1,label=['曲线主样本','波动延伸','随机带对冲'][i],fit=round(84-i*2.2,1))
 return out
def summary(m):return {'centers':[round(x['center'],2) for x in m],'sigmas':[round(x['sigma'],2) for x in m],'slopes':[round(x['slope'],3) for x in m],'cycleLags':[x['cycleLag'] for x in m]}
def reason(x,m):return f"从五个排序位置的预测中心 [{ ' / '.join(f'{a['center']:.1f}' for a in m) }] 及波动带中抽样；本组和值{sum(x['front'])}、跨度{x['front'][-1]-x['front'][0]}，并执行跨期与组间多样性约束。"
def archive(prev,ev):
 if not prev.get('targetIssue'):return
 h=read(H,[]);issue=str(prev['targetIssue'])
 if any(str(x.get('targetIssue'))==issue for x in h):return
 q=dict(prev);q['evaluation']=ev;h.append(q);h.sort(key=lambda x:int(x.get('targetIssue',0)));write(H,h[-500:])
def main():
 draws=load();prev=read(F,{});logs=read(L,[]);state=read(S,state0());ev=evaluate(prev,draws,state,logs);archive(prev,ev);p,cal=choose(draws,state);adj=float(state.get('temperatureAdjustment',0));p['temperature']*=1+adj;fm=model(draws,'front',p,1,35);bm=model(draws,'back',p,1,12);latest=draws[-1];issue=str(int(latest['issue'])+1);dt=nextday(latest['date']);rng=random.Random(seed(VERSION,issue,dt,len(draws)));fp=pool(rng,fm,draws,'front',1,35,adj,1600);bp=pool(rng,bm,draws,'back',1,12,adj,120);chosen=assemble(rng,fp,bp,prev);now=datetime.now(timezone.utc).isoformat()
 out={'modelVersion':VERSION,'modelFamily':'curve-trajectory-generative-sampler','generatedAt':now,'targetIssue':issue,'targetDate':dt,'historyCount':len(draws),'historyRange':{'earliestIssue':draws[0]['issue'],'earliestDate':draws[0]['date'],'latestIssue':latest['issue'],'latestDate':latest['date']},'latestDraw':{'front':[f'{x:02d}' for x in latest['front']],'back':[f'{x:02d}' for x in latest['back']]},'lastEvaluation':ev,'calibration':{**cal,'temperature':round(p['temperature'],3),'temperatureAdjustment':round(adj,4),'note':'Forecasts sorted-position curves and samples their uncertainty band; it does not reuse a fixed hot-number list.'},'curveForecast':{'front':summary(fm),'back':summary(bm)},'diversity':{'maximumFrontOverlapBetweenResults':2,'maximumBackOverlapBetweenResults':1,'maximumFrontOverlapWithPreviousForecast':3,'selection':'temperature-weighted sampling from the high-fit curve band'},'results':[{'rank':x['rank'],'label':x['label'],'front':[f'{n:02d}' for n in x['front']],'back':[f'{n:02d}' for n in x['back']],'fit':x['fit'],'reason':reason(x,fm)} for x in chosen],'note':'All valid combinations remain equally likely in a fair lottery. Curve fit is not a winning probability.'}
 state.update(updatedAt=now,selectedProfile=p['name']);write(S,state);write(L,logs[-200:]);write(F,out);print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()

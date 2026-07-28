#!/usr/bin/env python3
"""Formula-only Feel the Chee. No historical winning numbers, no learning state."""
from __future__ import annotations
import itertools,json,math
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
R=Path(__file__).resolve().parents[1];D=R/'data/draws.json';A=R/'data/forecast.json';O=R/'data/chee-forecast.json';VERSION='v2.0-formula-only';FORMULA='hetu-luoshu-date-issue-v1'
E=['木','火','土','金','水'];SHOW=['金','火','土','木','水'];M={0:'土',1:'水',2:'火',3:'木',4:'金',5:'土',6:'水',7:'火',8:'木',9:'金'};GEN={'木':'火','火':'土','土':'金','金':'水','水':'木'};CTRL={'木':'土','土':'水','水':'火','火':'金','金':'木'};LO=[4,9,2,3,5,7,8,1,6]
def read(p,d):
 try:return json.loads(p.read_text(encoding='utf-8'))
 except (OSError,json.JSONDecodeError):return d
def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def dsum(x):return sum(int(c) for c in str(x) if c.isdigit())
def root(x):return 9 if x%9==0 else x%9
def nextday(s):
 d=date.fromisoformat(s)+timedelta(days=1)
 while d.weekday() not in {0,2,5}:d+=timedelta(days=1)
 return d.isoformat()
def target():
 p=read(A,{})
 if p.get('targetIssue') and p.get('targetDate'):return str(p['targetIssue']),str(p['targetDate'])
 m=read(D,{}).get('meta',{});return str(int(m['latestIssue'])+1),nextday(m['latestDate'])
def elem(n):return M[n%10]
def cd(a,b):
 x=abs(a-b);return min(x,9-x)
def context(issue,dt):
 d=date.fromisoformat(dt);compact=d.strftime('%Y%m%d');ds=dsum(compact);ins=dsum(issue);h=root(ds);e=root(ins);human=root(h+e+d.day);line=(h+e+d.month+d.day)%6+1;pd=(h+line)%10;pe=M[pd];support=GEN[pe];balance=GEN[support];control=CTRL[pe]
 return {'targetIssue':issue,'targetDate':dt,'dateDigits':compact,'dateDigitSum':ds,'issueDigitSum':ins,'heavenNumber':h,'earthNumber':e,'humanNumber':human,'movingLine':line,'guaNumber':root(h+e+human+line),'primaryDigit':pd,'issueTailDigit':int(issue[-1]),'dateTailDigit':int(compact[-1]),'yinYang':'阳' if (h+e+line+int(issue[-1]))%2 else '阴','primaryElement':pe,'supportElement':support,'balanceElement':balance,'controlElement':control}
def nscore(n,c,v):
 el=elem(n);ew={c['primaryElement']:1,c['supportElement']:.88,c['balanceElement']:.66,c['controlElement']:.30}.get(el,.44);r=root(n);res=lambda x:1-cd(r,x)/4.5;gm=1 if r==c['guaNumber'] else .70 if r in {LO[(c['guaNumber']-2)%9],LO[c['guaNumber']%9]} else .28;par=1 if n%2==(1 if c['yinYang']=='阳' else 0) else .45;tail=1 if n%10 in {c['primaryDigit'],c['issueTailDigit'],c['dateTailDigit']} else .35;vr=res(root(c['guaNumber']+v*c['movingLine']))
 return .34*ew+.14*res(c['heavenNumber'])+.12*res(c['earthNumber'])+.09*res(c['humanNumber'])+.10*gm+.08*par+.07*tail+.06*vr
def counts(ns):return {x:sum(elem(n)==x for n in ns) for x in E}
def pattern(c,pick,v):
 w={x:.2 for x in E}
 if v==1:w[c['primaryElement']]+=.70;w[c['supportElement']]+=.56;w[c['balanceElement']]+=.30
 else:w[c['primaryElement']]+=.42;w[c['supportElement']]+=.72;w[c['balanceElement']]+=.48;w[c['controlElement']]+=.18
 t=sum(w.values());return {x:pick*w[x]/t for x in E}
def cscore(combo,s,c,v,maxn):
 pick=len(combo);ec=counts(combo);tar=pattern(c,pick,v);bal=max(0,1-sum(abs(ec[x]-tar[x]) for x in E)/(2*pick));gs=root(sum(combo));gm=1 if gs==c['guaNumber'] else max(0,1-cd(gs,c['guaNumber'])/4.5);odd=math.exp(-abs(sum(n%2 for n in combo)-min(pick,3 if c['yinYang']=='阳' else 2))/max(1,pick));cov=len(set(map(root,combo))&{c['heavenNumber'],c['earthNumber'],c['humanNumber'],c['guaNumber']})/4;space=math.exp(-abs((combo[-1]-combo[0])/maxn-(.64 if pick==5 else .48))/.30)
 return .48*sum(s[n] for n in combo)/pick+.24*bal+.10*gm+.07*odd+.06*cov+.05*space
def rank(maxn,pick,c,v):
 s={n:nscore(n,c,v) for n in range(1,maxn+1)};return sorted(((q,cscore(q,s,c,v,maxn)) for q in itertools.combinations(range(1,maxn+1),pick)),key=lambda x:x[1],reverse=True)
def select(fr,br,old,v):
 of=set(old['front']) if old else set();ob=set(old['back']) if old else set()
 for f,fs in fr[:800]:
  if old and len(set(f)&of)>2:continue
  for b,bs in br[:50]:
   if old and len(set(b)&ob)>1:continue
   return {'front':f,'back':b,'raw':.79*fs+.21*bs,'variant':v}
 f,fs=fr[0];b,bs=br[0];return {'front':f,'back':b,'raw':.79*fs+.21*bs,'variant':v}
def strengths(c):
 x={e:30 for e in E};x[c['primaryElement']]+=58;x[c['supportElement']]+=42;x[c['balanceElement']]+=24;x[c['controlElement']]+=10;return {e:min(100,x[e]) for e in SHOW}
def fmt(x):return [f'{n:02d}' for n in x]
def reason(c):return f"公式输入第{c['targetIssue']}期与{c['targetDate']}；天数{c['heavenNumber']}、地数{c['earthNumber']}、人数{c['humanNumber']}、动爻{c['movingLine']}。按{c['primaryElement']}→{c['supportElement']}→{c['balanceElement']}生化路径及河图洛书数位共振选取，不读取历史开奖。"
def main():
 issue,dt=target();c=context(issue,dt);a=select(rank(35,5,c,1),rank(12,2,c,1),None,1);b=select(rank(35,5,c,2),rank(12,2,c,2),a,2);rows=[a,b];best=max(x['raw'] for x in rows);worst=min(x['raw'] for x in rows);span=best-worst or 1
 for i,x in enumerate(rows):x['cheeValue']=round(80+(x['raw']-worst)/span*6-i*.4,1);x['label']=['五行主衡','生化对冲'][i]
 out={'modelVersion':VERSION,'formulaVersion':FORMULA,'formulaOnly':True,'historyUsed':False,'learningEnabled':False,'generatedAt':datetime.now(timezone.utc).isoformat(),'targetIssue':issue,'targetDate':dt,'mapping':{'水':[1,6],'火':[2,7],'木':[3,8],'金':[4,9],'土':[0,5]},'elementStrengths':strengths(c),'calculation':c,'results':[{'rank':i+1,'label':x['label'],'front':fmt(x['front']),'back':fmt(x['back']),'cheeValue':x['cheeValue'],'elements':counts([*x['front'],*x['back']]),'reason':reason(c)} for i,x in enumerate(rows)],'note':'Feel the Chee uses only target issue/date and the He Tu / Luo Shu formula. No historical draw learning is used; Chee value is not a winning probability.'};write(O,out);print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()

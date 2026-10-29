#!/usr/bin/env python3
"""Daily million-iteration Monte Carlo trainer for AI, Chee audit, and Agent Instinct.

The trainer runs 1,000,000 stochastic historical simulations per model by default.
AI and Agent updates are accepted only when their held-out historical validation
objective improves. Feel the Chee remains formula-only: its million simulations
are an audit only and never change formula parameters.

This improves internal out-of-sample calibration scores, not the mathematical
probability of winning a fair lottery.
"""
from __future__ import annotations
import json, math, os, random, statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
AI_BACKTEST=DATA/"ai-backtest.json"
CHEE_BACKTEST=DATA/"chee-backtest.json"
HYBRID_BACKTEST=DATA/"hybrid-backtest.json"
AI_STATE=DATA/"model-state.json"
CHEE_STATE=DATA/"chee-model-state.json"
HYBRID_STATE=DATA/"hybrid-model-state.json"
LOG_FILE=DATA/"million-simulation-log.json"
CYCLE_LOG=DATA/"model-cycle-log.json"
ITERATIONS=max(1,int(os.environ.get("SIM_ITERATIONS","1000000")))
MIN_HOURS=max(0.0,float(os.environ.get("MIN_HOURS_BETWEEN_RUNS","20")))
AI_MAX_ANCHOR=0.88
SOURCES=("ai","chee","instinct")
CATEGORIES=("allThree","aiChee","aiInstinct","cheeInstinct","aiOnly","cheeOnly","instinctOnly")

def read_json(path,default):
    try:return json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError):return default

def write_json(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def clone(x):return json.loads(json.dumps(x))
def clamp(a,b,x):return max(a,min(b,x))

def split_rows(rows,f=.22):
    if len(rows)<40:return rows,rows
    cut=max(20,min(len(rows)-20,int(len(rows)*(1-f))))
    return rows[:cut],rows[cut:]

def score_from_loss(loss):return round(100*math.exp(-4*max(0.,loss)),4)

def last_age(logs,now):
    if not logs or not logs[-1].get("generatedAt"):return None
    try:t=datetime.fromisoformat(str(logs[-1]["generatedAt"]).replace("Z","+00:00"))
    except ValueError:return None
    return max(0.,(now-t).total_seconds()/3600)

def ai_vals(row):
    q=row.get("curveLoss",{})
    try:return float(q["model"]),float(q["trailingMean60"]),float(q.get("persistence",q["model"]))
    except (KeyError,TypeError,ValueError):return None

def ai_loss(rows,anchor):
    vals=[]
    for row in rows:
        v=ai_vals(row)
        if v:
            m,t,_=v;vals.append((1-anchor)*m+anchor*t)
    return statistics.fmean(vals) if vals else float("inf")

def train_ai(bt,state,rng):
    rows=[r for r in bt.get("draws",[]) if ai_vals(r)]
    train,val=split_rows(rows)
    old_cfg=state.get("millionSimulationTraining",{}) if isinstance(state.get("millionSimulationTraining"),dict) else {}
    current=clamp(0.,AI_MAX_ANCHOR,float(old_cfg.get("meanAnchorBlend",0.) or 0.))
    incumbent=current;accepted_moves=0;n=max(1,len(train))
    for i in range(ITERATIONS):
        row=train[rng.randrange(n)];m,t,_=ai_vals(row)
        progress=i/max(1,ITERATIONS-1);sigma=.22*(1-progress)+.015
        c=clamp(0.,AI_MAX_ANCHOR,incumbent+rng.gauss(0,sigma))
        li=(1-incumbent)*m+incumbent*t
        lc=(1-c)*m+c*t+.0008*abs(c-current)
        if lc+1e-12<li:incumbent=c;accepted_moves+=1
    before=ai_loss(val,current);candidate=ai_loss(val,incumbent)
    accepted=candidate+1e-9<before;final=incumbent if accepted else current
    bench=bt.get("summary",{}).get("curveBenchmark",{})
    ml=float(bench.get("modelAverageLoss",before) or before);tl=float(bench.get("trailingMean60AverageLoss",ml) or ml)
    target=clamp(-.18,.18,-2.4*(ml-tl));old_temp=float(state.get("temperatureAdjustment",0.) or 0.)
    new_temp=round(.75*old_temp+.25*target,4) if accepted else round(old_temp,4)
    after=ai_loss(val,final);state["temperatureAdjustment"]=new_temp
    state["millionSimulationTraining"]={
      "version":1,"iterationsPerRun":ITERATIONS,"totalIterations":int(old_cfg.get("totalIterations",0))+ITERATIONS,
      "runs":int(old_cfg.get("runs",0))+1,"meanAnchorBlend":round(final,6),"validationLoss":round(after,8),
      "validationScore":score_from_loss(after),"accepted":accepted,"acceptedTrialMoves":accepted_moves,"validationRows":len(val),
      "rule":"Challengers replace live AI calibration only when chronological held-out curve loss falls. Score is validation, not winning probability."
    }
    return {"iterations":ITERATIONS,"trainingRows":len(train),"validationRows":len(val),"anchorBefore":round(current,6),"anchorAfter":round(final,6),
      "validationLossBefore":round(before,8),"validationLossAfter":round(after,8),"validationScoreBefore":score_from_loss(before),
      "validationScoreAfter":score_from_loss(after),"accepted":accepted,"acceptedTrialMoves":accepted_moves,
      "temperatureBefore":round(old_temp,4),"temperatureAfter":new_temp}

def chee_samples(bt):
    out=[]
    for d in bt.get("drawResults",[]):
        for t in d.get("tickets",[]):
            try:out.append((int(t.get("frontHitCount",0)),int(t.get("backHitCount",0)),float(t.get("elementSimilarity",0.))))
            except (TypeError,ValueError):pass
    return out

def audit_chee(bt,state,rng):
    samples=chee_samples(bt)
    if not samples:raise RuntimeError("Chee backtest has no tickets")
    fs=bs=es=0.;n=len(samples)
    for _ in range(ITERATIONS):
        f,b,e=samples[rng.randrange(n)];fs+=f;bs+=b;es+=e
    fm=fs/ITERATIONS;bm=bs/ITERATIONS;em=es/ITERATIONS;base=25/35+4/12
    audit=round(clamp(0,100,50+22*((fm+bm)-base)),4)
    old=state.get("millionSimulationAudit",{}) if isinstance(state.get("millionSimulationAudit"),dict) else {}
    state["millionSimulationAudit"]={"version":1,"iterationsPerRun":ITERATIONS,"totalIterations":int(old.get("totalIterations",0))+ITERATIONS,
      "runs":int(old.get("runs",0))+1,"sampledAverageFrontHits":round(fm,6),"sampledAverageBackHits":round(bm,6),
      "sampledAverageElementSimilarity":round(em,6),"auditScore":audit,"formulaOnly":True,"learningEnabled":False,
      "rule":"Million-run bootstrap audit only. No historical outcome changes the Chee formula."}
    return {"iterations":ITERATIONS,"historicalTicketPool":n,"sampledAverageFrontHits":round(fm,6),"sampledAverageBackHits":round(bm,6),
      "sampledAverageElementSimilarity":round(em,6),"auditScore":audit,"formulaChanged":False}

def hybrid_rows(bt):
    out=[]
    for row in bt.get("draws",[]):
        ev=row.get("evaluation",{});s=ev.get("sourcePerformance",{});c=ev.get("strategyPerformance",{})
        if s:out.append((s,c))
    return out

def rr(source,area,name):
    try:return float(source.get(area,{}).get(name,{}).get("rewardRatio",1.))
    except (TypeError,ValueError):return 1.

def cr(strategy,area,name):
    try:return float(strategy.get(area,{}).get(name,{}).get("rewardRatio",1.))
    except (TypeError,ValueError):return 1.

def norm_sources(rewards):
    raw={n:math.exp(1.8*(float(rewards.get(n,1.))-1.)) for n in SOURCES};total=sum(raw.values()) or 1.;floor=.15;free=1-floor*len(SOURCES)
    return {n:floor+free*raw[n]/total for n in SOURCES}

def norm_cats(rewards):
    vals={n:float(rewards.get(n,1.)) for n in CATEGORIES};m=statistics.fmean(vals.values()) or 1.
    return {n:clamp(.65,1.35,vals[n]/m) for n in CATEGORIES}

def hybrid_score(rows,sw,cw):
    if not rows:return float("-inf")
    total=0.
    for s,c in rows:
        val=0.
        for area,aw in (("front",.72),("back",.28)):
            src=sum(float(sw.get(area,{}).get(n,0.))*rr(s,area,n) for n in SOURCES)
            den=sum(float(cw.get(area,{}).get(n,1.)) for n in CATEGORIES) or 1.
            cat=sum(float(cw.get(area,{}).get(n,1.))*cr(c,area,n) for n in CATEGORIES)/den
            val+=aw*(.72*src+.28*cat)
        total+=val
    return total/len(rows)

def train_hybrid(bt,state,rng):
    rows=hybrid_rows(bt);train,val=split_rows(rows)
    if not train:raise RuntimeError("Agent backtest has no reward rows")
    ss={a:{n:0. for n in SOURCES} for a in ("front","back")}
    cs={a:{n:0. for n in CATEGORIES} for a in ("front","back")};n=len(train)
    for _ in range(ITERATIONS):
        s,c=train[rng.randrange(n)]
        for a in ("front","back"):
            for name in SOURCES:ss[a][name]+=rr(s,a,name)
            for name in CATEGORIES:cs[a][name]+=cr(c,a,name)
    se={a:{n:ss[a][n]/ITERATIONS for n in SOURCES} for a in ("front","back")}
    ce={a:{n:cs[a][n]/ITERATIONS for n in CATEGORIES} for a in ("front","back")}
    sw={a:norm_sources(se[a]) for a in ("front","back")};cw={a:norm_cats(ce[a]) for a in ("front","back")}
    current_sw=clone(state.get("sourceWeights",{}));current_cw=clone(state.get("strategyWeights",{}))
    before=hybrid_score(val,current_sw,current_cw);candidate=hybrid_score(val,sw,cw);accepted=candidate>before+1e-8
    if accepted:
        state["sourceEma"]={a:{n:round(se[a][n],9) for n in SOURCES} for a in ("front","back")}
        state["strategyEma"]={a:{n:round(ce[a][n],9) for n in CATEGORIES} for a in ("front","back")}
        state["sourceWeights"]={a:{n:round(sw[a][n],6) for n in SOURCES} for a in ("front","back")}
        state["strategyWeights"]={a:{n:round(cw[a][n],6) for n in CATEGORIES} for a in ("front","back")}
    after=candidate if accepted else before;old=state.get("millionSimulationTraining",{}) if isinstance(state.get("millionSimulationTraining"),dict) else {}
    state["millionSimulationTraining"]={"version":1,"iterationsPerRun":ITERATIONS,"totalIterations":int(old.get("totalIterations",0))+ITERATIONS,
      "runs":int(old.get("runs",0))+1,"validationRawScore":round(after,8),"validationScore":round(clamp(0,100,50+18*(after-1)),4),
      "accepted":accepted,"validationRows":len(val),
      "rule":"Million bootstrap reward simulations estimate source/category weights; write only when chronological held-out validation improves."}
    conv=lambda x:round(clamp(0,100,50+18*(x-1)),4)
    return {"iterations":ITERATIONS,"trainingRows":len(train),"validationRows":len(val),"validationRawBefore":round(before,8),
      "validationRawAfter":round(after,8),"validationScoreBefore":conv(before),"validationScoreAfter":conv(after),"accepted":accepted,
      "sourceWeightsBefore":current_sw,"sourceWeightsAfter":clone(state.get("sourceWeights",{})),"strategyWeightsAfter":clone(state.get("strategyWeights",{}))}

def main():
    now=datetime.now(timezone.utc);logs=read_json(LOG_FILE,[])
    if not isinstance(logs,list):logs=[]
    age=last_age(logs,now)
    if age is not None and age<MIN_HOURS and os.environ.get("FORCE_MILLION_SIMULATION")!="1":
        print(json.dumps({"skipped":True,"reason":f"Last million run was {age:.2f} hours ago.","minimumHoursBetweenRuns":MIN_HOURS},ensure_ascii=False,indent=2));return
    ab=read_json(AI_BACKTEST,{});cb=read_json(CHEE_BACKTEST,{});hb=read_json(HYBRID_BACKTEST,{})
    if not ab.get("draws"):raise RuntimeError("AI backtest required")
    if not cb.get("drawResults"):raise RuntimeError("Chee backtest required")
    if not hb.get("draws"):raise RuntimeError("Agent backtest required")
    ast=read_json(AI_STATE,{});cst=read_json(CHEE_STATE,{});hst=read_json(HYBRID_STATE,{})
    if not isinstance(ast,dict):ast={}
    if not isinstance(cst,dict):cst={}
    if not isinstance(hst,dict):hst={}
    rid=now.strftime("%Y%m%dT%H%M%S.%fZ");seed=sum((i+1)*ord(ch) for i,ch in enumerate(rid))%(2**63-1)
    ar=train_ai(ab,ast,random.Random(seed^0xA11CE))
    crs=audit_chee(cb,cst,random.Random(seed^0xC4EE))
    hr=train_hybrid(hb,hst,random.Random(seed^0xA63E7))
    stamp=now.isoformat();ast["updatedAt"]=stamp;cst["updatedAt"]=stamp;hst["updatedAt"]=stamp
    write_json(AI_STATE,ast);write_json(CHEE_STATE,cst);write_json(HYBRID_STATE,hst)
    event={"runId":rid,"generatedAt":stamp,"iterationsPerModel":ITERATIONS,"totalIterations":ITERATIONS*3,
      "cadence":"once per 24h; draw-night retries skip when a recent million-run exists","ai":ar,"chee":crs,"agent":hr,
      "policy":{"ai":"adaptive; held-out validation gate","chee":"formula-only audit; no historical learning","agent":"adaptive; held-out validation gate"},
      "disclaimer":"Validation score can improve while future lottery accuracy does not. All legal combinations remain equally likely in a fair draw."}
    logs.append(event);write_json(LOG_FILE,logs[-400:])
    cyc=read_json(CYCLE_LOG,[])
    if isinstance(cyc,list) and cyc:
        cyc[-1]["millionSimulation"]=event;write_json(CYCLE_LOG,cyc)
    print(json.dumps(event,ensure_ascii=False,indent=2))

if __name__=="__main__":main()

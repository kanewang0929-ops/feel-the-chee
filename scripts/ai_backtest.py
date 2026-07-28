#!/usr/bin/env python3
"""Past-only walk-forward audit for the AI curve sampler."""
from __future__ import annotations
import json,math,statistics
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
import curve_forecast as ai

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data/ai-backtest.json"
VERSION="v1.1-walk-forward-bounded"
WARMUP=500
RECALIBRATE_EVERY=60
FRONT_POOL=100
BACK_POOL=25

def write(x):
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(x,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def fmt(x):return [f"{int(n):02d}" for n in x]

def hyper(pop,winners,picks):
    d=math.comb(pop,picks)
    return {str(h):math.comb(winners,h)*math.comb(pop-winners,picks-h)/d for h in range(min(winners,picks)+1)}

def centers(values):return [{"center":float(v)} for v in values]

def mean_centers(history,area,window=60):
    q=history[-min(window,len(history)):];width=len(q[0][area])
    return [{"center":statistics.fmean(x[area][i] for x in q)} for i in range(width)]

def ticket_distance(front,back,actual):
    f=statistics.fmean(abs(a-b) for a,b in zip(front,actual["front"]))/35
    r=statistics.fmean(abs(a-b) for a,b in zip(back,actual["back"]))/12
    return .72*f+.28*r

def audit_pool(rng,m,history,area,lo,hi,adj,target,attempts):
    sh=ai.shape(history,area);out={}
    for _ in range(attempts):
        v=ai.sample(rng,m,lo,hi,adj)
        if v:out[v]=max(out.get(v,0.),ai.score(v,m,sh))
        if len(out)>=target:break
    rows=sorted(out.items(),key=lambda x:x[1],reverse=True)
    if len(rows)<25:raise RuntimeError(f"Candidate pool too small for {area}: {len(rows)}")
    return rows

def forecast(history,actual,state,previous,profile0,cal0):
    p=dict(profile0);cal=dict(cal0);adj=float(state.get("temperatureAdjustment",0.))
    p["temperature"]*=1+adj
    fm=ai.model(history,"front",p,1,35);bm=ai.model(history,"back",p,1,12)
    rng=ai.random.Random(ai.seed(ai.VERSION,actual["issue"],actual["date"],len(history)))
    fp=audit_pool(rng,fm,history,"front",1,35,adj,FRONT_POOL,300)
    bp=audit_pool(rng,bm,history,"back",1,12,adj,BACK_POOL,120)
    chosen=ai.assemble(rng,fp,bp,previous)
    out={
      "targetIssue":actual["issue"],"targetDate":actual["date"],
      "calibration":{**cal,"temperature":round(p["temperature"],4),"temperatureAdjustment":round(adj,4)},
      "curveForecast":{"front":ai.summary(fm),"back":ai.summary(bm)},
      "results":[{"rank":x["rank"],"label":x["label"],"front":fmt(x["front"]),"back":fmt(x["back"]),"fit":x["fit"]} for x in chosen]
    }
    return out,fm,bm

def score(actual,pred,fm,bm,history):
    af=set(actual["front"]);ab=set(actual["back"]);tickets=[]
    for x in pred["results"]:
        f=[int(n) for n in x["front"]];b=[int(n) for n in x["back"]]
        fh=sorted(af&set(f));bh=sorted(ab&set(b))
        tickets.append({
          "rank":x["rank"],"label":x["label"],"front":x["front"],"back":x["back"],
          "frontHits":fmt(fh),"backHits":fmt(bh),"frontHitCount":len(fh),"backHitCount":len(bh),
          "curveDistance":round(ticket_distance(f,b,actual),6)
        })
    best=max(tickets,key=lambda x:(x["frontHitCount"]+x["backHitCount"],x["frontHitCount"],x["backHitCount"],-x["curveDistance"]))
    ml=.72*ai.loss(actual["front"],fm,35)+.28*ai.loss(actual["back"],bm,12)
    pl=.72*ai.loss(actual["front"],centers(history[-1]["front"]),35)+.28*ai.loss(actual["back"],centers(history[-1]["back"]),12)
    mf=mean_centers(history,"front");mb=mean_centers(history,"back")
    tl=.72*ai.loss(actual["front"],mf,35)+.28*ai.loss(actual["back"],mb,12)
    return {
      "issue":actual["issue"],"date":actual["date"],"trainingDraws":len(history),
      "actual":{"front":fmt(actual["front"]),"back":fmt(actual["back"])},
      "profile":{"name":pred["calibration"]["selectedProfile"],"label":pred["calibration"]["selectedLabel"],"temperature":pred["calibration"]["temperature"]},
      "curveLoss":{"model":round(ml,6),"persistence":round(pl,6),"trailingMean60":round(tl,6)},
      "tickets":tickets,
      "bestTicket":{"rank":best["rank"],"frontHitCount":best["frontHitCount"],"backHitCount":best["backHitCount"],"curveDistance":best["curveDistance"]}
    }

def aggregate(rows):
    tickets=[t for x in rows for t in x["tickets"]];n=len(tickets)
    fd=Counter(t["frontHitCount"] for t in tickets);bd=Counter(t["backHitCount"] for t in tickets)
    patterns=Counter(f'{t["frontHitCount"]}+{t["backHitCount"]}' for t in tickets)
    bfd=Counter(x["bestTicket"]["frontHitCount"] for x in rows);bbd=Counter(x["bestTicket"]["backHitCount"] for x in rows)
    af=statistics.fmean(t["frontHitCount"] for t in tickets);ab=statistics.fmean(t["backHitCount"] for t in tickets)
    td=statistics.fmean(t["curveDistance"] for t in tickets)
    ml=statistics.fmean(x["curveLoss"]["model"] for x in rows)
    pl=statistics.fmean(x["curveLoss"]["persistence"] for x in rows)
    tl=statistics.fmean(x["curveLoss"]["trailingMean60"] for x in rows)
    fb=25/35;bb=4/12;fp=hyper(35,5,5);bp=hyper(12,2,2)
    template=lambda:{"draws":0,"tickets":0,"front":0,"back":0,"loss":0.}
    byyear=defaultdict(template);byprofile=defaultdict(template)
    for x in rows:
        for g in (byyear[x["date"][:4]],byprofile[x["profile"]["label"]]):
            g["draws"]+=1;g["tickets"]+=len(x["tickets"]);g["front"]+=sum(t["frontHitCount"] for t in x["tickets"]);g["back"]+=sum(t["backHitCount"] for t in x["tickets"]);g["loss"]+=x["curveLoss"]["model"]
    def finish(groups):
        return {k:{"draws":v["draws"],"tickets":v["tickets"],"averageFrontHits":round(v["front"]/max(1,v["tickets"]),4),"averageBackHits":round(v["back"]/max(1,v["tickets"]),4),"averageModelCurveLoss":round(v["loss"]/max(1,v["draws"]),6)} for k,v in groups.items()}
    examples=sorted(rows,key=lambda x:(x["bestTicket"]["frontHitCount"]+x["bestTicket"]["backHitCount"],x["bestTicket"]["frontHitCount"],x["bestTicket"]["backHitCount"],-x["bestTicket"]["curveDistance"]),reverse=True)[:20]
    return {
      "drawsEvaluated":len(rows),"warmupDraws":WARMUP,"ticketsEvaluated":n,
      "dateRange":{"earliest":rows[0]["date"],"latest":rows[-1]["date"]},
      "observed":{
        "averageFrontHitsPerTicket":round(af,6),"averageBackHitsPerTicket":round(ab,6),"averageTotalHitsPerTicket":round(af+ab,6),"averageTicketCurveDistance":round(td,6),
        "ticketsWithAnyFrontHit":sum(t["frontHitCount"]>=1 for t in tickets),"ticketsWithAnyBackHit":sum(t["backHitCount"]>=1 for t in tickets),
        "ticketsWithFrontAndBackHit":sum(t["frontHitCount"]>=1 and t["backHitCount"]>=1 for t in tickets),
        "frontHitDistribution":{str(h):fd[h] for h in range(6)},"backHitDistribution":{str(h):bd[h] for h in range(3)},
        "hitPatternDistribution":dict(sorted(patterns.items())),"bestOfThreeFrontDistribution":{str(h):bfd[h] for h in range(6)},
        "bestOfThreeBackDistribution":{str(h):bbd[h] for h in range(3)},"exactFivePlusTwo":patterns["5+2"]
      },
      "curveBenchmark":{"modelAverageLoss":round(ml,6),"persistenceAverageLoss":round(pl,6),"trailingMean60AverageLoss":round(tl,6),"improvementVsPersistence":round(pl-ml,6),"improvementVsTrailingMean60":round(tl-ml,6),"note":"Lower is better. Persistence uses the previous draw; trailingMean60 uses prior 60-draw positional means."},
      "theoreticalFixedTicketBaseline":{
        "averageFrontHitsPerTicket":round(fb,6),"averageBackHitsPerTicket":round(bb,6),"averageTotalHitsPerTicket":round(fb+bb,6),
        "frontHitProbabilities":{k:round(v,10) for k,v in fp.items()},"backHitProbabilities":{k:round(v,10) for k,v in bp.items()},
        "expectedFrontHitCounts":{k:round(v*n,3) for k,v in fp.items()},"expectedBackHitCounts":{k:round(v*n,3) for k,v in bp.items()},
        "note":"Exact fair-draw expectation per ticket; best-of-three is reported descriptively because AI tickets are deliberately dependent."
      },
      "comparison":{"frontMeanDifference":round(af-fb,6),"backMeanDifference":round(ab-bb,6),"totalMeanDifference":round(af+ab-fb-bb,6),"frontMeanRatio":round(af/fb,6),"backMeanRatio":round(ab/bb,6)},
      "byYear":finish(byyear),"byProfile":finish(byprofile),"bestExamples":examples
    }

def main():
    draws=ai.load()
    if len(draws)<=WARMUP:raise RuntimeError(f"Need more than {WARMUP} draws")
    state=ai.state0();previous={"results":[]};rows=[];p0=cal0=None
    for i in range(WARMUP,len(draws)):
        history=draws[:i];actual=draws[i]
        if p0 is None or (i-WARMUP)%RECALIBRATE_EVERY==0:p0,cal0=ai.choose(history,state)
        pred,fm,bm=forecast(history,actual,state,previous,p0,cal0)
        row=score(actual,pred,fm,bm,history)
        ev=ai.evaluate(pred,draws[:i+1],state,[])
        if ev is None:raise RuntimeError(f"Could not evaluate {actual['issue']}")
        row["learningUpdate"]=ev["learningUpdate"];rows.append(row);previous=pred
        if len(rows)%100==0:print(f"Evaluated {len(rows)} / {len(draws)-WARMUP} draws",flush=True)
    out={
      "backtestVersion":VERSION,"modelVersion":ai.VERSION,"modelFamily":"curve-trajectory-generative-sampler",
      "walkForward":True,"futureLeakage":False,"generatedAt":datetime.now(timezone.utc).isoformat(),
      "method":{"warmupDraws":WARMUP,"trainingRule":"Every forecast uses only draws published before its target.","profileRecalibrationInterval":RECALIBRATE_EVERY,"curveRefitEveryDraw":True,"auditSamplingBudget":{"frontPool":FRONT_POOL,"backPool":BACK_POOL,"note":"The live model uses a larger candidate pool; the audit uses a fixed bounded pool for thousands of reproducible steps."}},
      "summary":aggregate(rows),"draws":rows,
      "note":"All valid combinations remain equally likely in a fair lottery. This audit measures historical behavior, not future winning probability."
    }
    write(out);print(json.dumps({"backtestVersion":VERSION,"modelVersion":ai.VERSION,"summary":out["summary"]},ensure_ascii=False,indent=2))

if __name__=="__main__":main()

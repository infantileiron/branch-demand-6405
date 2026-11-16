import math,json,hashlib
from datetime import date,timedelta
def holt(values,horizon,alpha,beta):
 if len(values)<2:raise ValueError('Holt至少需要2天数据')
 level=float(values[0]);trend=float(values[1]-values[0])
 for value in values[1:]:
  previous=level;level=alpha*value+(1-alpha)*(level+trend);trend=beta*(level-previous)+(1-beta)*trend
 return [level+h*trend for h in range(1,horizon+1)]
def seasonal(values,horizon):return [float(values[-7+i%7]) for i in range(horizon)]
def scores(actual,predicted):
 errors=[abs(a-p) for a,p in zip(actual,predicted)];pairs=[(a,p) for a,p in zip(actual,predicted) if a!=0]
 return {'mae':sum(errors)/len(errors),'mape':sum(abs(a-p)/a for a,p in pairs)/len(pairs)*100 if pairs else None,'mape_used':len(pairs),'zero_actual':len(actual)-len(pairs)}
def forecast(rows,backtest_days,alpha,beta):
 rows=sorted(rows,key=lambda r:r['day']);days=[date.fromisoformat(r['day']) for r in rows]
 if len(rows)<backtest_days+28:raise ValueError(f'至少需要{backtest_days+28}个连续日量，保证回测前28天训练窗口')
 if len(set(days))!=len(days):raise ValueError('同网点存在重复日期，请先核对')
 gaps=[(a.isoformat(),b.isoformat()) for a,b in zip(days,days[1:]) if b-a!=timedelta(days=1)]
 if gaps:raise ValueError('日期不连续，缺口：'+str(gaps[:3])+'；不可将缺日当作零量')
 values=[r['volume'] for r in rows];start=len(values)-backtest_days;predictions={'seasonal_naive':[],'holt':[]};clipped={'seasonal_naive':0,'holt':0}
 for i in range(start,len(values)):
  train=values[:i]
  for model,raw in [('seasonal_naive',seasonal(train,1)[0]),('holt',holt(train,1,alpha,beta)[0])]:
   if raw<0:clipped[model]+=1
   predictions[model].append(max(0,raw))
 metrics={m:scores(values[start:],ps) for m,ps in predictions.items()}
 selected=min(metrics,key=lambda m:(metrics[m]['mae'],m!='seasonal_naive'))
 future={m:[] for m in predictions}
 for model,raw in [('seasonal_naive',seasonal(values,7)),('holt',holt(values,7,alpha,beta))]:
  for h,p in enumerate(raw,1):future[model].append({'day':(days[-1]+timedelta(days=h)).isoformat(),'raw':p,'prediction':max(0,int(math.floor(p+.5))),'clipped':p<0})
 return dict(branch=rows[0]['branch'],n=len(rows),train_initial=start,backtest_days=backtest_days,alpha=alpha,beta=beta,metrics=metrics,selected_model=selected,backtest=[{'day':rows[i]['day'],'actual':values[i],**{m:predictions[m][i-start] for m in predictions}} for i in range(start,len(values))],future=future,history=[{'day':r['day'],'volume':r['volume']} for r in rows],backtest_clipped=clipped,checksum=hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),warning='按时间顺序滚动一步回测，每个预测只用此前数据；α/β为提交前指定，不用回测真值调参。回测MAE用于选模，不是独立最终泛化估计。MAPE跳过实际值0并报告数量；全部为0时MAPE未定义。负预测先截为0，未来值四舍五入为非负整数。')


def _allocation_weights(errors):
 """按各网点入选模型的回测MAE分配区域校正量：误差越大，承担越多校正。
 全部为0（零误差）时平均分担，避免除零。"""
 n=len(errors);total=sum(max(0.0,e) for e in errors.values())
 if total<=0:return {b:1.0/n for b in errors}
 return {b:max(0.0,e)/total for b,e in errors.items()}


def _exact_integers(ideal,target):
 """把浮点需求变成非负整数且合计恰为target（最大余数法，并处理截负溢出）。"""
 if target<0:raise ValueError('协调目标不能为负')
 work=[max(0.0,float(x)) for x in ideal]
 result=[int(math.floor(x)) for x in work]
 diff=target-sum(result)
 fractions=[work[i]-result[i] for i in range(len(work))]
 if diff>0:
  order=sorted(range(len(work)),key=lambda i:(-fractions[i],i))
  for k in range(diff):result[order[k%len(order)]]+=1
 elif diff<0:
  need=-diff
  order=sorted([i for i in range(len(work)) if result[i]>0],key=lambda i:(fractions[i],i))
  if not order:raise ValueError('无法在非负约束下协调到目标合计')
  k=0
  while need>0:
   changed=False
   for i in order:
    if need<=0:break
    if result[i]>0:result[i]-=1;need-=1;changed=True
   if not changed:raise ValueError('无法在非负约束下协调到目标合计')
 if sum(result)!=target:raise ValueError('协调后合计与区域不一致')
 return result


def reconcile(region_result,member_results):
 """区域总量为准，按网点回测误差分配差额；输出调整前后、权重与逐日依据。"""
 region_model=region_result['selected_model'];region_future=region_result['future'][region_model]
 branches=list(member_results)
 models={b:member_results[b]['selected_model'] for b in branches}
 mae={b:float(member_results[b]['metrics'][models[b]]['mae']) for b in branches}
 mape={b:member_results[b]['metrics'][models[b]]['mape'] for b in branches}
 weights=_allocation_weights(mae)
 credibility={b:round(1.0/(1.0+mae[b]),6) for b in branches}
 days=[]
 for h,point in enumerate(region_future):
  target=int(point['prediction']);raw={b:int(member_results[b]['future'][models[b]][h]['prediction']) for b in branches}
  total=sum(raw.values());gap=target-total
  ideal={b:raw[b]+gap*weights[b] for b in branches}
  adjusted=_exact_integers([ideal[b] for b in branches],target)
  after={b:adjusted[i] for i,b in enumerate(branches)}
  if sum(after.values())!=target:raise ValueError('每日网点合计与区域不一致')
  days.append({'day':point['day'],'region':target,'branch_raw_sum':total,'gap':gap,'branches':{b:{'before':raw[b],'after':after[b],'delta':after[b]-raw[b],'correction':gap*weights[b]} for b in branches},'after_sum':target})
 return {'region_model':region_model,'region_mae':float(region_result['metrics'][region_model]['mae']),'region_mape':region_result['metrics'][region_model]['mape'],'region_credibility':round(1.0/(1.0+float(region_result['metrics'][region_model]['mae'])),6),'branches':{b:{'model':models[b],'mae':mae[b],'mape':mape[b],'credibility':credibility[b],'adjust_weight':weights[b]} for b in branches},'days':days,'rule':'区域逐日预测为总量锚点；各网点独立选模后与区域差额按回测MAE分摊，MAE越大的网点承担越多校正；结果取非负整数且逐日合计等于区域。回测MAE仅用于可信度排序，不是独立泛化精度。'}

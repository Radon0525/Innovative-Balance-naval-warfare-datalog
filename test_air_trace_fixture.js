rpc.exports.reservoir=function(){
  airExamples.clear();let seed=123456;
  const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};
  for(let n=1;n<=10000;n++)for(const reverse of [false,true]){
    const src={id:'carrier',name:'Carrier',country:reverse?2:1,kind:'ship'},dst={id:'ship',name:'Ship',country:reverse?1:2,kind:'ship'};
    sampleCarrier({kind:'air',channel:n%2?'carrier_battle':'carrier_mission',source:src,target:dst,sequence:n,planes:10,successes:n%4},random);
  }
  sampleCarrier({kind:'air',source:{kind:'airbase',country:3},target:{country:1}},random);
  return snapshotAirExamples();
};
rpc.exports.traceattack=function(){
  airExamples.clear();CONFIG.air_trace_layout={globals:{}};CONFIG.damage_layout={fixed_scale:100000};
  const frame2=alloc(0x200).add(0x80),cell=alloc(8);
  const reg={rbp:frame2,rax:cell,rdx:ptr(50000),r8:ptr(0),rdi:ptr(0),rbx:ptr(0)};
  function point(name,value){cell.writeS64(value);airTracePoint(name,reg);}
  const notify=new NativeCallback(function(){
    airTracePoint('probability',reg);point('hit_random',50000);
    frame.sub(0x20).writeS64(250000);air(10,3);
    point('reduction',25000);reg.r8=ptr(450000);airTracePoint('base_damage',reg);
    frame2.sub(0x38).writeS64(900000);frame2.sub(0x30).writeS64(450000);point('reliability',80000);
    reg.rbx=ptr(1000);point('critical_modifier',0);
    reg.rdi=ptr(1000);point('critical_roll',99999);
    reg.rdi=ptr(0);airTracePoint('critical_branch',reg);
    airTracePoint('final_damage',reg);
  },'void',[]);
  const helper=new CModule(`void apply(char *p,long long hp,long long org){long long *s=(long long *)(p+0x6f8),*o=(long long *)(p+0x700);*s=hp>*s?0:*s-hp;*o=org>*o?0:*o-org;}`);
  const drv=new CModule(`extern void notify(void);extern void apply(char*,long long,long long);
    void attack(char *p,long long t,long long m,int n,long long a,char *target,void *b){notify();apply(target,900000,450000);}`,
    {notify,apply:helper.apply});
  keep.push(notify,helper,drv);
  installAttackScope('air',drv.attack);
  installDamageFunction(helper.apply,{str_offset:0x6f8,org_offset:0x700},callReturns(drv.attack,'air'));
  Interceptor.flush();health(500000,200000);
  new NativeFunction(drv.attack,'void',['pointer','int64','int64','int','int64','pointer','pointer'])(group,50000,100000,10,200000,target.ship,battle);
  return snapshotDetails();
};
rpc.exports.tracebranches=function(){
  const scope={kind:'air',trace:{values:{},applications:[]}};
  attackScopes.set(Process.getCurrentThreadId(),[scope]);
  const f=alloc(0x180).add(0x80),value=alloc(8),effect=alloc(0x180),c={rbp:f,rax:value,rdi:ptr(1),rbx:ptr(150000)};
  airTracePoint('critical_branch',c);value.writeS64(10);c.rdi=ptr(500);airTracePoint('critical_roll',c);
  effect.add(0x148).writeS64(200000);effect.add(0x150).writeS64(100000);effect.add(0x158).writeS64(50000);effect.add(0x160).writeS64(0);
  c.rdi=effect;airTracePoint('effect_apply',c);
  f.sub(0x38).writeS64(250000);f.sub(0x30).writeS64(100000);c.rax=ptr(1);airTracePoint('special_result',c);
  airTracePoint('final_damage',c);attackScopes.clear();return scope.trace;
};

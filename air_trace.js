// Independent reservoir sampling: never consume or modify the game's random state.
const airExamples=new Map();
const airExampleStats={flow_overflow:0,read_errors:0};
const AIR_FLOW_LIMIT=128,AIR_EXAMPLE_LIMIT=5;
const airDispatchScopes=new Map();
function airScope(){const s=attackScopes.get(Process.getCurrentThreadId());const t=s&&s[s.length-1];return t&&t.kind==='air'?t:null;}
function signed(p){return BigInt.asIntN(64,BigInt(p.toString())).toString();}
function beginAirTrace(scope,args) {
  if(!CONFIG.air_trace_layout)return;
  scope.trace={version:1,complete:false,values:{},applications:[]};
  try {
    const v=scope.trace.values;
    const parents=airDispatchScopes.get(Process.getCurrentThreadId());
    if(parents&&parents.length)scope.trace.upstream={...parents[parents.length-1]};
    v.targetting=signed(args[1]);v.targetting_modifier=signed(args[2]);
    v.planes=args[3].toInt32();v.attack=signed(args[4]);
    for(const [key,rva] of Object.entries(CONFIG.air_trace_layout.globals))v[key]=detailModule.base.add(rva).readS64().toString();
  }catch(e){scope.trace.error='入力値を取得できませんでした';airExampleStats.read_errors++;}
}
function sampleCarrier(event,random=Math.random) {
  if(event.kind!=='air'||event.source.kind!=='ship')return false;
  const key=JSON.stringify([event.source.country||0,event.target.country||0]);
  let bucket=airExamples.get(key);
  if(!bucket){
    if(airExamples.size>=AIR_FLOW_LIMIT){airExampleStats.flow_overflow++;return false;}
    bucket={source_country:event.source.country||0,target_country:event.target.country||0,seen:0,examples:[]};airExamples.set(key,bucket);
  }
  bucket.seen++;
  const index=bucket.seen<=AIR_EXAMPLE_LIMIT?bucket.seen-1:Math.floor(random()*bucket.seen);
  if(index>=AIR_EXAMPLE_LIMIT)return false;
  bucket.examples[index]=event;return true;
}
function attachAirExample(event,cpu) {
  const scope=airScope();
  if(scope&&scope.trace){
    event.air_trace=scope.trace;
    scope.trace.values.successes=event.successes;
    try{scope.trace.values.round_input=cpu.rbp.sub(0x20).readS64().toString();}
    catch(e){scope.trace.error='丸め前の値を取得できませんでした';airExampleStats.read_errors++;}
  }
  event.recorded_at=new Date().toISOString();
  const selected=sampleCarrier(event);
  if(scope){scope.traceSelected=selected;if(!selected)scope.trace=null;}
  if(!selected)delete event.air_trace;
  // Retained samples share the event until its damage application is complete.
}
function snapshotAirExamples(){return {limit:AIR_EXAMPLE_LIMIT,flow_limit:AIR_FLOW_LIMIT,stats:{...airExampleStats},buckets:Array.from(airExamples.values())};}
function airTracePoint(name,c) {
  if(name.startsWith('stat_')||name.startsWith('wing_')){captureAirAttackBuild(name,c);return;}
  if(name.startsWith('up_')){captureAirDispatch(name,c);return;}
  const scope=airScope();if(!scope||!scope.trace||scope.traceSelected===false)return;
  const v=scope.trace.values,reg=p=>signed(p),mem=p=>p.readS64().toString();
  try {
    switch(name){
      case 'probability':v.probability=reg(c.rdx);break;
      case 'hit_random':v.hit_random=mem(c.rax);break;
      case 'aa_fleet':v.aa_fleet=reg(c.rdx);break;
      case 'aa_sum':v.aa_sum=reg(c.rdx);break;
      case 'aa_power':v.aa_power=mem(c.rax);break;
      case 'reduction':v.reduction=mem(c.rax);break;
      case 'base_damage':v.base_damage=reg(c.r8);break;
      case 'reliability':v.reliability=mem(c.rax);v.base_str=mem(c.rbp.sub(0x38));v.base_org=mem(c.rbp.sub(0x30));break;
      case 'critical_modifier':v.critical_modifier=mem(c.rax);v.critical_base_threshold=reg(c.rbx);break;
      case 'critical_roll':v.critical_threshold=reg(c.rdi);v.critical_random=mem(c.rax);break;
      case 'critical_branch':v.critical_active=(c.rdi.toUInt32()&255)!==0;v.critical_factor=reg(c.rbx);break;
      case 'special_result':v.special_handled=(c.rax.toUInt32()&255)!==0;v.special_str=mem(c.rbp.sub(0x38));v.special_org=mem(c.rbp.sub(0x30));break;
      case 'final_damage':v.final_str=mem(c.rbp.sub(0x38));v.final_org=mem(c.rbp.sub(0x30));break;
      case 'special_gate':v.special_gate_blocked=(c.rax.toUInt32()&255)!==0;break;
      case 'special_input':v.special_ship_factor=mem(c.rdi.add(0x568));break;
      case 'special_reliability':v.special_reliability=mem(c.rsp.add(0x50));v.special_numerator=reg(c.rbx);break;
      case 'special_threshold':v.special_threshold=reg(c.rbx);break;
      case 'special_roll':v.special_random=mem(c.rax);break;
      case 'effect_candidates':{
        const n=c.r13.toInt32(),base=c.r14;
        v.effect_count=n;v.effect_weight_sum=reg(c.rbx);v.effect_candidates=[];
        scope.effectRefs=[];
        for(let i=0;i<Math.min(n,256);i++){const p=base.add(i*8).readPointer();scope.effectRefs.push(p);v.effect_candidates.push({index:i,weight:mem(p.add(0x168))});}
        v.effect_candidates_truncated=n>256;break;
      }
      case 'effect_choice':v.effect_random=mem(c.rax);break;
      case 'effect_apply':
        v.effect_selected=scope.effectRefs?scope.effectRefs.findIndex(p=>p.equals(c.rdi)):-1;
        v.effect_str_multiplier=mem(c.rdi.add(0x148));v.effect_org_multiplier=mem(c.rdi.add(0x150));
        v.effect_str_add=mem(c.rdi.add(0x158));v.effect_org_add=mem(c.rdi.add(0x160));
        break;
    }
  }catch(e){scope.trace.error='途中の値を取得できませんでした';airExampleStats.read_errors++;}
}
function installAirTrace(){
  if(!CONFIG.air_trace_layout)return;
  installAirAttackBuild();
  const entry=CONFIG.air_trace_layout.dispatch_entry;
  if(entry)listeners.push(Interceptor.attach(detailModule.base.add(entry),{
    onEnter(args){
      this.tid=Process.getCurrentThreadId();this.values={};
      let stack=airDispatchScopes.get(this.tid);if(!stack){stack=[];airDispatchScopes.set(this.tid,stack);}stack.push(this.values);
      try{this.values.initial_planes=args[0].add(0x5c).readS32();this.values.external=args[0].add(0x81).readU8()!==0;this.values.participation=signed(args[3]);}
      catch(e){this.values.error=true;airExampleStats.read_errors++;}
    },
    onLeave(){const stack=airDispatchScopes.get(this.tid);if(stack){const i=stack.indexOf(this.values);if(i>=0)stack.splice(i,1);if(!stack.length)airDispatchScopes.delete(this.tid);}}
  }));
  for(const p of CONFIG.air_trace_layout.points)listeners.push(Interceptor.attach(detailModule.base.add(p.rva),function(){airTracePoint(p.name,this.context);}));
}
function captureAirDispatch(name,c){
  const stack=airDispatchScopes.get(Process.getCurrentThreadId());if(!stack||!stack.length)return;
  const v=stack[stack.length-1],mem=p=>p.readS64().toString();
  try{switch(name){
    case 'up_stats':v.attack=mem(c.rsp.add(0x78));v.targetting=mem(c.rbp.sub(0x80));break;
    case 'up_efficiency':v.efficiency=signed(c.rcx);break;
    case 'up_effective_planes':v.effective_planes=c.rax.toInt32();break;
    case 'up_cap':v.cap_losses=c.rax.toInt32();v.before_cap=c.r15.toInt32();break;
    case 'up_aa':v.aa_losses=c.rax.toInt32();break;
    case 'up_carrier':v.carrier_bonus=!c.rsp.add(0x60).readPointer().isNull();break;
    case 'up_call':v.final_planes=c.r9.toInt32();break;
  }}catch(e){v.error=true;airExampleStats.read_errors++;}
}

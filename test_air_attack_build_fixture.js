rpc.exports.attackbuild=function(disrupted,external=false,countryBonus=0){
  const f=alloc(0x200).add(0x80),s=alloc(0x120),cell=alloc(8),grp=alloc(0x148),out=alloc(8);
  grp.add(0x5c).writeS32(100);grp.add(0x81).writeU8(external?1:0);grp.add(0xc0).writeS64(50000);
  const wings=[alloc(0x600),alloc(0x600)];
  for(const w of wings){w.add(0x7c).writeS32(100);w.add(0x530).writeS64(2600000);w.add(0x138).writeS64(int64(disrupted?'6000000000':'0'));}
  const emit=new NativeCallback(function(stage,wing,output,n,amount){
    const c={rbp:f,rsp:s,r14:wing,rax:ptr(n),rdi:ptr(10000000),rdx:ptr(amount)};
    if(stage===0){s.add(0x38).writeS64(n*100000);captureAirAttackBuild('stat_wing',c);}
    if(stage===1){s.add(0x70).writeS64(2600000);captureAirAttackBuild('wing_raw',c);}
    if(stage===2){c.r14=output;captureAirAttackBuild('wing_scaled',c);c.rbx=ptr(115000);captureAirAttackBuild('wing_factor',c);}
    if(stage===3){
      if(disrupted){
        c.rbx=ptr(1000000);c.rbp=ptr(200000);s.add(0x80).writeS64(100000);
        captureAirAttackBuild('stat_disruption_inputs',c);
        c.rcx=ptr(n*1000000);captureAirAttackBuild('stat_disruption_denominator',c);
        const ratio=Math.trunc(6000000000/(n*10)),root=Math.trunc(Math.sqrt(ratio/100000)*100000);
        c.rax=ptr(ratio);captureAirAttackBuild('stat_disruption_ratio',c);
        cell.writeS64(root);c.rax=cell;captureAirAttackBuild('stat_disruption_root',c);
        const q=(BigInt(root)*100000n*(-7646589624380956197n)>>64n)>>17n;
        c.rax=ptr('0x'+BigInt.asUintN(64,100000n+q+(q<0n?1n:0n)).toString(16));captureAirAttackBuild('stat_disruption_preclamp',c);
      }
      c.rbp=f;f.sub(0x59).writeS64(disrupted?100:100000);captureAirAttackBuild('stat_disruption',c);
    }
    if(stage===4)captureAirAttackBuild('stat_contribution',c);
    if(stage===5)captureAirAttackBuild('stat_sum',c);
    if(stage===6)captureAirAttackBuild('stat_average',c);
    if(stage===7){cell.writeS64(countryBonus);c.rax=cell;captureAirAttackBuild('stat_country',c);}
    if(stage===8)captureAirAttackBuild('stat_external',c);
  },'void',['int','pointer','pointer','int','int64']);
  const module=new CModule(`
    extern void emit(int stage,char *wing,long long *out,int n,long long amount);
    void wing_attack(char *wing,long long *out,int province,int mission){
      emit(1,wing,out,0,0);*out=260000;emit(2,wing,out,0,0);*out=(*out*115000)/100000;
    }
    void aggregate(char *group,char **wings,long long *out,long long *targetting,long long *agility,char *carrier,int mode){
      long long amount=0,attack=0;int i,n;
      *out=0;
      for(i=0;i<2;i++){
        n=i==0?20:80;emit(0,wings[i],out,n,0);wing_attack(wings[i],&attack,1,16);
        emit(3,wings[i],out,n,0);amount=(attack*n*(mode?100:100000))/100000;
        emit(4,wings[i],out,n,amount);*out+=amount;
      }
      emit(5,wings[0],out,100,0);*out=*out/100;emit(6,wings[0],out,100,0);
      if(carrier){emit(7,wings[0],out,0,0);*out=(*out*(100000+*(long long*)carrier))/100000;}
      emit(8,wings[0],out,100,0);if(group[0x81])*out=(*out*(*(long long*)(group+0xc0)))/100000;
    }
  `,{emit});
  keep.push(emit,module);const ptrs=alloc(16);ptrs.writePointer(wings[0]);ptrs.add(8).writePointer(wings[1]);
  const parent={};airDispatchScopes.set(Process.getCurrentThreadId(),[parent]);
  CONFIG.air_trace_layout={aggregate_entry:parseInt(module.aggregate.toString(),16),wing_attack_entry:parseInt(module.wing_attack.toString(),16)};
  CONFIG.air_trace_layout.globals={};
  for(const [label,value] of [['attack',0],['defence',150000],['speed',150000]]){
    const p=alloc(8);p.writeS64(value);CONFIG.air_trace_layout.globals['disruption_'+label+'_factor']=parseInt(p.toString(),16);
  }
  installAirAttackBuild();Interceptor.flush();cell.writeS64(countryBonus);
  new NativeFunction(module.aggregate,'void',['pointer','pointer','pointer','pointer','pointer','pointer','int'])(grp,ptrs,out,alloc(8),alloc(8),cell,disrupted?1:0);
  airDispatchScopes.clear();return {data:parent.attack_build,result:out.readS64().toString(),scopes:airStatScopes.size+airWingScopes.size};
};

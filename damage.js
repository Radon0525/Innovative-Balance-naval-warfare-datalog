// Attribute actual HP/organization reduction to the selected attack invocation.
// All reads occur while the damage function owns a live target, before destruction.
const attackScopes=new Map();
const damageStats={read_errors:0,unmatched_calls:0,unfinished:0};

function damageFields(row) {
  if(row.damage_measured===undefined)Object.assign(row,{
    damage_measured:0,str_loss_raw:'0',org_loss_raw:'0'});
}
function finishDamage(ticket,complete=true) {
  if(!ticket||ticket.finished)return;
  ticket.finished=true;
  const e=ticket.event;
  if(!complete||ticket.failed) {
    e.damage_status='unavailable';damageStats.unfinished++;
  } else {
    e.damage_status='measured';e.str_loss_raw=ticket.str.toString();e.org_loss_raw=ticket.org.toString();
    for(const row of [ticket.pair,ticket.totals])if(row) {
      damageFields(row);row.damage_measured++;
      row.str_loss_raw=(BigInt(row.str_loss_raw)+ticket.str).toString();
      row.org_loss_raw=(BigInt(row.org_loss_raw)+ticket.org).toString();
    }
  }
  markDetailDirty(ticket);
}
function startDamage(ticket,record) {
  if(!CONFIG.damage_layout)return;
  const stack=attackScopes.get(Process.getCurrentThreadId());
  const scope=stack&&stack[stack.length-1];
  if(!scope||scope.kind!==ticket.event.kind) {finishDamage(ticket,false);return;}
  finishDamage(scope.pending);scope.pending=null;
  const e=ticket.event;
  if((e.kind==='heavy'&&!e.hit)||(e.kind==='air'&&e.successes===0)) {
    finishDamage(ticket);return;
  }
  try {
    const ref=record.add(referenceKey(record.add(8))==='0:0'?0x10:8);
    ticket.target=resolveReference(ref);
    if(ticket.target.isNull())throw new Error('Damage target unresolved');
  } catch(error){ticket.failed=true;damageStats.read_errors++;}
  scope.pending=ticket;
}
function installAttackScope(kind,address,filterWeapon=true) {
  listeners.push(Interceptor.attach(address,{
    onEnter(args) {
      this.scope={kind,pending:null,track:kind!=='heavy'||!filterWeapon||args[2].toInt32()===0};this.thread=Process.getCurrentThreadId();
      let stack=attackScopes.get(this.thread);
      if(!stack){stack=[];attackScopes.set(this.thread,stack);}
      stack.push(this.scope);
      if(kind==='air')beginAirTrace(this.scope,args);
    },
    onLeave() {
      finishDamage(this.scope.pending);
      if(this.scope.trace)this.scope.trace.complete=true;
      const stack=attackScopes.get(this.thread);
      if(stack){const index=stack.indexOf(this.scope);if(index>=0)stack.splice(index,1);if(!stack.length)attackScopes.delete(this.thread);}
    }
  }));
}
function installDamageFunction(address,config,returns) {
  listeners.push(Interceptor.attach(address,{
    onEnter(args) {
      const kind=returns.get(this.returnAddress.toString());
      if(!kind)return; // Repairs, accidents, light guns and unrelated callers are excluded.
      const stack=attackScopes.get(Process.getCurrentThreadId());
      const scope=stack&&stack[stack.length-1];
      if(scope&&!scope.track)return;
      if(!scope||scope.kind!==kind||!scope.pending){damageStats.unmatched_calls++;return;}
      this.ticket=scope.pending;
      if(this.ticket.failed)return;
      try {
        if(!args[0].equals(this.ticket.target))throw new Error('Damage target mismatch');
        this.target=args[0];
        this.beforeStr=BigInt(this.target.add(config.str_offset).readS64().toString());
        this.beforeOrg=BigInt(this.target.add(config.org_offset).readS64().toString());
        if(this.ticket.event.air_trace){
          this.application={calculated_str:signed(args[1]),calculated_org:signed(args[2]),before_str:this.beforeStr.toString(),before_org:this.beforeOrg.toString()};
          this.ticket.event.air_trace.applications.push(this.application);
        }
        if(this.beforeStr<0n||this.beforeOrg<0n)throw new Error('Negative pre-damage state');
      }catch(error){this.ticket.failed=true;damageStats.read_errors++;}
    },
    onLeave() {
      if(!this.ticket||this.ticket.failed||this.ticket.finished)return;
      try {
        const afterStr=BigInt(this.target.add(config.str_offset).readS64().toString());
        const afterOrg=BigInt(this.target.add(config.org_offset).readS64().toString());
        if(afterStr<0n||afterOrg<0n||afterStr>this.beforeStr||afterOrg>this.beforeOrg)
          throw new Error('Invalid damage delta');
        this.ticket.str+=this.beforeStr-afterStr;
        this.ticket.org+=this.beforeOrg-afterOrg;
        if(this.application)Object.assign(this.application,{after_str:afterStr.toString(),after_org:afterOrg.toString(),actual_str:(this.beforeStr-afterStr).toString(),actual_org:(this.beforeOrg-afterOrg).toString()});
      }catch(error){this.ticket.failed=true;damageStats.read_errors++;}
    }
  }));
}
function abandonDamageScopes() {
  for(const stack of attackScopes.values())for(const scope of stack)finishDamage(scope.pending,false);
  attackScopes.clear();
}

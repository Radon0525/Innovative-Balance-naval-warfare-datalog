// Real native function calls against synthetic objects, never game memory.
const damageModule=new CModule(`
void apply(char *p, long long hp, long long org) {
  long long *s=(long long *)(p+0x6f8), *o=(long long *)(p+0x700);
  *s=hp>*s?0:*s-hp; *o=org>*o?0:*o-org;
}
`);
let testKind='heavy',suppressObservation=false,nested=false,inNested=false;
const notice=new NativeCallback(function(hit){
  if(suppressObservation)return;
  if(testKind==='heavy')heavy(hit?1:100);else air(10,hit?2:0);
  if(nested&&!inNested){inNested=true;attack(target.ship,1,100000,50000);inNested=false;}
},'void',['int']);
const driver=new CModule(`
extern void notice(int hit);
extern void damage(char *p,long long hp,long long org);
void attack(char *p,int hit,long long hp,long long org) {
  notice(hit);if(hit)damage(p,hp,org);
}
void twice(char *p,int hit,long long hp,long long org) {
  notice(hit);if(hit)damage(p,hp,org);
  notice(hit);if(hit)damage(p,hp,org);
}
`,{notice,damage:damageModule.apply});
function callReturns(fn,kind){
  const map=new Map();let at=fn;
  for(let i=0;i<300;i++) {
    const ins=Instruction.parse(at);
    if(ins.mnemonic==='call')map.set(ins.next.toString(),kind);
    if(ins.mnemonic==='ret')return map;
    at=ins.next;
  }
  throw new Error('Test function has no return');
}
const attack=new NativeFunction(driver.attack,'void',['pointer','int','int64','int64']);
const twice=new NativeFunction(driver.twice,'void',['pointer','int','int64','int64']);
const directDamage=new NativeFunction(damageModule.apply,'void',['pointer','int64','int64']);
function setupDamage(kind) {
  CONFIG.damage_layout={fixed_scale:100000};testKind=kind;
  const returns=new Map([...callReturns(driver.attack,kind),...callReturns(driver.twice,kind)]);
  installAttackScope(kind,driver.attack,false);installAttackScope(kind,driver.twice,false);
  installDamageFunction(damageModule.apply,{str_offset:0x6f8,org_offset:0x700},returns);
  Interceptor.flush();
}
function health(s,o){target.ship.add(0x6f8).writeS64(s);target.ship.add(0x700).writeS64(o);}
rpc.exports.damage=function(kind){
  setupDamage(kind);group.add(0x81).writeU8(1);
  health(500000,200000);
  attack(target.ship,1,800000,300000); // Overkill: only 5 HP / 2 org actually lost.
  attack(target.ship,1,100000,100000); // Hit on depleted target: actual zero.
  attack(target.ship,0,100000,100000); // Miss: actual zero.
  health(1000000,500000);twice(target.ship,1,100000,50000);
  directDamage(target.ship,50000,25000); // Unrelated caller: excluded.
  const first=deltaDetails(),empty=deltaDetails();
  return {first,empty,health:[target.ship.add(0x6f8).readS64().toString(),target.ship.add(0x700).readS64().toString()],scopes:attackScopes.size};
};
rpc.exports.damageerrors=function(){
  setupDamage('heavy');health(1000000,500000);
  attack(target.ship,1,-100000,0); // Healing is not negative damage.
  attack(attacker.ship,1,1,1); // Wrong target must not be attributed.
  suppressObservation=true;attack(target.ship,1,1,1);suppressObservation=false;
  heavy(1); // No invocation scope: unavailable, never silently zero.
  return snapshotDetails();
};
rpc.exports.damagenested=function(){
  setupDamage('heavy');health(1000000,500000);nested=true;
  attack(target.ship,1,200000,100000);
  return {details:snapshotDetails(),scopes:attackScopes.size};
};
rpc.exports.damagepending=function(){
  CONFIG.damage_layout={};
  const scope={kind:'heavy',pending:null,track:true};attackScopes.set(Process.getCurrentThreadId(),[scope]);
  heavy(1);const before=JSON.parse(JSON.stringify(deltaDetails()));
  scope.pending.str=123456n;scope.pending.org=789n;finishDamage(scope.pending);
  const after=JSON.parse(JSON.stringify(deltaDetails()));
  heavy(1);abandonDamageScopes();
  return {before,after,stopped:deltaDetails()};
};
rpc.exports.damageconvoy=function(){
  CONFIG.damage_layout={};
  const helper=new CModule(`void apply(char *p,long long hp,long long org) {
    long long *s=(long long *)(p+0x20),*o=(long long *)(p+0x28);
    *s=hp>*s?0:*s-hp;*o=org>*o?0:*o-org;
  }`);
  const calls=new CModule(`extern void notice(int hit);extern void damage(char *p,long long hp,long long org);
    void attack(char *p,int hit,long long hp,long long org){notice(hit);if(hit)damage(p,hp,org);}
  `,{notice,damage:helper.apply});
  target.record.add(8).writeU64(0);copyRef(target.record.add(0x10),target.ref);
  target.ship.add(0x20).writeS64(200000);target.ship.add(0x28).writeS64(50000);
  installAttackScope('heavy',calls.attack,false);
  installDamageFunction(helper.apply,{str_offset:0x20,org_offset:0x28},callReturns(calls.attack,'heavy'));
  Interceptor.flush();
  new NativeFunction(calls.attack,'void',['pointer','int','int64','int64'])(target.ship,1,1000000,1000000);
  const result=snapshotDetails();
  // Keep executable memory alive until its listeners are detached in stop().
  keep.push(helper,calls);
  return result;
};

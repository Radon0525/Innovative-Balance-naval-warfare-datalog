// Synthetic objects, never attached to HOI4. Exercises the production readers and hooks.
const keep=[];
function alloc(n){const p=Memory.alloc(n);keep.push(p);return p;}
const roots=alloc(800), table=alloc(32), entries=alloc(24*768);
roots.add(42*8).writePointer(table);table.add(8).writePointer(entries);table.add(20).writeU32(511);
CONFIG.details_layout={registry:{small:parseInt(roots.toString(),16),medium:0,large:0}};
detailModule={base:ptr(0)};
let nextId=1;
function register(object){
  const ref=alloc(8),id=nextId++;ref.writeU32(42);ref.add(4).writeU32(id);
  const h=BigInt.asUintN(64,((42n<<32n)|BigInt(id))*0x49631a45n);
  let p=entries.add(Number(((h>>32n)^h)&511n)*24),distance=1;
  while(p.add(4).readU8()!==0){p=p.add(24);distance++;}
  p.add(4).writeU8(distance);p.add(8).writeU32(42);p.add(12).writeU32(id);p.add(16).writePointer(object);
  return ref;
}
function copyRef(dst,src){dst.writeU64(src.readU64());}
function string(p,s){
  const b=Memory.allocUtf8String(s);keep.push(b);
  const length=unescape(encodeURIComponent(s)).length;
  if(length>15)p.writePointer(b);else Memory.copy(p,b,length+1);
  p.add(16).writeU64(length);p.add(24).writeU64(length>15?length:15);
}
function makeShip(name,country){
  const ship=alloc(0x840),unit=alloc(0x200),identity=alloc(0xa0),record=alloc(0x200);
  unit.add(0x1d8).writeS32(country);ship.add(0x728).writePointer(unit);
  ship.add(0x818).writePointer(identity);string(identity.add(0x60),name);
  const ref=register(ship);copyRef(ship.add(8),ref);copyRef(record.add(8),ref);
  return {ship,ref,record};
}
const attacker=makeShip('大和',1),target=makeShip('Iowa',2),carrier=makeShip('翔鶴',1);
const base=alloc(0x90);copyRef(base.add(0x60),carrier.ref);const baseRef=register(base);
const landBase=alloc(0x90),landRef=register(landBase);
const group=alloc(0x148);copyRef(group.add(0x1c),baseRef);group.add(0x64).writeS32(1);
string(group.add(0x88),'翔鶴');
const battle=alloc(0x200),frame=alloc(512).add(0x80);
frame.add(0x90).writePointer(attacker.record);frame.add(0x98).writePointer(target.record);
frame.add(0xa0).writeS32(0);frame.sub(0x38).writeS64(100);
function heavy(random){observeHeavy({rbp:frame,rcx:ptr(random)});}
function air(n,h){
  frame.add(0x30).writePointer(group);frame.add(0x60).writePointer(battle);
  observeAir({rbp:frame,r15:target.record,rsi:ptr(n),rax:ptr(h)});
}
rpc.exports.readers=function(){
  heavy(99);heavy(100);heavy(101);
  air(100,25); // Carrier involved in ongoing naval combat.
  group.add(0x81).writeU8(1);air(50,10); // External mission joining an existing battle.
  battle.add(0x10d).writeU8(1);air(40,0); // External mission hitting a fleet outside battle.
  copyRef(group.add(0x1c),landRef);string(group.add(0x88),'基地A');group.add(0x64).writeS32(2);
  air(30,3);
  battle.add(0x10c).writeU8(1);air(20,2);
  air(0,0);air(1,2); // Invalid values must not enter detailed denominators.
  const invalid=alloc(8);invalid.writeU32(42);invalid.add(4).writeU32(9999);
  copyRef(group.add(0x1c),invalid);air(10,1); // Explicitly unknown, never silently land-based.
  return snapshotDetails();
};
function machine(hex){const p=alloc(Process.pageSize);p.writeByteArray(hex.match(/../g).map(x=>parseInt(x,16)));Memory.protect(p,Process.pageSize,'r-x');return p;}
function immediate(p){return p.toString().slice(2).padStart(16,'0').match(/../g).reverse().join('');}
// Real mid-function hook. The native total and detailed callback see the same CPU context.
const prefix='554881ec80010000488d6c2460'+
  '48898d9000000048899598000000c785a0000000000000004c894dc84c89c1';
const body='48394dc80f8e07000000b801000000eb0231c0'+'90'.repeat(24)+'4881c4800100005dc3';
const gun=machine(prefix+body);
const airPrefix='55535641574881ec90000000488d6c241048894d304c894d604989d74c89c6b805000000';
const airBody='4863d885c0'+'90'.repeat(32)+'4881c490000000415f5e5b5dc3';
const airMachine=machine(airPrefix+airBody);
rpc.exports.hookedair=function(){
  install('air',airMachine.add(airPrefix.length/2));Interceptor.flush();
  const call=new NativeFunction(airMachine,'int',['pointer','pointer','int64','pointer']);
  group.add(0x81).writeU8(1);battle.add(0x10d).writeU8(1);
  const results=[call(group,target.record,100,battle),call(group,target.record,4,battle)];
  return {results,counts:snapshot(),details:snapshotDetails()};
};
rpc.exports.hooked=function(){
  install('heavy',gun.add(prefix.length/2));Interceptor.flush();
  const call=new NativeFunction(gun,'int',['pointer','pointer','int64','int64']);
  const results=[call(attacker.record,target.record,99,100),call(attacker.record,target.record,100,100),call(target.record,attacker.record,0,100)];
  return {results,counts:snapshot(),details:snapshotDetails()};
};
rpc.exports.overflow=function(){
  for(let i=0;i<20002;i++)addDetail({kind:'heavy',channel:'heavy',context:'battle',hit:true,
    source:{id:'s'+i,name:'同名艦',country:1},target:{id:'target',name:'相手',country:2}});
  return snapshotDetails();
};
rpc.exports.tags=function(){
  const global=alloc(8),game=alloc(0x380),tags=alloc(96);
  global.writePointer(game);game.add(0x358).writePointer(tags);
  string(tags.add(32),'JAP');string(tags.add(64),'USA');
  CONFIG.details_layout.game_state=parseInt(global.toString(),16);
  heavy(1);return snapshotDetails();
};

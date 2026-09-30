// Optional detailed observation. Only bounded memory reads; no game functions are called.
const detailPairs = new Map();
const detailChannels = new Map();
const detailSamples = [];
const dirtyPairs=new Set(),dirtySamples=new Set();
const detailStats = {events:0, read_errors:0, pair_overflow:0, sample_omitted:0};
const PAIR_LIMIT = 20000, SAMPLE_LIMIT = 2000;
let detailModule = null;

function referenceKey(p) {
  return p.readU32()+':'+p.add(4).readU32();
}
function resolveReference(ref) {
  const type=ref.readU32(), id=ref.add(4).readU32();
  if(type===0 && id===0)return ptr(0);
  const tables=CONFIG.details_layout.registry;
  const address=type<100 ? detailModule.base.add(tables.small+type*8) :
    detailModule.base.add(type<0x1269 ? tables.medium : tables.large);
  const table=address.readPointer();
  if(table.isNull())return ptr(0);
  const data=table.add(8).readPointer(), mask=table.add(0x14).readU32();
  if(mask>0x3fffffff || data.isNull())throw new Error('Invalid reference table');
  const hash=BigInt.asUintN(64, ((BigInt(type)<<32n)|BigInt(id))*0x49631a45n);
  const slot=Number(((hash>>32n)^hash)&BigInt(mask));
  let item=data.add(slot*24);
  if(item.add(4).readU8()===0)return ptr(0);
  for(let distance=1;distance<256;distance++,item=item.add(24)) {
    if(distance>item.add(4).readU8())break;
    if(item.add(8).readU32()===type && item.add(12).readU32()===id)
      return item.add(16).readPointer();
  }
  return ptr(0);
}
function readString(p) {
  const size=p.add(16).readU64().toNumber(),capacity=p.add(24).readU64().toNumber();
  if(size===0)return '';
  if(!Number.isSafeInteger(size)||size>512||capacity<size||capacity>1048576)
    throw new Error('Invalid name string');
  return (capacity>15?p.readPointer():p).readUtf8String(size);
}
function shipEntity(ship, key) {
  const entity={id:'ship:'+key, name:'艦艇 #'+key, country:null, kind:'ship'};
  if(ship.isNull())return entity;
  // CShip::GetName and GetCountryTag, audited in both exact supported builds.
  try {
    const name=readString(ship.add(0x818).readPointer().add(0x60));
    if(name)entity.name=name;
  } catch(e) {detailStats.read_errors++;}
  try {
    const unit=ship.add(0x728).readPointer();
    if(!unit.isNull())entity.country=unit.add(0x1d8).readS32();
  } catch(e) {detailStats.read_errors++;}
  return entity;
}
function countryTag(country) {
  if(!country||country<0||country>100000||!CONFIG.details_layout.game_state)return null;
  try {
    const game=detailModule.base.add(CONFIG.details_layout.game_state).readPointer();
    if(game.isNull())return null;
    const name=readString(game.add(0x358).readPointer().add(country*32));
    return /^[A-Z0-9]{3}$/.test(name)?name:null;
  } catch(e){detailStats.read_errors++;return null;}
}
function shipRecord(record) {
  const ref=record.add(8), key=referenceKey(ref);
  if(key!=='0:0')return shipEntity(resolveReference(ref),key);
  const convoyKey=referenceKey(record.add(0x10));
  return {id:'convoy:'+convoyKey,name:'輸送船 #'+convoyKey,country:null,kind:'convoy'};
}
function airSource(group) {
  const ref=group.add(0x1c), key=referenceKey(ref);
  const base=resolveReference(ref);
  if(key!=='0:0'&&base.isNull())throw new Error('Air base reference is unresolved');
  let carrier=ptr(0),carrierKey='0:0';
  if(!base.isNull()) {
    carrierKey=referenceKey(base.add(0x60));
    carrier=resolveReference(base.add(0x60));
    if(carrierKey!=='0:0'&&carrier.isNull())throw new Error('Carrier reference is unresolved');
  }
  let entity;
  if(!carrier.isNull())entity=shipEntity(carrier,carrierKey);
  else entity={id:'airbase:'+key,name:'航空基地 #'+key,country:null,kind:'airbase'};
  if(entity.kind==='airbase') {
    const name=readString(group.add(0x88));
    if(name)entity.name=name;
  }
  // This is the attacking air wing's country, not necessarily the carrier owner's.
  const country=group.add(0x64).readS32();
  entity.country=country>0?country:null;
  return {entity,carrier:!carrier.isNull(),external:group.add(0x81).readU8()!==0};
}
function addDetail(event) {
  for(const entity of [event.source,event.target]) {
    if(entity.country && entity.tag===undefined)entity.tag=countryTag(entity.country);
  }
  detailStats.events++;
  const n=event.kind==='heavy'?1:event.planes;
  const h=event.kind==='heavy'?(event.hit?1:0):event.successes;
  const key=JSON.stringify([event.channel,event.context,event.source.id,event.source.country,
                            event.target.id,event.target.country]);
  let pair=detailPairs.get(key);
  if(!pair && detailPairs.size<PAIR_LIMIT) {
    pair={kind:event.kind,channel:event.channel,context:event.context,
      source:event.source,target:event.target,events:0,attempts:0,hits:0,zero_groups:0};
    detailPairs.set(key,pair);
  }
  if(pair) {
    pair.events++;pair.attempts+=n;pair.hits+=h;
    if(h===0)pair.zero_groups++;
    pair.source=event.source;pair.target=event.target;
  } else detailStats.pair_overflow++;
  let totals=detailChannels.get(event.channel);
  if(!totals){totals={events:0,attempts:0,hits:0};detailChannels.set(event.channel,totals);}
  totals.events++;totals.attempts+=n;totals.hits+=h;
  // The pair totals are cumulative. Only individual examples have a sample limit.
  event.sequence=detailStats.events;
  if(detailSamples.length<SAMPLE_LIMIT)detailSamples.push(event);
  else detailStats.sample_omitted++;
  const ticket={event,pair,totals,key,str:0n,org:0n,failed:false,finished:false};
  if(CONFIG.damage_layout) {
    event.damage_status='pending';
    for(const row of [pair,totals])if(row)damageFields(row);
  }
  markDetailDirty(ticket);
  return ticket;
}
function markDetailDirty(ticket) {
  if(ticket.pair)dirtyPairs.add(ticket.key);
  if(ticket.event.sequence<=SAMPLE_LIMIT)dirtySamples.add(ticket.event.sequence-1);
}
function observeHeavy(cpu) {
  if(cpu.rbp.add(0xa0).readS32()!==0)return;
  const hit=cpu.rbp.sub(0x38).readS64().compare(int64(cpu.rcx.toString()))>0;
  let source={id:'unknown',name:'攻撃元不明',country:null,kind:'unknown'};
  let target={id:'unknown',name:'攻撃先不明',country:null,kind:'unknown'};
  try {
    source=shipRecord(cpu.rbp.add(0x90).readPointer());
    target=shipRecord(cpu.rbp.add(0x98).readPointer());
  } catch(e) {detailStats.read_errors++;}
  const ticket=addDetail({kind:'heavy',channel:'heavy',context:'battle',source,target,hit,
    threshold:cpu.rbp.sub(0x38).readS64().toString(),random_scaled:int64(cpu.rcx.toString()).toString()});
  startDamage(ticket,cpu.rbp.add(0x98).readPointer());
}
function observeAir(cpu) {
  const planes=int64(cpu.rsi.toString()).toNumber(), successes=cpu.rax.toInt32();
  if(planes<=0||successes<0||successes>planes)return;
  let source={id:'unknown',name:'発進元不明',country:null,kind:'unknown'};
  let target={id:'unknown',name:'攻撃先不明',country:null,kind:'unknown'};
  let channel='unknown_air',context='unknown';
  try {
    const group=cpu.rbp.add(0x30).readPointer(); // saved first argument
    const battle=cpu.rbp.add(0x60).readPointer(); // seventh argument
    target=shipRecord(cpu.r15); // sixth argument: targeted naval combat record
    const origin=airSource(group);source=origin.entity;
    const port=battle.add(0x10c).readU8()!==0;
    const temporary=battle.add(0x10d).readU8()!==0;
    context=port?'port':temporary?'temporary':'battle';
    channel=port?'port_air':origin.carrier ?
      (origin.external||temporary?'carrier_mission':'carrier_battle'):'land_mission';
  } catch(e) {detailStats.read_errors++;}
  const ticket=addDetail({kind:'air',channel,context,source,target,planes,successes});
  attachAirExample(ticket.event,cpu);
  startDamage(ticket,cpu.r15);
}
function installDetails(name,address) {
  // A function callback is an instruction probe. An onEnter object would assume
  // a function entry and track an invalid return address at this mid-body site.
  listeners.push(Interceptor.attach(address,function(){
    try {
      const c=this.context;
      if(name==='heavy') {
        countHeavy(c.rbp.add(0xa0).readS32(),c.rbp.sub(0x38).readS64(),int64(c.rcx.toString()));
        observeHeavy(c);
      } else {
        countAir(int64(c.rsi.toString()),c.rax.toInt32());observeAir(c);
      }
    }
    catch(e){detailStats.read_errors++;}
  }));
}
function snapshotDetails() {
  return {schema_version:2,stats:{...detailStats},damage_stats:{...damageStats},damage_enabled:!!CONFIG.damage_layout,
    pair_count:detailPairs.size,pair_limit:PAIR_LIMIT,sample_limit:SAMPLE_LIMIT,
    air_examples:snapshotAirExamples(),channels:Object.fromEntries(detailChannels),pairs:Array.from(detailPairs.values()),samples:detailSamples};
}
function deltaDetails() {
  const result={schema_version:2,delta:true,stats:{...detailStats},damage_stats:{...damageStats},
    damage_enabled:!!CONFIG.damage_layout,pair_count:detailPairs.size,pair_limit:PAIR_LIMIT,sample_limit:SAMPLE_LIMIT,
    air_examples:snapshotAirExamples(),channels:Object.fromEntries(detailChannels),pairs:Array.from(dirtyPairs,key=>detailPairs.get(key)),
    samples:Array.from(dirtySamples,i=>detailSamples[i])};
  dirtyPairs.clear();dirtySamples.clear();return result;
}

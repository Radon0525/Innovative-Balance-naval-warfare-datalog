// CONFIG and COUNTER_SOURCE are supplied by the host after SHA-256 verification.
if(Process.platform!=='windows' || Process.arch!=='x64') throw new Error('Windows x64専用です');
const state=Memory.alloc(128);
const kernel=Process.getModuleByName('kernel32.dll');
const cm=new CModule(COUNTER_SOURCE,{
  state,
  acquire:kernel.getExportByName('AcquireSRWLockExclusive'),
  release:kernel.getExportByName('ReleaseSRWLockExclusive')
});
const buf=Memory.alloc(80);
const readCounters=new NativeFunction(cm.snapshot,'void',['pointer']);
const countHeavy=new NativeFunction(cm.count_heavy,'void',['int','int64','int64'],{scheduling:'exclusive'});
const countAir=new NativeFunction(cm.count_air,'void',['int64','int'],{scheduling:'exclusive'});
let listeners=[];
function install(name,address) {
  if(CONFIG.details)installDetails(name,address);
  else listeners.push(Interceptor.attach(address, name==='heavy' ? cm.heavy_probe : cm.air_probe));
}
if(!CONFIG.test) {
  const module=Process.getModuleByName('hoi4.exe');
  detailModule=module;
  const selected=CONFIG.mode==='both' ? ['heavy','air'] : [CONFIG.mode];
  function check(rva,hex) {
    const p=module.base.add(rva);
    const actual=Array.from(new Uint8Array(p.readByteArray(hex.length/2)))
      .map(b=>b.toString(16).padStart(2,'0')).join('');
    if(actual!==hex) throw new Error('メモリ上の命令が対応表と一致しません。計測を中止します。');
    return p;
  }
  // Verify both function entries and observation instructions before changing anything.
  const addresses=selected.map(name=>{
    const p=CONFIG.probes[name];
    check(p.entry_rva,p.entry_bytes);
    return [name,check(p.rva,p.bytes)];
  });
  if(CONFIG.details) {
    if(!CONFIG.details_layout)throw new Error('この対応表には詳細計測の検証情報がありません。');
    for(const p of CONFIG.details_layout.checks)check(p.rva,p.bytes);
    if(CONFIG.air_trace_layout)for(const p of CONFIG.air_trace_layout.checks)check(p.rva,p.bytes);
    if(!CONFIG.damage_layout)throw new Error('ダメージ計測の対応表がありません。');
    for(const p of CONFIG.damage_layout.helpers) {
      check(p.entry_rva,p.entry_bytes);
      for(const r of p.returns)check(r.call_rva,r.call_bytes);
    }
  }
  if(CONFIG.first_airplanes&&selected.includes('air')) {
    if(!CONFIG.air_participant_layout||!CONFIG.details_layout)throw new Error('初回機数の検証情報がありません。');
    for(const p of CONFIG.air_participant_layout.checks)check(p.rva,p.bytes);
    for(const p of CONFIG.details_layout.checks)check(p.rva,p.bytes);
  }
  try {
    if(CONFIG.details) {
      for(const kind of selected)installAttackScope(kind,module.base.add(CONFIG.probes[kind].entry_rva));
      for(const p of CONFIG.damage_layout.helpers) {
        const returns=new Map(p.returns.filter(r=>selected.includes(r.kind)).map(r=>[module.base.add(r.return_rva).toString(),r.kind]));
        installDamageFunction(module.base.add(p.entry_rva),p,returns);
      }
    }
    for(const [name,address] of addresses) install(name,address);
    if(CONFIG.details&&selected.includes('air'))installAirTrace();
    if(CONFIG.first_airplanes&&selected.includes('air'))installAirParticipants();
    Interceptor.flush();
  } catch(error) {
    for(const listener of listeners) listener.detach();
    throw error;
  }
}
function snapshot() {
  readCounters(buf);
  return Array.from({length:10},(_,i)=>buf.add(i*8).readU64().toString());
}
rpc.exports={
  snapshot,
  airparticipants:snapshotAirParticipants,
  ackairparticipants:acknowledgeAirParticipants,
  details:snapshotDetails,
  detailsdelta:deltaDetails,
  async stop() {
    stopAirParticipants();
    for(const listener of listeners) listener.detach();
    listeners=[];
    Interceptor.flush();
    // Allow already-dispatched native callbacks to finish before the final snapshot.
    await new Promise(resolve=>setTimeout(resolve,50));
    abandonDamageScopes();
    return snapshot();
  }
};

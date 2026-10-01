// Synthetic native calls only: no HOI4 process or game executable is run.
const participantPointCode='41575641564989cf4889d64d89c64489c8';
const participantScanPoint=machine(participantPointCode+'90'.repeat(24)+'415e5e415fc3');
const participantWingPoint=machine(participantPointCode+'90'.repeat(24)+'415e5e415fc3');
const censusScan=new NativeFunction(participantScanPoint,'void',['pointer','int','pointer','int']);
const censusWing=new NativeFunction(participantWingPoint,'void',['pointer','int','pointer','int']);
const censusRegion=alloc(0x100),censusProvince=alloc(0x200),censusBattle=alloc(0x200),censusBattleWrapper=alloc(0x200);
censusProvince.add(0xc8).writePointer(censusRegion);censusBattle.add(0x38).writePointer(censusProvince);
censusBattleWrapper.add(0x18).writePointer(censusBattle);
const censusGame=alloc(0x400),censusGameCell=alloc(8),censusRegionTable=alloc(32),censusTags=alloc(128);
censusGameCell.writePointer(censusGame);censusGame.add(0x2e0).writePointer(censusRegionTable);
censusGame.add(0x2ec).writeS32(4);
censusRegionTable.add(8).writePointer(censusRegion);censusGame.add(0x358).writePointer(censusTags);
string(censusTags.add(32),'JAP');string(censusTags.add(64),'USA');
CONFIG.details_layout.game_state=parseInt(censusGameCell.toString(),16);
function censusMakeWing(country,carrierBased,mission,ready,escort=0){
  const w=alloc(0xa00),holder=alloc(0x80),baseObject=alloc(0x90),provinceObject=alloc(0x200);
  const wr=register(w),br=register(baseObject);copyRef(w.add(0x18),wr);copyRef(holder.add(0x18),br);
  w.add(0x38).writePointer(holder);w.add(0x9c4).writeS32(country);w.add(0x7c).writeS32(ready);
  if(carrierBased)copyRef(baseObject.add(0x60),carrier.ref);else baseObject.add(0x68).writePointer(provinceObject);
  const m=w.add(0x90);m.add(0x28).writePointer(w);m.add(0x14).writeU32(mission);m.add(0xe0).writeS32(ready);m.add(0xb8).writeS64(escort);
  return {wing:w,mission:m,ready,country};
}
const cw=[censusMakeWing(1,true,16,77),censusMakeWing(1,true,1,20,100000),
          censusMakeWing(1,false,1,15,100000),censusMakeWing(2,true,16,80),
          censusMakeWing(2,true,1,30,100000),censusMakeWing(2,false,16,40),censusMakeWing(2,false,1,25,100000)];
function censusOwner(rows,duplicate){
  const owner=alloc(0x160),normal=alloc(48),automatic=alloc(48),n=alloc(rows.length*8),a=alloc(8);
  rows.forEach((w,i)=>n.add(i*8).writePointer(w.mission));
  normal.add(24).writePointer(n);normal.add(36).writeS32(rows.length);
  if(duplicate){a.writePointer(rows[0].mission);automatic.add(24).writePointer(a);automatic.add(36).writeS32(1);}
  owner.add(0x98).writePointer(normal);owner.add(0x140).writePointer(automatic);return owner;
}
const censusOwners=[censusOwner(cw.slice(0,3),true),censusOwner(cw.slice(3),true)];
function censusVector(rows){
  const vec=alloc(24),data=alloc(rows.length*24);vec.writePointer(data);vec.add(12).writeS32(rows.length);
  rows.forEach((w,i)=>{data.add(i*24).writePointer(w.mission);data.add(i*24+8).writeS32(w.ready);data.add(i*24+12).writeS32(w.ready);});return vec;
}
const censusVectors=[censusVector([cw[1],cw[2]]),censusVector(cw.slice(3)),
                     censusVector([cw[4],cw[6]]),censusVector(cw.slice(0,3))];
const censusCountries=[alloc(8),alloc(8)];censusCountries[0].writeS32(1);censusCountries[1].writeS32(2);
const censusGroups=[alloc(0x148),alloc(0x148)];
censusGroups[0].add(0x5c).writeS32(77);censusGroups[1].add(0x5c).writeS32(80);
const censusEmit=new NativeCallback(function(stage,group){
  if(stage===0){for(const owner of censusOwners)censusScan(owner,1,ptr(0),0);}
  if(stage===1){const index=group.equals(censusGroups[0])?0:3;censusWing(ptr(0),0,cw[index].wing,cw[index].ready);}
},'void',['int','pointer']);
const censusModule=new CModule(`
  extern void census_emit(int stage,char *group);
  void aggregate(char *group,void *wings,void *out,void *t,void *a,void *country){census_emit(1,group);}
  void dispatch(char *group,void *enemy,char *battle,long long participation){aggregate(group,0,0,0,0,0);}
  void naval_update(char *wrapper,char *a,char *b){
    char *battle=*(char**)(wrapper+0x18);dispatch(a,0,battle,100000);dispatch(a,0,battle,100000);dispatch(b,0,battle,100000);
  }
  void air_pair(char *target,void *entry,long long power,int province,long long allocation,char *wing){}
  void regional(void *region,int province,int *country,char *attackers,char *targets){
    char *attacker=*(char**)(*(char**)attackers);char *wing=*(char**)(attacker+0x28);char *target=*(char**)(*(char**)targets);
    air_pair(target,0,100000,0,*country==1?500000:600000,wing);
    if(*country==1){target=*(char**)(*(char**)targets+24);air_pair(target,0,100000,0,300000,wing);}
  }
  void update(void *region,int *country1,char *a1,char *t1,int *country2,char *a2,char *t2,char *wrapper,char *g1,char *g2,int during){
    census_emit(0,0);regional(region,0,country1,a1,t1);regional(region,0,country2,a2,t2);
    if(during)naval_update(wrapper,g1,g2);
  }
`,{census_emit:censusEmit});
keep.push(censusEmit,censusModule);
const censusNativeUpdate=new NativeFunction(censusModule.update,'void',
 ['pointer','pointer','pointer','pointer','pointer','pointer','pointer','pointer','pointer','pointer','int']);
const censusNativeNaval=new NativeFunction(censusModule.naval_update,'void',['pointer','pointer','pointer']);
function censusInstall(){
  CONFIG.first_airplanes=true;CONFIG.mode='air';
  CONFIG.air_participant_layout={entries:Object.fromEntries(['update','naval_update','regional','air_pair','dispatch','aggregate'].map(k=>[k,parseInt(censusModule[k].toString(),16)])),
    points:{mission_scan:parseInt(participantScanPoint.add(participantPointCode.length/2).toString(),16),naval_wing:parseInt(participantWingPoint.add(participantPointCode.length/2).toString(),16)}};
  installAirParticipants();Interceptor.flush();
}
function censusRunUpdate(during){censusNativeUpdate(censusRegion,censusCountries[0],censusVectors[0],censusVectors[1],
 censusCountries[1],censusVectors[2],censusVectors[3],censusBattleWrapper,censusGroups[0],censusGroups[1],during?1:0);}
rpc.exports.census=async function(kind='preceding'){
  censusInstall();
  if(kind==='stop_empty'){stopAirParticipants();return snapshotAirParticipants();}
  if(kind==='following'){
    censusNativeNaval(censusBattleWrapper,censusGroups[0],censusGroups[1]);
    const waiting=snapshotAirParticipants();censusRunUpdate(false);await new Promise(resolve=>setTimeout(resolve,20));return {waiting,result:snapshotAirParticipants()};
  }
  if(kind==='partial'){censusNativeNaval(censusBattleWrapper,censusGroups[0],censusGroups[1]);stopAirParticipants();return snapshotAirParticipants();}
  if(kind==='bad_count')cw[0].mission.add(0xe0).writeS32(-1);
  if(kind==='limit')participantLimits.vector=1;
  if(kind==='unknown_origin'){
    const b=resolveReference(cw[2].wing.add(0x38).readPointer().add(0x18));b.add(0x68).writePointer(ptr(0));
  }
  censusRunUpdate(kind==='same');if(kind!=='same')censusNativeNaval(censusBattleWrapper,censusGroups[0],censusGroups[1]);
  await new Promise(resolve=>setTimeout(resolve,20));const first=snapshotAirParticipants();
  cw[0].wing.add(0x7c).writeS32(9999);censusRunUpdate(true);
  return {first,after:snapshotAirParticipants(),remaining_hooks:participantHooks.length};
};

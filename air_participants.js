// A bounded census of one naval update and its region's air update.
// No game functions are called. Aircraft roles use the executing mission,
// and the actual base determines carrier versus land origin.
const participantLimits={regions:64,wings:4096,vector:4096,groups:1024};
const participantNavalScopes=new Map(),participantRegionalScopes=new Map(),participantAggregateScopes=new Map();
let participantWave=null,participantPrevious=null,participantSelected=null,participantResult=null;
let participantHooks=[],participantDone=false;
const participantStats={read_errors:0,omitted_regions:0,omitted_wings:0,omitted_groups:0,overlapping_updates:0};

function participantEnabled(){return CONFIG.first_airplanes===true&&CONFIG.mode!=='heavy';}
function participantCategory(origin,mission){
  const naval=(mission&0x190)!==0,fighter=(mission&5)!==0;
  if(naval===fighter||origin==='unknown')return 'other';
  return origin==='carrier'?(naval?'carrier_bomber':'carrier_fighter'):(naval?'land_bomber':'land_fighter');
}
function participantIdentity(wing,mission){
  const ref=referenceKey(wing.add(0x18));if(ref==='0:0')throw new Error('Missing wing reference');
  let country=wing.add(0x9c4).readS32();
  if(country<=0)country=wing.add(0x38).readPointer().add(0x40).readPointer().add(0x90).readS32();
  const holder=wing.add(0x38).readPointer(),base=resolveReference(holder.add(0x18));
  let origin='unknown',base_ref=referenceKey(holder.add(0x18));
  if(!base.isNull()){
    if(!base.add(0x68).readPointer().isNull())origin='land';
    else if(referenceKey(base.add(0x60))!=='0:0'&&!resolveReference(base.add(0x60)).isNull())origin='carrier';
  }
  return {id:ref,country:country>0?country:null,tag:countryTag(country),origin,base_ref,
          mission,category:participantCategory(origin,mission)};
}
function participantCount(p){const n=p.readS32();if(n<0||n>10000000)throw new Error('Invalid aircraft count');return n;}
function participantRow(rows,wing,mission){
  const id=participantIdentity(wing,mission),key=JSON.stringify([id.id,id.country]);
  let row=rows.get(key);
  if(!row){
    if(rows.size>=participantLimits.wings||(rows.wave&&rows.wave.total_rows>=participantLimits.wings)){participantStats.omitted_wings++;return null;}
    row={...id,registered:0,candidate:0,engaged_wing_planes:0,escort:0,shot_allocated_raw:'0',
         naval_ready:0,naval_assigned:0,normal:false,automatic:false};rows.set(key,row);
    if(rows.wave)rows.wave.total_rows++;
  }else if(row.category!==id.category){row.category='other';row.mixed_missions=true;}
  return row;
}
function participantRegion(wave,key,index=null){
  if(!wave)return null;
  if(participantSelected&&participantSelected.region_key!==key)return null;
  let region=wave.regions.get(key);
  if(!region){
    if(wave.regions.size>=participantLimits.regions){participantStats.omitted_regions++;return null;}
    region={key,index,rows:new Map(),registration_observed:false,candidate_calls:0,pair_calls:0};
    region.rows.wave=wave;wave.regions.set(key,region);
  }
  if(index!==null)region.index=index;
  return region;
}
function participantMissionScan(c){
  if(!participantWave||participantDone)return;
  try{
    const index=c.rsi.toInt32();if(index<0||index>65535)throw new Error('Invalid region index');
    const game=detailModule.base.add(CONFIG.details_layout.game_state).readPointer();
    if(index>=participantCount(game.add(0x2ec)))throw new Error('Region index out of range');
    const regionPtr=game.add(0x2e0).readPointer().add(index*8).readPointer();
    if(regionPtr.isNull())throw new Error('Missing region');
    const region=participantRegion(participantWave,regionPtr.toString(),index);if(!region)return;
    for(const [offset,route] of [[0x98,'normal'],[0x140,'automatic']]){
      const list=c.r15.add(offset).readPointer().add(index*24),n=participantCount(list.add(12));
      if(n>participantLimits.vector){participantStats.omitted_wings+=n;continue;}
      const entries=list.readPointer();if(n&&!entries.isNull()){
        for(let i=0;i<n;i++){
          try{
            const mission=entries.add(i*8).readPointer(),mask=mission.add(0x14).readU32();if(!mask)continue;
            const ready=participantCount(mission.add(0xe0)),row=participantRow(region.rows,mission.add(0x28).readPointer(),mask);
            if(!row)continue;
            row[route]=true;row.registered=Math.max(row.registered,ready);
            if(mission.add(0xb8).readS64().compare(int64(0))>0)row.escort=Math.max(row.escort,ready);
          }catch(e){participantStats.read_errors++;}
        }
      }else if(n)throw new Error('Missing mission list');
    }
    region.registration_observed=true;
  }catch(e){participantStats.read_errors++;}
}
function participantCandidates(region,vector){
  const n=participantCount(vector.add(12));if(n>participantLimits.vector){participantStats.omitted_wings+=n;return;}
  const data=vector.readPointer();if(n&&data.isNull())throw new Error('Missing candidate vector');
  for(let i=0;i<n;i++){
    try{
      const m=data.add(i*24).readPointer(),ready=participantCount(m.add(0xe0));
      const row=participantRow(region.rows,m.add(0x28).readPointer(),m.add(0x14).readU32());
      if(row)row.candidate=Math.max(row.candidate,ready);
    }catch(e){participantStats.read_errors++;}
  }
}
function participantSelect(pass,group,battle){
  if(participantDone||!pass||!pass.battle.equals(battle)||participantCount(group.add(0x5c))===0)return;
  if(participantSelected)return;
  const province=battle.add(0x38).readPointer(),region=province.add(0xc8).readPointer();
  if(region.isNull())throw new Error('Missing naval region');
  participantSelected=pass;pass.region_key=region.toString();pass.started_at=new Date().toISOString();pass.rows=new Map();pass.groups=new Set();
  pass.regional=null;pass.association=null;
  if(participantWave&&participantWave.regions.has(pass.region_key)){
    pass.regional_wave=participantWave;pass.association='same_air_update';
  }else if(participantPrevious&&participantPrevious.regions.has(pass.region_key)){
    pass.regional_wave=participantPrevious;pass.association='preceding_air_update';
  }
}
function participantMergedRows(regional,naval){
  const rows=new Map();
  for(const row of regional?regional.rows.values():[])rows.set(JSON.stringify([row.id,row.country]),{...row});
  for(const row of naval.rows.values()){
    const key=JSON.stringify([row.id,row.country]),old=rows.get(key);
    if(old){old.naval_ready=row.naval_ready;old.naval_assigned=row.naval_assigned;if(old.category!==row.category){old.category='other';old.mixed_missions=true;}}
    else rows.set(key,{...row});
  }
  return Array.from(rows.values());
}
function detachParticipantHooks(){
  const old=participantHooks;participantHooks=[];
  for(const h of old)h.detach();
  listeners=listeners.filter(h=>!old.includes(h));
  participantWave=null;participantPrevious=null;
}
function participantFinish(interrupted=false){
  const pass=participantSelected;if(!pass||participantDone)return;
  const wave=pass.regional_wave,region=wave&&wave.regions.get(pass.region_key);
  if(!interrupted&&(!pass.complete||!wave||!wave.complete||!region))return;
  const partial=interrupted||!region||Object.values(participantStats).some(n=>n>0);
  participantResult={version:1,status:partial?'partial':'complete',sampling:'first_naval_update',
    naval_started_at:pass.started_at,naval_ended_at:pass.ended_at||null,naval_complete:!!pass.complete,
    regional_started_at:wave?wave.started_at:null,regional_ended_at:wave?wave.ended_at:null,
    regional_observed:!!region,registration_observed:!!(region&&region.registration_observed),
    association:pass.association,region:region?region.index:null,limits:{...participantLimits},stats:{...participantStats},
    candidate_calls:region?region.candidate_calls:0,pair_calls:region?region.pair_calls:0,
    naval_groups:pass.groups.size,rows:participantMergedRows(region,pass)};
  participantDone=true;setTimeout(detachParticipantHooks,0);
}
function snapshotAirParticipants(){
  if(participantResult)return {...participantResult,hooks_active:participantHooks.length>0};
  return {version:1,status:!participantEnabled()?'disabled':participantSelected?'waiting_regional_update':'waiting_naval_update',
          hooks_active:participantHooks.length>0,limits:{...participantLimits},stats:{...participantStats},rows:[]};
}
function stopAirParticipants(){
  if(participantSelected)participantFinish(true);
  else if(participantEnabled()&&!participantDone)participantResult={...snapshotAirParticipants(),status:'not_observed',hooks_active:false};
  detachParticipantHooks();
}
function acknowledgeAirParticipants(){
  if(!participantDone||!participantResult||!participantResult.rows)return false;
  participantResult={...participantResult,storage:'air_participants.json',row_count:participantResult.rows.length};
  delete participantResult.rows;participantSelected=null;return true;
}
function installAirParticipants(){
  const layout=CONFIG.air_participant_layout;if(!participantEnabled()||!layout)return;
  function hook(address,callback){const h=Interceptor.attach(detailModule.base.add(address),callback);participantHooks.push(h);listeners.push(h);}
  hook(layout.entries.update,{
    onEnter(){
      if(participantDone)return;
      if(participantWave){participantStats.overlapping_updates++;return;}
      this.wave={started_at:new Date().toISOString(),regions:new Map(),total_rows:0,complete:false};participantWave=this.wave;
    },
    onLeave(){
      if(!this.wave||participantDone)return;
      this.wave.complete=true;this.wave.ended_at=new Date().toISOString();participantPrevious=this.wave;participantWave=null;
      if(participantSelected&&!participantSelected.regional_wave&&this.wave.regions.has(participantSelected.region_key)){
        participantSelected.regional_wave=this.wave;participantSelected.association='following_air_update';
      }
      participantFinish();
    }
  });
  hook(layout.points.mission_scan,function(){participantMissionScan(this.context);});
  hook(layout.entries.regional,{
    onEnter(args){
      if(!participantWave||participantDone)return;
      try{
        const region=participantRegion(participantWave,args[0].toString());if(!region)return;
        region.candidate_calls++;participantCandidates(region,args[3]);participantCandidates(region,args[4]);
        this.scope={region};this.tid=pushScope(participantRegionalScopes,this.scope);
      }catch(e){participantStats.read_errors++;}
    },
    onLeave(){if(this.scope)popScope(participantRegionalScopes,this.tid,this.scope);}
  });
  hook(layout.entries.air_pair,{
    onEnter(args){
      const scope=latestScope(participantRegionalScopes);if(!scope||participantDone)return;
      try{
        const region=scope.region,target=args[0],wing=args[5],mask=wing.add(0xa4).readU32();
        const attacker=participantRow(region.rows,wing,mask),defender=participantRow(region.rows,target.add(0x28).readPointer(),target.add(0x14).readU32());
        if(attacker){attacker.engaged_wing_planes=Math.max(attacker.engaged_wing_planes,attacker.candidate);const amount=BigInt(signed(args[4]));
          if(amount<0n)throw new Error('Negative allocation');attacker.shot_allocated_raw=(BigInt(attacker.shot_allocated_raw)+amount).toString();}
        if(defender)defender.engaged_wing_planes=Math.max(defender.engaged_wing_planes,defender.candidate);
        region.pair_calls++;
      }catch(e){participantStats.read_errors++;}
    }
  });
  hook(layout.entries.naval_update,{
    onEnter(args){
      if(participantDone||participantSelected)return;
      try{
        const battle=args[0].add(0x18).readPointer();if(battle.isNull()||battle.add(0x10c).readU8()||battle.add(0x10d).readU8())return;
        this.scope={battle,complete:false};this.tid=pushScope(participantNavalScopes,this.scope);
      }catch(e){participantStats.read_errors++;}
    },
    onLeave(){
      if(!this.scope)return;
      popScope(participantNavalScopes,this.tid,this.scope);
      if(this.scope===participantSelected){this.scope.complete=true;this.scope.ended_at=new Date().toISOString();participantFinish();}
    }
  });
  hook(layout.entries.dispatch,{
    onEnter(args){try{participantSelect(latestScope(participantNavalScopes),args[0],args[2]);}catch(e){participantStats.read_errors++;}}
  });
  hook(layout.entries.aggregate,{
    onEnter(args){
      const pass=latestScope(participantNavalScopes);if(!pass||pass!==participantSelected||participantDone)return;
      const key=args[0].toString();if(pass.groups.has(key))return;
      if(pass.groups.size>=participantLimits.groups){participantStats.omitted_groups++;return;}
      pass.groups.add(key);this.scope={pass,group:args[0]};this.tid=pushScope(participantAggregateScopes,this.scope);
    },
    onLeave(){if(this.scope)popScope(participantAggregateScopes,this.tid,this.scope);}
  });
  hook(layout.points.naval_wing,function(){
    const scope=latestScope(participantAggregateScopes);if(!scope||participantDone)return;
    try{
      const c=this.context,assigned=c.rax.toInt32();if(assigned<0)throw new Error('Negative allocation');
      const row=participantRow(scope.pass.rows,c.r14,0x10);if(!row)return;
      row.naval_ready=Math.max(row.naval_ready,participantCount(c.r14.add(0x7c)));row.naval_assigned+=assigned;
    }catch(e){participantStats.read_errors++;}
  });
}

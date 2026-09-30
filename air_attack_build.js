// Track each contributing wing, while the real aggregation function owns it.
const airStatScopes=new Map(),airWingScopes=new Map();
const AIR_WING_TRACE_LIMIT=128;
function latestScope(map){const s=map.get(Process.getCurrentThreadId());return s&&s[s.length-1];}
function pushScope(map,scope){const tid=Process.getCurrentThreadId();let s=map.get(tid);if(!s){s=[];map.set(tid,s);}s.push(scope);return tid;}
function popScope(map,tid,scope){const s=map.get(tid);if(s){const i=s.indexOf(scope);if(i>=0)s.splice(i,1);if(!s.length)map.delete(tid);}}
function installAirAttackBuild(){
  const layout=CONFIG.air_trace_layout;if(!layout||!layout.aggregate_entry)return;
  listeners.push(Interceptor.attach(detailModule.base.add(layout.aggregate_entry),{
    onEnter(args){
      const parent=latestScope(airDispatchScopes);if(!parent)return;
      const data={version:1,wings:[],wing_limit:AIR_WING_TRACE_LIMIT,omitted_wings:0,complete:false};
      this.scope={data,group:args[0],output:args[2],current:null};this.tid=pushScope(airStatScopes,this.scope);
      parent.attack_build=data;
      try{data.carrier_country_applied=!args[5].isNull();data.external=args[0].add(0x81).readU8()!==0;
        if(data.external)data.external_factor=args[0].add(0xc0).readS64().toString();}
      catch(e){data.error='集約の入力読取に失敗';airExampleStats.read_errors++;}
    },
    onLeave(){if(!this.scope)return;try{this.scope.data.final_attack=this.scope.output.readS64().toString();this.scope.data.complete=true;}
      catch(e){this.scope.data.error='集約の出力読取に失敗';airExampleStats.read_errors++;}popScope(airStatScopes,this.tid,this.scope);}
  }));
  listeners.push(Interceptor.attach(detailModule.base.add(layout.wing_attack_entry),{
    onEnter(args){
      const stat=latestScope(airStatScopes);if(!stat||!stat.current||!stat.current.wing.equals(args[0]))return;
      this.scope={row:stat.current.row,output:args[1]};this.tid=pushScope(airWingScopes,this.scope);
      this.scope.row.province=args[2].toInt32();this.scope.row.mission=args[3].toUInt32();
    },
    onLeave(){if(!this.scope)return;try{this.scope.row.attack_before_disruption=this.scope.output.readS64().toString();}
      catch(e){this.scope.row.error='航空隊の出力読取に失敗';airExampleStats.read_errors++;}popScope(airWingScopes,this.tid,this.scope);}
  }));
}
function captureAirAttackBuild(name,c){
  const mem=p=>p.readS64().toString(),stat=latestScope(airStatScopes);
  try{
    if(name.startsWith('wing_')){
      const scope=latestScope(airWingScopes);if(!scope)return;const r=scope.row;
      switch(name){
        case 'wing_raw':r.cached_attack=mem(c.rsp.add(0x70));break;
        case 'wing_scaled':r.scaled_attack=mem(c.r14);
          if(r.province>0&&r.mission===0x80){const rva=CONFIG.air_trace_layout.globals.port_attack_multiplier;
            if(rva!==undefined)r.port_attack_factor=mem(detailModule.base.add(rva));}break;
        case 'wing_ace':r.ace_bonus=mem(c.rax);break;
        case 'wing_country':r.country_bonus=mem(c.rax);break;
        case 'wing_mission':r.mission_bonus=mem(c.rax);break;
        case 'wing_experience':r.experience=mem(c.rax);r.experience_bonus=mem(c.rdi);break;
        case 'wing_weather':r.weather=mem(c.rax);r.weather_bonus=mem(c.rdi);break;
        case 'wing_factor':r.total_factor=signed(c.rbx);break;
      }return;
    }
    if(!stat)return;const d=stat.data;
    switch(name){
      case 'stat_wing':{
        const row={index:d.wings.length+1,assigned_planes:c.rax.toInt32(),allocation_before_round:mem(c.rsp.add(0x38)),eligible_planes_scaled:signed(c.rdi)};
        if(d.wings.length<AIR_WING_TRACE_LIMIT)d.wings.push(row);else d.omitted_wings++;
        stat.current={wing:c.r14,row};row.disruption_raw=mem(c.r14.add(0x138));
        row.ready_planes=c.r14.add(0x7c).readS32();row.group_planes=stat.group.add(0x5c).readS32();
        break;
      }
      case 'stat_disruption':if(stat.current)stat.current.row.disruption_factor=mem(c.rbp.sub(0x59));break;
      case 'stat_disruption_inputs':if(stat.current){
        const r=stat.current.row;r.disruption_attack=signed(c.rbx);r.disruption_defence=signed(c.rbp);
        r.disruption_speed=mem(c.rsp.add(0x80));
        for(const label of ['attack','defence','speed']){
          const rva=CONFIG.air_trace_layout.globals['disruption_'+label+'_factor'];
          if(rva!==undefined)r['disruption_'+label+'_factor']=mem(detailModule.base.add(rva));
        }
      }break;
      case 'stat_disruption_denominator':if(stat.current)stat.current.row.disruption_denominator=signed(c.rcx);break;
      case 'stat_disruption_ratio':if(stat.current)stat.current.row.disruption_ratio=signed(c.rax);break;
      case 'stat_disruption_root':if(stat.current)stat.current.row.disruption_root=mem(c.rax);break;
      case 'stat_disruption_preclamp':if(stat.current)stat.current.row.disruption_preclamp=signed(c.rax);break;
      case 'stat_contribution':if(stat.current)stat.current.row.attack_contribution=signed(c.rdx);break;
      case 'stat_sum':d.assigned_planes=c.rax.toInt32();d.attack_sum=mem(stat.output);break;
      case 'stat_average':d.average_attack=mem(stat.output);break;
      case 'stat_country':d.carrier_country_bonus=mem(c.rax);break;
      case 'stat_external':d.after_carrier_country=mem(stat.output);break;
    }
  }catch(e){if(stat)stat.data.error='集約の途中読取に失敗';airExampleStats.read_errors++;}
}

// Disposable-process test only. These functions model the exact probe register layout.
function code(hex) {
  const p=Memory.alloc(Process.pageSize);
  p.writeByteArray(hex.match(/../g).map(x=>parseInt(x,16)));
  Memory.protect(p,Process.pageSize,'r-x');
  return p;
}
const gunPrefix='554881ec80010000488d6c2460898da00000004c8945c84889d1';
const gunBody='48394dc80f8e07000000b801000000eb0231c0'+'90'.repeat(24)+'4881c4800100005dc3';
const gun=code(gunPrefix+gunBody);
const airPrefix='53564863f189d0';
const airBody='4863d885c07e05'+'90'.repeat(32)+'5e5bc3';
const air=code(airPrefix+airBody);
if(CONFIG.mode!=='air') install('heavy',gun.add(gunPrefix.length/2));
if(CONFIG.mode!=='heavy') install('air',air.add(airPrefix.length/2));
Interceptor.flush();
const gunCall=new NativeFunction(gun,'int',['int','int64','int64']);
const airCall=new NativeFunction(air,'int',['int','int']);
const runner=new CModule(`
  typedef int (*Gun)(int,long long,long long);
  typedef int (*Air)(int,int);
  typedef struct { Gun gun; Air air; int n; int failures; } Work;
  unsigned long run(void *opaque) {
    Work *w = (Work *)opaque; int i;
    for(i=0;i<w->n;i++) {
      if(w->gun(0,100,101)!=1) w->failures++;
      if(w->gun(0,100,100)!=0) w->failures++;
      if(w->gun(0,100,99)!=0) w->failures++;
      w->gun(2,0,100); w->gun(1,100,0);
      if(w->air(100,25)!=25) w->failures++;
      if(w->air(50,0)!=0) w->failures++;
      if(w->air(1,1)!=1) w->failures++;
    }
    return 0;
  }
`);
rpc.exports.exercise=function(n,threads) {
  const create=new NativeFunction(kernel.getExportByName('CreateThread'),'pointer',
    ['pointer','size_t','pointer','pointer','uint','pointer']);
  const wait=new NativeFunction(kernel.getExportByName('WaitForSingleObject'),'uint',['pointer','uint']);
  const close=new NativeFunction(kernel.getExportByName('CloseHandle'),'int',['pointer']);
  const jobs=[];
  for(let i=0;i<threads;i++) {
    const work=Memory.alloc(24);
    work.writePointer(gun); work.add(8).writePointer(air); work.add(16).writeS32(n);
    const thread=create(ptr(0),0,runner.run,work,0,ptr(0));
    if(thread.isNull()) throw new Error('CreateThread failed');
    jobs.push({thread,work});
  }
  for(const job of jobs) {
    if(wait(job.thread,30000)!==0) throw new Error('fixture timeout');
    close(job.thread);
  }
  return jobs.map(job=>job.work.add(20).readS32());
};
rpc.exports.invalid=function() {
  gunCall(3,0,100); airCall(0,0); airCall(1,2); airCall(1,-1);
};

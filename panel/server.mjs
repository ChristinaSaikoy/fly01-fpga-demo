import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Motion} from './app/motion.js';
import {R6Adapter} from './r6.mjs';
import {StringDecoder} from 'node:string_decoder';
import {randomBytes} from 'node:crypto';
import {ControlBridge} from './control_bridge.mjs';
const root=path.dirname(fileURLToPath(import.meta.url));
const args=process.argv.slice(2),arg=k=>args.includes(k)?path.resolve(args[args.indexOf(k)+1]):null;
const r6log=arg('--r6-log'),r6dir=arg('--r6-dir'),isR6=!!(r6log||r6dir);let log=r6log||arg('--log');let adapter=new R6Adapter('tail');
function latestR6(){if(!r6dir)return log;const dirs=fs.readdirSync(r6dir).filter(n=>/^manual_/.test(n)).sort().reverse();return dirs.map(n=>path.join(r6dir,n,'events.jsonl')).find(p=>fs.existsSync(p))||null;}

const port=Number(process.env.PORT||8765);let offset=0,partial='',identity='',last=null,received=0,version=0,epoch=0,error=null,motion=new Motion(),decoder=new StringDecoder('utf8');
const controlToken=randomBytes(24).toString('hex');let controlLast=null,controlReceived=0,controlVersion=0,controlEpoch=0,controlSession=null,controlAdapter=new R6Adapter('panel');
const bridge=new ControlBridge(root,row=>{if(controlSession!==row.session){controlSession=row.session;controlEpoch++;}try{const e=controlAdapter.accept(row,'live_fpga');if(e){controlLast=e;controlReceived=performance.now();controlVersion++;}}catch{controlLast=null;}});
function close(){bridge.close();server.close();setTimeout(()=>process.exit(0),700).unref();}
process.once('SIGINT',close);process.once('SIGTERM',close);
// Legacy read-only log tail; hardware control is isolated in ControlBridge.
if(log||r6dir)setInterval(()=>{try{
 log=latestR6();if(!log){last=null;error='等待新的R6日志';return;}
 const st=fs.statSync(log),id=`${log}:${st.dev}:${st.ino}`;
 if(id!==identity||st.size<offset){identity=id;offset=st.size;partial='';last=null;error=null;epoch++;motion=new Motion();decoder=new StringDecoder('utf8');adapter=new R6Adapter(path.basename(path.dirname(log))+'-'+epoch);return;}
 if(st.size-offset>8*1024*1024){error='日志增量超过8MB，请轮转日志';return;}
 if(st.size===offset)return;
 const fd=fs.openSync(log,'r'),buf=Buffer.alloc(st.size-offset);let count;try{count=fs.readSync(fd,buf,0,buf.length,offset);}finally{fs.closeSync(fd);}offset+=count;
 partial+=decoder.write(buf.subarray(0,count));const lines=partial.split('\n');partial=lines.pop();
 for(const line of lines){if(!line.trim())continue;try{const raw=JSON.parse(line),e=isR6?adapter.accept(raw,'live_fpga'):raw;if(!e)continue;if(motion.receive(e,performance.now())){last=e;received=performance.now();version++;error=null;}}catch(ex){error=ex.message;last=null;}}
 if(partial.length>1024*1024){partial='';error='单行过大';last=null;}
 }catch(ex){error=ex.code||ex.message;last=null;}},100).unref();
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.jsonl':'application/x-ndjson'};
const server=http.createServer(async(req,res)=>{
 const host=req.headers.host;if(![`127.0.0.1:${port}`,`localhost:${port}`].includes(host)){res.writeHead(403).end();return;}
 const url=new URL(req.url,'http://127.0.0.1');
 if(url.pathname==='/api/control'){
  res.setHeader('Content-Type','application/json');res.setHeader('Cache-Control','no-store');
  if(req.method==='GET'){res.end(JSON.stringify({token:controlToken,...bridge.state}));return;}
  if(req.method!=='POST'){res.writeHead(405).end();return;}
  if(![`http://127.0.0.1:${port}`,`http://localhost:${port}`].includes(req.headers.origin)){res.writeHead(403).end();return;}
  let body='';try{for await(const chunk of req){body+=chunk;if(body.length>2048)throw Error('Request too large');}const data=JSON.parse(body);
   if(data.token!==controlToken){res.writeHead(403).end();return;}
   if(!['connect','arm','stop','disconnect','heartbeat','retry','configure_pwm','inspect_chassis','chassis_test','chassis_feedback'].includes(data.cmd)){res.writeHead(400).end(JSON.stringify({ok:false,error:'Unsupported command'}));return;}
   const answer=await bridge.command(data.cmd,data.raised===true,{trim:data.trim,cap:data.cap,level:data.level,observation:data.observation});res.writeHead(answer.ok?200:409).end(JSON.stringify(answer));
  }catch{res.writeHead(400).end(JSON.stringify({ok:false,error:'Invalid request'}));}return;
 }
 if(req.method!=='GET'){res.writeHead(405).end();return;}
 if(url.pathname==='/api/live-snapshot'){res.setHeader('Content-Type','application/json');res.setHeader('Cache-Control','no-store');res.end(JSON.stringify({connected:bridge.state.connected,epoch:controlEpoch,version:controlVersion,event:controlLast,age_ms:controlLast?performance.now()-controlReceived:null,error:bridge.state.connected?null:'设备未连接'}));return;}
 if(url.pathname==='/api/snapshot'){res.setHeader('Content-Type','application/json');res.setHeader('Cache-Control','no-store');res.end(JSON.stringify({connected:!!(log||r6dir),epoch,version,event:last,age_ms:last?performance.now()-received:null,error}));return;}
 const routes={'/':'app/index.html','/sample':'samples/telemetry_synthetic.jsonl','/demo':'samples/demo_synthetic.jsonl','/r6':'samples/r6_recorded.jsonl'};
 let decoded;try{decoded=decodeURIComponent(url.pathname);}catch{res.writeHead(400).end();return;}
 const rel=routes[url.pathname]||('app/'+decoded.replace(/^\//,''));
 const target=path.resolve(root,rel);if(!target.startsWith(root+path.sep)){res.writeHead(403).end();return;}
 if(!routes[url.pathname]&&!target.startsWith(path.join(root,'app')+path.sep)){res.writeHead(403).end();return;}
 fs.readFile(target,(err,data)=>{if(err){res.writeHead(404).end('Not found');return;}res.setHeader('Content-Type',types[path.extname(target)]||'application/octet-stream');res.setHeader('Cache-Control','no-store');res.end(data);});
}).listen(port,'127.0.0.1',()=>console.log(`FLY01 mirror http://127.0.0.1:${port} | ${log?'只读日志模式':'仅回放；无实时源'}`));

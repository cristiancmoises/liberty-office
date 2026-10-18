// Synthetic loopback TLS only; the certificate is generated for this fixture.
import http2 from 'node:http2';
import fs from 'node:fs';
const signals='/signals';
const mark=(name,value='true')=>fs.writeFileSync(`${signals}/${name}`,value);
const session=http2.connect('https://127.0.0.1:18881',{rejectUnauthorized:false});
let retired=false,finished=false;
const finish=()=>{if(retired&&finished)session.close()};
session.on('error',error=>{mark('h2.error',error.code||error.name);process.exitCode=1});
session.on('goaway',()=>{
  if(retired)return;retired=true;mark('h2.goaway');
  try{
    const forbidden=session.request({':method':'POST',':path':'/fixture/write/must-not-write',':authority':'office.example.test'});
    forbidden.on('error',error=>mark('h2.refused',JSON.stringify({code:error.code||error.name,rstCode:forbidden.rstCode})));
    forbidden.on('response',()=>{mark('h2.unexpected-response');process.exitCode=1});
    forbidden.end('forbidden');
  }catch(error){mark('h2.refused',JSON.stringify({code:error.code||error.name}))}
  finish();
});
const active=session.request({':method':'POST',':path':'/fixture/write/h2-active',':authority':'office.example.test'});
let status=null,body='';
active.on('response',headers=>{status=headers[':status']});
active.on('data',chunk=>{body+=chunk});
active.on('error',error=>{mark('h2.error',error.code||error.name);process.exitCode=1;session.close()});
active.on('end',()=>{
  const result=JSON.parse(body);if(status!==200||result.mutation!=='h2-active')process.exitCode=1;
  mark('h2.done',JSON.stringify({status,mutation:result.mutation}));finished=true;finish();
});
active.end('h2-buffer');

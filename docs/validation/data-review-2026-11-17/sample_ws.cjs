// Read-only dashboard stream and owner-reported source health.
const WebSocket = require("/app/node_modules/ws");
(async () => {
  const response = await fetch("http://localhost:3000/auth/token", {method:"POST",
    headers:{"Content-Type":"application/json"},body:JSON.stringify({client_id:"dashboard",secret:"art-dev-secret"})});
  const {token} = await response.json();
  if (!token) throw new Error(`Token request failed: ${response.status}`);
  const sources = await (await fetch("http://localhost:3000/api/v1/data-sources",
    {headers:{Authorization:`Bearer ${token}`}})).json();
  const counts = {}; let bytes=0; let first;
  const ws = new WebSocket(`ws://localhost:3000/ws?token=${token}`);
  ws.on("open",()=>ws.send(JSON.stringify({action:"subscribe",topics:["flights","passengers","baggage","weather","incidents","alerts","sim","analysis","costs"]})));
  ws.on("message", raw => {bytes+=raw.length;const e=JSON.parse(raw); const k=e.event_type||e.type||"unknown";counts[k]=(counts[k]||0)+1;if(!first)first={keys:Object.keys(e),type:k};});
  ws.on("error",err=>{console.error(err);process.exitCode=1;});
  setTimeout(()=>{console.log(JSON.stringify({duration_s:45,counts,bytes,first,sources},null,2));ws.close();},45000);
})();

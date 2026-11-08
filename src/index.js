const JSON_HEADERS = { "Content-Type": "application/json; charset=utf-8" };
const MAX_TEXT_LENGTH = 10000;
const MAX_RATE = 50;
const JOB_TTL = 60 * 60;

const VOICES = [
  ...[
    ["sirio","Sirio","Male"],["nestor","Néstor","Male"],["carina","Carina","Female"],
    ["celeste","Celeste","Female"],["alvaro","Álvaro","Male"],["diana","Diana","Female"],
    ["aquila","Áquila","Male"],["selena","Selena","Female"],["estrella","Estrella","Female"],
    ["javier","Javier","Male"]
  ].map(([speaker,name,gender]) => ({id:`es-ES-${speaker}`,name,locale:"es-ES",gender,model:"@cf/deepgram/aura-2-es",speaker})),
  ...[
    "amalthea","andromeda","apollo","arcas","aries","asteria","athena","atlas",
    "aurora","callista","cora","cordelia","delia","draco","electra","harmonia",
    "helena","hera","hermes","hyperion","iris","janus","juno","jupiter","luna",
    "mars","minerva","neptune","odysseus","ophelia","orion","orpheus","pandora",
    "phoebe","pluto","saturn","thalia","theia","vesta","zeus"
  ].map((speaker) => ({id:`en-US-${speaker}`,name:speaker[0].toUpperCase()+speaker.slice(1),locale:"en-US",gender:"",model:"@cf/deepgram/aura-2-en",speaker}))
];

function json(data, status=200, origin="*") {
  return new Response(JSON.stringify(data), {status,headers:{...JSON_HEADERS,"Access-Control-Allow-Origin":origin,"Access-Control-Allow-Methods":"GET,POST,OPTIONS","Access-Control-Allow-Headers":"Content-Type"}});
}
function error(message,status=400,origin="*"){return json({detail:message},status,origin);}
function pauseSegments(text) {
  const pattern=/\[(?:silence|silencio|pause|pausa|break)(?:\s+(\d+(?:[.,]\d+)?)\s*(ms|milliseconds?|millisecond|s|sec|secs|seconds?|seg|segs|segundos?))?\s*\]/gi;
  const parts=[];let cursor=0;let match;
  while((match=pattern.exec(text))){
    const spoken=text.slice(cursor,match.index).trim();
    if(spoken) parts.push({type:"text",text:spoken});
    let seconds=match[1]?Number(match[1].replace(",",".")):1;
    if((match[2]||"s").toLowerCase().startsWith("ms")) seconds/=1000;
    parts.push({type:"pause",seconds:Math.min(10,Math.max(.1,seconds))});
    cursor=pattern.lastIndex;
  }
  const tail=text.slice(cursor).trim();if(tail)parts.push({type:"text",text:tail});
  return parts.length?parts:[{type:"text",text}];
}
function splitText(text,limit=3500){
  const out=[];let rest=text.trim();
  while(rest.length>limit){let cut=rest.lastIndexOf(" ",limit);if(cut<limit*.5)cut=limit;out.push(rest.slice(0,cut).trim());rest=rest.slice(cut).trim();}
  if(rest)out.push(rest);return out;
}
async function synthesize(env,text,voice,rate){
  const segments=pauseSegments(text);
  if(segments.some(x=>x.type==="pause")) {
    throw new Error("Pause markers are not supported by the selected Cloudflare speech model yet. Remove the pause markers and try again.");
  }
  const chunks=segments.flatMap(x=>splitText(x.text));
  if(chunks.length>3) throw new Error("This Cloudflare voice currently accepts up to 10,000 characters per request. Please shorten the text.");
  const chunksAudio=[];
  for(const chunk of chunks){
    const result=await env.AI.run(voice.model,{text:chunk,speaker:voice.speaker,encoding:"mp3"});
    if(result instanceof ReadableStream) chunksAudio.push(new Uint8Array(await new Response(result).arrayBuffer()));
    else if(result?.audio) chunksAudio.push(Uint8Array.from(atob(result.audio),c=>c.charCodeAt(0)));
    else throw new Error("The speech provider returned an unsupported audio response.");
  }
  if(chunksAudio.length!==1) throw new Error("Long-text MP3 joining is not enabled in this Worker version.");
  return chunksAudio[0];
}
export default {
  async fetch(request,env){
    const origin=request.headers.get("Origin")||"*";
    if(request.method==="OPTIONS")return new Response(null,{status:204,headers:{"Access-Control-Allow-Origin":origin,"Access-Control-Allow-Methods":"GET,POST,OPTIONS","Access-Control-Allow-Headers":"Content-Type","Access-Control-Max-Age":"86400"}});
    const url=new URL(request.url);const path=url.pathname;
    if(path==="/api/health"&&request.method==="GET")return json({status:"ok"},200,origin);
    if(path==="/api/voices"&&request.method==="GET")return json({voices:VOICES.map(({id,name,locale,gender})=>({id,name,locale,gender})),default:"es-ES-alvaro"},200,origin);
    if(path==="/api/generate"&&request.method==="POST"){
      let body;try{body=await request.json();}catch{return error("Invalid JSON request.",400,origin);}
      const text=String(body.text||"").trim();const voice=VOICES.find(v=>v.id===body.voice);
      const rate=Number(body.rate??0);
      if(!text)return error("Escribe un texto antes de generar la voz.",400,origin);
      if(text.length>MAX_TEXT_LENGTH)return error("El texto supera el máximo actual de 10.000 caracteres.",413,origin);
      if(!voice)return error("La voz seleccionada no está disponible. Actualiza la lista de voces.",400,origin);
      if(!Number.isFinite(rate)||rate < -MAX_RATE||rate > MAX_RATE)return error("Invalid reading speed.",400,origin);
      const id=crypto.randomUUID();
      await env.JOBS.put(id,JSON.stringify({status:"processing",progress:10,completed_chunks:0,total_chunks:1}),{expirationTtl:JOB_TTL});
      try{
        const audio=await synthesize(env,text,voice,rate);
        await env.AUDIO.put(id,audio,{httpMetadata:{contentType:"audio/mpeg"},expirationTtl:JOB_TTL});
        await env.JOBS.put(id,JSON.stringify({status:"done",progress:100,completed_chunks:1,total_chunks:1}),{expirationTtl:JOB_TTL});
        return json({job_id:id},202,origin);
      }catch(e){
        await env.JOBS.put(id,JSON.stringify({status:"error",progress:0,error:e.message||"Audio generation failed."}),{expirationTtl:JOB_TTL});
        return error(e.message||"Audio generation failed.",502,origin);
      }
    }
    const jobMatch=path.match(/^\/api\/jobs\/([a-f0-9-]+)$/i);
    if(jobMatch&&request.method==="GET"){
      const value=await env.JOBS.get(jobMatch[1]);if(!value)return error("La tarea no existe o ha caducado.",404,origin);
      return json(JSON.parse(value),200,origin);
    }
    const downloadMatch=path.match(/^\/api\/jobs\/([a-f0-9-]+)\/download$/i);
    if(downloadMatch&&request.method==="GET"){
      const object=await env.AUDIO.get(downloadMatch[1]);if(!object)return error("El MP3 todavía no está listo o la tarea ha caducado.",404,origin);
      return new Response(object.body,{headers:{"Content-Type":"audio/mpeg","Content-Disposition":'attachment; filename="voz-kovo.mp3"',"Cache-Control":"no-store","Access-Control-Allow-Origin":origin}});
    }
    return error("Not found.",404,origin);
  }
};

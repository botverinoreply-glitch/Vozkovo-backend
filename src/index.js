const JSON_HEADERS = { "Content-Type": "application/json; charset=utf-8" };
const MAX_TEXT_LENGTH = 10000;
const CHUNK_SIZE = 3000;
const JOB_TTL = 3600;

const VOICES = [
  ...[
    ["sirio","Sirio","Male"],["nestor","Néstor","Male"],["carina","Carina","Female"],
    ["celeste","Celeste","Female"],["alvaro","Álvaro","Male"],["diana","Diana","Female"],
    ["aquila","Aquila","Male"],["selena","Selena","Female"],["estrella","Estrella","Female"],
    ["javier","Javier","Male"]
  ].map(([speaker,name,gender]) => ({id:`es-ES-${speaker}`,name,locale:"es-ES",gender,model:"@cf/deepgram/aura-2-es",speaker})),
  ...[
    "amalthea","andromeda","apollo","arcas","aries","asteria","athena","atlas",
    "aurora","callista","cora","cordelia","delia","draco","electra","harmonia",
    "helena","hera","hermes","hyperion","iris","janus","juno","jupiter","luna",
    "mars","minerva","neptune","odysseus","ophelia","orion","orpheus","pandora",
    "phoebe","pluto","saturn","thalia","theia","vesta","zeus"
  ].map(speaker => ({id:`en-US-${speaker}`,name:speaker[0].toUpperCase()+speaker.slice(1),locale:"en-US",gender:"",model:"@cf/deepgram/aura-2-en",speaker}))
];

const PUBLIC_VOICES = VOICES.map(({id,name,locale,gender})=>({id,name,locale,gender}));
const DEFAULT_VOICE = "es-ES-alvaro";

function corsHeaders(origin,env) {
  const allowed=(env.ALLOWED_ORIGINS||"*").split(",").map(x=>x.trim());
  const selected=allowed.includes("*")?(origin||"*"):(allowed.includes(origin)?origin:"null");
  return {
    "Access-Control-Allow-Origin":selected,
    "Access-Control-Allow-Methods":"GET,POST,OPTIONS",
    "Access-Control-Allow-Headers":"Content-Type",
    "Access-Control-Max-Age":"86400",
    "Vary":"Origin"
  };
}
function json(data,status,origin,env,extra={}) {
  return new Response(JSON.stringify(data),{status,headers:{...JSON_HEADERS,...corsHeaders(origin,env),...extra}});
}
function fail(message,status,origin,env){return json({detail:message},status,origin,env);}
function splitText(text,limit=CHUNK_SIZE) {
  const chunks=[];let remaining=text.trim();
  while(remaining.length>limit){
    let cut=remaining.lastIndexOf(" ",limit);
    if(cut<limit*.6)cut=limit;
    chunks.push(remaining.slice(0,cut).trim());
    remaining=remaining.slice(cut).trim();
  }
  if(remaining)chunks.push(remaining);
  return chunks;
}
function concatAudio(parts) {
  const length=parts.reduce((sum,part)=>sum+part.length,0);
  const output=new Uint8Array(length);let offset=0;
  for(const part of parts){output.set(part,offset);offset+=part.length;}
  return output;
}
async function synthesize(env,text,voice) {
  const chunks=splitText(text);
  const audioParts=[];
  for(const chunk of chunks){
    const result=await env.AI.run(voice.model,{
      text:chunk,
      speaker:voice.speaker,
      encoding:"mp3"
    });
    let bytes;
    if(result instanceof ReadableStream) bytes=new Uint8Array(await new Response(result).arrayBuffer());
    else if(result?.audio) bytes=Uint8Array.from(atob(result.audio),char=>char.charCodeAt(0));
    else throw new Error("The speech model returned an unsupported audio response.");
    if(!bytes.length)throw new Error("The speech model returned an empty audio segment.");
    audioParts.push(bytes);
  }
  return {audio:concatAudio(audioParts),chunks:chunks.length};
}
function getPublicVoices(){return {default:DEFAULT_VOICE,total:PUBLIC_VOICES.length,voices:PUBLIC_VOICES};}

export default {
  async fetch(request,env) {
    const origin=request.headers.get("Origin")||"";
    const cors=corsHeaders(origin,env);
    if(request.method==="OPTIONS")return new Response(null,{status:204,headers:cors});
    const url=new URL(request.url);
    const path=url.pathname.replace(/\/+$/,"")||"/";

    if(path==="/api/health"&&request.method==="GET")
      return json({status:"ok",service:"VozKovo API",enabled:env.API_ENABLED==="true"},200,origin,env);

    if((path==="/vozes"||path==="/voices"||path==="/api/voices")&&request.method==="GET"){
      if(env.API_ENABLED!=="true")return fail("The VozKovo API is not public yet.",503,origin,env);
      return json(getPublicVoices(),200,origin,env,{"Cache-Control":"public, max-age=300"});
    }

    if(env.API_ENABLED!=="true")return fail("The VozKovo API is not public yet.",503,origin,env);

    if(path==="/api/generate"&&request.method==="POST"){
      let body;
      try{body=await request.json();}catch{return fail("Invalid JSON body.",400,origin,env);}
      const text=String(body.text||"").trim();
      const voice=VOICES.find(item=>item.id===body.voice);
      if(!text)return fail("Escribe un texto antes de generar audio.",400,origin,env);
      if(text.length>MAX_TEXT_LENGTH)return fail("El máximo actual es de 10.000 caracteres.",413,origin,env);
      if(!voice)return fail("La voz seleccionada no existe. Actualiza el catálogo.",400,origin,env);
      const id=crypto.randomUUID();
      await env.JOBS.put(id,JSON.stringify({status:"processing",progress:5,completed_chunks:0,total_chunks:1,created_at:Date.now()}),{expirationTtl:JOB_TTL});
      try{
        const {audio,chunks}=await synthesize(env,text,voice);
        await env.AUDIO.put(id,audio,{httpMetadata:{contentType:"audio/mpeg"},customMetadata:{voice:voice.id,createdAt:new Date().toISOString()}});
        await env.JOBS.put(id,JSON.stringify({status:"done",progress:100,completed_chunks:chunks,total_chunks:chunks}),{expirationTtl:JOB_TTL});
        return json({job_id:id,status:"done",chunks},202,origin,env);
      }catch(error){
        const message=error?.message||"Audio generation failed.";
        await env.JOBS.put(id,JSON.stringify({status:"error",progress:0,error:message}),{expirationTtl:JOB_TTL});
        return fail(message,502,origin,env);
      }
    }

    const job=path.match(/^\/api\/jobs\/([a-f0-9-]+)$/i);
    if(job&&request.method==="GET"){
      const value=await env.JOBS.get(job[1]);
      if(!value)return fail("La tarea no existe o ha caducado.",404,origin,env);
      return json(JSON.parse(value),200,origin,env,{"Cache-Control":"no-store"});
    }

    const download=path.match(/^\/api\/jobs\/([a-f0-9-]+)\/download$/i);
    if(download&&request.method==="GET"){
      const object=await env.AUDIO.get(download[1]);
      if(!object)return fail("El MP3 no está disponible o ha caducado.",404,origin,env);
      return new Response(object.body,{headers:{
        ...cors,
        "Content-Type":"audio/mpeg",
        "Content-Disposition":'attachment; filename="vozkovo.mp3"',
        "Cache-Control":"no-store"
      }});
    }
    return fail("Not found.",404,origin,env);
  }
};

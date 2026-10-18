export const DEMO_LIMITS=Object.freeze({maxFileBytes:50_000_000,maxProjectBytes:100_000_000,maxProjectFiles:10});
const MIB=1024*1024;
const textPolicy=(appId,extensions,kind='text')=>Object.freeze({appId,extensions:Object.freeze(extensions),kind,
 maxFileBytes:2*MIB,maxDecodedBytes:4*MIB,qualified:true});
const policies={wordcraft:textPolicy('wordcraft',['.txt']),gridcraft:textPolicy('gridcraft',['.csv','.tsv'],'csv'),
 deckcraft:textPolicy('deckcraft',['.txt','.md'],'outline')};
const light=textPolicy('wordcraft-light',['.txt','.md','.html','.htm'],'light');
const reasons={
 pdfcraft:'PDF streams and embedded objects do not yet have a qualified demo decode budget.',
 filmcraft:'Video decoding and project media do not yet have a qualified demo memory budget.',
 soundcraft:'Audio decoding and resampling do not yet have a qualified demo memory budget.',
 lightcraft:'RAW image expansion does not yet have a qualified demo memory budget.',
 photocraft:'Image pixels and compressed metadata do not yet have a qualified demo decode budget.',
 vectorcraft:'Vector resources and embedded images are not yet qualified for demo import.',
 figcraft:'Design resources and embedded images are not yet qualified for demo import.',
 deckcraft:'Presentation archives and media are not yet qualified for demo import.',
 effectcraft:'Composition structures and media are not yet qualified for demo import.',
 designcraft:'Document archives and embedded resources are not yet qualified for demo import.',
 cadcraft:'Drawing entities and geometry do not yet have a qualified demo memory budget.'
};
export function demoPolicy(appId,{light:useLight=false}={}){
 if(appId==='wordcraft'&&useLight)return light;
 return Object.hasOwn(policies,appId)?policies[appId]:Object.freeze({appId,extensions:Object.freeze([]),maxFileBytes:0,maxDecodedBytes:null,qualified:false,
  reason:Object.hasOwn(reasons,appId)?reasons[appId]:'This format is not yet qualified for demo import.'});
}

// Match the pinned GridCraft delimiter sniff, including quoted newlines,
// Unicode characters, the 64K sample and comma/semicolon/tab tie order.
function csvDelimiter(value){
 let best=',',bestMin=0,bestTotal=0;
 for(const delimiter of [',',';','\t']){
  const counts=[];let count=0,quoted=false,blank=true,sampled=0;
  for(const char of value){
   if(sampled++>=64*1024)break;
   if(!quoted&&char==='\n'){
    if(!blank)counts.push(count);count=0;blank=true;if(counts.length>=20)break;continue;
   }
   if(char!=='\r')blank=false;
   if(char==='"')quoted=!quoted;else if(!quoted&&char===delimiter)count++;
  }
  if(!blank)counts.push(count);
  const minimum=counts.length?Math.min(...counts):0,total=counts.reduce((sum,n)=>sum+n,0);
  if(minimum>0&&(minimum>bestMin||minimum===bestMin&&total>bestTotal)){best=delimiter;bestMin=minimum;bestTotal=total}
 }
 return best;
}
function validateCSV(value,name){
 const delimiter=/\.tsv$/i.test(name)?'\t':csvDelimiter(value);
 let phase='field',length=0,rows=1,columns=1,cells=1;
 for(let i=0;i<value.length;i++){
  const char=value[i];
  if(phase==='quoted'){
   if(char==='"'){if(value[i+1]==='"'){length++;i++}else phase='closed'}else length++;
  }else if(char===delimiter){length=0;columns++;cells++;phase='field'}
  else if(char==='\n'||char==='\r'){
   if(char==='\r'&&value[i+1]==='\n')i++;
   length=0;columns=1;rows++;cells++;phase='field';
  }else if(phase==='closed')throw Error('Malformed CSV: unexpected content after a quoted field.');
  else if(char==='"'){if(length)throw Error('Malformed CSV: quote inside an unquoted field.');phase='quoted'}
  else length++;
  if(length>4096||rows>2000||columns>100||cells>20_000)throw Error('CSV exceeds its field, row, column or cell limit.');
 }
 if(phase==='quoted')throw Error('Malformed CSV: an unfinished quoted field.');
}
async function validateFile(file,policy){
 const bytes=await file.arrayBuffer();
 if(!(bytes instanceof ArrayBuffer)||bytes.byteLength!==file.size)throw Error('The selected file changed during admission.');
 let value;try{value=new TextDecoder('utf-8',{fatal:true}).decode(bytes)}catch{throw Error('Demo text imports require valid UTF-8.');}
 if(!Number.isSafeInteger(policy.maxDecodedBytes)||value.length*2>policy.maxDecodedBytes)throw Error('The decoded text exceeds this format’s memory limit.');
 if(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(value))throw Error('Binary or control-character content is not supported by this text format.');
 if(value.length>500_000)throw Error('Demo text imports are limited to 500,000 UTF-16 units.');
 if(policy.kind==='csv')validateCSV(value,file.name);
 else if(['text','light','outline'].includes(policy.kind)){
  const lines=value.split(/\r\n|\r|\n/),limit=policy.kind==='outline'?100:10_000;
  if(lines.length>limit||lines.some(line=>line.length>100_000))throw Error('Text exceeds its line-count or line-length limit.');
  if(policy.kind==='outline'&&value.startsWith('PK'))throw Error('Presentation archives are not supported by this text import.');
  if(policy.kind==='light'&&/\.html?$/i.test(file.name)){
   let tags=0;for(const char of value)if(char==='<'&&++tags>10_000)throw Error('HTML exceeds its markup limit.');
  }
 }else throw Error('This format is not yet qualified for demo import.');
}

export function validateDemoPaste(value,policy){
 if(typeof value!=='string'||value.length>500_000||/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(value))
  throw Error('Clipboard text exceeds the demo text limits or contains binary controls.');
 // Some engines reinterpret ordinary text as SVG or offer it as HTML/RTF in
 // Paste Special. Strip rich MIME flavors too; text/plain alone is not a guard.
 if(policy.kind!=='light'&&/(?:<[!?/]?[a-z]|\{\\rtf|\bdata:)/i.test(value))
  throw Error('Rich clipboard imports are not qualified in this demo. Use plain text or a supported local file.');
 const lines=value.split(/\r\n|\r|\n/),limit=policy.kind==='outline'?100:10_000;
 if(lines.length>limit||lines.some(line=>line.length>100_000))throw Error('Clipboard text exceeds the demo line limits.');
 // Grid's clipboard parser is TSV with quoted fields, never CSV auto-sniff.
 if(policy.kind==='csv')validateCSV(value,'clipboard.tsv');
 return value;
}

export function createDemoBudget(){
 let files=0,bytes=0,pending=0;
 return {
  get usage(){return Object.freeze({files,bytes})},
  async admit(selection,policy){
   if(!Array.isArray(selection)||!selection.length)throw Error('Choose at least one local file.');
   if(!policy?.qualified)throw Error('Import is not yet qualified for this demo. '+(policy?.reason??''));
   if(files+selection.length>DEMO_LIMITS.maxProjectFiles)throw Error('Each demo project is limited to 10 files. Finish and clear to start a new project.');
   let size=0;
   for(const file of selection){
    if(!file||!Number.isSafeInteger(file.size)||file.size<0||typeof file.arrayBuffer!=='function'||
     typeof file.name!=='string'||file.name.length>180||/[\x00-\x1f\x7f/\\]/.test(file.name))throw Error('Invalid local file metadata.');
    if(file.size>DEMO_LIMITS.maxFileBytes)throw Error('Each demo file is limited to 50 MB.');
    if(file.size>policy.maxFileBytes)throw Error('This format is limited to '+(policy.maxFileBytes/MIB)+' MiB.');
    if(!policy.extensions.some(extension=>file.name.toLowerCase().endsWith(extension)))throw Error('This file format is not supported by the selected demo.');
    size+=file.size;
   }
   if(bytes+size>DEMO_LIMITS.maxProjectBytes)throw Error('Each demo project is limited to 100 MB. Finish and clear to start a new project.');
   // Reserve synchronously, before the first read. Failed content validation
   // still consumes the read budget; replacement never silently refunds it.
   files+=selection.length;bytes+=size;pending++;
   try{for(const file of selection)await validateFile(file,policy);return selection.slice()}
   finally{pending--}
  },
  // The owner calls this only after confirmed project cleanup, never on replace.
  resetAfterClear(){if(pending)throw Error('File admission is still pending.');files=0;bytes=0}
 };
}

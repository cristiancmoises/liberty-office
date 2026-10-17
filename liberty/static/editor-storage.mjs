import {msg,text} from './i18n.mjs';;
// All Artcraft editors share this origin. Clear every browser persistence API
// before allowing a different account to execute an upstream module.
export async function clearEditorIdentity(identity,{local,session,indexed,filesystem,caches,locks}){
 const clean=async()=>{
  const previous=local.getItem('liberty.identity'),opfs=local.getItem('liberty.opfs.identity');
  if(previous!==identity){
   local.clear();session.clear();
   if(indexed){
    if(!indexed.databases)throw Error(text(msg('Este navegador não permite limpar os bancos locais. Use um navegador atualizado.')));
    const databases=await indexed.databases();
    await Promise.all(databases.filter(d=>d.name).map(d=>new Promise((resolve,reject)=>{
     const request=indexed.deleteDatabase(d.name);request.onsuccess=resolve;
     request.onerror=()=>reject(Error(text(msg('Não foi possível limpar dados locais da conta anterior. Use outro perfil de navegador.'))));
     request.onblocked=()=>reject(Error(text(msg('Feche os editores da conta anterior ou use outro perfil de navegador.'))));
    })));
   }
   if(caches)for(const key of await caches.keys())await caches.delete(key);
  }
  // A separate marker handles OPFS becoming available after an earlier visit.
  if(filesystem?.getDirectory&&opfs!==identity){
   const root=await filesystem.getDirectory();
   for await(const name of root.keys())await root.removeEntry(name,{recursive:true});
  }
  if(filesystem?.getDirectory)local.setItem('liberty.opfs.identity',identity);
  local.setItem('liberty.identity',identity);
 };
 if(locks?.request)return locks.request('liberty.identity-cleanup',clean);
 return clean();
}

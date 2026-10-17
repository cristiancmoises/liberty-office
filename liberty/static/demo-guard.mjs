export function disableDemoImports(win,notify){
 const denied=()=>{notify('Na demonstração, use os exemplos ou digite no editor. A importação de arquivos está desativada.');throw new DOMException('Importação desativada na demonstração.','NotAllowedError')};
 win.showOpenFilePicker=async()=>denied();
 win.showDirectoryPicker=async()=>denied();
 const click=win.HTMLInputElement.prototype.click;
 win.HTMLInputElement.prototype.click=function(){if(this.type==='file'){notify('Importação de arquivos desativada na demonstração.');return}return click.call(this)};
 const picker=win.HTMLInputElement.prototype.showPicker;
 if(picker)win.HTMLInputElement.prototype.showPicker=function(){if(this.type==='file')return denied();return picker.call(this)};
 const block=event=>{if(event.type==='drop'||event.type==='dragover'||event.target?.type==='file'||event.clipboardData?.files?.length){event.preventDefault();event.stopImmediatePropagation();if(event.type!=='dragover')notify('Importação de arquivos desativada na demonstração.')}};
 for(const name of ['click','drop','dragover','paste'])win.addEventListener(name,block,true);
}

import test from 'node:test';
import assert from 'node:assert/strict';
import {languageFromURL, msg, text, setLanguage, bindText, languageURL} from '../liberty/static/i18n.mjs';

test('English is default and Portuguese is an explicit URL choice',()=>{
 assert.equal(languageFromURL('http://localhost/demo'),'en');
 assert.equal(languageFromURL('http://localhost/demo?lang=fr'),'en');
 assert.equal(languageFromURL('http://localhost/demo?lang=pt-BR'),'pt-BR');
 assert.equal(languageURL('http://localhost/demo?light=1#anchor','pt-BR'),'http://localhost/demo?light=1&lang=pt-BR#anchor');
});
test('language changes update only bound interface text, preserving document and form values',()=>{
 const button={textContent:'',isConnected:true},input={value:'Nome'},documentContent={textContent:'Nome'};
 setLanguage('en');
 bindText(button,msg('Salvar'));
 assert.equal(button.textContent,'Save');
 setLanguage('pt-BR');
 assert.equal(button.textContent,'Salvar');
 assert.equal(input.value,'Nome');
 assert.equal(documentContent.textContent,'Nome');
 setLanguage('en');
 assert.equal(button.textContent,'Save');
 assert.equal(text(msg('Olá, {0}.','Nome')),'Hello, Nome.');
});

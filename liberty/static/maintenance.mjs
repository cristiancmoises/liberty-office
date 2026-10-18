import {installLanguage,languageSelector,languageURL,onLanguageChange,getLanguage} from './i18n.mjs';

installLanguage(window);
document.querySelector('#language').append(languageSelector(document));
const demo=document.querySelector('#try-demo');
const update=()=>{demo.href=languageURL(new URL('/demo',location.origin).href,getLanguage())};
onLanguageChange(update);update();

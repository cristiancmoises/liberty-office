import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./tests/browser',timeout:1200000,globalTimeout:1500000,workers:1,retries:0,
 reporter:[['list'],['html',{open:'never'}]],use:{headless:true,trace:'off',screenshot:'off',video:'off',
 launchOptions:{args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']}}});

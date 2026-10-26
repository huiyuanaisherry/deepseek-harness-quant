const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {formatCell,formatPct,formatFactor,chartModel,errorMessage}=require('../ui_v2/assets/real-watchlist.js');

const PAGE_SRC=fs.readFileSync(path.join(__dirname,'../ui_v2/assets/real-watchlist.js'),'utf8');
const SIDEBAR_SRC=fs.readFileSync(path.join(__dirname,'../ui_v2/components/sidebar.js'),'utf8');

const IDS=['wl-eyebrow','wl-title','wl-refresh','wl-status','wl-retry','wl-source-label','wl-source-asof',
  'wl-main-card','wl-main-source','wl-main-note','wl-scope','wl-notes','wl-search','wl-list-meta','wl-list',
  'wl-detail-empty','wl-detail-body','wl-stock-title','wl-stock-meta','wl-adjust-none','wl-adjust-qfq',
  'wl-detail-status','wl-chart','wl-chart-caption','wl-bars-meta','wl-bars-body','wl-finance-meta',
  'wl-finance-body','wl-tech-meta','wl-tech-body','wl-tech-accept','wl-blockers','wl-verify'];

function node(id){
  return {id:id,textContent:'',className:'',hidden:false,value:'',children:[],attrs:{},_html:'',
    setAttribute:function(k,v){this.attrs[k]=v;},getAttribute:function(k){return this.attrs[k];},
    appendChild:function(el){this.children.push(el);},replaceChildren:function(){this.children=[];
      this.textContent='';},
    addEventListener:function(type,fn){this['on'+type]=fn;},
    set innerHTML(v){this._html=String(v);},get innerHTML(){return this._html;}};
}
function setup(resolver){
  const els={},calls=[];
  IDS.forEach(function(id){els[id]=node(id);});
  const context={
    document:{readyState:'complete',getElementById:function(id){return els[id]||null;},
      createElement:function(){return node(null);},addEventListener:function(){}},
    LW:{api:{get:function(url,opts){calls.push({url:url,opts:opts||{}});
      return Promise.resolve().then(function(){return resolver(url,opts||{});});}}},
    Promise:Promise,setTimeout:setTimeout,clearTimeout:clearTimeout,
    encodeURIComponent:encodeURIComponent,console:console
  };
  vm.runInNewContext(PAGE_SRC,context);
  return {els:els,calls:calls};
}
function flush(){return new Promise(function(resolve){setTimeout(resolve,0);});}
function deferred(){
  const d={};
  d.promise=new Promise(function(resolve,reject){d.resolve=resolve;d.reject=reject;});
  return d;
}
function ctx(patch){
  const base={ok:true,page:{title:'真实观察池',eyebrow:'WORKSPACE / REAL WATCHLIST'},
    main:{mode:'demo',label:'主系统：演示数据',note:'当前读取演示数据'},
    watchlist:{mode:'real_snapshot',label:'此页：真实历史快照 · 小样本观察池',asOf:'2026-10-23',
      scope:{symbols:2,bars:240,financeRows:4,latestDate:'2026-10-23'},
      verification:{status:'passed',passed:true,demoUnchanged:true},revision:'r1',
      strategyAcceptance:false,notes:['历史快照，非实时行情']}};
  return Object.assign(base,patch||{});
}
function stock(code,name,status,date){
  return {code:code,name:name,industry:'计算机',close_unadjusted:status==='ok'?25.5:null,
    pct_chg:status==='ok'?1.23:null,latest_date:date===undefined?'2026-10-23':date,
    history_count:status==='ok'?240:0,verification_status:status==='ok'?'passed':'failed',
    status:status,note:status==='ok'?null:'缺少行情'};
}
function listDto(revision,stocks){
  return {ok:true,revision:revision,source:{kind:'real_sample',label:'此页：真实历史快照 · 小样本观察池',
    asOf:'2026-10-23',mainMode:'demo',note:'小样本历史快照'},scope:{symbols:stocks.length,bars:240,
    financeRows:4,latestDate:'2026-10-23'},stocks:stocks};
}
function detailDto(code,adjust,revision,patch){
  const base={ok:true,revision:revision,source:{kind:'real_sample',label:'此页：真实历史快照 · 小样本观察池',
    asOf:'2026-10-23',mainMode:'demo',note:'小样本历史快照'},
    stock:{code:code,name:code==='000977.SZ'?'浪潮信息':'紫光股份',industry:'计算机',
      listDate:'1999-11-04',latestDate:'2026-10-23',historyCount:2,verificationStatus:'passed',
      status:'ok',note:null},
    adjust:{value:adjust,label:adjust==='qfq'?'前复权':'未复权'},
    bars:[{date:'2026-10-22',open:10,high:11,low:9.5,close:10.5,volume:1000,amount:2000,
      pct_chg:1.5,turn:2.1},{date:'2026-10-23',open:10.5,high:11.2,low:10.2,close:11,
      volume:1200,amount:2400,pct_chg:4.76,turn:2.2}],
    barsTotal:2,barsReturned:2,barsTruncated:false,units:{price:'元',volume:'股',amount:'元'},
    finance:{available:true,rows:[{end_date:'2026-06-30',ann_date:'2026-08-20',eps:0.5,roe:0.08,
      netprofit_yoy:12.3,or_yoy:8.1,grossprofit_margin:0.32,debt_to_assets:0.41,ocfps:0.6,
      revenue_ps:3.2}],rowCount:1,note:'原始财务指标，未经验证。'},
    technical:{available:true,status:'ready',factors:{ma20:10.5,rsi14:55.2,vol_ratio:1.1,is_st:0},
      fields:{ma20:{label:'MA20',unit:'price'},rsi14:{label:'RSI14',unit:'index'},
        vol_ratio:{label:'量比',unit:'ratio'},is_st:{label:'ST',unit:'bool'}},
      blockers:['样本天数不足 250 日'],strategyAcceptance:false,note:'仅展示样本已生成指标。'},
    verification:{status:'passed',repeatWriteReadback:true,suspensionEvidenceDays:0,
      missingDateCount:0,demoUnchanged:true}};
  return Object.assign(base,patch||{});
}
const okStock=stock('000938.SZ','紫光股份','ok');
const failStock=stock('000977.SZ','浪潮信息','fail',null);

test('blank and invalid values render 暂无 while zero stays a real number',function(){
  for(const value of [null,undefined,'',NaN,Infinity]) assert.equal(formatCell(value),'暂无');
  assert.equal(formatCell(0),'0.00');
  assert.equal(formatCell(0,0),'0');
  assert.equal(formatCell('12.345'),'12.35');
  assert.equal(formatPct(null),'暂无');
  assert.equal(formatPct(0),'0.00%');
  assert.equal(formatPct(1.236),'+1.24%');
  assert.equal(formatPct(-1.236),'-1.24%');
});

test('factor units follow server metadata and missing values never become zero',function(){
  assert.equal(formatFactor(0.1234,'percent'),'12.34%');
  assert.equal(formatFactor(55.25,'index'),'55.25');
  assert.equal(formatFactor(0,'bool'),'否');
  assert.equal(formatFactor(1,'bool'),'是');
  assert.equal(formatFactor(1.5,'ratio'),'1.50');
  assert.equal(formatFactor(null,'percent'),'暂无');
  assert.equal(formatFactor(0.1,'percent'),'10.00%');
});

test('chart model splits gaps, keeps single point finite and ignores missing closes',function(){
  const gaps=chartModel([{date:'2026-10-20',close:10},{date:'2026-10-21',close:null},
    {date:'2026-10-22',close:12}]);
  assert.equal(gaps.paths.length,2);
  assert.equal(gaps.count,3);
  assert.equal(gaps.min,10);
  assert.equal(gaps.max,12);
  const single=chartModel([{date:'2026-10-22',close:7}]);
  assert.equal(single.paths.length,1);
  assert.ok(!single.paths[0].includes('NaN'));
  assert.ok(!JSON.stringify(single.volumes).includes('NaN'));
  assert.equal(chartModel([]).paths.length,0);
  assert.equal(chartModel([{date:'2026-10-22',close:NaN}]).paths.length,0);
});

test('error mapping is actionable and never leaks raw server text',function(){
  assert.match(errorMessage({status:409}),/稍后刷新/);
  assert.match(errorMessage({status:404}),/名单/);
  assert.match(errorMessage({status:400}),/未复权/);
  assert.match(errorMessage({status:503}),/暂不可用/);
  assert.match(errorMessage({message:'TIMEOUT'}),/超时/);
  const raw=errorMessage(new Error('HTTP 500 token=secret'));
  assert.match(raw,/网络/);
  assert.ok(!raw.includes('secret'));
});

test('successful load separates source labels, prefers verified stock and renders numeric chart',async function(){
  const calls=[];
  const harness=setup(function(url){
    calls.push(url);
    if(url==='/api/data-context') return ctx();
    if(url==='/api/real-watchlist') return listDto('r1',[failStock,okStock]);
    if(url.indexOf('/api/real-watchlist/stocks/000938.SZ')===0) return detailDto('000938.SZ','none','r1');
    throw new Error('unexpected '+url);
  });
  await flush();await flush();
  const e=harness.els;
  assert.equal(e['wl-source-label'].textContent,'此页：真实历史快照 · 小样本观察池');
  assert.equal(e['wl-main-source'].textContent,'主系统：演示数据');
  assert.equal(e['wl-main-card'].attrs['data-mode'],'demo');
  assert.match(e['wl-source-asof'].textContent,/2026-10-23/);
  assert.equal(e['wl-list'].children.length,2);
  const detail=calls.filter(function(url){return url.indexOf('/stocks/')>=0;});
  assert.equal(detail.length,1);
  assert.match(detail[0],/000938\.SZ/);
  assert.match(detail[0],/adjust=none/);
  assert.match(detail[0],/revision=r1/);
  assert.match(e['wl-stock-title'].textContent,/000938\.SZ/);
  assert.match(e['wl-detail-status'].textContent,/版本 r1/);
  assert.match(e['wl-chart'].innerHTML,/<svg/);
  assert.ok(!e['wl-chart'].innerHTML.includes('NaN'));
  assert.match(e['wl-chart-caption'].textContent,/2026-10-22 至 2026-10-23/);
  assert.equal(e['wl-bars-body'].children.length,2);
  assert.equal(e['wl-bars-body'].children[0].children[8].textContent,'2.10%');
  assert.match(e['wl-scope'].textContent,/2 只样本/);
  assert.match(e['wl-scope'].textContent,/240 条行情/);
  assert.equal(e['wl-finance-body'].children.length,1);
  assert.equal(e['wl-tech-body'].children.length,4);
  assert.match(e['wl-verify'].textContent,/演示库未变：是/);
  assert.equal(e['wl-detail-body'].hidden,false);
});

test('every watchlist request is strict, uncached detail and single attempt',async function(){
  const harness=setup(function(url){
    if(url==='/api/data-context') return ctx();
    if(url==='/api/real-watchlist') return listDto('r1',[okStock]);
    return detailDto('000938.SZ','none','r1');
  });
  await flush();await flush();
  for(const call of harness.calls){
    assert.equal(call.opts.strict,true,call.url);
    assert.equal(call.opts.retry,0,call.url);
  }
  const detail=harness.calls.find(function(call){return call.url.indexOf('/stocks/')>=0;});
  assert.equal(detail.opts.bypass,true);
  assert.equal(detail.opts.timeout,15000);
});

test('empty watchlist shows empty state without inventing a stock or detail request',async function(){
  const harness=setup(function(url){
    if(url==='/api/data-context') return ctx();
    return listDto('r1',[]);
  });
  await flush();await flush();
  const e=harness.els;
  assert.equal(e['wl-list'].children.length,1);
  assert.match(e['wl-list'].children[0].children[0].textContent,/暂无股票/);
  assert.match(e['wl-status'].textContent,/暂无可用股票/);
  assert.match(e['wl-detail-empty'].textContent,/暂无可用股票/);
  assert.equal(harness.calls.filter(function(c){return c.url.indexOf('/stocks/')>=0;}).length,0);
});

test('list failure clears data, marks the page source unavailable and offers retry',async function(){
  const harness=setup(function(url){
    if(url==='/api/data-context') return ctx();
    throw {status:503};
  });
  await flush();await flush();
  const e=harness.els;
  assert.equal(e['wl-source-label'].textContent,'此页：真实历史快照不可用');
  assert.match(e['wl-status'].textContent,/暂不可用/);
  assert.equal(e['wl-status'].className,'wl-status error');
  assert.equal(e['wl-retry'].hidden,false);
  assert.equal(e['wl-list'].children.length,1);
  assert.equal(e['wl-main-source'].textContent,'主系统：演示数据');
});

test('partial success reports failed samples and never claims full verification',async function(){
  const harness=setup(function(url){
    if(url==='/api/data-context') return ctx();
    if(url==='/api/real-watchlist') return listDto('r1',[okStock,failStock]);
    return detailDto('000938.SZ','none','r1');
  });
  await flush();await flush();
  const status=harness.els['wl-status'].textContent;
  assert.match(status,/2 只样本/);
  assert.match(status,/1 只校验通过/);
  assert.match(status,/1 只未通过或缺少行情/);
  assert.match(status,/不可用于策略/);
  assert.equal(harness.els['wl-status'].className,'wl-status warn');
});

test('unauthorized list rejection renders no stocks and no old content',async function(){
  const harness=setup(function(url){
    if(url==='/api/data-context') return ctx();
    throw {status:401};
  });
  await flush();await flush();
  const e=harness.els;
  assert.equal(e['wl-list'].children.length,1);
  assert.match(e['wl-list'].children[0].children[0].textContent,/暂无股票/);
  assert.equal(e['wl-retry'].hidden,false);
  assert.equal(e['wl-detail-body'].hidden,true);
});

test('rapid stock switching keeps only the latest response',async function(){
  const pending={};
  const harness=setup(function(url){
    if(url==='/api/data-context') return ctx();
    if(url==='/api/real-watchlist') return listDto('r1',[okStock,stock('000977.SZ','浪潮信息','ok')]);
    if(url.indexOf('/stocks/000938.SZ')>=0){pending.a=deferred();return pending.a.promise;}
    if(url.indexOf('/stocks/000977.SZ')>=0){pending.b=deferred();return pending.b.promise;}
    throw new Error('unexpected '+url);
  });
  await flush();await flush();
  const buttons=harness.els['wl-list'].children;
  assert.equal(buttons.length,2);
  buttons[1].onclick();
  await flush();
  pending.a.resolve(detailDto('000938.SZ','none','r1'));
  await flush();
  assert.ok(!harness.els['wl-stock-title'].textContent.includes('000938.SZ'));
  pending.b.resolve(detailDto('000977.SZ','none','r1'));
  await flush();
  assert.match(harness.els['wl-stock-title'].textContent,/000977\.SZ/);
  assert.match(harness.els['wl-chart-caption'].textContent,/2026-10-23/);
});

test('adjust switching ignores a slower previous mode response',async function(){
  const pending={};
  const harness=setup(function(url){
    if(url==='/api/data-context') return ctx();
    if(url==='/api/real-watchlist') return listDto('r1',[okStock]);
    if(url.indexOf('adjust=none')>=0 && !pending.initial){
      pending.initial=deferred();return pending.initial.promise;
    }
    if(url.indexOf('adjust=none')>=0){pending.none=deferred();return pending.none.promise;}
    if(url.indexOf('adjust=qfq')>=0){pending.qfq=deferred();return pending.qfq.promise;}
    throw new Error('unexpected '+url);
  });
  await flush();await flush();
  pending.initial.resolve(detailDto('000938.SZ','none','r1'));
  await flush();
  harness.els['wl-adjust-qfq'].onclick();
  await flush();
  harness.els['wl-adjust-none'].onclick();
  await flush();
  pending.qfq.resolve(detailDto('000938.SZ','qfq','r1'));
  await flush();
  assert.equal(harness.els['wl-adjust-none'].className,'active');
  pending.none.resolve(detailDto('000938.SZ','none','r1'));
  await flush();
  assert.equal(harness.els['wl-adjust-none'].className,'active');
  assert.equal(harness.els['wl-adjust-qfq'].className,'');
  assert.match(harness.els['wl-chart-caption'].textContent,/未复权/);
});

test('zero values stay numeric while missing bars, finance and factors stay 暂无',async function(){
  const harness=setup(function(url){
    if(url==='/api/data-context') return ctx();
    if(url==='/api/real-watchlist') return listDto('r1',[okStock]);
    return detailDto('000938.SZ','none','r1',{
      bars:[{date:'2026-10-23',open:null,high:null,low:null,close:0,volume:0,amount:null,
        pct_chg:null,turn:null}],
      barsTotal:1,barsReturned:1,
      finance:{available:true,rows:[{end_date:'2026-06-30',ann_date:null,eps:0,roe:null,
        netprofit_yoy:null,or_yoy:null,grossprofit_margin:null,debt_to_assets:null,ocfps:null,
        revenue_ps:null}],rowCount:1,note:'原始财务指标，未经验证。'},
      technical:{available:true,status:'ready',factors:{is_st:0,rsi14:null},
        fields:{is_st:{label:'ST',unit:'bool'},rsi14:{label:'RSI14',unit:'index'}},
        blockers:[],strategyAcceptance:false,note:'仅展示样本已生成指标。'}});
  });
  await flush();await flush();
  const cells=harness.els['wl-bars-body'].children[0].children;
  assert.equal(cells[1].textContent,'暂无');
  assert.equal(cells[4].textContent,'0.00');
  assert.equal(cells[5].textContent,'0');
  assert.equal(cells[6].textContent,'暂无');
  assert.equal(cells[7].textContent,'暂无');
  assert.equal(cells[8].textContent,'暂无');
  const finance=harness.els['wl-finance-body'].children[0].children;
  assert.equal(finance[2].textContent,'0.00');
  assert.equal(finance[3].textContent,'暂无');
  assert.equal(finance[1].textContent,'暂无');
  const tech=harness.els['wl-tech-body'].children;
  assert.equal(tech[0].children[1].textContent,'否');
  assert.equal(tech[1].children[1].textContent,'暂无');
  assert.equal(harness.els['wl-blockers'].children.length,1);
  assert.match(harness.els['wl-blockers'].children[0].textContent,/暂无阻塞项/);
});

test('missing finance and technical data never fabricate rows and explain why',async function(){
  const harness=setup(function(url){
    if(url==='/api/data-context') return ctx();
    if(url==='/api/real-watchlist') return listDto('r1',[okStock]);
    return detailDto('000938.SZ','none','r1',{
      finance:{available:false,rows:[],rowCount:0,note:'供应商财务文件缺失或为空。'},
      technical:{available:false,status:'not_ready',factors:{},fields:{},blockers:[],
        strategyAcceptance:false,note:'技术指标尚未生成。'}});
  });
  await flush();await flush();
  const e=harness.els;
  assert.equal(e['wl-finance-body'].children.length,0);
  assert.match(e['wl-finance-meta'].textContent,/暂无/);
  assert.match(e['wl-finance-meta'].textContent,/缺失/);
  assert.equal(e['wl-tech-body'].children.length,0);
  assert.match(e['wl-tech-meta'].textContent,/尚未生成/);
});

test('revision conflict reloads the list once instead of showing a stale snapshot',async function(){
  let lists=0,details=0;
  const harness=setup(function(url){
    if(url==='/api/data-context') return ctx();
    if(url==='/api/real-watchlist'){lists+=1;return listDto(lists===1?'r1':'r2',[okStock]);}
    details+=1;
    return detailDto('000938.SZ','none',details===1?'r2':'r2');
  });
  await flush();await flush();await flush();
  assert.equal(lists,2);
  assert.equal(details,2);
  assert.match(harness.els['wl-detail-status'].textContent,/版本 r2/);
});

test('repeated snapshot conflicts stop after one reload and ask the user to refresh',async function(){
  let lists=0;
  const harness=setup(function(url){
    if(url==='/api/data-context') return ctx();
    if(url==='/api/real-watchlist'){
      lists+=1;
      if(lists===1) return listDto('r1',[okStock]);
      throw {status:409};
    }
    return detailDto('000938.SZ','none','r2');
  });
  await flush();await flush();await flush();
  assert.equal(lists,2);
  assert.match(harness.els['wl-status'].textContent,/稍后刷新/);
  assert.equal(harness.els['wl-retry'].hidden,false);
});

test('detail 409 reloads list once and clears the old chart before retrying',async function(){
  let lists=0,details=0;
  const harness=setup(function(url){
    if(url==='/api/data-context') return ctx();
    if(url==='/api/real-watchlist'){lists+=1;return listDto(lists===1?'r1':'r2',[okStock]);}
    details+=1;
    if(details===1) throw {status:409};
    return detailDto('000938.SZ','none','r2');
  });
  await flush();await flush();await flush();
  assert.equal(lists,2);
  assert.equal(details,2);
  assert.match(harness.els['wl-detail-status'].textContent,/版本 r2/);
  assert.match(harness.els['wl-chart'].innerHTML,/<svg/);
});

test('automatic list success preserves the conflict budget until consistent detail succeeds',async function(){
  let lists=0,details=0;
  const harness=setup(function(url){
    if(url==='/api/data-context') return ctx();
    if(url==='/api/real-watchlist'){
      lists+=1;
      if(lists===1) throw {status:409};
      return listDto('r2',[okStock]);
    }
    details+=1;
    if(details===1) throw {status:409};
    return detailDto('000938.SZ','none','r2');
  });
  for(let i=0;i<8;i+=1) await flush();
  assert.equal(lists,2);
  assert.equal(details,1);
  assert.equal(harness.els['wl-chart'].innerHTML,'');
  assert.match(harness.els['wl-status'].textContent,/稍后刷新/);
  assert.equal(harness.els['wl-retry'].hidden,false);
});

test('data-context failure leaves successful list as source authority',async function(){
  const harness=setup(function(url){
    if(url==='/api/data-context') throw {status:500};
    return listDto('r1',[okStock]);
  });
  await flush();await flush();
  const e=harness.els;
  assert.equal(e['wl-main-source'].textContent,'主系统数据模式未知');
  assert.equal(e['wl-main-card'].attrs['data-mode'],'unknown');
  assert.equal(e['wl-source-label'].textContent,'此页：真实历史快照 · 小样本观察池');
  assert.match(e['wl-main-note'].textContent,/不默认为真实数据/);
  assert.equal(e['wl-source-label'].textContent.includes('演示'),false);
});

test('sidebar badge only shows the main-system source and never the page label',async function(){
  const registry={};
  function el(id){
    return {id:id,textContent:'',title:'',attrs:{},children:[],_html:'',style:{},
      set innerHTML(v){this._html=String(v);
        const re=/id="([^"]+)"/g;let m;
        while((m=re.exec(this._html))){if(!registry[m[1]]) registry[m[1]]=el(m[1]);}},
      get innerHTML(){return this._html;},
      setAttribute:function(k,v){this.attrs[k]=v;},querySelector:function(){return null;},
      appendChild:function(){},addEventListener:function(){},
      classList:{toggle:function(){return false;},add:function(){},remove:function(){}},
      getBoundingClientRect:function(){return {width:256};}};
  }
  registry.sidebar=el('sidebar');
  const context={
    window:{addEventListener:function(){},dispatchEvent:function(){}},
    document:{readyState:'complete',getElementById:function(id){return registry[id]||null;},
      querySelector:function(){return null;},createElement:function(){return el(null);},
      addEventListener:function(){},head:{appendChild:function(){}},
      body:{appendChild:function(){},classList:{toggle:function(){},contains:function(){return false;}},
        style:{}},documentElement:{style:{setProperty:function(){}}}},
    localStorage:{getItem:function(){return null;},setItem:function(){}},
    Event:function(){},console:console,setTimeout:setTimeout,clearTimeout:clearTimeout,
    LW:{api:{get:function(url){
      if(url==='/api/navigation') return Promise.resolve({items:[{id:'portal',label:'门户',url:'/'}],
        more:[{id:'real-watchlist',label:'真实观察池',url:'/real-watchlist'}]});
      if(url==='/api/data-context') return Promise.resolve(ctx());
      if(url==='/api/build_mode') return Promise.resolve({mode:'release'});
      return Promise.resolve({});
    }}}
  };
  context.window.LW=context.LW;
  vm.runInNewContext(SIDEBAR_SRC,context);
  context.LW.sidebar.render('sidebar',{active:'real-watchlist'});
  await flush();await flush();
  const mode=registry['sidebar-datamode'];
  assert.ok(mode,'sidebar datamode element missing');
  assert.match(registry.sidebar.innerHTML,/sb-datamode/);
  assert.equal(mode.textContent,'主系统：演示数据');
  assert.equal(mode.attrs['data-mode'],'demo');
  assert.equal(mode.textContent.includes('此页'),false);
  assert.match(mode.title,/演示数据/);
});

test('page markup states strategy is not accepted and never hardcodes sample symbols',function(){
  const html=fs.readFileSync(path.join(__dirname,'../ui_v2/pages/real-watchlist.html'),'utf8');
  const js=PAGE_SRC;
  const cfg=fs.readFileSync(path.join(__dirname,'../config/real_watchlist.json'),'utf8');
  assert.match(html,/策略验收：未验收/);
  assert.match(html,/不提供评分、胜率或排名/);
  assert.match(html,/historyCount|wl-bars-body/);
  const symbols=['000938','000977','000063','603019','601138','688041'];
  const names=['紫光股份','浪潮信息','中兴通讯','中科曙光','工业富联','海光信息'];
  for(const text of [html,js,cfg]){
    for(const symbol of symbols) assert.equal(text.includes(symbol),false,symbol+' should come from config only');
    for(const name of names) assert.equal(text.includes(name),false,name+' should come from config only');
  }
});


test('continuous detail 409 stops after one automatic list reload',async function(){
  let lists=0,details=0;
  const h=setup(url=>{
    if(url==='/api/data-context') return ctx();
    if(url==='/api/real-watchlist'){lists++;if(lists>4) return new Promise(()=>{});return listDto('r'+lists,[okStock]);}
    details++;throw {status:409};
  });
  for(let i=0;i<12;i++) await flush();
  assert.equal(lists,2);assert.equal(details,2);
  assert.match(h.els['wl-status'].textContent,/稍后刷新/);
  assert.equal(h.els['wl-retry'].hidden,false);
});

for(const removal of [false,true]) test('refresh invalidates pending detail before '+(removal?'selected stock removal':'empty list'),async function(){
  const old=deferred(),newList=deferred();let lists=0;
  const replacement=stock('000977.SZ','浪潮信息','ok');
  const h=setup(url=>{
    if(url==='/api/data-context') return ctx();
    if(url==='/api/real-watchlist') return ++lists===1?listDto('r1',[okStock]):newList.promise;
    if(url.includes('000938.SZ')) return old.promise;
    return detailDto(replacement.code,'none','r2');
  });
  await flush();await flush();h.els['wl-refresh'].onclick();await flush();
  assert.equal(h.els['wl-detail-body'].hidden,true);
  newList.resolve(listDto('r2',removal?[replacement]:[]));await flush();await flush();
  old.resolve(detailDto(okStock.code,'none','r1'));await flush();
  assert.ok(!h.els['wl-stock-title'].textContent.includes(okStock.code));
  if(removal) assert.match(h.els['wl-stock-title'].textContent,/000977/);
  else {assert.equal(h.els['wl-detail-body'].hidden,true);assert.equal(h.els['wl-chart'].innerHTML,'');}
});

test('late context cannot restore source or scope after list 503',async function(){
  const pending=deferred();
  const h=setup(url=>{if(url==='/api/data-context') return pending.promise;throw {status:503};});
  await flush();await flush();pending.resolve(ctx());await flush();
  assert.equal(h.els['wl-source-label'].textContent,'此页：真实历史快照不可用');
  assert.equal(h.els['wl-source-asof'].textContent,'实际截至日未知');
  assert.ok(!h.els['wl-scope'].textContent.includes('240'));
});

for(const failure of [false,true]) test('old context '+(failure?'failure':'success')+' cannot override refreshed context',async function(){
  const old=deferred();let contexts=0;
  const h=setup((url,opts)=>{
    if(url==='/api/data-context') return ++contexts===1?old.promise:ctx({main:{mode:'cache',label:'新主系统来源'}});
    if(url==='/api/real-watchlist') return listDto('r1',[okStock]);
    return detailDto(okStock.code,'none','r1');
  });
  await flush();await flush();h.els['wl-refresh'].onclick();await flush();await flush();
  if(failure) old.reject({status:503});else old.resolve(ctx());await flush();
  assert.equal(h.els['wl-main-source'].textContent,'新主系统来源');
  const contextCalls=h.calls.filter(c=>c.url==='/api/data-context');
  assert.equal(contextCalls[1].opts.bypass,true);
});

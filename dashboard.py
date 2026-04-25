# dashboard.py

dashboard_html = r'''
<!DOCTYPE html>
<html lang="pt-BR"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Tickmill Sniper Bot v11.0</title>
<style>
:root{
  --bg:#02040a;--bg2:#080c14;--bg3:#0d1320;--bg4:#151d2e;--bg5:#1e2840;
  --text:#cfe2f5;--text2:#8aaccf;--muted:#3d5f85;--muted2:#5577a0;
  --border:rgba(255,255,255,0.06);--border2:rgba(255,255,255,0.1);
  --green:#00e676;--green2:#00c853;--g3:rgba(0,230,118,.12);--g2:rgba(0,230,118,.22);
  --red:#ff3d71;--red2:#d50000;--r3:rgba(255,61,113,.12);--r2:rgba(255,61,113,.22);
  --blue:#448aff;--blue2:#2979ff;--b3:rgba(68,138,255,.12);--b2:rgba(68,138,255,.22);
  --cyan:#18ffff;--c3:rgba(24,255,255,.12);
  --gold:#ffd740;--y3:rgba(255,215,64,.10);
  --mono:'JetBrains Mono',monospace;--sans:'Inter',system-ui,-apple-system,sans-serif;
  --r:16px;--rsm:10px;--nav:68px;--safe:env(safe-area-inset-bottom,0px);--head:56px;--subhd:40px
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html,body{height:100%;overflow:hidden;background:var(--bg);color:var(--text);font-family:var(--sans);-webkit-font-smoothing:antialiased}
#app{display:flex;flex-direction:column;height:100%;max-width:480px;margin:0 auto}
.g{color:var(--green)}.r{color:var(--red)}.cy{color:var(--cyan)}.bl{color:var(--blue)}.go{color:var(--gold)}
#hdr{height:var(--head);flex-shrink:0;background:rgba(8,12,20,.97);backdrop-filter:blur(16px);border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;padding:0 16px;z-index:100}
.hdr-l{display:flex;align-items:center;gap:10px}
.logo{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,#e8002d,#002868);display:flex;align-items:center;justify-content:center;font-family:var(--mono);font-size:18px;font-weight:800;color:#fff;box-shadow:0 0 0 1px rgba(232,0,45,.35)}
.t1{font-size:15px;font-weight:700;letter-spacing:-.4px}.t2{font-size:10px;color:var(--muted2);letter-spacing:1.2px;text-transform:uppercase;margin-top:1px}
.hdr-r{display:flex;align-items:center;gap:8px}
.badge{display:flex;align-items:center;gap:4px;background:var(--g3);border:1px solid rgba(0,230,118,.2);border-radius:20px;padding:3px 8px;font-size:9px;color:var(--green);font-weight:600}
.dot{width:5px;height:5px;border-radius:50%;background:var(--green);animation:blink 2s ease-in-out infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
.ibtn{width:36px;height:36px;border-radius:10px;border:1px solid var(--border2);background:var(--bg3);display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:18px;color:var(--text2);transition:all .15s}
.ibtn:active{background:var(--bg4);transform:scale(.9)}
#subhdr{height:var(--subhd);flex-shrink:0;background:rgba(5,9,18,.95);border-bottom:1px solid var(--border);display:flex;align-items:stretch;z-index:99}
.shi{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;border-right:1px solid var(--border);padding:0 4px}
.shi:last-child{border-right:none}
.shl{font-size:8px;letter-spacing:.8px;text-transform:uppercase;color:var(--muted2);font-weight:600}
.shv{font-size:13px;font-weight:800;font-family:var(--mono);line-height:1.2}
#pages{flex:1;overflow:hidden;position:relative}
.pg{position:absolute;inset:0;display:none;overflow-y:auto;padding:14px 14px calc(var(--nav) + var(--safe) + 18px);opacity:0;transform:translateY(5px);transition:all .2s ease-out}
.pg.on{display:block;opacity:1;transform:translateY(0)}
.pg::-webkit-scrollbar{width:2px}.pg::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}
#nav{position:fixed;bottom:0;left:50%;transform:translateX(-50%);width:100%;max-width:480px;height:var(--nav);background:rgba(8,12,20,.97);backdrop-filter:blur(16px);border-top:1px solid var(--border2);display:flex;z-index:200;padding-bottom:var(--safe)}
.nb{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;border:none;background:none;cursor:pointer;font-size:10px;color:var(--muted2);letter-spacing:.4px;text-transform:uppercase;font-weight:500;position:relative;transition:all .2s}
.nb .ni{font-size:20px;transition:all .2s;opacity:.5}
.nb.on{color:var(--green)}.nb.on .ni{transform:scale(1.1);opacity:1;filter:drop-shadow(0 0 4px var(--green))}
.nb:active{opacity:.7}
.nbadge{position:absolute;top:3px;right:calc(50% - 18px);min-width:16px;height:16px;border-radius:8px;background:var(--red);color:#fff;font-size:9px;display:none;align-items:center;justify-content:center;font-family:var(--mono);font-weight:700;padding:0 3px;box-shadow:0 0 8px rgba(255,61,113,.5)}
.srow{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:12px}
.sb{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:12px 8px;text-align:center;transition:all .2s}
.sb:hover{background:var(--bg3);border-color:var(--border2)}
.sl{font-size:9px;letter-spacing:1px;text-transform:uppercase;color:var(--muted);margin-bottom:4px;font-weight:600}
.sv{font-size:20px;font-weight:800;font-family:var(--mono);line-height:1}
.ss{font-size:10px;color:var(--muted2);margin-top:3px}
.chd{font-size:11px;letter-spacing:1.2px;text-transform:uppercase;color:var(--muted2);margin-bottom:10px;display:flex;align-items:center;justify-content:space-between;font-weight:700}
.ts{font-size:9px;color:var(--muted);font-weight:400;letter-spacing:0}
.empty{text-align:center;padding:30px 16px;color:var(--muted2)}
.empi{font-size:32px;margin-bottom:8px;display:block;opacity:.6}.empt{font-size:12px;line-height:1.6}
.risk-panel{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:12px}
.risk-head{font-size:10px;letter-spacing:1px;text-transform:uppercase;color:var(--muted2);font-weight:700;margin-bottom:10px}
.risk-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.risk-item{background:var(--bg3);border-radius:10px;padding:10px 12px;display:flex;align-items:center;justify-content:space-between;transition:all .2s}
.risk-item:hover{background:var(--bg4)}
.risk-lbl{font-size:10px;color:var(--muted2);font-weight:500}
.risk-val{font-size:13px;font-weight:800;font-family:var(--mono)}
.tcard{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:16px;margin-bottom:12px;position:relative;overflow:hidden;transition:all .3s}
.tcard.buy{border-left:3px solid var(--green)}.tcard.sell{border-left:3px solid var(--red)}
.tcard-head{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:12px}
.tsym{font-size:18px;font-weight:700;font-family:var(--mono)}.tname{font-size:11px;color:var(--muted2);margin-top:2px}
.tdir{font-size:11px;font-weight:700;padding:4px 10px;border-radius:16px;background:var(--g3);color:var(--green);border:1px solid rgba(0,230,118,.2)}
.tdir.sell{background:var(--r3);color:var(--red);border:1px solid rgba(255,61,113,.2)}
.tlvs{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:10px}
.tlv{background:var(--bg3);border-radius:var(--rsm);padding:10px;text-align:center;transition:all .2s}
.tlv:hover{background:var(--bg4)}
.tll{font-size:10px;letter-spacing:.6px;text-transform:uppercase;color:var(--muted);margin-bottom:4px;font-weight:600}
.tlvv{font-size:13px;font-weight:700;font-family:var(--mono)}
.pnl-row{display:flex;align-items:center;justify-content:space-between;background:rgba(0,0,0,.25);border-radius:10px;padding:10px 14px;margin:8px 0;border:1px solid rgba(255,255,255,.06)}
.pnl-label{font-size:10px;color:var(--muted2);font-weight:600;letter-spacing:.6px;text-transform:uppercase}
.pnl-val{font-size:20px;font-weight:800;font-family:var(--mono);line-height:1}
.pnl-val.g{color:var(--green);text-shadow:0 0 12px rgba(0,230,118,.35)}
.pnl-val.r{color:var(--red);text-shadow:0 0 12px rgba(255,61,113,.35)}
.pnl-sub{font-size:11px;font-family:var(--mono);font-weight:600;margin-top:2px;color:var(--muted2)}
.tprog{height:6px;background:var(--bg4);border-radius:3px;margin:8px 0 6px;overflow:hidden}
.tfill{height:100%;border-radius:3px;transition:width .4s}
.tdist{display:flex;justify-content:space-between;font-size:10px;color:var(--muted2)}
.tv-btn{width:100%;margin-top:12px;padding:11px;background:rgba(41,121,255,.1);border:1px solid rgba(41,121,255,.25);border-radius:10px;color:var(--blue);font-size:12px;font-weight:700;font-family:var(--sans);cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px;letter-spacing:.3px;transition:all .18s}
.tv-btn:hover{background:rgba(41,121,255,.2);transform:translateY(-1px)}
.tv-btn:active{background:rgba(41,121,255,.22);transform:scale(.97)}

.pcard{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:16px;margin-bottom:12px;position:relative;overflow:hidden;border-left:3px solid var(--gold);transition:all .3s}
.pcard-head{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:12px}
.psym{font-size:20px;font-weight:700;font-family:var(--mono);color:var(--gold)}.pname{font-size:11px;color:var(--muted2);margin-top:2px}
.pdir{font-size:11px;font-weight:700;padding:4px 10px;border-radius:16px;background:var(--g3);color:var(--green);border:1px solid rgba(0,230,118,.2)}
.pdir.sell{background:var(--r3);color:var(--red);border:1px solid rgba(255,61,113,.2)}
.pmeta{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:12px}
.pbox{background:var(--bg3);border-radius:var(--rsm);padding:10px;text-align:center;transition:all .2s}
.pbox:hover{background:var(--bg4)}
.pbl{font-size:9px;letter-spacing:.6px;text-transform:uppercase;color:var(--muted);margin-bottom:3px;font-weight:600}
.pbv{font-size:13px;font-weight:700;font-family:var(--mono)}
.amt-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:10px}
.amt-btn{padding:12px 4px;border-radius:10px;border:none;cursor:pointer;font-size:13px;font-weight:700;font-family:var(--mono);transition:all .15s;text-align:center;position:relative;overflow:hidden}
.amt-btn:hover{transform:translateY(-2px);filter:brightness(1.1)}
.amt-btn:active{transform:scale(.95)}
.amt-50{background:linear-gradient(135deg,#00796b,#26a69a);color:#e0f7f4}
.amt-100{background:linear-gradient(135deg,#1565c0,#1e88e5);color:#e3f2fd}
.amt-250{background:linear-gradient(135deg,#6a1b9a,#8e24aa);color:#f3e5f5}
.amt-500{background:linear-gradient(135deg,#e65100,#fb8c00);color:#fff3e0}
.amt-1000{background:linear-gradient(135deg,#c62828,#e53935);color:#ffebee}
.amt-custom{background:var(--bg4);border:1px solid var(--border2);color:var(--text2)}
.amt-input-wrap{display:flex;gap:8px;align-items:center;margin-top:10px}
.amt-input{flex:1;background:rgba(255,255,255,0.07);border:1px solid rgba(255,215,64,.4);border-radius:10px;padding:12px;color:var(--text);font-size:14px;font-family:var(--mono);outline:none}
.amt-input:focus{border-color:var(--gold)}
.amt-ok{background:linear-gradient(135deg,#4a148c,#7b1fa2);color:#f3e5f5;border:none;border-radius:10px;padding:12px 18px;font-weight:700;cursor:pointer;font-size:14px;white-space:nowrap}
.amt-ok:hover{filter:brightness(1.15)}
.amt-ok:active{transform:scale(.95)}
.preject{width:100%;padding:12px;border-radius:10px;border:1px solid rgba(255,61,113,.3);background:var(--r3);color:var(--red);font-size:13px;font-weight:700;cursor:pointer;margin-top:8px;transition:all .15s}
.preject:hover{background:rgba(255,61,113,.25)}
.preject:active{transform:scale(.97)}
.preview-box{background:rgba(0,230,118,.05);border:1px solid rgba(0,230,118,.15);border-radius:12px;padding:12px;margin-top:10px;display:none;animation:fadeIn .3s ease}
.preview-box.show{display:block}
@keyframes fadeIn{from{opacity:0;transform:translateY(-5px)}to{opacity:1;transform:translateY(0)}}
.prv-row{display:flex;justify-content:space-between;padding:4px 0;font-size:12px}
.prv-l{color:var(--muted2)}.prv-v{font-family:var(--mono);font-weight:700}

.hist-item{display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--border);transition:all .2s}
.hist-item:hover{background:var(--bg3);padding:10px 8px;border-radius:8px}
.hist-icon{width:28px;height:28px;border-radius:8px;display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:14px}
.hist-sym{font-size:13px;font-weight:600;font-family:var(--mono)}.hist-time{font-size:10px;color:var(--muted2);margin-top:2px}
.hist-pnl{font-size:14px;font-weight:700;font-family:var(--mono)}
.hist-usd{font-size:11px;font-family:var(--mono);font-weight:600;margin-top:2px}

.tgroup{margin-bottom:14px}
.tghd{font-size:11px;letter-spacing:1.2px;text-transform:uppercase;color:var(--muted2);margin-bottom:8px;font-weight:700;display:flex;align-items:center;gap:8px}
.titem{display:flex;align-items:center;justify-content:space-between;background:var(--bg2);border:1px solid var(--border);border-radius:var(--rsm);padding:12px 14px;margin-bottom:6px;transition:all .2s}
.titem:hover{background:var(--bg3);transform:translateX(2px)}
.titem.up{border-left:3px solid var(--green);background:linear-gradient(90deg,rgba(0,230,118,.04) 0%,var(--bg2) 60%)}
.titem.dn{border-left:3px solid var(--red);background:linear-gradient(90deg,rgba(255,61,113,.04) 0%,var(--bg2) 60%)}
.titem.neut{border-left:3px solid var(--muted)}
.tsym-scan{font-size:14px;font-weight:700;font-family:var(--mono)}.tname-scan{font-size:11px;color:var(--muted2);margin-top:1px}
.ttag{font-size:10px;font-weight:700;padding:3px 8px;border-radius:6px}
.ttag.up{background:var(--g3);color:var(--green)}.ttag.dn{background:var(--r3);color:var(--red)}.ttag.neut{background:var(--bg4);color:var(--muted2)}
.tscan-r{display:flex;flex-direction:column;align-items:flex-end;gap:2px}
.tprice{font-size:13px;font-weight:700;font-family:var(--mono)}
.tchg{font-size:11px;font-family:var(--mono);font-weight:600}

.ctcard{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:8px;position:relative;transition:all .3s}
.ctcard::before{content:'';position:absolute;top:0;left:0;width:3px;height:100%;background:var(--cyan)}
.ctcard:hover{background:var(--bg3)}
.ctsym{font-size:16px;font-weight:700;font-family:var(--mono)}
.ctdir{font-size:11px;font-weight:700;padding:4px 10px;border-radius:8px;background:var(--c3);color:var(--cyan);border:1px solid rgba(24,255,255,.2)}
.ctstat{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:10px}
.ctbox{background:var(--bg3);border-radius:8px;padding:10px;text-align:center}
.ctl{font-size:10px;color:var(--muted);margin-bottom:3px}.ctv{font-size:14px;font-weight:700;font-family:var(--mono)}
.ctbar{height:5px;background:var(--bg4);border-radius:3px;margin-bottom:10px;overflow:hidden}
.ctfill{height:100%;background:var(--cyan);transition:width .5s}
.ctrs{display:flex;flex-wrap:wrap;gap:4px}
.cttag{font-size:10px;background:var(--bg3);color:var(--text2);padding:3px 8px;border-radius:6px;border:1px solid var(--border2)}

.sig-card{border:1px solid var(--border);border-radius:10px;padding:12px;margin-bottom:8px;transition:all .2s}
.sig-card:hover{background:var(--bg3)}
.sig-tipo{font-size:10px;font-weight:700;padding:2px 8px;border-radius:6px;background:var(--bg3);letter-spacing:.5px;text-transform:uppercase}
.sig-ts{font-size:10px;color:var(--muted2)}
.sig-txt{font-size:12px;line-height:1.5;color:var(--text2);margin-top:6px}

.news-item{padding:12px 0;border-bottom:1px solid var(--border);display:flex;flex-direction:column;gap:4px}
.news-title{font-size:13px;color:var(--blue);text-decoration:none;line-height:1.4;font-weight:500}
.news-title:hover{text-decoration:underline}
.news-src{font-size:10px;color:var(--muted2);font-weight:600;letter-spacing:.5px;text-transform:uppercase}

.cfgsec{margin-bottom:18px}
.cfgl{font-size:10px;letter-spacing:1.2px;text-transform:uppercase;color:var(--muted2);margin-bottom:10px;font-weight:700}
.mdg{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}
.mdb{background:var(--bg3);border:1px solid var(--border2);border-radius:10px;padding:14px 8px;cursor:pointer;font-size:13px;color:var(--text2);text-align:center;transition:all .15s;line-height:1.4;font-weight:500}
.mdb:hover{background:var(--bg4);transform:translateY(-1px)}
.mdb:active{transform:scale(.97)}.mdb.on{background:var(--g3);border:1px solid rgba(0,230,118,.3);color:var(--green)}
.tfg{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
.tfb{background:var(--bg3);border:1px solid var(--border2);border-radius:10px;padding:12px 6px;cursor:pointer;font-size:12px;font-family:var(--mono);color:var(--text2);text-align:center;transition:all .15s}
.tfb:hover{background:var(--bg4)}
.tfb.on{background:var(--b3);border:1px solid rgba(68,138,255,.3);color:var(--blue)}
.tfb:active{transform:scale(.97)}
.tfd{font-size:15px;display:block;margin-bottom:2px;font-weight:700}.tfl{font-size:9px;color:var(--muted)}
.ab{width:100%;padding:14px;border-radius:12px;border:none;cursor:pointer;font-size:13px;font-weight:600;font-family:var(--sans);margin-bottom:10px;transition:all .15s}
.ab:hover{transform:translateY(-1px)}
.ab:active{transform:scale(.97)}.abd{background:var(--r3);color:var(--red);border:1px solid rgba(255,61,113,.2)}.abp{background:var(--g3);color:var(--green);border:1px solid rgba(0,230,118,.2)}.abn{background:var(--b3);color:var(--blue);border:1px solid rgba(68,138,255,.2)}
.pgrid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.pbox{background:var(--bg3);border:1px solid var(--border);border-radius:10px;padding:12px}
.plb{font-size:10px;color:var(--muted);margin-bottom:4px;font-weight:600}.pvl{font-size:15px;font-family:var(--mono);font-weight:700}

.perf-panel{display:flex;align-items:stretch;background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);overflow:hidden;margin-bottom:14px}
.perf-col{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:14px 6px;gap:4px;transition:all .2s}
.perf-col:hover{background:var(--bg3)}
.perf-div{width:1px;background:var(--border);flex-shrink:0}
.perf-period{font-size:9px;letter-spacing:1.2px;text-transform:uppercase;color:var(--muted2);font-weight:700}
.perf-pct{font-size:18px;font-weight:800;font-family:var(--mono);line-height:1}
.perf-usd{font-size:12px;font-weight:700;font-family:var(--mono);color:var(--muted2)}
.perf-wl{font-size:9px;color:var(--muted);font-weight:500;margin-top:2px}
.perf-pct.pos{color:var(--green)}.perf-pct.neg{color:var(--red)}.perf-pct.zero{color:var(--muted2)}

.lev-current-row{display:flex;align-items:center;gap:10px;margin-bottom:12px;background:var(--bg3);border:1px solid var(--border2);border-radius:12px;padding:12px 14px}
.lev-label{font-size:11px;color:var(--muted2);font-weight:600;text-transform:uppercase;letter-spacing:.8px}
.lev-val{font-size:22px;font-weight:800;font-family:var(--mono);color:var(--gold)}
.lev-presets{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-bottom:10px}
.levb{background:var(--bg3);border:1px solid var(--border2);border-radius:10px;padding:11px 4px;cursor:pointer;font-size:13px;font-family:var(--mono);color:var(--text2);font-weight:700;transition:all .15s;text-align:center}
.levb:hover{background:var(--bg4);transform:translateY(-1px)}
.levb:active{transform:scale(.94)}
.levb.on{background:rgba(255,215,64,.15);border-color:rgba(255,215,64,.45);color:var(--gold)}
.levb-ok{background:linear-gradient(135deg,#e65100,#fb8c00)!important;color:#fff3e0!important;border:none!important;padding:11px 18px!important}
.lev-custom-row{display:flex;gap:8px;align-items:center;margin-bottom:10px}
.lev-input{flex:1;background:rgba(255,255,255,0.06);border:1px solid var(--border2);border-radius:10px;padding:12px;color:var(--text);font-size:14px;font-family:var(--mono);outline:none}
.lev-input:focus{border-color:rgba(255,215,64,.5)}

.toast{position:fixed;bottom:calc(var(--nav) + var(--safe) + 10px);left:50%;transform:translateX(-50%) translateY(10px);background:var(--bg4);border:1px solid var(--border2);border-radius:12px;padding:10px 16px;display:flex;align-items:center;gap:10px;opacity:0;pointer-events:none;transition:all .25s;z-index:300;max-width:92%;box-shadow:0 4px 20px rgba(0,0,0,.5)}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0);pointer-events:auto}
.toast.t-success{border-color:rgba(0,230,118,.3);background:rgba(0,230,118,.09)}
.toast.t-error{border-color:rgba(255,61,113,.3);background:rgba(255,61,113,.09)}
.ticon{font-size:18px;flex-shrink:0}.ttxt{font-size:12px;font-weight:600}

@keyframes shimmer{0%{background-position:-200% 0}100%{background-position:200% 0}}
.skel{background:linear-gradient(90deg,var(--bg3) 25%,var(--bg4) 50%,var(--bg3) 75%);background-size:200% 100%;animation:shimmer 1.6s infinite;border-radius:var(--r)}
.skel-card{height:120px;margin-bottom:10px}
.eb{background:var(--r3);border:1px solid rgba(255,61,113,.2);border-radius:10px;padding:12px 14px;margin-bottom:10px;font-size:12px;color:var(--red);display:none;text-align:center}
.amt-btn:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
</head>
<body>
<div id="app">
<div id="hdr">
  <div class="hdr-l">
    <div class="logo">T</div>
    <div><div class="t1">Tickmill Sniper</div><div class="t2">MT5 • PRO v11.0</div></div>
  </div>
  <div class="hdr-r">
    <div class="badge">LIVE <span class="dot"></span></div>
    <button class="ibtn" id="refbtn" onclick="refreshAll()">↻</button>
  </div>
</div>
<div id="subhdr">
  <div class="shi"><div class="shl">Hoje</div><div class="shv" id="sh-dpnl">--</div></div>
  <div class="shi"><div class="shl">Win%</div><div class="shv" id="sh-wr">--%</div></div>
  <div class="shi"><div class="shl">Abertos</div><div class="shv bl" id="sh-open">0</div></div>
  <div class="shi"><div class="shl">Status</div><div class="shv" id="sh-status">●</div></div>
</div>
<div id="pages">
<div class="pg on" id="pg-dash">
  <div id="eb" class="eb">⚠ Erro de conexão. Verifique sua rede.</div>
  <div class="srow">
    <div class="sb"><div class="sl">Lucro Hoje</div><div class="sv" id="d-dpnl">--%</div><div class="ss" id="d-drec">0W / 0L</div></div>
    <div class="sb"><div class="sl">Win Rate</div><div class="sv" id="d-wr">--%</div><div class="ss" id="d-wlt">0W / 0L</div></div>
    <div class="sb"><div class="sl">Abertos</div><div class="sv" id="d-open">0</div><div class="ss" id="d-maxopen">de 3 max</div></div>
    <div class="sb"><div class="sl">Fechados</div><div class="sv" id="d-closed">0</div><div class="ss">Hoje</div></div>
  </div>
  <div class="risk-panel">
    <div class="risk-head">⚖ Gestão de Risco — Tickmill MT5</div>
    <div class="risk-grid">
      <div class="risk-item"><span class="risk-lbl">Saldo</span><span class="risk-val bl" id="r-balance">0</span></div>
      <div class="risk-item"><span class="risk-lbl">Equity</span><span class="risk-val" id="r-equity">0</span></div>
      <div class="risk-item"><span class="risk-lbl">Margem usada</span><span class="risk-val go" id="r-margin">0</span></div>
      <div class="risk-item"><span class="risk-lbl">Free margin</span><span class="risk-val bl" id="r-free">0</span></div>
      <div class="risk-item"><span class="risk-lbl">Margin level</span><span class="risk-val" id="r-level">0%</span></div>
      <div class="risk-item"><span class="risk-lbl">Alavancagem</span><span class="risk-val go" id="r-leverage">0x</span></div>
      <div class="risk-item"><span class="risk-lbl">Risco/trade</span><span class="risk-val go" id="r-risk">0%</span></div>
      <div class="risk-item"><span class="risk-lbl">Exposição</span><span class="risk-val bl" id="r-exposure">0%</span></div>
      <div class="risk-item"><span class="risk-lbl">CB Status</span><span class="risk-val" id="r-cb">OK</span></div>
      <div class="risk-item"><span class="risk-lbl">Seq. Perdas</span><span class="risk-val" id="r-losses">0 / 2</span></div>
      <div class="risk-item"><span class="risk-lbl">W / L Total</span><span class="risk-val" id="r-wl">--</span></div>
      <div class="risk-item"><span class="risk-lbl">Tipo Conta</span><span class="risk-val cy" id="r-actype">RAW</span></div>
      <div class="risk-item" style="grid-column:span 2"><span class="risk-lbl">Margin Call / Stop Out</span><span class="risk-val go" id="r-mcso">100% / 30%</span></div>
    </div>
  </div>
  <div class="chd">💼 Trades Ativos <span class="ts">Auto: 5s</span></div>
  <div id="d-trades"><div class="skel skel-card"></div></div>
  <div class="chd">📜 Histórico Hoje</div>
  <div id="d-closed-list"><div class="empty"><span class="empi">📂</span><div class="empt">Nenhuma operação finalizada.</div></div></div>
  <div class="chd" style="margin-top:4px">📊 Performance</div>
  <div class="perf-panel">
    <div class="perf-col"><div class="perf-period">Hoje</div><div class="perf-pct" id="perf-d-pct">--%</div><div class="perf-usd" id="perf-d-usd">$--</div><div class="perf-wl" id="perf-d-wl">--W / --L</div></div>
    <div class="perf-div"></div>
    <div class="perf-col"><div class="perf-period">Semana</div><div class="perf-pct" id="perf-w-pct">--%</div><div class="perf-usd" id="perf-w-usd">$--</div><div class="perf-wl" id="perf-w-wl">--W / --L</div></div>
    <div class="perf-div"></div>
    <div class="perf-col"><div class="perf-period">Mês</div><div class="perf-pct" id="perf-m-pct">--%</div><div class="perf-usd" id="perf-m-usd">$--</div><div class="perf-wl" id="perf-m-wl">--W / --L</div></div>
  </div>
</div>
<div class="pg" id="pg-pend">
  <div class="chd">⏳ Aprovação Rápida <span class="ts">Auto: 5s</span></div>
  <div id="pendingQueue"><div class="skel skel-card"></div></div>
</div>
<div class="pg" id="pg-scan">
  <div class="chd">📡 Tendências de Mercado</div>
  <div id="scan-list"><div class="skel skel-card"></div><div class="skel skel-card"></div></div>
</div>
<div class="pg" id="pg-sig">
  <div class="chd">🔔 Feed de Sinais</div>
  <div id="sig-list"><div class="skel skel-card"></div></div>
</div>
<div class="pg" id="pg-ct">
  <div class="chd">⚡ Oportunidades de Reversão</div>
  <div id="ct-list"><div class="skel skel-card"></div></div>
  <div class="chd" style="margin-top:16px">📰 Notícias & Sentimento</div>
  <div id="fg-card-wrap"></div>
  <div id="news-list"><div class="skel skel-card"></div></div>
</div>
<div class="pg" id="pg-cfg">
  <div class="cfgsec"><div class="cfgl">Mercado</div><div class="mdg">
    <div class="mdb" data-mode="FOREX" onclick="setMode('FOREX')">📈 FOREX</div>
    <div class="mdb" data-mode="CRYPTO" onclick="setMode('CRYPTO')">₿ CRIPTO</div>
    <div class="mdb" data-mode="COMMODITIES" onclick="setMode('COMMODITIES')">🏅 COMM.</div>
    <div class="mdb" data-mode="INDICES" onclick="setMode('INDICES')">📊 ÍNDICES</div>
    <div class="mdb" data-mode="TUDO" onclick="setMode('TUDO')" style="grid-column:span 2">🌐 TUDO</div>
  </div></div>
  <div class="cfgsec"><div class="cfgl">Timeframe</div><div class="tfg">
    <div class="tfb" data-tf="1m" onclick="setTf('1m')"><span class="tfd">1m</span><span class="tfl">Agressivo</span></div>
    <div class="tfb" data-tf="5m" onclick="setTf('5m')"><span class="tfd">5m</span><span class="tfl">Alto</span></div>
    <div class="tfb" data-tf="15m" onclick="setTf('15m')"><span class="tfd">15m</span><span class="tfl">Moderado</span></div>
    <div class="tfb" data-tf="30m" onclick="setTf('30m')"><span class="tfd">30m</span><span class="tfl">Conserv.</span></div>
    <div class="tfb" data-tf="1h" onclick="setTf('1h')"><span class="tfd">1h</span><span class="tfl">Seguro</span></div>
    <div class="tfb" data-tf="4h" onclick="setTf('4h')"><span class="tfd">4h</span><span class="tfl">Muito Seg.</span></div>
  </div></div>
  <div class="cfgsec"><div class="cfgl">Parâmetros de Risco</div><div class="pgrid">
    <div class="pbox"><div class="plb">SL Auto</div><div class="pvl" id="p-sl">--</div></div>
    <div class="pbox"><div class="plb">TP Auto</div><div class="pvl" id="p-tp">--</div></div>
    <div class="pbox"><div class="plb">Max Trades</div><div class="pvl" id="p-mt">--</div></div>
    <div class="pbox"><div class="plb">Confluência</div><div class="pvl" id="p-mc">--</div></div>
    <div class="pbox"><div class="plb">Comissão RT</div><div class="pvl cy" id="p-comm">--</div></div>
    <div class="pbox"><div class="plb">Lote Mínimo</div><div class="pvl" id="p-minlot">0.01</div></div>
  </div></div>
  <div class="cfgsec"><div class="cfgl">Saldo da Conta</div>
    <div class="pgrid">
      <div class="pbox"><div class="plb">Saldo atual</div><div class="pvl" id="p-bal">--</div></div>
      <div class="pbox"><div class="plb">Editar saldo</div><button class="ab abn" onclick="setBalance()">Alterar</button></div>
    </div>
  </div>
  <div class="cfgsec">
    <div class="cfgl">Alavancagem</div>
    <div class="lev-current-row">
      <span class="lev-label">Atual:</span>
      <span class="lev-val" id="p-lev">--</span>
      <span class="lev-max" id="p-lev-max"></span>
    </div>
    <div class="lev-presets" id="lev-presets">
      <button class="levb" data-lev="50"   onclick="setLeverage(50)">50x</button>
      <button class="levb" data-lev="100"  onclick="setLeverage(100)">100x</button>
      <button class="levb" data-lev="200"  onclick="setLeverage(200)">200x</button>
      <button class="levb" data-lev="300"  onclick="setLeverage(300)">300x</button>
      <button class="levb" data-lev="500"  onclick="setLeverage(500)">500x</button>
    </div>
    <div class="lev-custom-row">
      <input type="number" id="lev-input" min="1" max="1000" placeholder="Valor manual (1–1000)" class="lev-input" onkeydown="if(event.key==='Enter')submitLeverage()">
      <button class="levb levb-ok" onclick="submitLeverage()">✓ OK</button>
    </div>
    <div style="font-size:10px;color:var(--muted2);line-height:1.5;padding:8px 10px;background:rgba(255,215,64,.05);border:1px solid rgba(255,215,64,.15);border-radius:8px">
      ⚠ Alavancagem alta aumenta risco. A Tickmill aplica dynamic leverage — lotes maiores podem ter alavancagem reduzida automaticamente.
    </div>
  </div>
  <button class="ab abd" onclick="resetPausa()">⛔ Resetar Circuit Breaker</button>
  <button class="ab abn" onclick="requestNotif()">🔔 Ativar Notificações Push</button>
  <button class="ab abp" onclick="refreshAll()">↻ Atualizar App</button>
</div>
</div>
<div id="nav">
  <button class="nb on" onclick="goTo('dash',this)"><span class="ni">⬡</span>Dashboard</button>
  <button class="nb" onclick="goTo('pend',this)"><span class="ni">⏳</span>Pendentes<div class="nbadge" id="nbadge-pend">0</div></button>
  <button class="nb" onclick="goTo('scan',this)"><span class="ni">📡</span>Scanner</button>
  <button class="nb" onclick="goTo('sig',this)"><span class="ni">🔔</span>Sinais<div class="nbadge" id="nbadge-sig">0</div></button>
  <button class="nb" onclick="goTo('ct',this)"><span class="ni">⚡</span>CT/News</button>
  <button class="nb" onclick="goTo('cfg',this)"><span class="ni">⚙</span>Config</button>
</div>
</div>
<div class="toast" id="toast"><span class="ticon">🔔</span><span class="ttxt"></span></div>


<script>
let _st=null,_sigs=[],_unread=0,_lastSigLen=0,_pending=[];
function fp(p){
  if(p==null)return'--';
  if(p>=10000)return p.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
  if(p>=1000)return p.toFixed(2);
  if(p>=10)return p.toFixed(4);
  if(p>=1)return p.toFixed(5);
  return p.toFixed(6);
}
async function apiFetch(path,opts={}){
  const r=await fetch(path,{headers:{'Content-Type':'application/json'},mode:'same-origin',...opts});
  if(!r.ok)throw new Error(r.status);
  return r.json();
}
let _toastTimer=null;
function toast(msg,type=''){
  const t=document.getElementById('toast');
  const icon=t.querySelector('.ticon');
  const txt=t.querySelector('.ttxt');
  t.className='toast'+(type?' t-'+type:'');
  icon.textContent=type==='success'?'✅':type==='error'?'❌':type==='warning'?'⚠':type==='info'?'ℹ':'🔔';
  txt.textContent=msg;
  t.classList.add('show');
  if(_toastTimer)clearTimeout(_toastTimer);
  _toastTimer=setTimeout(()=>t.classList.remove('show'),3200);
}
function goTo(pg,btn){
  document.querySelectorAll('.pg').forEach(p=>{p.classList.remove('on');p.style.display='none';});
  document.querySelectorAll('.nb').forEach(b=>b.classList.remove('on'));
  const t=document.getElementById('pg-'+pg);
  if(t){t.classList.add('on');t.style.display='block';}
  btn.classList.add('on');
  if(pg==='pend')loadPending();
  if(pg==='scan')loadScanner();
  if(pg==='sig'){loadSigs();_unread=0;updBadge();}
  if(pg==='ct'){loadCT();loadNews();}
  if(pg==='cfg')loadCfg();
}
async function refreshAll(){
  const b=document.getElementById('refbtn');
  b.style.opacity='.4';b.style.pointerEvents='none';
  try{
    await loadDash();await loadPending();
    const a=document.querySelector('.pg.on');
    if(a){
      if(a.id==='pg-scan')await loadScanner();
      if(a.id==='pg-sig')await loadSigs();
      if(a.id==='pg-ct'){await loadCT();await loadNews();}
    }
    toast('Dados atualizados','success');
  }finally{b.style.opacity='1';b.style.pointerEvents='auto';}
}
function updSubHeader(st){
  if(!st)return;
  const dpnl=document.getElementById('sh-dpnl');
  const wr=document.getElementById('sh-wr');
  const op=document.getElementById('sh-open');
  const sts=document.getElementById('sh-status');
  dpnl.textContent=(st.daily_pnl>=0?'+':'')+st.daily_pnl+'%';
  dpnl.className='shv '+(st.daily_pnl>0?'g':st.daily_pnl<0?'r':'');
  wr.textContent=st.winrate+'%';
  wr.className='shv '+(st.winrate>=50?'g':st.winrate>0?'go':'r');
  op.textContent=st.active_trades.length;
  if(st.paused){sts.textContent='⛔CB';sts.className='shv r';}
  else if(st.consecutive_losses>=1){sts.textContent='⚠'+st.consecutive_losses+'L';sts.className='shv go';}
  else{sts.textContent='●OK';sts.className='shv g';}
}
function updRiskPanel(st){
  if(!st)return;
  document.getElementById('r-balance').textContent=fp(st.balance||0);
  const eqEl=document.getElementById('r-equity');
  if(eqEl){eqEl.textContent=fp(st.equity||st.balance||0); eqEl.className='risk-val '+((st.equity||0)>=(st.balance||0)?'g':'r');}
  const marEl=document.getElementById('r-margin');
  if(marEl){marEl.textContent=fp(st.used_margin||0); marEl.className='risk-val go';}
  const freeEl=document.getElementById('r-free');
  if(freeEl){freeEl.textContent=fp(st.free_margin||0); freeEl.className='risk-val '+((st.free_margin||0)>0?'bl':'r');}
  const lvlEl=document.getElementById('r-level');
  if(lvlEl){
    const ml=st.margin_level||0;
    lvlEl.textContent=ml.toFixed(1)+'%';
    lvlEl.className='risk-val '+(ml<=(st.stop_out_level||30)?'r':ml<=(st.margin_call_level||100)?'go':'g');
  }
  document.getElementById('r-leverage').textContent=(st.leverage||0)+'x';
  document.getElementById('r-risk').textContent=(st.risk_pct||0).toFixed(1)+'%';
  const exposure=Math.round((st.active_trades.length/3)*100);
  document.getElementById('r-exposure').textContent=exposure+'%';
  document.getElementById('r-exposure').className='risk-val '+(exposure>=80?'r':exposure>=50?'go':'bl');
  const cbEl=document.getElementById('r-cb');
  cbEl.textContent=st.paused?'⛔ ATIVO':'✅ OK';
  cbEl.className='risk-val '+(st.paused?'r':'g');
  document.getElementById('r-losses').textContent=st.consecutive_losses+' / 2';
  document.getElementById('r-losses').className='risk-val '+(st.consecutive_losses>=2?'r':st.consecutive_losses>=1?'go':'g');
  document.getElementById('r-wl').textContent=st.wins+'W / '+st.losses+'L';
  document.getElementById('r-wl').className='risk-val '+(st.winrate>=50?'g':'r');
  const actEl=document.getElementById('r-actype');
  if(actEl){actEl.textContent=st.account_type||'RAW'; actEl.className='risk-val cy';}
  const mcsoEl=document.getElementById('r-mcso');
  if(mcsoEl){mcsoEl.textContent=(st.margin_call_level||100)+'% / '+(st.stop_out_level||30)+'%';}
}
function updPerfPanel(st){
  if(!st)return;
  function fillCol(pctId,usdId,wlId,pct,usd,wins,losses){
    const pctEl=document.getElementById(pctId);
    const usdEl=document.getElementById(usdId);
    const wlEl=document.getElementById(wlId);
    if(!pctEl)return;
    const pos=pct>0,neg=pct<0;
    pctEl.textContent=(pos?'+':'')+pct.toFixed(2)+'%';
    pctEl.className='perf-pct '+(pos?'pos':neg?'neg':'zero');
    if(usdEl){
      const usdPos=usd>0,usdNeg=usd<0;
      usdEl.textContent=(usdPos?'+$':usdNeg?'−$':'$')+Math.abs(usd).toFixed(2);
      usdEl.className='perf-usd '+(usdPos?'pos':usdNeg?'neg':'');
    }
    if(wlEl) wlEl.textContent=wins+'W / '+losses+'L';
  }
  fillCol('perf-d-pct','perf-d-usd','perf-d-wl', st.daily_pnl||0, st.daily_pnl_usd||0, st.daily_wins||0, st.daily_losses||0);
  fillCol('perf-w-pct','perf-w-usd','perf-w-wl', st.weekly_pnl||0, st.weekly_pnl_usd||0, st.weekly_wins||0, st.weekly_losses||0);
  fillCol('perf-m-pct','perf-m-usd','perf-m-wl', st.monthly_pnl||0, st.monthly_pnl_usd||0, st.monthly_wins||0, st.monthly_losses||0);
}
async function loadDash(){
  try{
    _st=await apiFetch('/api/status');
    document.getElementById('eb').style.display='none';
    updSubHeader(_st);updRiskPanel(_st);updPerfPanel(_st);
    const dpnl=document.getElementById('d-dpnl');
    dpnl.textContent=(_st.daily_pnl>=0?'+':'')+_st.daily_pnl+'%';
    dpnl.className='sv '+(_st.daily_pnl>=0?'g':'r');
    document.getElementById('d-drec').textContent=_st.daily_wins+'W / '+_st.daily_losses+'L hoje';
    const wr=document.getElementById('d-wr');
    wr.textContent=_st.winrate+'%';
    wr.className='sv '+(_st.winrate>=50?'g':_st.winrate>0?'go':'r');
    document.getElementById('d-wlt').textContent=_st.wins+'W / '+_st.losses+'L total';
    document.getElementById('d-open').textContent=_st.active_trades.length;
    document.getElementById('d-closed').textContent=_st.today_closed;
    document.getElementById('d-trades').innerHTML=_st.active_trades.length
      ?_st.active_trades.map(renderOpenTrade).join('')
      :'<div class="empty"><span class="empi">📭</span><div class="empt">Nenhum trade aberto.</div></div>';
    document.getElementById('d-closed-list').innerHTML=_st.today_closed
      ?renderClosedToday(_st.history_today)
      :'<div class="empty"><span class="empi">📂</span><div class="empt">Nenhuma operação finalizada.</div></div>';
    updCfgBtns();
  }catch(e){document.getElementById('eb').style.display='block';}
}
function tvSymbol(sym){
  const map={
    'EURUSD':'FX:EURUSD','GBPUSD':'FX:GBPUSD','USDJPY':'FX:USDJPY','AUDUSD':'FX:AUDUSD',
    'USDCAD':'FX:USDCAD','USDCHF':'FX:USDCHF','NZDUSD':'FX:NZDUSD','EURGBP':'FX:EURGBP',
    'EURJPY':'FX:EURJPY','GBPJPY':'FX:GBPJPY',
    'BTCUSD':'BITSTAMP:BTCUSD','ETHUSD':'BITSTAMP:ETHUSD','SOLUSD':'COINBASE:SOLUSD',
    'BNBUSD':'BINANCE:BNBUSDT','XRPUSD':'BITSTAMP:XRPUSD','ADAUSD':'COINBASE:ADAUSD',
    'DOGEUSD':'BITSTAMP:DOGEUSD','LTCUSD':'BITSTAMP:LTCUSD',
    'XAUUSD':'TVC:GOLD','XAGUSD':'TVC:SILVER','XTIUSD':'TVC:USOIL',
    'BRENT':'TVC:UKOIL','NATGAS':'TVC:NATURALGAS','COPPER':'COMEX:HG1!',
    'US500':'SP:SPX','USTEC':'NASDAQ:NDX','US30':'DJ:DJI',
    'DE40':'XETR:DAX','UK100':'LSE:UKX','JP225':'TVC:NI225',
    'AUS200':'ASX:XJO','STOXX50':'TVC:SX5E',
  };
  return map[sym]||('FX:'+sym);
}
function openChart(sym){
  window.open('https://www.tradingview.com/chart/?symbol='+encodeURIComponent(tvSymbol(sym)),'_blank');
}
function renderOpenTrade(t){
  const buy=t.dir==='BUY',pos=t.pnl>=0;
  const cls=buy?'buy':'sell';
  const pnlUsd=t.pnl_money||0;
  const pnlUsdPos=pnlUsd>=0;
  const pnlUsdStr=(pnlUsdPos?'+$':'−$')+Math.abs(pnlUsd).toFixed(2);
  const capitalStr=t.capital_base>0?'$'+fp(t.capital_base):'--';
  const slPctStr=t.sl_pct!=null?t.sl_pct+'%':'--';
  const tpPctStr=t.tp_pct!=null?t.tp_pct+'%':'--';
  const openTime=t.opened_at||'';
  return`<div class="tcard ${cls}">
    <div class="tcard-head">
      <div style="cursor:pointer" onclick="openChart('${t.symbol}')" title="Abrir gráfico no TradingView">
        <div class="tsym">${t.symbol} <span style="font-size:10px;color:var(--muted2)">[MT5]</span></div>
        <div class="tname">${t.name||''}</div>
      </div>
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:5px">
        <div class="tdir ${buy?'':'sell'}">${buy?'▲ BUY':'▼ SELL'}</div>
        <span style="font-size:9px;color:var(--muted2)">${openTime}</span>
      </div>
    </div>
    <div class="pnl-row">
      <div>
        <div class="pnl-label">P&amp;L em tempo real</div>
        <div class="pnl-sub ${pnlUsdPos?'g':'r'}">${t.pnl>=0?'+':''}${t.pnl.toFixed(3)}%</div>
      </div>
      <div class="pnl-val ${pnlUsdPos?'g':'r'}">${pnlUsdStr}</div>
    </div>
    <div class="tlvs">
      <div class="tlv"><div class="tll">Entrada</div><div class="tlvv">${fp(t.entry)}</div></div>
      <div class="tlv"><div class="tll">Atual</div><div class="tlvv ${pos?'g':'r'}">${fp(t.current)}</div></div>
      <div class="tlv"><div class="tll">Margem</div><div class="tlvv go">${capitalStr}</div></div>
    </div>
    <div class="tlvs">
      <div class="tlv"><div class="tll">SL</div><div class="tlvv r">${fp(t.sl)} (${-slPctStr})</div></div>
      <div class="tlv"><div class="tll">TP</div><div class="tlvv g">${fp(t.tp)} (+${tpPctStr})</div></div>
      <div class="tlv"><div class="tll">Lote</div><div class="tlvv bl">${(t.lot||0).toFixed(2)}</div></div>
    </div>
    <div class="tprog"><div class="tfill" style="width:${t.progress}%;background:${pos?'var(--green)':'var(--red)'}"></div></div>
    <div class="tdist">
      <span>🛡 Dist. SL: <span class="${t.dist_sl<30?'near':'far'}">${t.dist_sl.toFixed(1)}%</span></span>
      <span>🎯 Dist. TP: <span class="${t.dist_tp<30?'near':'far'}">${t.dist_tp.toFixed(1)}%</span></span>
    </div>
    <button class="tv-btn" onclick="openChart('${t.symbol}')">▲ Ver no TradingView</button>
  </div>`;
}
function renderClosedToday(list){
  if(!list||!list.length)return'<div class="empty"><span class="empi">📂</span><div class="empt">Nenhuma operação finalizada.</div></div>';
  return list.map(h=>{
    const win=h.result==='WIN';
    const moneyVal=h.pnl_money!=null?parseFloat(h.pnl_money):null;
    const moneyCls=moneyVal!==null?(moneyVal>=0?'pos':'neg'):'';
    const moneyStr=moneyVal!==null?((moneyVal>=0?'+$':'−$')+Math.abs(moneyVal).toFixed(2)):'';
    return`<div class="hist-item">
      <div style="display:flex;align-items:center;gap:10px">
        <div class="hist-icon" style="background:${win?'var(--g3)':'var(--r3)'};color:${win?'var(--green)':'var(--red)'}">${win?'✅':'❌'}</div>
        <div>
          <div class="hist-sym">${h.symbol} <span style="font-size:10px;color:var(--muted2)">${h.dir||''}</span></div>
          <div class="hist-time">${h.closed_at}${h.lot?` · ${parseFloat(h.lot).toFixed(2)} lotes`:''}</div>
        </div>
      </div>
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:1px">
        <div class="hist-pnl ${win?'g':'r'}">${win?'+':''}${h.pnl.toFixed(2)}%</div>
        ${moneyStr?`<div class="hist-usd ${moneyCls}">${moneyStr}</div>`:''}
      </div>
    </div>`;
  }).join('');
}

async function loadPending(){
  try{const d=await apiFetch('/api/pending');renderPendingFromApi(d);}
  catch(e){console.log('pending err',e);}
}
function renderPendingFromApi(list){
  const el=document.getElementById('pendingQueue');if(!el)return;
  el.innerHTML=list.length?list.map(p=>{
    const buy=p.dir==='BUY';const cls=buy?'buy':'sell';const dirLabel=buy?'▲ BUY':'▼ SELL';
    const slPct=p.sl_pct||0;const tpPct=p.tp_pct||0;
    const minMargin = p.min_margin_for_min_lot || null;
    const minMarginStr = minMargin ? `$${minMargin.toFixed(2)}` : '--';
    const is50ok  = minMargin !== null && 50  >= minMargin;
    const is100ok = minMargin !== null && 100 >= minMargin;
    const is250ok = minMargin !== null && 250 >= minMargin;
    const is500ok = minMargin !== null && 500 >= minMargin;
    const is1000ok= minMargin !== null && 1000>= minMargin;
    const amtBtn = (val, label, ok) => {
      const clsBtn = ok ? `amt-btn amt-${val}` : `amt-btn amt-custom`;
      const disabled = ok ? '' : 'disabled';
      const click = ok ? `onclick="openPendingAmt(${p.pending_id},${val},this)"` : '';
      return `<button class="${clsBtn}" ${click} ${disabled} style="${ok ? '' : 'opacity:0.4; cursor:not-allowed'}">
        ${label}
      </button>`;
    };

    return`<div class="pcard" data-pid="${p.pending_id}">
      <div class="pcard-head">
        <div>
          <div class="psym">${p.symbol}</div>
          <div class="pname">${p.name||''} <span style="font-size:9px;color:var(--muted2)">[MT5]</span></div>
        </div>
        <div style="display:flex;flex-direction:column;align-items:flex-end;gap:5px">
          <div class="pdir ${cls}">${dirLabel}</div>
          <span style="font-size:9px;color:var(--muted2)">R: 1:${(tpPct/slPct).toFixed(1)}</span>
        </div>
      </div>
      <div class="pmeta">
        <div class="pbox"><div class="pbl">Entrada</div><div class="pbv">${fp(p.entry)}</div></div>
        <div class="pbox"><div class="pbl">SL</div><div class="pbv r">${fp(p.sl)} (${-slPct}%)</div></div>
        <div class="pbox"><div class="pbl">TP</div><div class="pbv g">${fp(p.tp)} (+${tpPct}%)</div></div>
      </div>
      <div style="font-size:11px;color:var(--muted2);margin-bottom:8px;text-align:center">
        💡 Clique no valor para ver o preview
      </div>
      <div class="amt-grid">
        ${amtBtn(50, '$50', is50ok)}
        ${amtBtn(100, '$100', is100ok)}
        ${amtBtn(250, '$250', is250ok)}
        ${amtBtn(500, '$500', is500ok)}
        ${amtBtn(1000, '$1000', is1000ok)}
        <button class="amt-btn amt-custom" onclick="toggleCustomAmt(${p.pending_id},this)">✏️ Custom</button>
      </div>
      <div class="amt-input-wrap" id="custom-wrap-${p.pending_id}" style="display:none">
        <input type="number" min="1" step="1" placeholder="Valor em USD (ex: 750)" class="amt-input" id="custom-inp-${p.pending_id}" oninput="previewTradePlan(${p.pending_id},'custom')" onkeydown="if(event.key==='Enter')submitCustomAmt(${p.pending_id})">
        <button class="amt-ok" onclick="submitCustomAmt(${p.pending_id})">✓ OK</button>
      </div>
      <div class="preview-box" id="preview-${p.pending_id}">
        <div class="prv-row"><span class="prv-l">Lote mínimo</span><span class="prv-v">0.01 (${minMarginStr})</span></div>
        <div class="prv-row"><span class="prv-l">Lote calculado</span><span class="prv-v" id="prv-lot-${p.pending_id}">--</span></div>
        <div class="prv-row"><span class="prv-l">Margem necessária</span><span class="prv-v" id="prv-margin-${p.pending_id}">--</span></div>
        <div class="prv-row"><span class="prv-l">Comissão RT</span><span class="prv-v" id="prv-comm-${p.pending_id}">--</span></div>
        <div class="prv-row"><span class="prv-l">Risco se SL</span><span class="prv-v r" id="prv-risk-${p.pending_id}">--</span></div>
        <div class="prv-row"><span class="prv-l">Potencial se TP</span><span class="prv-v g" id="prv-profit-${p.pending_id}">--</span></div>
      </div>
      <button class="preject" onclick="rejectPending(${p.pending_id},this)">❌ Recusar Sinal</button>
    </div>`;
  }).join('')
  :'<div class="empty"><span class="empi">✨</span><div class="empt">Nenhuma confirmação pendente</div></div>';
  _pending=list;updBadge();
}
  _pending=list;updBadge();
}
async function previewTradePlan(pid, src){
  let amount;
  if(src==='custom'){
    const inp=document.getElementById('custom-inp-'+pid);
    if(!inp)return;
    amount=parseFloat(inp.value);
    if(!Number.isFinite(amount)||amount<=0)return;
  } else {
    amount = src;
  }
  try{
    const plan=await apiFetch('/api/trade_plan',{method:'POST',body:JSON.stringify({symbol:_pending.find(p=>p.pending_id==pid).symbol, entry:_pending.find(p=>p.pending_id==pid).entry, amount})});
    if(plan.ok){
      document.getElementById('prv-lot-'+pid).textContent=plan.lot.toFixed(2);
      document.getElementById('prv-margin-'+pid).textContent='$'+plan.margin_required.toFixed(2);
      document.getElementById('prv-comm-'+pid).textContent='$'+plan.commission.toFixed(2);
      document.getElementById('prv-risk-'+pid).textContent='$'+plan.risk_money.toFixed(2)+' ('+plan.risk_pct_of_balance.toFixed(2)+'%)';
      document.getElementById('prv-profit-'+pid).textContent='$'+plan.potential_profit.toFixed(2);
      document.getElementById('preview-'+pid).classList.add('show');
    } else {
      document.getElementById('preview-'+pid).classList.remove('show');
      toast(plan.error,'error');
    }
  }catch(e){
    document.getElementById('preview-'+pid).classList.remove('show');
  }
}
async function openPendingAmt(id,amt,btn){
  btn.textContent='…';btn.disabled=true;
  try{
    await apiFetch('/api/execute_pending',{method:'POST',body:JSON.stringify({pending_id:id,amount:amt})});
    toast('✅ Trade aberto com $'+amt,'success');
    loadPending();loadDash();
  }catch(e){btn.textContent='$'+amt;btn.disabled=false;toast('Erro: '+e.message,'error');}
}
function toggleCustomAmt(id,btn){
  const wrap=document.getElementById('custom-wrap-'+id);
  if(!wrap)return;
  const show=wrap.style.display==='none';
  wrap.style.display=show?'flex':'none';
  if(show){document.getElementById('custom-inp-'+id).focus();previewTradePlan(id,'custom');}
}
async function submitCustomAmt(id){
  const inp=document.getElementById('custom-inp-'+id);
  if(!inp)return;
  const amt=parseFloat(inp.value);
  if(!Number.isFinite(amt)||amt<=0){inp.style.borderColor='var(--red)';toast('Valor inválido','error');return;}
  inp.disabled=true;
  try{
    await apiFetch('/api/execute_pending',{method:'POST',body:JSON.stringify({pending_id:id,amount:amt})});
    toast('✅ Trade aberto com $'+amt.toFixed(2),'success');
    loadPending();loadDash();
  }catch(e){inp.disabled=false;inp.style.borderColor='var(--red)';toast('Erro: '+e.message,'error');}
}
async function rejectPending(id,btn){
  btn.textContent='…';btn.disabled=true;
  try{await apiFetch('/api/reject',{method:'POST',body:JSON.stringify({pending_id:id})});toast('Trade recusado','error');loadPending();}
  catch(e){btn.textContent='❌ Recusar Sinal';btn.disabled=false;}
}

async function loadScanner(){
  try{
    const d=await apiFetch('/api/trends');
    const g={};
    d.forEach(x=>{const c=x.category||'OUTROS';(g[c]=g[c]||[]).push(x);});
    let h='';
    const lb={FOREX:'FOREX',CRYPTO:'CRIPTO',COMMODITIES:'COMMODITIES',INDICES:'ÍNDICES',OUTROS:'OUTROS'};
    const order=['FOREX','CRYPTO','COMMODITIES','INDICES'];
    for(const c of [...order,...Object.keys(g).filter(k=>!order.includes(k))]){
      if(!g[c])continue;
      const up=g[c].filter(x=>x.cenario==='ALTA').length;
      const dn=g[c].filter(x=>x.cenario==='BAIXA').length;
      h+=`<div class="tgroup"><div class="tghd">${lb[c]||c}<span style="font-size:9px;font-weight:400;margin-left:4px"><span style="color:var(--green)">${up}▲</span> <span style="color:var(--red)">${dn}▼</span></span></div>`;
      h+=g[c].map(x=>{
        const cls=x.cenario==='ALTA'?'up':x.cenario==='BAIXA'?'dn':'neut';
        const tag=x.cenario==='ALTA'?'▲ ALTA':x.cenario==='BAIXA'?'▼ BAIXA':'NEUTRO';
        const chgCls=x.change_pct>=0?'g':'r';
        return`<div class="titem ${cls}">
          <div><div class="tsym-scan">${x.symbol}</div><div class="tname-scan">${x.name}</div></div>
          <div style="display:flex;align-items:center;gap:8px">
            <span class="ttag ${cls}">${tag}</span>
            <div class="tscan-r">
              <span class="tprice">${fp(x.price)}</span>
              <span class="tchg ${chgCls}">${x.change_pct>=0?'+':''}${x.change_pct.toFixed(2)}%</span>
            </div>
          </div>
        </div>`;
      }).join('');
      h+='</div>';
    }
    document.getElementById('scan-list').innerHTML=h||'<div class="empty"><span class="empi">📡</span><div class="empt">Nenhum dado</div></div>';
  }catch(e){}
}
async function loadSigs(){
  try{
    const d=await apiFetch('/api/signals');
    if(d.length>_lastSigLen){_unread+=d.length-_lastSigLen;updBadge();toast((d.length-_lastSigLen)+' novo(s) sinal(is)','info');}
    _lastSigLen=d.length;_sigs=d;
    const bgMap={radar:'y3',gatilho:'b3',sinal:'b3',ct:'r3',close:'g3',cb:'r3',insuf:'bg4'};
    document.getElementById('sig-list').innerHTML=d.length?d.map(s=>{
      const bg=bgMap[s.tipo]||'bg4';
      return`<div class="sig-card" style="background:var(--${bg})">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <span class="sig-tipo">${s.tipo.toUpperCase()}</span>
          <span class="sig-ts">${s.ts}</span>
        </div>
        <div class="sig-txt">${s.texto}</div>
      </div>`;
    }).join('')
    :'<div class="empty"><span class="empi">🔔</span><div class="empt">Nenhum sinal ainda.</div></div>';
  }catch(e){}
}
async function loadCT(){
  try{
    const d=await apiFetch('/api/reversals');
    document.getElementById('ct-list').innerHTML=d.length?d.map(x=>{
      const pct=Math.min(x.strength,100);
      const rsiCls=x.rsi>70?'r':x.rsi<30?'g':'';
      return`<div class="ctcard">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
          <div><div class="ctsym">${x.symbol}</div><div style="font-size:11px;color:var(--muted2);margin-top:2px">${x.name||''}</div></div>
          <div class="ctdir">${x.direction}</div>
        </div>
        <div class="ctstat">
          <div class="ctbox"><div class="ctl">Força</div><div class="ctv cy">${x.strength}%</div></div>
          <div class="ctbox"><div class="ctl">RSI</div><div class="ctv ${rsiCls}">${x.rsi}</div></div>
        </div>
        <div class="ctbar"><div class="ctfill" style="width:${pct}%"></div></div>
        <div class="ctrs">${x.reasons.map(r=>`<span class="cttag">${r}</span>`).join('')}</div>
      </div>`;
    }).join('')
    :'<div class="empty"><span class="empi">⚡</span><div class="empt">Nenhuma CT detectada.</div></div>';
  }catch(e){}
}
async function loadNews(){
  try{
    const d=await apiFetch('/api/news');
    const fg=d.fg||{};
    const fgVal=parseInt(fg.value)||0;
    const fgColor=fgVal<=25?'var(--red)':fgVal<=45?'var(--gold)':fgVal<=55?'var(--text2)':fgVal<=75?'var(--green)':'var(--cyan)';
    const dashArr=Math.round(fgVal*1.759)+' 175.9';
    document.getElementById('fg-card-wrap').innerHTML=`<div style="background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:16px;margin-bottom:14px;display:flex;align-items:center;justify-content:space-between">
      <div style="display:flex;flex-direction:column;gap:5px">
        <div style="font-size:10px;letter-spacing:1px;text-transform:uppercase;color:var(--muted2);font-weight:600">Fear & Greed Index</div>
        <div style="font-size:36px;font-weight:900;font-family:var(--mono);line-height:1;color:${fgColor}">${fg.value||'N/D'}</div>
        <div style="font-size:13px;font-weight:700;color:${fgColor}">${fg.label||'--'}</div>
      </div>
      <svg width="64" height="64" viewBox="0 0 64 64">
        <circle cx="32" cy="32" r="28" fill="none" stroke="var(--bg4)" stroke-width="7"/>
        <circle cx="32" cy="32" r="28" fill="none" stroke="${fgColor}" stroke-width="7" stroke-dasharray="${dashArr}" stroke-linecap="round" style="transform:rotate(-90deg);transform-origin:50% 50%"/>
      </svg>
    </div>`;
    document.getElementById('news-list').innerHTML=d.articles&&d.articles.length
      ?d.articles.map(a=>`<div class="news-item">
          <a class="news-title" href="${a.url}" target="_blank">${a.title}</a>
          <span class="news-src">${a.source}</span>
        </div>`).join('')
      :'<div class="empty"><span class="empi">📰</span><div class="empt">Sem notícias disponíveis.</div></div>';
  }catch(e){}
}
async function loadCfg(){
  try{
    const c=await apiFetch('/api/config');
    document.getElementById('p-sl').textContent='-'+c.sl_auto+'%';
    document.getElementById('p-tp').textContent='+'+c.tp_auto+'%';
    document.getElementById('p-mt').textContent=c.max_trades;
    document.getElementById('p-mc').textContent=c.min_conf+'/7';
    const pbal=document.getElementById('p-bal'); if(pbal) pbal.textContent=fp(c.balance||0);
    const pcomm=document.getElementById('p-comm'); if(pcomm) pcomm.textContent='$'+c.commission_rt_forex+'/lote';
    const pml=document.getElementById('p-minlot'); if(pml) pml.textContent=c.min_lot||'0.01';
    const plev=document.getElementById('p-lev'); if(plev) plev.textContent=(c.leverage||0)+'x';
    const plevmax=document.getElementById('p-lev-max'); if(plevmax) plevmax.textContent='máx Tickmill';
    updLevBtns(c.leverage||0);
  }catch(_){}
  updCfgBtns();
}
function updLevBtns(cur){
  document.querySelectorAll('.levb[data-lev]').forEach(b=>{
    b.classList.toggle('on', parseInt(b.dataset.lev)===parseInt(cur));
  });
  const inp=document.getElementById('lev-input');
  if(inp) inp.value='';
}
async function setLeverage(val){
  try{
    await apiFetch('/api/leverage',{method:'POST',body:JSON.stringify({leverage:val})});
    const plev=document.getElementById('p-lev'); if(plev) plev.textContent=val+'x';
    updLevBtns(val);
    if(_st) _st.leverage=val;
    toast('Alavancagem: '+val+'x','success');
    await loadDash();
  }catch(e){toast('Erro: '+e.message,'error');}
}
async function submitLeverage(){
  const inp=document.getElementById('lev-input');
  if(!inp)return;
  const val=parseInt(inp.value);
  if(!Number.isFinite(val)||val<1||val>1000){
    inp.style.borderColor='var(--red)';
    toast('Alavancagem deve ser entre 1 e 1000','error');
    setTimeout(()=>inp.style.borderColor='',1500);
    return;
  }
  await setLeverage(val);
}
function updCfgBtns(){
  if(!_st)return;
  document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('on',b.dataset.mode===_st.mode));
  document.querySelectorAll('[data-tf]').forEach(b=>b.classList.toggle('on',b.dataset.tf===_st.timeframe));
}
async function setMode(m){
  try{await apiFetch('/api/mode',{method:'POST',body:JSON.stringify({mode:m})});await loadDash();toast('Modo: '+m,'success');}
  catch(e){toast('Erro: '+e.message,'error');}
}
async function setTf(t){
  try{await apiFetch('/api/timeframe',{method:'POST',body:JSON.stringify({timeframe:t})});await loadDash();toast('Timeframe: '+t,'success');}
  catch(e){toast('Erro: '+e.message,'error');}
}
async function setBalance(){
  const raw=prompt('Digite o novo saldo da conta em USD','500');
  if(raw===null)return;
  const balance=parseFloat(String(raw).replace(',','.'));
  if(!Number.isFinite(balance)||balance<=0){toast('Saldo inválido','error');return;}
  try{
    await apiFetch('/api/balance',{method:'POST',body:JSON.stringify({balance})});
    await loadDash();
    toast('Saldo atualizado','success');
  }catch(e){toast('Erro: '+e.message,'error');}
}
async function resetPausa(){
  if(!confirm('Resetar Circuit Breaker?'))return;
  try{await apiFetch('/api/resetpausa',{method:'POST'});toast('Circuit Breaker resetado','success');await loadDash();}
  catch(e){toast('Erro: '+e.message,'error');}
}
async function requestNotif(){
  if(!('serviceWorker' in navigator)||!('PushManager' in window)){toast('Navegador não suporta notificações','warning');return;}
  try{
    const perm=await Notification.requestPermission();
    if(perm!=='granted'){toast('Permissão negada','warning');return;}
    const reg=await navigator.serviceWorker.ready;
    const key=await apiFetch('/api/vapid-public-key').then(r=>r.key);
    const sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:key});
    await apiFetch('/api/subscribe',{method:'POST',body:JSON.stringify(sub)});
    toast('Notificações ativadas!','success');
  }catch(e){toast('Erro ao ativar: '+e.message,'error');}
}
function updBadge(){
  const pend=_pending?_pending.length:0;
  document.getElementById('nbadge-pend').textContent=pend>0?pend:'';
  document.getElementById('nbadge-pend').style.display=pend>0?'flex':'none';
  const sig=_unread>0?_unread:0;
  document.getElementById('nbadge-sig').textContent=sig>0?sig:'';
  document.getElementById('nbadge-sig').style.display=sig>0?'flex':'none';
}
window.addEventListener('load',()=>{
  loadDash();loadPending();
  setInterval(()=>{
    loadDash();
    const pg=document.querySelector('.pg.on');
    if(pg&&pg.id==='pg-pend')loadPending();
    if(pg&&pg.id==='pg-sig')loadSigs();
  },5000);
  if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});
});
</script>
</body>
</html>
'''

sw_js = """
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => clients.claim());
self.addEventListener('push', e => {
let data = {title: 'Sniper Bot', body: 'Novo sinal!', icon: '/icon-192.png'};
try { data = JSON.parse(e.data.text()); } catch(_) {}
e.waitUntil(self.registration.showNotification(data.title, {
body: data.body, icon: data.icon || '/icon-192.png',
badge: '/icon-192.png', vibrate: [200, 100, 200],
data: { url: '/' }
}));
});
self.addEventListener('notificationclick', e => {
e.notification.close();
e.waitUntil(clients.matchAll({type:'window'}).then(cs => {
if (cs.length) cs[0].focus();
else clients.openWindow('/');
}));
});
"""

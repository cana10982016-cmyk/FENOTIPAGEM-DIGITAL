"use strict";
/* INOVAAGRO Fenotipagem — site. Fala com a API em /api. */

const $ = id => document.getElementById(id);
const fmt = (x, d) => x == null || !isFinite(x) ? "–" : Number(x).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
let toastT; function toast(m) { const t = $("toast"); t.textContent = m; t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => t.hidden = true, 3000); }
const sleep = ms => new Promise(r => setTimeout(r, ms));

/* ---------------------------------------------------------------- API */
const API = {
  token: (() => { try { return localStorage.getItem("fd_token") || ""; } catch (_) { return ""; } })(),
  setToken(t) { this.token = t; try { t ? localStorage.setItem("fd_token", t) : localStorage.removeItem("fd_token"); } catch (_) { } },
  async req(method, url, body, raw) {
    const opt = { method, headers: {} };
    if (this.token) opt.headers.Authorization = "Bearer " + this.token;
    if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    const r = await fetch(url, opt);
    if (r.status === 401) { this.setToken(""); showLogin(); throw new Error("Sessão expirada."); }
    if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch (_) { } throw new Error(typeof m === "string" ? m : JSON.stringify(m)); }
    return raw ? r : r.json();
  },
  get(u) { return this.req("GET", u); }, post(u, b) { return this.req("POST", u, b ?? {}); },
  put(u, b) { return this.req("PUT", u, b); }, del(u) { return this.req("DELETE", u); },
};
async function download(url, name) {
  try {
    const r = await API.req("GET", url, undefined, true);
    const a = document.createElement("a"); a.href = URL.createObjectURL(await r.blob()); a.download = name;
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  } catch (e) { toast(e.message); }
}

/* ---------------------------------------------------------------- telas */
const VIEWS = ["vLogin", "vList", "vTeam", "vWork"];
function show(v) {
  VIEWS.forEach(x => $(x).hidden = x !== v);
  const inApp = v !== "vLogin";
  $("nav").hidden = $("topbar").hidden = !inApp; document.body.classList.toggle("shell", inApp);
  document.body.classList.remove("nav-open");
  $("navTrial").hidden = v !== "vWork";
  $("backList").setAttribute("aria-current", v === "vList" ? "page" : "false");
  $("teamBtn").setAttribute("aria-current", v === "vTeam" ? "page" : "false");
  if (v === "vList") crumb("Fenotipagem", "Ensaios");
  if (v === "vTeam") crumb("Fenotipagem", "Equipe");
  if (ME) {
    $("uName").textContent = ME.nome || ME.email; $("uPapel").textContent = ME.admin ? "Administrador" : "Técnico";
    $("uAv").textContent = (ME.nome || ME.email).split(/[\s@.]+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join("");
    $("teamBtn").hidden = !ME.admin;
  }
}
function crumb(g, t) { $("crumbGrp").textContent = g; $("crumbTitle").textContent = t; }
$("menuBtn").onclick = () => document.body.classList.toggle("nav-open");
$("navScrim").onclick = () => document.body.classList.remove("nav-open");
let ME = null;

function showLogin() { show("vLogin"); $("lEmail").focus(); }
$("loginForm").addEventListener("submit", async e => {
  e.preventDefault(); $("lErr").textContent = "";
  try { const r = await API.post("/api/auth/login", { email: $("lEmail").value, senha: $("lSenha").value }); API.setToken(r.token); ME = r.usuario; $("lSenha").value = ""; openList(); }
  catch (err) { $("lErr").textContent = err.message; }
});
$("logoutBtn").onclick = () => { API.setToken(""); ME = null; showLogin(); };

/* trocar senha */
$("pwBtn").onclick = () => { $("pwForm").reset(); $("pwErr").textContent = ""; $("pwDlg").showModal(); $("pwAtual").focus(); };
$("pwCancel").onclick = () => $("pwDlg").close();
$("pwForm").addEventListener("submit", async e => {
  e.preventDefault(); $("pwErr").textContent = "";
  if ($("pwNova").value !== $("pwConf").value) { $("pwErr").textContent = "As duas senhas novas não são iguais."; return; }
  try { await API.put("/api/auth/senha", { atual: $("pwAtual").value, nova: $("pwNova").value }); $("pwDlg").close(); toast("Senha trocada"); }
  catch (err) { $("pwErr").textContent = err.message; }
});

/* no site da nuvem não há envio de imagens nem processamento */
let ENVIO = true;
fetch("/api/saude").then(r => r.json()).then(h => {
  ENVIO = h.envio !== false;
  $("drop").hidden = !ENVIO; $("noUpload").hidden = ENVIO;
  if (!ENVIO) { $("runBtn").disabled = true; $("runBtn").title = "Processe pelo computador do servidor"; }
}).catch(() => { });

async function openList() {
  show("vList");
  const box = $("trialCards"); box.innerHTML = '<p class="hint">Carregando…</p>';
  try {
    const list = await API.get("/api/ensaios");
    box.innerHTML = list.length ? "" : '<div class="card"><b>Nenhum ensaio ainda.</b><p class="hint">Clique em Novo ensaio para começar.</p></div>';
    list.forEach(t => {
      const b = document.createElement("button"); b.className = "tcard";
      b.innerHTML = `<b>${esc(t.nome)}</b><span class="m">${esc([t.cliente, t.local, t.cultura].filter(Boolean).join(" · ") || "Sem detalhes")}</span>
        <span class="k">${t.tratamentos} tratamentos · ${t.voos} voo(s) · ${t.atualizado_em ? new Date(t.atualizado_em).toLocaleDateString("pt-BR") : ""}</span>`;
      b.onclick = () => openTrial(t.id); box.appendChild(b);
    });
  } catch (e) { box.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
}
$("newTrial").onclick = async () => {
  try {
    const t = await API.post("/api/ensaios", { nome: "Novo ensaio", tratamentos: [{ code: "1", sigla: "C", nome: "Controle", ctrl: true }, { code: "2", sigla: "", nome: "" }] });
    openTrial(t.id, "ensaio");
  } catch (e) { toast(e.message); }
};

/* equipe */
$("teamBtn").onclick = e => { e.preventDefault(); flushSave(); openTeam(); };
async function openTeam() {
  show("vTeam");
  const us = await API.get("/api/usuarios");
  $("teamBody").innerHTML = us.map(u => `<tr><td>${esc(u.nome)}</td><td>${esc(u.email)}</td><td>${u.admin ? "Administrador" : "Técnico"}${u.ativo ? "" : " (inativo)"}</td>
    <td>${u.ativo && u.id !== ME.id ? `<button class="btn" data-off="${u.id}">Desativar</button>` : ""}</td></tr>`).join("");
}
$("teamBody").addEventListener("click", async e => { const id = e.target.dataset.off; if (!id) return; await API.del("/api/usuarios/" + id); openTeam(); });
$("teamForm").addEventListener("submit", async e => {
  e.preventDefault(); $("nErr").textContent = "";
  try { await API.post("/api/usuarios", { nome: $("nNome").value, email: $("nEmail").value, senha: $("nSenha").value, admin: $("nAdmin").checked }); e.target.reset(); toast("Pessoa cadastrada"); openTeam(); }
  catch (err) { $("nErr").textContent = err.message; }
});

/* ---------------------------------------------------------------- índices */
const IDX = {
  CC: { l: "Cobertura vegetal (CC)", u: "%", d: 1, desc: "Porcentagem de pixels classificados como planta (ExG acima do limiar)." },
  ExG: { l: "Excesso de verde (ExG)", u: "", d: 3, desc: "2g − r − b, com r, g, b normalizados pela soma RGB. Woebbecke et al. (1995)." },
  ExGR: { l: "ExG − ExR", u: "", d: 3, desc: "ExG − (1,4r − g). Acima de zero indica vegetação. Meyer & Neto (2008)." },
  VARI: { l: "VARI", u: "", d: 3, desc: "(G − R) / (G + R − B). Gitelson et al. (2002)." },
  GLI: { l: "GLI", u: "", d: 3, desc: "(2G − R − B) / (2G + R + B). Louhaichi et al. (2001)." },
  NGRDI: { l: "NGRDI", u: "", d: 3, desc: "(G − R) / (G + R). Tucker (1979)." },
  MGRVI: { l: "MGRVI", u: "", d: 3, desc: "(G² − R²) / (G² + R²). Bendig et al. (2015)." },
  RGBVI: { l: "RGBVI", u: "", d: 3, desc: "(G² − B·R) / (G² + B·R). Bendig et al. (2015)." },
  ExGveg: { l: "ExG da planta", u: "", d: 3, desc: "ExG médio só dos pixels de planta: vigor do verde sem a influência do solo exposto." },
};
const IDXK = Object.keys(IDX);
$("idxSel").innerHTML = IDXK.map(k => `<option value="${k}">${IDX[k].l}</option>`).join("");
$("rIdx").innerHTML = $("idxSel").innerHTML;

/* ---------------------------------------------------------------- estado do ensaio */
const S = { trial: null, flights: [], bmp: {}, cur: null, step: "mapa", view: { s: 1, tx: 0, ty: 0 }, pick: null, masks: {} };
const curFlight = () => S.flights.find(f => f.id === S.cur) || null;
const readyFlights = () => S.flights.filter(f => f.previa_w && S.bmp[f.id]);
const C = () => S.trial.croqui;

async function openTrial(id, step) {
  show("vWork"); S.bmp = {}; S.masks = {}; S.cur = null;
  try { S.trial = await API.get("/api/ensaios/" + id); } catch (e) { toast(e.message); openList(); return; }
  const c = S.trial.croqui;
  S.trial.croqui = Object.assign({ kind: null, corners: null, rows: 4, cols: 6, margin: 8, gx: 3, gy: 2, cells: [] }, c || {});
  S.trial.ajustes = Object.assign({ thr_mode: "otsu", thr_value: 0.05 }, S.trial.ajustes || {});
  S.flights = S.trial.voos; fillTrial(); fillCroq(); renderFlights(); renderDateRadios();
  $("thrMode").value = S.trial.ajustes.thr_mode; $("thrVal").value = S.trial.ajustes.thr_value; $("thrFixedF").hidden = S.trial.ajustes.thr_mode !== "fixed";
  $("saved").textContent = "";
  go(step || (S.flights.length ? "mapa" : "ensaio"));
  await loadPreviews(); pollIfBusy();
}
$("backList").onclick = e => { e.preventDefault(); flushSave(); openList(); };

async function loadPreviews() {
  for (const f of S.flights) {
    if (!f.previa_w || S.bmp[f.id]) continue;
    try {
      const r = await API.req("GET", `/api/voos/${f.id}/previa.png`, undefined, true);
      S.bmp[f.id] = await createImageBitmap(await r.blob());
      if (!S.cur) { S.cur = f.id; fitView(); }
    } catch (e) { console.warn(e); }
  }
  if (!S.cur && readyFlights().length) S.cur = readyFlights()[0].id;
  renderFlights(); renderDateRadios(); draw();
}
async function refreshTrial() {
  const t = await API.get("/api/ensaios/" + S.trial.id);
  S.flights = t.voos; S.trial.voos = t.voos; await loadPreviews(); markDone();
}
let polling = false;
async function pollIfBusy() {
  if (polling) return; polling = true;
  try {
    while (S.trial && S.flights.some(f => f.status === "preparando" || f.status === "calculando")) {
      await sleep(2500); if (!S.trial) break; await refreshTrial(); runStatusFromFlights();
    }
  } finally { polling = false; }
  runStatusFromFlights(); if (S.step === "resultados") renderResults();
}

/* salvar automático */
let saveT = null, dirty = false;
function save() { dirty = true; $("saved").textContent = "Salvando…"; clearTimeout(saveT); saveT = setTimeout(flushSave, 700); }
async function flushSave() {
  if (!dirty || !S.trial) return; dirty = false; clearTimeout(saveT);
  const t = S.trial;
  try {
    await API.put("/api/ensaios/" + t.id, { nome: t.nome, cliente: t.cliente, local: t.local, cultura: t.cultura, variedade: t.variedade, observacoes: t.observacoes, tratamentos: t.tratamentos, croqui: t.croqui, ajustes: t.ajustes });
    $("saved").textContent = "Salvo";
  } catch (e) { $("saved").textContent = "Não salvou"; toast(e.message); }
}
window.addEventListener("beforeunload", () => { if (dirty) flushSave(); });

/* ---------------------------------------------------------------- navegação */
function go(step) {
  S.step = step;
  document.querySelectorAll("#steps a").forEach(b => b.setAttribute("aria-current", b.dataset.s === step ? "page" : "false"));
  document.body.classList.remove("nav-open");
  document.querySelectorAll("#side section").forEach(s => s.hidden = s.dataset.p !== step);
  const res = step === "resultados";
  $("results").hidden = !res; $("view").hidden = res; $("side").hidden = res;
  $("work").style.gridTemplateColumns = res ? "1fr" : "";
  if (res) { flushSave(); renderResults(); } else { resize(); draw(); }
  if (step !== "croqui") setPick(null);
  markDone();
}
function markDone() {
  if (!S.trial) return;
  const ok = { ensaio: S.trial.tratamentos.length > 0, imagens: S.flights.some(f => f.status === "pronto" || f.status === "processado"), croqui: !!C().corners && parsedPlots().valid, mapa: S.flights.some(f => f.tem_resultados) };
  document.querySelectorAll("#steps a").forEach(b => b.classList.toggle("done", !!ok[b.dataset.s]));
  $("trialName").textContent = S.trial.nome || "Ensaio";
  crumb(S.trial.nome || "Ensaio", { ensaio: "Ensaio", imagens: "Voos", croqui: "Croqui", mapa: "Mapa", resultados: "Resultados" }[S.step] || "");
}
document.querySelectorAll("#steps a").forEach(b => b.addEventListener("click", e => { e.preventDefault(); go(b.dataset.s); }));

/* ---------------------------------------------------------------- ensaio */
const TF = { tNome: "nome", tCliente: "cliente", tLocal: "local", tCultura: "cultura", tVar: "variedade", tObs: "observacoes" };
function fillTrial() { for (const [k, f] of Object.entries(TF)) $(k).value = S.trial[f] || ""; renderTrts(); }
for (const [k, f] of Object.entries(TF)) $(k).addEventListener("input", e => { S.trial[f] = e.target.value; markDone(); save(); });
function renderTrts() {
  $("trtBody").innerHTML = S.trial.tratamentos.map((t, i) => `<tr>
   <td style="width:46px"><input type="text" data-i="${i}" data-f="code" value="${esc(t.code)}" aria-label="Número"></td>
   <td style="width:64px"><input type="text" data-i="${i}" data-f="sigla" value="${esc(t.sigla)}" aria-label="Sigla"></td>
   <td><input type="text" data-i="${i}" data-f="nome" value="${esc(t.nome)}" aria-label="Produto e dose"></td>
   <td style="text-align:center"><input type="radio" name="ctrl" data-i="${i}" ${t.ctrl ? "checked" : ""} aria-label="Controle"></td>
   <td><button class="x" data-del="${i}" aria-label="Remover">×</button></td></tr>`).join("");
}
$("trtBody").addEventListener("input", e => {
  const i = +e.target.dataset.i;
  if (e.target.type === "radio") S.trial.tratamentos.forEach((t, j) => t.ctrl = j === i); else S.trial.tratamentos[i][e.target.dataset.f] = e.target.value;
  croqStatus(); draw(); save();
});
$("trtBody").addEventListener("click", e => { if (e.target.dataset.del != null) { S.trial.tratamentos.splice(+e.target.dataset.del, 1); renderTrts(); croqStatus(); save(); } });
$("addTrt").onclick = () => { const T = S.trial.tratamentos; T.push({ code: String(T.length + 1), sigla: "", nome: "", ctrl: T.length === 0 }); renderTrts(); save(); };
$("delTrial").onclick = () => $("delConfirm").hidden = false;
$("delNo").onclick = () => $("delConfirm").hidden = true;
$("delYes").onclick = async () => { try { await API.del("/api/ensaios/" + S.trial.id); S.trial = null; $("delConfirm").hidden = true; toast("Ensaio excluído"); openList(); } catch (e) { toast(e.message); } };

/* ---------------------------------------------------------------- voos */
const drop = $("drop");
drop.onclick = () => $("fileIn").click();
drop.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("fileIn").click(); } };
drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
drop.ondragleave = () => drop.classList.remove("over");
drop.ondrop = e => { e.preventDefault(); drop.classList.remove("over"); if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]); };
$("fileIn").onchange = e => { if (e.target.files[0]) upload(e.target.files[0]); e.target.value = ""; };
function guessDate(n) { const m = n.match(/(\d{4})[-_.]?(\d{2})[-_.]?(\d{2})/); return m ? `${m[1]}-${m[2]}-${m[3]}` : ""; }
function upload(file) {
  const fd = new FormData(); fd.append("arquivo", file);
  const date = $("upDate").value || guessDate(file.name);
  fd.append("data_voo", date);
  fd.append("rotulo", $("upLabel").value || (date ? date.split("-").reverse().join("/") : file.name));
  const xhr = new XMLHttpRequest(); xhr.open("POST", `/api/ensaios/${S.trial.id}/voos`); xhr.setRequestHeader("Authorization", "Bearer " + API.token);
  $("upProg").hidden = false; $("upTxt").textContent = `Enviando ${file.name}…`; $("upBar").style.width = "0";
  xhr.upload.onprogress = e => { if (e.lengthComputable) { const p = e.loaded / e.total * 100; $("upBar").style.width = p + "%"; $("upTxt").textContent = `Enviando ${file.name}: ${fmt(p, 0)}% de ${fmt(e.total / 1048576, 0)} MB`; } };
  xhr.onload = async () => {
    if (xhr.status >= 200 && xhr.status < 300) { $("upTxt").textContent = "Arquivo recebido. O servidor está preparando a imagem…"; $("upLabel").value = ""; $("upDate").value = ""; await refreshTrial(); renderFlights(); pollIfBusy().then(() => { $("upProg").hidden = true; }); }
    else { let m = xhr.statusText; try { m = JSON.parse(xhr.responseText).detail; } catch (_) { } $("upTxt").textContent = "Falhou: " + m; }
  };
  xhr.onerror = () => { $("upTxt").textContent = "A conexão caiu durante o envio. Tente de novo."; };
  xhr.send(fd);
}
const STATUS = { recebido: ["Recebido", ""], preparando: ["Preparando", "run"], pronto: ["Pronto", "ok"], calculando: ["Calculando", "run"], processado: ["Processado", "ok"], erro: ["Erro", "err"] };
function renderFlights() {
  const L = $("imgList"); L.innerHTML = "";
  if (!S.flights.length) { L.innerHTML = '<p class="hint">Nenhum voo ainda.</p>'; return; }
  S.flights.forEach(f => {
    const d = document.createElement("div"); d.className = "imgcard";
    const th = document.createElement("canvas"); th.width = 128; th.height = 96;
    const b = S.bmp[f.id]; if (b) { const x = th.getContext("2d"); const k = Math.max(128 / b.width, 96 / b.height); x.drawImage(b, (128 - b.width * k) / 2, (96 - b.height * k) / 2, b.width * k, b.height * k); }
    d.appendChild(th);
    const st = STATUS[f.status] || [f.status, ""];
    const m = document.createElement("div");
    m.innerHTML = `<input type="text" value="${esc(f.rotulo)}" aria-label="Rótulo do voo"><div class="meta">${esc(f.arquivo)} · ${fmt(f.tamanho / 1048576, 1)} MB<br>
      ${f.largura ? `${f.largura}×${f.altura} px · ` : ""}${f.gsd_m ? fmt(f.gsd_m * 100, 1) + " cm/px" : f.status === "pronto" || f.status === "processado" ? "sem georref." : ""} <span class="badge ${st[1]}">${st[0]}</span></div>`;
    m.querySelector("input").onchange = async e => { f.rotulo = e.target.value; await API.put("/api/voos/" + f.id, { rotulo: f.rotulo }); renderDateRadios(); };
    d.appendChild(m);
    const del = document.createElement("button"); del.className = "x"; del.textContent = "×"; del.setAttribute("aria-label", "Excluir voo");
    del.onclick = async () => { if (del.dataset.sure !== "1") { del.dataset.sure = "1"; del.textContent = "Excluir?"; setTimeout(() => { del.dataset.sure = ""; del.textContent = "×"; }, 3000); return; }
      await API.del("/api/voos/" + f.id); delete S.bmp[f.id]; if (S.cur === f.id) S.cur = null; await refreshTrial(); renderFlights(); renderDateRadios(); fitView(); };
    d.appendChild(del);
    if (f.erro) { const e = document.createElement("p"); e.className = "err"; e.textContent = f.erro; d.appendChild(e); }
    L.appendChild(d);
  });
}

/* ---------------------------------------------------------------- coordenadas */
// "mundo": lon/lat (imagens georreferenciadas) ou fração da imagem (0–1)
function kindFor(f) { return f && f.limites ? "lonlat" : "frac"; }
function toPix(f, p) {
  if (C().kind === "lonlat") { if (!f.limites) return [NaN, NaN]; const [w, s, e, n] = f.limites; return [(p[0] - w) / (e - w) * f.previa_w, (n - p[1]) / (n - s) * f.previa_h]; }
  return [p[0] * f.previa_w, p[1] * f.previa_h];
}
function toWorld(f, q) {
  if (C().kind === "lonlat") { const [w, s, e, n] = f.limites; return [w + q[0] / f.previa_w * (e - w), n - q[1] / f.previa_h * (n - s)]; }
  return [q[0] / f.previa_w, q[1] / f.previa_h];
}

/* ---------------------------------------------------------------- croqui */
function fitCorners() {
  const f = curFlight(); if (!f) { toast("Envie um voo primeiro"); return; }
  C().kind = kindFor(f);
  const a = [f.previa_w * .2, f.previa_h * .25], b = [f.previa_w * .8, f.previa_h * .75];
  C().corners = [[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]].map(p => toWorld(f, p)); draw(); croqStatus(); save();
}
$("fitCorners").onclick = fitCorners;
const CQ = { cRows: "rows", cCols: "cols", cMargin: "margin", gX: "gx", gY: "gy" };
function fillCroq() { for (const [k, f] of Object.entries(CQ)) $(k).value = C()[f]; renderCroqTbl(); }
for (const [k, f] of Object.entries(CQ)) $(k).addEventListener("input", e => {
  if (e.target.value === "") return; const v = Math.max(+e.target.min || 0, Math.min(+e.target.max || 99, parseInt(e.target.value) || 0));
  C()[f] = v; if (f === "rows" || f === "cols") renderCroqTbl(); croqStatus(); draw(); save();
});
function cell(r, c) { return (C().cells[r] || [])[c] || ""; }
function renderCroqTbl() {
  const { rows, cols } = C(); let h = "<tr><th></th>" + Array.from({ length: cols }, (_, c) => `<th>${c + 1}</th>`).join("") + "</tr>";
  for (let r = 0; r < rows; r++) { h += `<tr><th>${r + 1}</th>`; for (let c = 0; c < cols; c++) h += `<td><input type="text" data-r="${r}" data-c="${c}" value="${esc(cell(r, c))}" aria-label="Linha ${r + 1}, coluna ${c + 1}"></td>`; h += "</tr>"; }
  $("croqTbl").innerHTML = h; croqStatus();
}
$("croqTbl").addEventListener("input", e => { const r = +e.target.dataset.r, c = +e.target.dataset.c; (C().cells[r] || (C().cells[r] = []))[c] = e.target.value.trim(); croqStatus(); draw(); save(); });
$("croqTbl").addEventListener("paste", e => { const t = e.clipboardData.getData("text"); if (!/[\t\n]/.test(t)) return; e.preventDefault(); applyPaste(t, +e.target.dataset.r || 0, +e.target.dataset.c || 0); });
function applyPaste(t, r0 = 0, c0 = 0) {
  const rows = t.replace(/\r/g, "").split("\n").filter(l => l.trim()).map(l => l.split(/\t|;|\s+/).map(s => s.trim()).filter(Boolean));
  if (!rows.length) return;
  if (r0 === 0 && c0 === 0) { C().rows = rows.length; C().cols = Math.max(...rows.map(r => r.length)); $("cRows").value = C().rows; $("cCols").value = C().cols; C().cells = []; }
  rows.forEach((row, i) => row.forEach((v, j) => { (C().cells[r0 + i] || (C().cells[r0 + i] = []))[c0 + j] = v; }));
  renderCroqTbl(); draw(); save();
}
$("pasteBtn").onclick = () => { $("pasteBox").hidden = !$("pasteBox").hidden; };
$("pasteApply").onclick = () => { applyPaste($("pasteTxt").value); $("pasteBox").hidden = true; };
$("geojsonBtn").onclick = async () => { await flushSave(); if (C().kind !== "lonlat") { toast("O GeoJSON precisa de um voo georreferenciado"); return; } download(`/api/ensaios/${S.trial.id}/parcelas.geojson`, `ensaio-${S.trial.id}-parcelas.geojson`); };
$("randDBC").onclick = () => {
  const T = S.trial.tratamentos, n = T.length, { rows, cols } = C(); if (!n) { toast("Cadastre os tratamentos primeiro"); return; }
  const nb = Math.floor(rows * cols / n); if (nb < 1) { toast("O croqui tem menos parcelas que tratamentos"); return; }
  const seq = []; for (let b = 0; b < nb; b++) { const p = T.map(t => t.code); for (let i = p.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1));[p[i], p[j]] = [p[j], p[i]]; } p.forEach(code => seq.push(code + String.fromCharCode(65 + b))); }
  C().cells = []; let k = 0; for (let r = 0; r < rows; r++) { C().cells[r] = []; for (let c = 0; c < cols; c++) C().cells[r][c] = seq[k++] || ""; }
  renderCroqTbl(); draw(); save(); toast(`Sorteio feito: ${n} tratamentos × ${nb} blocos`);
};
function parseCell(v, r) {
  const T = S.trial.tratamentos, by = c => T.find(t => String(t.code).toLowerCase() === c.toLowerCase() || (t.sigla && t.sigla.toLowerCase() === c.toLowerCase()));
  const m = v.match(/^(.+?)[-_ ]?([A-Za-z])$/); if (m && by(m[1])) return { trt: by(m[1]), bloco: m[2].toUpperCase() };
  if (by(v)) return { trt: by(v), bloco: String.fromCharCode(65 + r) }; return { trt: null, bloco: null };
}
function parsedPlots() {
  const out = []; let bad = 0; const { rows, cols } = C();
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) { const v = cell(r, c); if (!v) continue; const p = parseCell(v, r); if (!p.trt) bad++; out.push({ id: v, r, c, trt: p.trt, bloco: p.bloco }); }
  return { plots: out, bad, valid: out.length > 0 && bad === 0 };
}
function croqStatus() {
  const p = parsedPlots(), el = $("croqStatus"), blocks = new Set(p.plots.filter(x => x.bloco).map(x => x.bloco));
  el.classList.toggle("warn", p.bad > 0 || !p.plots.length);
  el.textContent = !p.plots.length ? "Preencha a identificação das parcelas." : p.bad ? `${p.bad} parcela(s) com tratamento não encontrado no cadastro.` : `${p.plots.length} parcelas · ${new Set(p.plots.map(x => x.trt.code)).size} tratamentos · ${blocks.size} blocos.`;
  markDone();
}
function bil(q, u, v) { return [(1 - u) * (1 - v) * q[0][0] + u * (1 - v) * q[1][0] + u * v * q[2][0] + (1 - u) * v * q[3][0], (1 - u) * (1 - v) * q[0][1] + u * (1 - v) * q[1][1] + u * v * q[2][1] + (1 - u) * v * q[3][1]]; }
function plotQuad(cp, r, c, u0 = 0, u1 = 1, v0 = 0, v1 = 1) {
  const { rows, cols, margin } = C(), m = margin / 100 / 2;
  const a0 = (c + m) / cols, a1 = (c + 1 - m) / cols, b0 = (r + m) / rows, b1 = (r + 1 - m) / rows, U = t => a0 + (a1 - a0) * t, V = t => b0 + (b1 - b0) * t;
  return [bil(cp, U(u0), V(v0)), bil(cp, U(u1), V(v0)), bil(cp, U(u1), V(v1)), bil(cp, U(u0), V(v1))];
}
function cornersPix(f) { return C().corners ? C().corners.map(p => toPix(f, p)) : null; }

/* ---------------------------------------------------------------- processar */
$("thrMode").onchange = () => { S.trial.ajustes.thr_mode = $("thrMode").value; $("thrFixedF").hidden = $("thrMode").value !== "fixed"; S.masks = {}; draw(); save(); };
$("thrVal").oninput = () => { S.trial.ajustes.thr_value = +$("thrVal").value; S.masks = {}; draw(); save(); };
$("runBtn").onclick = async () => {
  await flushSave();
  try { await API.post(`/api/ensaios/${S.trial.id}/processar`); $("runStatus").hidden = false; $("runStatus").classList.remove("warn"); $("runStatus").textContent = "Calculando no servidor…"; await refreshTrial(); pollIfBusy(); }
  catch (e) { $("runStatus").hidden = false; $("runStatus").classList.add("warn"); $("runStatus").textContent = e.message; }
};
function runStatusFromFlights() {
  const st = $("runStatus"); if (!S.flights.length) { st.hidden = true; return; }
  const busy = S.flights.filter(f => f.status === "calculando").length, err = S.flights.filter(f => f.erro), done = S.flights.filter(f => f.tem_resultados);
  if (!busy && !done.length && !err.length) { st.hidden = true; return; }
  st.hidden = false; st.classList.toggle("warn", err.length > 0);
  st.textContent = busy ? `Calculando ${busy} voo(s)…` : `${done.length} de ${S.flights.length} voo(s) processado(s).` + (err.length ? " " + err.map(f => `${f.rotulo}: ${f.erro}`).join(" ") : "");
  if (!busy) { $("lyPlot").checked = true; draw(); renderFlights(); }
}
function thrFor(f) { return S.trial.ajustes.thr_mode === "fixed" ? +S.trial.ajustes.thr_value : (f.otsu ?? .05); }
function buildMask(f) {
  const b = S.bmp[f.id], c = document.createElement("canvas"); c.width = b.width; c.height = b.height; const x = c.getContext("2d"); x.drawImage(b, 0, 0);
  const o = x.getImageData(0, 0, c.width, c.height), d = o.data, t = thrFor(f);
  for (let j = 0; j < d.length; j += 4) { if (!d[j + 3]) continue; const s = d[j] + d[j + 1] + d[j + 2]; const e = s < 60 ? 0 : (2 * d[j + 1] - d[j] - d[j + 2]) / s;
    if (e > t) { d[j] = 40; d[j + 1] = 230; d[j + 2] = 80; d[j + 3] = 150; } else { d[j] = 200; d[j + 1] = 60; d[j + 2] = 40; d[j + 3] = 90; } }
  x.putImageData(o, 0, 0); return c;
}

/* ---------------------------------------------------------------- visualizador */
const cv = $("cv"), ctx = cv.getContext("2d"); let DPR = 1;
function resize() { const r = cv.getBoundingClientRect(); DPR = window.devicePixelRatio || 1; cv.width = Math.max(1, r.width * DPR); cv.height = Math.max(1, r.height * DPR); }
window.addEventListener("resize", () => { if (!$("vWork").hidden) { resize(); draw(); } });
function fitView() { const f = curFlight(); if (!f || !S.bmp[f.id]) return; resize(); const W = cv.width / DPR, H = cv.height / DPR, s = Math.min(W / f.previa_w, H / f.previa_h) * .96; S.view = { s, tx: (W - f.previa_w * s) / 2, ty: (H - f.previa_h * s) / 2 }; draw(); }
const scr = p => [p[0] * S.view.s + S.view.tx, p[1] * S.view.s + S.view.ty];
const unscr = p => [(p[0] - S.view.tx) / S.view.s, (p[1] - S.view.ty) / S.view.s];
const RAMP = [[215, 48, 31], [252, 141, 89], [254, 224, 139], [217, 239, 139], [145, 207, 96], [26, 152, 80]];
function rampC(t, a = 1) { t = Math.max(0, Math.min(1, t)); const p = t * (RAMP.length - 1), i = Math.min(RAMP.length - 2, Math.floor(p)), f = p - i, A = RAMP[i], B = RAMP[i + 1]; return `rgba(${A.map((v, k) => Math.round(v + (B[k] - v) * f)).join(",")},${a})`; }
const curIdx = () => $("idxSel").value || "CC";
function rangeFor(res, k, grid) { let mn = Infinity, mx = -Infinity; for (const p of Object.values(res)) { const vs = grid ? (p.cells || []).map(c => c && c[k]) : [p[k]]; for (const v of vs) { if (v == null || !isFinite(v)) continue; mn = Math.min(mn, v); mx = Math.max(mx, v); } } return [mn, mx]; }
function poly(q) { ctx.beginPath(); q.forEach((p, i) => { const s = scr(p); i ? ctx.lineTo(s[0], s[1]) : ctx.moveTo(s[0], s[1]); }); ctx.closePath(); }
function draw() {
  if (!S.trial || S.step === "resultados" || $("vWork").hidden) return;
  const f = curFlight(), bmp = f && S.bmp[f.id];
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0); ctx.clearRect(0, 0, cv.width, cv.height);
  $("emptyMsg").hidden = !!bmp;
  if (!bmp) { const busy = S.flights.some(x => x.status === "preparando"); $("emptyTitle").textContent = busy ? "Preparando a imagem…" : "Nenhum voo pronto"; $("emptyText").textContent = busy ? "O servidor está lendo o ortomosaico." : "Vá em Voos e envie um ortomosaico."; return; }
  ctx.imageSmoothingEnabled = S.view.s < 2; ctx.drawImage(bmp, S.view.tx, S.view.ty, f.previa_w * S.view.s, f.previa_h * S.view.s);
  const mapStep = S.step === "mapa";
  if (mapStep && $("lyMask").checked) { if (!S.masks[f.id]) S.masks[f.id] = buildMask(f); ctx.drawImage(S.masks[f.id], S.view.tx, S.view.ty, f.previa_w * S.view.s, f.previa_h * S.view.s); }
  const cp = cornersPix(f); if (!cp || cp.some(p => !isFinite(p[0]))) return;
  const pp = parsedPlots(), res = f.resultados && Object.keys(f.resultados).length ? f.resultados : null, k = curIdx();
  const showPlot = mapStep && res && $("lyPlot").checked, showGrid = mapStep && res && $("lyGrid").checked;
  let rng = [0, 1]; if (res) { rng = rangeFor(res, k, showGrid && !showPlot); $("lgMin").textContent = fmt(rng[0], IDX[k].d); $("lgMax").textContent = fmt(rng[1], IDX[k].d); }
  const nrm = v => rng[1] > rng[0] ? (v - rng[0]) / (rng[1] - rng[0]) : .5;
  const { rows, cols, gx, gy } = C(), byRC = {}; pp.plots.forEach(p => byRC[p.r + "," + p.c] = p);
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    const p = byRC[r + "," + c], q = plotQuad(cp, r, c), R = p && res ? res[p.id] : null;
    if (showGrid && R && R.cells) R.cells.forEach((cl, i) => { if (!cl || cl[k] == null) return; const gi = i % gx, gj = Math.floor(i / gx); poly(plotQuad(cp, r, c, gi / gx, (gi + 1) / gx, gj / gy, (gj + 1) / gy)); ctx.fillStyle = rampC(nrm(cl[k]), .6); ctx.fill(); ctx.strokeStyle = "rgba(255,255,255,.35)"; ctx.lineWidth = 1; ctx.stroke(); });
    poly(q);
    if (showPlot && R && !showGrid && R[k] != null) { ctx.fillStyle = rampC(nrm(R[k]), .45); ctx.fill(); ctx.strokeStyle = rampC(nrm(R[k]), 1); ctx.lineWidth = 2.5; }
    else if (showPlot && R && R[k] != null) { ctx.strokeStyle = rampC(nrm(R[k]), 1); ctx.lineWidth = 3; }
    else { ctx.strokeStyle = p ? (p.trt ? "rgba(255,255,255,.95)" : "rgba(255,170,60,.95)") : "rgba(255,255,255,.35)"; ctx.lineWidth = S.step === "croqui" ? 1.5 : 2; }
    ctx.stroke();
    const lab = []; if (p && (S.step === "croqui" || $("lyTrt").checked) && p.trt) lab.push(p.trt.sigla || p.trt.code); if (p && (S.step === "croqui" || $("lyPlotId").checked)) lab.push(p.id);
    if (lab.length) {
      const ctr = scr(bil(q, .5, .5)), fs = Math.max(10, Math.min(16, S.view.s * Math.hypot(q[1][0] - q[0][0], q[1][1] - q[0][1]) / 5));
      ctx.font = `600 ${fs}px Inter,system-ui,sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.lineWidth = 3; ctx.strokeStyle = "rgba(0,0,0,.6)"; ctx.fillStyle = "#fff";
      const t = lab.join(" · "); ctx.strokeText(t, ctr[0], ctr[1]); ctx.fillText(t, ctr[0], ctr[1]);
      if (showPlot && R && !showGrid && R[k] != null) { const v = fmt(R[k], IDX[k].d); ctx.font = `500 ${fs * .85}px Inter,system-ui,sans-serif`; ctx.strokeText(v, ctr[0], ctr[1] + fs * 1.1); ctx.fillText(v, ctr[0], ctr[1] + fs * 1.1); }
    }
  }
  if (S.step === "croqui") {
    ctx.strokeStyle = "#ffd54a"; ctx.lineWidth = 2; ctx.setLineDash([6, 4]); poly(cp); ctx.stroke(); ctx.setLineDash([]);
    cp.forEach((pt, i) => { const s = scr(pt); ctx.beginPath(); ctx.arc(s[0], s[1], 9, 0, 7); ctx.fillStyle = "#ffd54a"; ctx.fill(); ctx.strokeStyle = "#222"; ctx.lineWidth = 1.5; ctx.stroke(); ctx.fillStyle = "#222"; ctx.font = '700 11px Inter,system-ui,sans-serif'; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(String(i + 1), s[0], s[1] + .5); });
  }
  if (S.pick && S.pick.pts.length) S.pick.pts.forEach(w => { const s = scr(w); ctx.beginPath(); ctx.arc(s[0], s[1], 7, 0, 7); ctx.fillStyle = "#4fc3f7"; ctx.fill(); });
}
let drag = null; const ptrs = new Map();
function evPt(e) { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
cv.addEventListener("pointerdown", e => {
  cv.setPointerCapture(e.pointerId); const p = evPt(e); ptrs.set(e.pointerId, p); const f = curFlight(); if (!f || !S.bmp[f.id]) return;
  if (ptrs.size === 2) { const [a, b] = [...ptrs.values()]; drag = { pinch: true, d: Math.hypot(a[0] - b[0], a[1] - b[1]), s: S.view.s, c: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] }; return; }
  if (S.pick) {
    S.pick.pts.push(unscr(p));
    if (S.pick.pts.length === 4) { C().kind = kindFor(f); C().corners = S.pick.pts.map(q => toWorld(f, q)); setPick(null); croqStatus(); save(); toast("Cantos marcados. Arraste para ajustar."); }
    else setPick(S.pick);
    draw(); return;
  }
  if (S.step === "croqui" && C().corners) { const cp = cornersPix(f), i = cp.findIndex(c => { const s = scr(c); return Math.hypot(s[0] - p[0], s[1] - p[1]) < 14; }); if (i >= 0) { drag = { corner: i }; return; } }
  drag = { pan: true, x: p[0], y: p[1], tx: S.view.tx, ty: S.view.ty }; cv.style.cursor = "grabbing";
});
cv.addEventListener("pointermove", e => {
  const p = evPt(e); if (ptrs.has(e.pointerId)) ptrs.set(e.pointerId, p); const f = curFlight(); if (!f || !S.bmp[f.id]) return;
  if (drag && drag.pinch && ptrs.size === 2) { const [a, b] = [...ptrs.values()]; zoomAt(drag.c, drag.s * Math.hypot(a[0] - b[0], a[1] - b[1]) / drag.d / S.view.s); return; }
  if (drag && drag.corner != null) { C().corners[drag.corner] = toWorld(f, unscr(p)); draw(); return; }
  if (drag && drag.pan) { S.view.tx = drag.tx + p[0] - drag.x; S.view.ty = drag.ty + p[1] - drag.y; draw(); hideTip(); return; }
  hover(p);
});
const endPtr = e => { ptrs.delete(e.pointerId); if (drag && drag.corner != null) save(); if (ptrs.size < 2 && drag && drag.pinch) drag = null; if (!ptrs.size) { drag = null; cv.style.cursor = ""; } };
cv.addEventListener("pointerup", endPtr); cv.addEventListener("pointercancel", endPtr); cv.addEventListener("pointerleave", () => hideTip());
cv.addEventListener("wheel", e => { e.preventDefault(); zoomAt(evPt(e), Math.exp(-e.deltaY * .0015)); }, { passive: false });
function zoomAt(c, f) { const s = Math.max(.02, Math.min(60, S.view.s * f)), k = s / S.view.s; S.view.tx = c[0] - (c[0] - S.view.tx) * k; S.view.ty = c[1] - (c[1] - S.view.ty) * k; S.view.s = s; draw(); }
$("zin").onclick = () => zoomAt([cv.width / DPR / 2, cv.height / DPR / 2], 1.4); $("zout").onclick = () => zoomAt([cv.width / DPR / 2, cv.height / DPR / 2], 1 / 1.4); $("zfit").onclick = fitView;
const CORNER = ["superior esquerdo", "superior direito", "inferior direito", "inferior esquerdo"];
function setPick(p) { S.pick = p; cv.classList.toggle("pick", !!p); $("pickCorners").classList.toggle("on", !!p); const b = $("modeBadge"); b.hidden = !p; if (p) b.textContent = `Clique no canto ${CORNER[p.pts.length]} (${p.pts.length + 1}/4)`; }
$("pickCorners").onclick = () => { if (!curFlight() || !S.bmp[S.cur]) { toast("Envie um voo primeiro"); return; } setPick(S.pick ? null : { pts: [] }); draw(); };
document.addEventListener("keydown", e => { if (e.key === "Escape" && S.pick) { setPick(null); draw(); } });
function inQuad(q, p) { let s0 = 0; for (let i = 0; i < 4; i++) { const a = q[i], b = q[(i + 1) % 4], c = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]), sg = Math.sign(c); if (!sg) continue; if (!s0) s0 = sg; else if (sg !== s0) return false; } return true; }
function hideTip() { $("tip").hidden = true; }
function hover(p) {
  const f = curFlight(), cp = f && cornersPix(f); if (!cp || S.step === "imagens") { hideTip(); return; }
  const w = unscr(p), hit = parsedPlots().plots.find(x => inQuad(plotQuad(cp, x.r, x.c), w)); if (!hit) { hideTip(); return; }
  const R = f.resultados && f.resultados[hit.id], t = $("tip");
  let h = `<b>Parcela ${esc(hit.id)}</b><br>${hit.trt ? esc((hit.trt.sigla || hit.trt.code) + " · " + hit.trt.nome) : "tratamento não cadastrado"}${hit.bloco ? " · bloco " + hit.bloco : ""}`;
  if (R) h += "<table>" + ["CC", "ExG", "VARI", "GLI", "NGRDI"].map(k => `<tr><td>${k}</td><td>${fmt(R[k], IDX[k].d)}${IDX[k].u ? " " + IDX[k].u : ""}</td></tr>`).join("") + (R.area ? `<tr><td>Área</td><td>${fmt(R.area, 1)} m²</td></tr>` : "") + "</table>";
  t.innerHTML = h; t.hidden = false; const vr = $("view").getBoundingClientRect(); let x = p[0] + 14, y = p[1] + 14; if (x + 200 > vr.width) x = p[0] - 210; if (y + 150 > vr.height) y = p[1] - 160; t.style.left = Math.max(4, x) + "px"; t.style.top = Math.max(4, y) + "px";
}
function renderDateRadios() {
  const r = readyFlights();
  $("dateRadios").innerHTML = r.map(f => `<label class="chk"><input type="radio" name="dt" value="${f.id}" ${f.id === S.cur ? "checked" : ""}> ${esc(f.rotulo)}</label>`).join("") || '<p class="hint">Sem voos prontos.</p>';
}
$("dateRadios").addEventListener("change", e => { S.cur = +e.target.value; draw(); });
const setDesc = () => $("idxDesc").textContent = IDX[curIdx()].desc; setDesc();
$("idxSel").onchange = () => { setDesc(); draw(); };
["lyTrt", "lyPlotId", "lyPlot", "lyGrid", "lyMask"].forEach(id => $(id).onchange = draw);

/* ---------------------------------------------------------------- resultados */
const statCache = {};
async function getStats(fid, k, alpha) {
  const key = `${S.trial.id}:${fid}:${k}:${alpha}:${(S.flights.find(f => f.id === fid) || {}).processado_em}`;
  if (!statCache[key]) statCache[key] = API.get(`/api/ensaios/${S.trial.id}/estatistica?voo=${fid}&indice=${k}&alpha=${alpha}`);
  return statCache[key];
}
async function renderResults() {
  const sel = $("rDate"), prev = sel.value, done = S.flights.filter(f => f.tem_resultados);
  sel.innerHTML = done.map(f => `<option value="${f.id}">${esc(f.rotulo)}</option>`).join(""); if (prev && done.some(f => String(f.id) === prev)) sel.value = prev;
  const body = $("resBody");
  if (!done.length) { body.innerHTML = '<div class="card"><b>Ainda não há resultados.</b><p class="hint">Vá em Mapa e clique em Processar índices.</p></div>'; return; }
  const k = $("rIdx").value || "CC", alpha = +$("rAlpha").value, fid = +sel.value, ix = IDX[k], d = ix.d;
  body.innerHTML = '<p class="hint">Calculando…</p>';
  let A; try { A = await getStats(fid, k, alpha); } catch (e) { body.innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
  if (A.grupos.length < 2) { body.innerHTML = '<div class="card">São necessários ao menos 2 tratamentos com parcelas processadas.</div>'; return; }
  const sig = A.P != null && A.P < alpha;
  let h = `<div class="card"><div style="display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin-bottom:8px"><b style="font-family:var(--f-display);font-size:15px">${ix.l}${ix.u ? " (" + ix.u + ")" : ""}</b>` +
    (A.F != null ? `<span class="pill ${sig ? "sig" : ""}">${sig ? "Diferença significativa" : "Não significativo"} a ${alpha * 100}%</span><span style="color:var(--muted);font-size:12.5px">${A.delineamento} · F = ${fmt(A.F, 2)} · P = ${A.P < 1e-4 ? "<0,0001" : fmt(A.P, 4)} · CV = ${fmt(A.CV, 2)}% · DMS = ${fmt(A.DMS, d + 1)}</span>` : `<span style="color:var(--muted)">Repetições insuficientes para a análise de variância.</span>`) + `</div>`;
  h += barChart(A, ix, sig) + `</div>`;
  h += `<h3>Médias por tratamento</h3><div class="tw"><table class="res" id="trtTable"><thead><tr><th>Tratamento</th><th>n</th><th>Média</th><th>Grupo</th><th>Desvio</th><th>Ganho s/ controle</th><th>Ganho %</th></tr></thead><tbody>` +
    A.grupos.map(g => `<tr><td>${esc((g.sigla || g.code) + " · " + (g.nome || ""))}${g.ctrl ? " <span class='pill'>controle</span>" : ""}</td><td>${g.n}</td><td>${fmt(g.media, d)}</td><td class="l">${g.letras || ""}</td><td>${fmt(g.desvio, d)}</td>
      <td class="${g.ganho > 0 ? "pos" : g.ganho < 0 ? "neg" : ""}">${g.ctrl || g.ganho == null ? "–" : (g.ganho > 0 ? "+" : "") + fmt(g.ganho, d)}</td><td class="${g.ganho > 0 ? "pos" : g.ganho < 0 ? "neg" : ""}">${g.ctrl || g.ganho_pct == null ? "–" : (g.ganho_pct > 0 ? "+" : "") + fmt(g.ganho_pct, 1) + "%"}</td></tr>`).join("") +
    `</tbody></table></div><p class="hint" style="font-size:12px">Médias seguidas da mesma letra não diferem pelo teste DMS (t) a ${alpha * 100}%.</p>`;
  const evo = done.length > 1 ? await lineChart(done, k, alpha) : "";
  if (evo) h += `<h3>Evolução entre os voos</h3><div class="card">${evo}</div>`;
  const all = await Promise.all(IDXK.map(x => getStats(fid, x, alpha).catch(() => null)));
  h += `<h3>Todos os índices neste voo</h3><div class="tw"><table class="res"><thead><tr><th>Tratamento</th>${IDXK.map(x => `<th>${x}</th>`).join("")}</tr></thead><tbody>` +
    S.trial.tratamentos.map(t => `<tr><td>${esc((t.sigla || t.code) + " · " + (t.nome || ""))}</td>${all.map((a, i) => { const g = a && a.grupos.find(g => g.code === t.code); return `<td>${g ? fmt(g.media, IDX[IDXK[i]].d) + (a.P < alpha && g.letras ? " " + g.letras : "") : "–"}</td>`; }).join("")}</tr>`).join("") +
    `<tr class="stat"><td>P (F)</td>${all.map(a => `<td>${a && a.P != null ? (a.P < 1e-4 ? "<0,0001" : fmt(a.P, 4)) : "–"}</td>`).join("")}</tr><tr class="stat"><td>CV %</td>${all.map(a => `<td>${a && a.CV != null ? fmt(a.CV, 2) : "–"}</td>`).join("")}</tr></tbody></table></div>`;
  body.innerHTML = h;
}
["rIdx", "rDate", "rAlpha"].forEach(i => $(i).onchange = renderResults);
function niceTicks(lo, hi, n = 5) { if (lo === hi) { lo -= 1; hi += 1; } const st0 = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(st0)), st = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= st0); const a = Math.floor(lo / st) * st, b = Math.ceil(hi / st) * st, o = []; for (let v = a; v <= b + st / 2; v += st) o.push(+v.toFixed(10)); return o; }
function barChart(A, ix, sig) {
  const G = A.grupos, W = 900, H = 300, L = 60, R = W - 14, T = 22, B = H - 44, vals = G.flatMap(g => [g.media + (g.desvio || 0)]);
  let lo = Math.min(0, ...G.map(g => g.media)), hi = Math.max(...vals); const tk = niceTicks(lo, hi); lo = tk[0]; hi = tk[tk.length - 1];
  const y = v => B - (v - lo) / (hi - lo) * (B - T), gw = (R - L) / G.length, bw = Math.min(70, gw * .6);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Média por tratamento">`;
  tk.forEach(t => s += `<line class="gl" x1="${L}" x2="${R}" y1="${y(t)}" y2="${y(t)}"/><text class="ax" x="${L - 8}" y="${y(t) + 4}" text-anchor="end">${fmt(t, Math.abs(t) < 1 && t !== 0 ? 2 : Math.abs(t) < 10 ? 1 : 0)}</text>`);
  G.forEach((g, i) => {
    const cx = L + gw * i + gw / 2, y0 = y(Math.max(lo, 0)), ym = y(g.media);
    s += `<rect x="${cx - bw / 2}" y="${Math.min(y0, ym)}" width="${bw}" height="${Math.abs(y0 - ym)}" rx="3" fill="${g.ctrl ? "var(--muted)" : "var(--green)"}" opacity="${g.ctrl ? .55 : .9}"><title>${esc(g.nome)}: ${fmt(g.media, ix.d)}</title></rect>`;
    if (g.desvio) { const yt = y(g.media + g.desvio), yl = y(Math.max(lo, g.media - g.desvio)); s += `<line x1="${cx}" x2="${cx}" y1="${yt}" y2="${yl}" stroke="var(--fg)" stroke-width="1.2"/><line x1="${cx - 6}" x2="${cx + 6}" y1="${yt}" y2="${yt}" stroke="var(--fg)"/><line x1="${cx - 6}" x2="${cx + 6}" y1="${yl}" y2="${yl}" stroke="var(--fg)"/>`; }
    s += `<text x="${cx}" y="${y(g.media + (g.desvio || 0)) - 7}" text-anchor="middle" font-weight="600">${fmt(g.media, ix.d)} ${sig && g.letras ? g.letras : ""}</text><text x="${cx}" y="${B + 18}" text-anchor="middle" font-weight="600">${esc(g.sigla || g.code)}</text>`;
  });
  return s + "</svg>";
}
const PAL = ["#1d8a3a", "#155fa6", "#d4563a", "#8a5cc2", "#e0a11b", "#1e9fa8", "#7a7f78", "#c2417e", "#5a8f1d", "#3d4fb8"];
async function lineChart(fl, k, alpha) {
  const stats = await Promise.all(fl.map(f => getStats(f.id, k, alpha).catch(() => null)));
  const W = 900, H = 300, L = 60, R = W - 150, T = 16, B = H - 40;
  const series = S.trial.tratamentos.map((t, ti) => ({ t, c: PAL[ti % PAL.length], pts: stats.map(a => { const g = a && a.grupos.find(g => g.code === t.code); return g ? g.media : null; }) })).filter(s => s.pts.some(v => v != null));
  const all = series.flatMap(s => s.pts.filter(v => v != null)); if (!all.length) return "";
  const tk = niceTicks(Math.min(...all), Math.max(...all)), lo = tk[0], hi = tk[tk.length - 1];
  const y = v => B - (v - lo) / (hi - lo) * (B - T), x = i => L + 20 + (R - L - 40) * i / (fl.length - 1);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Evolução do índice entre os voos">`;
  tk.forEach(t => s += `<line class="gl" x1="${L}" x2="${R}" y1="${y(t)}" y2="${y(t)}"/><text class="ax" x="${L - 8}" y="${y(t) + 4}" text-anchor="end">${fmt(t, Math.abs(t) < 10 ? 2 : 0)}</text>`);
  fl.forEach((f, i) => s += `<text class="ax" x="${x(i)}" y="${B + 20}" text-anchor="middle">${esc(f.rotulo)}</text>`);
  series.forEach((se, j) => {
    const pts = se.pts.map((v, i) => v == null ? null : [x(i), y(v)]).filter(Boolean);
    s += `<polyline points="${pts.map(p => p.join(",")).join(" ")}" fill="none" stroke="${se.c}" stroke-width="2.2"/>` + pts.map(p => `<circle cx="${p[0]}" cy="${p[1]}" r="3.5" fill="${se.c}"/>`).join("");
    s += `<rect x="${R + 16}" y="${T + j * 20}" width="10" height="10" rx="2" fill="${se.c}"/><text x="${R + 32}" y="${T + j * 20 + 9}">${esc(se.t.sigla || se.t.code)}</text>`;
  });
  return s + "</svg>";
}
$("expXlsx").onclick = () => download(`/api/ensaios/${S.trial.id}/exportar.xlsx?alpha=${$("rAlpha").value}`, `ensaio-${S.trial.id}.xlsx`);
$("expCsv").onclick = () => download(`/api/ensaios/${S.trial.id}/parcelas.csv`, `ensaio-${S.trial.id}-parcelas.csv`);
$("copyTsv").onclick = () => {
  const t = $("trtTable"); if (!t) return; const txt = [...t.rows].map(r => [...r.cells].map(c => c.innerText.trim()).join("\t")).join("\n");
  navigator.clipboard.writeText(txt).then(() => toast("Tabela copiada. Cole no Excel."), () => toast("Não consegui copiar. Selecione a tabela e use Ctrl+C."));
};

/* ---------------------------------------------------------------- início */
(async () => {
  if (!API.token) { showLogin(); return; }
  try { ME = await API.get("/api/auth/eu"); openList(); } catch (_) { showLogin(); }
})();

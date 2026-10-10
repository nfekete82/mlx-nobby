/* MLX Nobby chart blocks: offline, validated, DOM-safe SVG rendering. */
(() => {
  "use strict";
  const MAX_ROWS = 120, MAX_SERIES = 5;
  const types = new Set(["auto","line","bar","donut","table","kpi"]);
  const numeric = value => typeof value === "number" && Number.isFinite(value);
  function normalize(raw) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
    const rows = raw.data;
    if (!Array.isArray(rows) || !rows.length || rows.length > MAX_ROWS) return null;
    if (!types.has(raw.type || "auto")) return null;
    const labels = [], values = [];
    for (const row of rows) {
      if (!row || typeof row !== "object" || Array.isArray(row)) return null;
      const label = String(row.label ?? "").slice(0, 90);
      const value = row.value;
      if (!label || !numeric(value) || Math.abs(value) > 1e15) return null;
      labels.push(label); values.push(value);
    }
    const requested = raw.type || "auto";
    const type = requested === "auto" ? choose(raw, labels, values) : requested;
    if (type === "donut" && values.some(v => v < 0)) return null;
    return { title:String(raw.title || "").slice(0,120), unit:String(raw.unit || "").slice(0,16),
      type, labels, values };
  }
  function choose(raw, labels, values) {
    if (values.length <= 3) return "kpi";
    const dated = labels.every(x => /^\d{4}[-/.]\d{1,2}([-/ .]\d{1,2})?$/.test(x));
    if (dated) return "line";
    if (values.length > 18) return "table";
    if (raw.part_of_whole === true && values.every(v => v >= 0) && values.reduce((a,b)=>a+b,0)>0 && values.length<=8) return "donut";
    return "bar";
  }
  function svgNode(tag, attrs = {}) {
    const node = document.createElementNS("http://www.w3.org/2000/svg",tag);
    for (const [key,value] of Object.entries(attrs)) node.setAttribute(key,String(value));
    return node;
  }
  function draw(spec) {
    const svg = svgNode("svg",{viewBox:"0 0 640 270",role:"img","aria-label":spec.title || spec.type});
    const {values,labels,type} = spec;
    const min = Math.min(0,...values), max = Math.max(0,...values);
    const span = max - min || 1, y = v => 228-(v-min)/span*190;
    if (type === "line") {
      const points=values.map((v,i)=>[46+i*556/Math.max(1,values.length-1),y(v)]);
      svg.appendChild(svgNode("line",{x1:46,x2:608,y1:y(0),y2:y(0),stroke:"#627086"}));
      const path=svgNode("polyline",{points:points.map(p=>p.join(",")).join(" "),fill:"none",stroke:"#60a5fa","stroke-width":3});
      svg.appendChild(path);
      points.forEach(([x,yy],i)=>{const point=svgNode("circle",{cx:x,cy:yy,r:3.6,fill:"#93c5fd"});const tt=svgNode("title");tt.textContent=labels[i]+": "+values[i];point.appendChild(tt);svg.appendChild(point);});
    } else if (type === "donut") {
      const total=values.reduce((a,b)=>a+b,0); let offset=0;
      values.forEach((v,i)=>{const part=total? v/total:0;if(!part)return;
        const ring=svgNode("circle",{cx:320,cy:133,r:80,fill:"none",stroke:["#60a5fa","#34d399","#fbbf24","#c084fc","#fb7185"][i%5],"stroke-width":34,"stroke-dasharray":(part*502.65)+" "+502.65,"stroke-dashoffset":-offset*502.65,transform:"rotate(-90 320 133)"});
        const title=svgNode("title");title.textContent=labels[i]+": "+v;ring.appendChild(title);svg.appendChild(ring);offset+=part;
      });
    } else {
      const width=556/values.length;
      values.forEach((v,i)=>{const top=Math.min(y(v),y(0)),height=Math.max(2,Math.abs(y(v)-y(0)));
        const bar=svgNode("rect",{x:46+i*width+3,y:top,width:Math.max(1,width-6),height,rx:3,fill:"#60a5fa"});
        const title=svgNode("title");title.textContent=labels[i]+": "+v;bar.appendChild(title);svg.appendChild(bar);
      });
    }
    return svg;
  }
  function csv(spec) {
    const quote=s=>'"'+String(s).replaceAll('"','""')+'"';
    return [["Label","Value"],...spec.labels.map((label,i)=>[label,spec.values[i]])].map(row=>row.map(quote).join(",")).join("\r\n");
  }
  function render(spec, original) {
    const card=document.createElement("section");card.className="nobby-chart";card.setAttribute("aria-label",spec.title||"Data visualization");
    const heading=document.createElement("h3");heading.textContent=spec.title||"Datenübersicht";card.appendChild(heading);
    const holder=document.createElement("div");holder.className="nobby-chart-body";card.appendChild(holder);
    const actions=document.createElement("div");actions.className="nobby-chart-actions";card.appendChild(actions);
    let mode=spec.type;
    const chooseMode=next=>{
      mode=next;holder.replaceChildren();
      if (next==="table" || next==="kpi") {
        const table=document.createElement("table"); const tbody=document.createElement("tbody");
        spec.labels.forEach((label,i)=>{const tr=document.createElement("tr");[label,new Intl.NumberFormat(undefined,{maximumFractionDigits:4}).format(spec.values[i])+(spec.unit?" "+spec.unit:"")].forEach(v=>{const td=document.createElement("td");td.textContent=v;tr.appendChild(td)});tbody.appendChild(tr)});
        table.appendChild(tbody);holder.appendChild(table);
      } else holder.appendChild(draw({...spec,type:next}));
    };
    const available=spec.values.every(v=>v>=0)?["line","bar","donut","table"]:["line","bar","table"];
    for(const kind of available){
      const b=document.createElement("button");b.type="button";b.textContent=({line:"Linie",bar:"Balken",donut:"Donut",table:"Tabelle"})[kind];b.addEventListener("click",()=>chooseMode(kind));actions.appendChild(b);
    }
    const exportCsv=document.createElement("button");exportCsv.type="button";exportCsv.textContent="CSV";
    exportCsv.addEventListener("click",()=>{const blob=new Blob(["\uFEFF",csv(spec)],{type:"text/csv;charset=utf-8"});const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download="nobby-chart.csv";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
    actions.appendChild(exportCsv);chooseMode(mode);return card;
  }
  function enhance(root) {
    if (!root?.querySelectorAll) return;
    // Models often emit `json` or an unlabelled fence despite the chart
    // instruction. Recognize the validated data schema, not just the fence tag.
    for(const code of root.querySelectorAll("pre > code")){
      const pre=code.parentElement;
      if(!pre || pre.dataset.nobbyChartDone) continue;
      const language=Array.from(code.classList || []).find(x=>x.startsWith("language-")) || "";
      if(language && !["language-nobby-chart","language-json"].includes(language)) continue;
      let parsed;
      try { parsed=JSON.parse(code.textContent); } catch(_) { continue; }
      if(!parsed || typeof parsed !== "object" || !Array.isArray(parsed.data) ||
          !("type" in parsed || "title" in parsed)) continue;
      const spec=normalize(parsed);
      if(!spec) continue;
      pre.dataset.nobbyChartDone="1";
      pre.replaceWith(render(spec,pre));
    }
  }
  window.MLXCharts={normalize,choose,enhance,csv};
})();
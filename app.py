from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from forecast_engine import Engine, blend, K

app = FastAPI(title="Zara new-style replenishment forecast")
eng = Engine()  # loads CSVs once at start-up


def _check(sku):
    if sku not in eng.new_styles:
        raise HTTPException(404, f"{sku} is not one of the new styles: {eng.new_styles}")


@app.get("/health")
def health():
    return {"status": "ok", "new_styles": len(eng.new_styles)}


@app.get("/api/styles")
def styles():
    return {"new_styles": eng.new_styles}


@app.get("/api/forecast")
def forecast(sku: str):
    _check(sku)
    return eng.for_style(sku).to_dict(orient="records")


@app.get("/api/dispatch")
def dispatch(sku: str):
    _check(sku)
    return eng.dispatch(sku).to_dict(orient="records")


@app.get("/api/forecast.csv")
def forecast_csv():
    return Response(eng.forecast.to_csv(index=False), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=replenishment_forecast_by_size.csv"})


@app.get("/api/blend")
def blend_one(own_avg: float, weeks_seen: int, store_id: str):
    if store_id not in eng.store_index.index:
        raise HTTPException(404, "unknown store_id")
    prior = eng.chain_avg * float(eng.store_index[store_id])
    trust = weeks_seen / (weeks_seen + K)
    return {"prior": round(prior, 1), "trust": round(trust, 2),
            "weekly_units": round(float(blend(own_avg, weeks_seen, prior)), 1)}


PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Zara replenishment forecast</title>
<style>
body{font-family:Calibri,Arial,sans-serif;margin:0;background:#f3f2f0;color:#111}
header{background:#111;color:#fff;padding:20px 24px}h1{margin:0;font-size:22px}
header p{margin:6px 0 0;color:#aaa;font-size:14px}main{max-width:900px;margin:0 auto;padding:20px}
select,a.btn{font-size:15px;padding:8px 12px;border-radius:6px;border:1px solid #ccc}
a.btn{background:#d7263d;color:#fff;border-color:#d7263d;text-decoration:none;margin-left:8px}
table{border-collapse:collapse;width:100%;background:#fff;margin:14px 0;border-radius:8px;overflow:hidden}
th,td{padding:8px 12px;text-align:right;border-bottom:1px solid #eee}th:first-child,td:first-child{text-align:left}
th{background:#eee}h2{font-size:17px;margin:22px 0 4px}small{color:#666}
</style></head><body>
<header><h1>Zara replenishment forecast</h1><p>Weekly units by size for new styles, next 4 weeks</p></header>
<main>
<label>New style: <select id=sku></select></label>
<a class=btn href="/api/forecast.csv">Download all as CSV</a>
<h2>DC dispatch: style total, all stores</h2><small>Sum of every store's forecast, by size</small>
<table id=disp></table>
<h2>Store detail, next week only</h2><small>Store-level numbers are noisier than the style total. Treat them as ranges.</small>
<table id=det></table>
</main>
<script>
const sizes=["XS","S","M","L","XL"];
function render(el,rows,cols){el.innerHTML="<tr>"+cols.map(c=>"<th>"+c+"</th>").join("")+"</tr>"+
rows.map(r=>"<tr>"+cols.map(c=>"<td>"+r[c]+"</td>").join("")+"</tr>").join("")}
async function load(){
 const sku=document.getElementById("sku").value;
 const d=await (await fetch("/api/dispatch?sku="+sku)).json();
 render(document.getElementById("disp"),d,["week_start_date",...sizes,"TOTAL"]);
 const f=await (await fetch("/api/forecast?sku="+sku)).json();
 const first=f.reduce((m,r)=>r.week_start_date<m?r.week_start_date:m,"9999");
 const by={};f.filter(r=>r.week_start_date===first).forEach(r=>{(by[r.store_id]=by[r.store_id]||{store_id:r.store_id,TOTAL:0})[r.size]=r.forecast_units;by[r.store_id].TOTAL+=r.forecast_units});
 render(document.getElementById("det"),Object.values(by),["store_id",...sizes,"TOTAL"]);
}
(async()=>{const s=await (await fetch("/api/styles")).json();const sel=document.getElementById("sku");
 sel.innerHTML=s.new_styles.map(x=>"<option>"+x+"</option>").join("");sel.onchange=load;load();})();
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE

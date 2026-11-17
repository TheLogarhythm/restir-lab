"""Rebuild final-presentation PNG assets from the frozen six-view archive.

Run from any directory with NumPy, Matplotlib and Pillow installed:
    python -B writing/final/tools/build_figures.py

Only writing/final/assets/figures and writing/final/data/figures.json are written.
No render runs, source arrays, source images or historical analysis are modified.
"""
from __future__ import annotations
import csv
import hashlib
import json
import shutil
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
from matplotlib.patches import Patch
from PIL import Image, ImageDraw, ImageFont
import numpy as np

REPO = Path(__file__).resolve().parents[3]
FINAL = Path(__file__).resolve().parents[1]
SOURCE = REPO / "runs/pt-6-views-spatial-compare"
OUTPUT = FINAL / "assets/figures"
MANIFEST = FINAL / "data/figures.json"
VIEWS = ["bistro-interior", "bistro-exterior", "classroom", "emerald-square", "veach-ajar", "zero-day-measure-seven"]
TITLES = dict(zip(VIEWS, ["Bistro Interior", "Bistro Exterior", "Classroom", "Emerald Square", "Veach Ajar", "Zero Day"]))
COLORS = {"pdf": "#817394", "cgns": "#c87536"}
LABELS = {"pdf": "PDF Similarity", "cgns": "CGNS"}
BG = "#ffffff"
NAVY = "#23150e"
plt.rcParams.update({"font.family": ["Arial", "Arial", "DejaVu Sans"], "font.size": 12,
    "text.color": NAVY, "axes.labelcolor": NAVY, "xtick.color": NAVY,
    "ytick.color": NAVY, "axes.facecolor": BG, "figure.facecolor": BG,
    "axes.edgecolor": "#81908f", "savefig.facecolor": BG, "axes.unicode_minus": True})
INPUTS = {}
ASSETS = []

def relative(path):
    return path.relative_to(REPO).as_posix()

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def track(path):
    INPUTS[relative(path)] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    return path

def record(path, description, inputs, details=None):
    with Image.open(path) as im:
        size = list(im.size)
    item = {"path": relative(path), "sha256": sha256(path), "bytes": path.stat().st_size,
        "width_px": size[0], "height_px": size[1], "description": description,
        "inputs": [relative(x) for x in inputs]}
    if details:
        item.update(details)
    ASSETS.append(item)

def save(fig, name, description, inputs, details=None):
    path = OUTPUT / name
    fig.savefig(path, dpi=200)
    plt.close(fig)
    record(path, description, inputs, details)

def read_summary():
    path = track(SOURCE / "statistics/summary.csv")
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    table = {(r["view"], r["method"]): r for r in rows}
    assert len(table) == 24
    for view in VIEWS:
        baseline = float(table[view, "temporal-on"]["smape_percent"])
        for method in ["pdf", "cgns"]:
            expected = 100 * (baseline - float(table[view, method]["smape_percent"])) / baseline
            assert abs(expected - float(table[view, method]["relative_smape_reduction_percent"])) < 1e-10
    return path, table

def style_bars(ax, views, limits, ticks):
    ax.set_xlim(*limits)
    ax.set_ylim(len(views)-.5, -.5)
    ax.set_yticks(np.arange(len(views)), [TITLES[v] for v in views], fontsize=15)
    ax.set_xticks(ticks, [f"{x:g}%" for x in ticks], fontsize=13)
    ax.tick_params(axis="y", length=0, pad=12)
    ax.tick_params(axis="x", length=0, pad=7)
    ax.spines[["left", "right", "top"]].set_visible(False)
    ax.spines["bottom"].set_color("#b3bdbc")
    ax.grid(axis="x", color="#dbe1df", linewidth=.7)
    ax.set_axisbelow(True)
    ax.axvline(0, color="#697c80", lw=.9)
    handles = [Patch(facecolor=COLORS[m], label=LABELS[m]) for m in ["pdf", "cgns"]]
    ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0,1.04), ncol=2,
        frameon=False, borderaxespad=0, handlelength=1.3, columnspacing=2, fontsize=15)

def quality(summary_path, table):
    fig, ax = plt.subplots(figsize=(8.2,5.0))
    fig.subplots_adjust(left=.235, right=.965, bottom=.14, top=.88)
    style_bars(ax, VIEWS, (-9.2, 28), [-5,0,5,10,15,20,25])
    ax.tick_params(axis="both", labelsize=12)
    ax.legend(handles=[Patch(facecolor=COLORS[m],label=LABELS[m]) for m in ["pdf","cgns"]],loc="lower left",bbox_to_anchor=(0,1.025),ncol=2,frameon=False,fontsize=12)
    data = {}
    for index, method in enumerate(["pdf", "cgns"]):
        values = [float(table[v,method]["relative_smape_reduction_percent"]) for v in VIEWS]
        data[method] = values
        ys = np.arange(6)+(index-.5)*.48
        ax.barh(ys, values, height=.265, color=COLORS[method], zorder=3)
        for y, value in zip(ys, values):
            ax.text(value+(.32 if value>=0 else -.32), y, f"{value:+.3f}%", va="center",
                ha="left" if value>=0 else "right", fontsize=11.5, color=NAVY)
    ax.set_xlabel("Relative SMAPE reduction vs. baseline (%)", fontsize=12, labelpad=7)
    save(fig,"quality-improvement.png","Six-view paired relative SMAPE reduction bars; positive is better.",[summary_path],
        {"values_percent": data, "view_order": VIEWS, "formula":"100 * (baseline_smape - method_smape) / baseline_smape",
         "baseline_method":"temporal-on", "unit":"percent (relative reduction), not percentage points"})

def timing(summary_path, table):
    views = [v for v in VIEWS if v != "emerald-square"]
    fig, ax = plt.subplots(figsize=(11,4))
    fig.subplots_adjust(left=.196, right=.959, bottom=.23, top=.84)
    style_bars(ax, views, (0,32), [0,5,10,15,20,25,30])
    data = {}
    for index, method in enumerate(["pdf", "cgns"]):
        values = [100*(float(table[v,method]["gpu_frame_ms"])/float(table[v,"temporal-on"]["gpu_frame_ms"])-1) for v in views]
        data[method] = values
        ys = np.arange(5)+(index-.5)*.48
        ax.barh(ys, values, height=.265, color=COLORS[method], zorder=3)
        for y, value in zip(ys,values):
            ax.text(value+.28,y,f"+{value:.2f}%",va="center",fontsize=13)
    ax.set_xlabel("GPU frame-time overhead vs. baseline (%)", fontsize=14, labelpad=7)
    save(fig,"timing-overhead.png","Five eligible views: PDF/CGNS GPU frame-time overhead from onFrameRender.",[summary_path],
        {"values_percent":data,"view_order":views,"formula":"100 * (method_gpu_frame_ms / baseline_gpu_frame_ms - 1)",
         "baseline_method":"temporal-on","excluded_views":["emerald-square"],"unit":"percent overhead",
         "comparison":"equal sampling settings, not equal-time quality"})

def stage_overview(summary_path, table):
    path = track(SOURCE / "statistics/stage-summary.csv")
    with path.open(newline="", encoding="utf-8-sig") as f:
        raw = list(csv.DictReader(f))
    stage_table = {(r["view"],r["method"]):r for r in raw}
    views = [v for v in VIEWS if v != "emerald-square"]
    methods = ["temporal-on","pdf","cgns"]
    method_labels = {"temporal-on":"Ordinary","pdf":"PDF","cgns":"CGNS"}
    fields = ["initial_ms","temporal_ms","spatial_ms","other_frame_ms"]
    labels = ["Initial sampling","Temporal reuse","Spatial reuse","Other frame"]
    stage_colors = [NAVY,"#8da6b0",COLORS["cgns"],"#d9e0dc"]
    text_colors = ["white",NAVY,"white",NAVY]
    rows = []
    sum_errors = []
    for view in views:
        for method in methods:
            row = stage_table[view,method]
            frame = float(row["frame_ms"])
            values = [float(row[k]) for k in fields]
            difference = sum(values)-frame
            sum_errors.append(abs(difference))
            assert abs(difference)<1e-10
            assert abs(frame-float(table[view,method]["gpu_frame_ms"]))<1e-10
            assert min(values)>=0
            rows.append({"view":view,"method":method,"frame_ms":frame,
                **dict(zip(fields,values)),"stage_sum_minus_frame_ms":difference})
    assert len(rows)==15
    fig, ax = plt.subplots(figsize=(11,4.5))
    fig.subplots_adjust(left=.25,right=.956,bottom=.21,top=.86)
    positions = np.array([group*4+method for group in range(5) for method in range(3)])
    ax.set_ylim(18.8,-.8)
    ax.set_xlim(0,84)
    ax.set_yticks(positions,[method_labels[r["method"]] for r in rows],fontsize=9.5)
    ax.tick_params(axis="y",length=0,pad=7)
    ax.set_xticks(np.arange(0,81,10),[str(x) for x in range(0,81,10)],fontsize=11)
    ax.tick_params(axis="x",length=0,pad=6)
    ax.spines[["left","top","right"]].set_visible(False)
    ax.spines["bottom"].set_color("#b3bdbc")
    ax.grid(axis="x",color="#dbe1df",lw=.7)
    ax.set_axisbelow(True)
    left = np.zeros(15)
    for field,label,color,text_color in zip(fields,labels,stage_colors,text_colors):
        values = np.array([r[field] for r in rows])
        ax.barh(positions,values,height=.78,left=left,color=color,edgecolor=BG,linewidth=.5,label=label,zorder=3)
        for y,x,value in zip(positions,left,values):
            ax.text(x+value/2,y,f"{value:.1f}",ha="center",va="center",fontsize=9.5,color=text_color)
        left += values
    for y,row in zip(positions,rows):
        ax.text(row["frame_ms"]+.55,y,f"{row['frame_ms']:.1f}",ha="left",va="center",fontsize=10.5)
    for group,view in enumerate(views):
        y=group*4+1
        ax.text(-.33,y,TITLES[view],transform=ax.get_yaxis_transform(),ha="left",va="center",fontsize=12,fontweight="semibold")
        if group<4:
            ax.axhline(group*4+3,color="#dbe1df",lw=.8,xmin=-.33,clip_on=False)
    ax.set_xlabel("Full GPU frame time (ms)",fontsize=12.5,labelpad=7)
    fig.legend(handles=[Patch(facecolor=c,label=l) for c,l in zip(stage_colors,labels)],
        loc="upper right",bbox_to_anchor=(.961,.995),ncol=4,frameon=False,fontsize=11.5,
        handlelength=1.25,columnspacing=1.6)
    fig.text(.018,.947,"FIVE ELIGIBLE VIEWS",fontsize=10.5,fontweight="semibold")
    fig.text(.25,.894,"Segment values: ms",fontsize=10.5)
    fig.text(.956,.894,"Totals at right · GPU onFrameRender",ha="right",fontsize=10.5)
    fig.text(.5,.021,"Temporal on · Seed 0 · Frames 41–104 · Other completes full frame; nested CGNS cache/selection is already in spatial",ha="center",fontsize=10.3)
    baseline_initial_shares=[100*float(stage_table[v,"temporal-on"]["initial_ms"])/float(stage_table[v,"temporal-on"]["frame_ms"]) for v in views]
    assert all(float(stage_table[v,"temporal-on"]["initial_ms"])>max(float(stage_table[v,"temporal-on"][f]) for f in ["temporal_ms","spatial_ms"]) for v in views)
    spatial_deltas=[float(stage_table[v,"cgns"]["spatial_ms"])-float(stage_table[v,"temporal-on"]["spatial_ms"]) for v in views]
    save(fig,"stage-overview.png","High-level full-GPU-frame stage composition, five views × Ordinary/PDF/CGNS.",[summary_path,path],
        {"unit":"milliseconds","view_order":views,"method_order":methods,"stage_fields":fields,
         "stage_colors":dict(zip(fields,stage_colors)),"rows":rows,
         "maximum_absolute_sum_error_ms":max(sum_errors),
         "baseline_initial_sampling_share_percent":baseline_initial_shares,
         "baseline_initial_largest_of_three_high_level_stages_in_all_views":True,
         "cgns_spatial_delta_ms":spatial_deltas,"excluded_views":["emerald-square"],
         "nested_cost_policy":"CGNS cache/selection is included in spatial; never added as another segment",
         "other_frame_definition":"frame_ms minus initial_ms minus temporal_ms minus spatial_ms"})

def emerald(summary_path, table):
    path = track(SOURCE / "data/emerald-square/arrays.npz")
    with np.load(path) as a:
        maps = {m:a[m+"_change_pp"].copy() for m in ["pdf","cgns"]}
        checks={}
        for method in ["pdf","cgns"]:
            baseline=float(table["emerald-square","temporal-on"]["smape_percent"])
            global_delta=float(table["emerald-square",method]["smape_percent"])-baseline
            mean_delta=float(maps[method].mean(dtype=np.float64))
            assert abs(global_delta-mean_delta)<1e-6
            reconstructed=a[method+"_smape"]-a["temporal-on_smape"]
            assert np.max(np.abs(reconstructed-maps[method]))<1e-5
            checks[method]={"mean_change_pp":mean_delta,"summary_change_pp":global_delta,
                "fraction_below_minus20":float(np.mean(maps[method]<-20)),
                "fraction_above_plus20":float(np.mean(maps[method]>20))}
    fig=plt.figure(figsize=(11,4))
    cmap=plt.get_cmap("RdBu_r").copy()
    for i,method in enumerate(["pdf","cgns"]):
        ax=fig.add_axes([.015+i*.5,.190,.47,.66125])
        ax.imshow(maps[method],cmap=cmap,vmin=-20,vmax=20,interpolation="nearest")
        ax.set_axis_off()
        fig.text(.25+i*.5,.965,f"{LABELS[method]} − baseline",ha="center",va="top",fontsize=16,fontweight="bold")
        fig.text(.25+i*.5,.865,f"Mean change: {checks[method]['mean_change_pp']:+.3f} percentage points",ha="center",fontsize=10.5)
    cbax=fig.add_axes([.30,.108,.40,.026])
    cb=fig.colorbar(ScalarMappable(norm=Normalize(-20,20),cmap=cmap),cax=cbax,orientation="horizontal",ticks=[-20,-10,0,10,20])
    cb.ax.set_xticklabels(["−20","−10","0","+10","+20"])
    cb.ax.tick_params(labelsize=10,length=0,pad=3)
    cb.outline.set_visible(False)
    fig.text(.285,.119,"Lower error",ha="right",va="center",color="#2166ac",fontsize=13)
    fig.text(.715,.119,"Higher error",ha="left",va="center",color="#b2182b",fontsize=13)
    fig.text(.5,.013,"SMAPE change (percentage points) · Shared display cap ±20 · 4 seeds × 16 frames",ha="center",fontsize=10.5)
    save(fig,"emerald-change-pp.png","Emerald Square error difference maps; blue lower error, red higher error.",[summary_path,path],
        {"array_keys":["pdf_change_pp","cgns_change_pp"],"display_range_pp":[-20,20],"colormap":"RdBu_r",
         "unit":"percentage points (method SMAPE minus baseline SMAPE)","checks":checks})

def font(size, bold=False):
    path=Path("C:/Windows/Fonts")/("seguisb.ttf" if bold else "segoeui.ttf")
    return ImageFont.truetype(str(path),size)

def montage():
    paths=[track(SOURCE/"images"/v/"reference.png") for v in VIEWS]
    # All frozen images are 16:9; do not crop or stretch their field of view.
    canvas=Image.new("RGB",(1600,1538),BG)
    draw=ImageDraw.Draw(canvas)
    for i,(view,path) in enumerate(zip(VIEWS,paths)):
        x=24+(i%2)*784
        y=24+(i//2)*502
        draw.text((x,y-4),TITLES[view],font=font(39,True),fill=NAVY)
        with Image.open(path) as im:
            assert im.size==(1920,1080)
            im=im.convert("RGB").resize((768,432),Image.Resampling.LANCZOS)
            canvas.paste(im,(x,y+54))
    dest=OUTPUT/"scene-montage.png"
    canvas.save(dest)
    record(dest,"Six full reference images in a 2-column × 3-row scene cover montage.",paths,
        {"view_order":VIEWS,"source_aspect_ratio":"16:9","resampling":"Lanczos; no crop; original field of view preserved"})

def crops():
    methods=["temporal-on","pdf","cgns","reference"]
    paths=[track(SOURCE/"images/emerald-square"/(m+"-frame48-seed0.png" if m!="reference" else "reference.png")) for m in methods]
    selection=track(SOURCE/"data/strips-presentation.json")
    strip=json.loads(selection.read_text(encoding="utf-8"))["emerald-square"][0]
    box=(strip["x"],strip["y"]-64,strip["x"]+128,strip["y"]+64)
    canvas=Image.new("RGB",(1600,540),BG)
    draw=ImageDraw.Draw(canvas)
    titles=["Baseline","PDF Similarity","CGNS","Reference"]
    for i,(title,path) in enumerate(zip(titles,paths)):
        x=24+i*394
        draw.text((x+188,8),title,font=font(37,True),fill=NAVY,anchor="mt")
        with Image.open(path) as im:
            crop=im.convert("RGB").crop(box).resize((376,376),Image.Resampling.NEAREST)
        canvas.paste(crop,(x,63))
    draw.text((800,460),"Emerald Square · Seed 0 · Frame 48 · Same 128 × 128 crop",font=font(31),fill=NAVY,anchor="mt")
    draw.text((800,503),"Illustrative gain-selected crop A; reference shown for visual context",font=font(25),fill=NAVY,anchor="mt")
    dest=OUTPUT/"emerald-frame48-crops.png"
    canvas.save(dest)
    record(dest,"Emerald Square same-location RGB crops, seed 0 frame 48; all three methods and reference.",paths+[selection],
        {"crop_xyxy":list(box),"source_crop_size_px":[128,128],"selection":"Frozen presentation strip A, gain-selected; illustrative, not representative unbiased selection",
         "resampling":"nearest neighbor","display_transform":"already frozen PNG display transform; unchanged"})

def appendix():
    copies={"timing-detail.png":"timing-detail.png",
        "covariance-summary.png":"covariance-summary.png",
        "temporal-ablation.png":"temporal-ablation.png",
        "emerald-square/temporal-strips.png":"appendix-emerald-temporal-strips.png",
        "classroom/temporal-strips.png":"classroom-temporal-strips.png",
        "emerald-square/spatial-strips.png":"appendix-emerald-spatial-strips.png",
        "emerald-square/temporal-covariance.png":"appendix-emerald-temporal-covariance.png",
        "emerald-square/spatial-covariance.png":"appendix-emerald-spatial-covariance.png"}
    for source_name,dest_name in copies.items():
        source=track(SOURCE/"figures"/(source_name if "/" in source_name else "overview/"+source_name))
        dest=OUTPUT/dest_name
        shutil.copyfile(source,dest)
        assert sha256(source)==sha256(dest)
        record(dest,"Unmodified frozen analysis appendix figure.",[source],{"operation":"byte-for-byte copy"})

def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    MANIFEST.parent.mkdir(parents=True,exist_ok=True)
    track(SOURCE/"analysis-report.md")
    summary_path,table=read_summary()
    quality(summary_path,table)
    timing(summary_path,table)
    stage_overview(summary_path,table)
    emerald(summary_path,table)
    montage()
    crops()
    appendix()
    for name,details in INPUTS.items():
        assert sha256(REPO/name)==details["sha256"],f"Source changed during build: {name}"
    payload={"schema_version":1,"purpose":"Derived static final-presentation figures; frozen analysis history preserved",
        "source_directory":relative(SOURCE),"build_script":relative(Path(__file__).resolve()),
        "build_script_sha256":sha256(Path(__file__).resolve()),
        "style":{"font":"Arial, Arial fallback","navy":NAVY,"teal":COLORS["cgns"],"purple":COLORS["pdf"],"method_colors":COLORS,"background":BG},
        "source_unchanged_after_build":True,"inputs":INPUTS,"assets":ASSETS,
        "software":{"numpy":np.__version__,"matplotlib":matplotlib.__version__,"pillow":Image.__version__}}
    MANIFEST.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    for asset in ASSETS:
        print(f"{asset['width_px']}x{asset['height_px']} {asset['path']}")
    print(f"Manifest: {relative(MANIFEST)}; {len(ASSETS)} assets; {len(INPUTS)} unchanged source inputs")

if __name__=="__main__":
    main()

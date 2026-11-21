import json, numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.dates as mdates
RED, BLK, GRY = "#C8102E", "#1A1A1A", "#9A9A9A"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 20, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.titleweight": "bold", "axes.titlesize": 22})
o = json.load(open("results.json"))
d = pd.read_excel("AQI_Ohio_2022_2026_with_weather.xlsx").rename(columns={"county Name": "County"})
m = d.Date.dt.month
d["Season"] = np.select([m.isin([12, 1, 2]), m.isin([3, 4, 5]), m.isin([6, 7, 8])], ["Winter", "Spring", "Summer"], "Fall")

# ---------- Descriptive figure (placed 10.6 in wide) ----------
fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.6, 5.2), gridspec_kw={"width_ratios": [1.8, 1]})
mon = (d.set_index("Date").groupby("County").AQI.resample("MS").agg(["mean", "count"])
       .reset_index().rename(columns={"mean": "AQI"}))
mon = mon[mon["count"] >= 10]          # drop the one-day stub month (May 31 2026 only has 1 obs for some counties)
state = d.set_index("Date").AQI.resample("MS").mean()
for c, col, lab in [("Cuyahoga", RED, "Cuyahoga"), ("Belmont", GRY, "Belmont")]:
    s = mon[mon.County == c]; a1.plot(s.Date, s.AQI, color=col, lw=2.6, label=lab)
a1.plot(state.index, state.values, color=BLK, lw=3.6, label="Ohio avg.")
a1.annotate("Wildfire smoke,\nJune 2023", xy=(pd.Timestamp("2023-06-01"), state["2023-06-01"]),
            xytext=(pd.Timestamp("2023-12-01"), 84), fontsize=17, arrowprops=dict(arrowstyle="->", color=BLK, lw=2))
a1.set_ylim(-9, 106); a1.set_yticks([20, 40, 60, 80, 100]); a1.set_ylabel("Monthly mean AQI")
a1.set_title("Monthly AQI", loc="left")
a1.legend(frameon=False, fontsize=17, loc="lower center", ncol=3, handlelength=1.1, columnspacing=1.0,
          bbox_to_anchor=(0.5, -0.02))
a1.xaxis.set_major_locator(mdates.YearLocator()); a1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
a1.grid(axis="y", alpha=.3)
order = ["Winter", "Spring", "Summer", "Fall"]
bp = a2.boxplot([d.loc[d.Season == s, "AQI"] for s in order], tick_labels=["Win", "Spr", "Sum", "Fall"], showfliers=False,
                patch_artist=True, widths=.6, medianprops=dict(color="white", lw=3))
for b, s in zip(bp["boxes"], order): b.set_facecolor(RED if s == "Summer" else BLK)
a2.set_title("AQI by season", loc="left"); a2.set_ylabel("Daily AQI"); a2.grid(axis="y", alpha=.3)
fig.tight_layout(); fig.savefig("fig_desc.png", dpi=300); plt.close(fig)

# ---------- Predictive figure (placed ~5.2 in wide, next to the table) ----------
lab = {"lag0": "AQI today", "Wind Gust Max (mph)": "Max wind gust", "doy_cos": "Day of year", "county_mean": "County mean",
       "Solar Radiation (MJ/m²)": "Solar rad.", "Temp Mean (°F)": "Mean temp", "Wind Speed Max (mph)": "Max wind",
       "Precipitation (in)": "Precip.", "County": "County", "roll7": "7-day mean", "roll3": "3-day mean"}
imp = pd.Series(o["importance"]).sort_values().tail(6)
fig, ax = plt.subplots(figsize=(5.2, 4.7))
ax.barh([lab.get(i, i) for i in imp.index], imp.values, color=[RED if v == imp.max() else BLK for v in imp.values], height=.7)
for y, v in enumerate(imp.values): ax.text(v + 0.06, y, f"{v:.2f}", va="center", fontsize=18)
ax.set_xlim(0, 4.0); ax.set_xticks([0, 1, 2, 3])
ax.set_xlabel("Importance (RMSE rise)", fontsize=19); ax.set_title("Top 6 features", loc="left", fontsize=22)
ax.tick_params(labelsize=19)
fig.tight_layout(); fig.savefig("fig_imp.png", dpi=300); plt.close(fig)


# ============================
# ADS PMF SCALING WEB APP
# ============================

import streamlit as st
import pandas as pd
import numpy as np
import io
import time

st.set_page_config(
    page_title="ADS PMF Scaling Tool",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ❌ DARK MODE CSS BLOCK REMOVED

st.title("📊 ADS PMF Scaling Web Application")
st.write("Upload your ADS, PMF, and Granular Spec files to perform PMF scaling with granular skip rules.")

# ---------------------------------------------------------
# ✅ Collapsible Upload Section
# ---------------------------------------------------------
with st.expander("📁 Upload Required Files", expanded=True):
    ads_file = st.file_uploader("Upload ADS File (CSV or XLSX)", type=["csv", "xlsx"])
    pmf_file = st.file_uploader("Upload PMF File (XLSX)", type=["xlsx"])
    gran_file = st.file_uploader("Upload Granular Spec File (XLSX)", type=["xlsx"])

if ads_file and pmf_file and gran_file:

    st.success("✅ All files uploaded. Ready to process.")

    progress = st.progress(0)
    status = st.empty()

    # --------------------------------------------------
    # STEP 1 — Load ADS
    # --------------------------------------------------
    status.write("Loading ADS file...")
    if ads_file.name.endswith(".csv"):
        ads_df = pd.read_csv(ads_file, dtype=str)
    else:
        ads_df = pd.read_excel(ads_file, dtype=str)

    progress.progress(10)

    import os
    from datetime import date
    ads_filename = os.path.splitext(ads_file.name)[0]
    today_str = date.today().isoformat()

    scaled_ads_filename = f"{ads_filename}_Scaled_{today_str}.csv"
    log_filename = f"{ads_filename}_Logs_{today_str}.xlsx"

    ads_df.columns = [c.strip() for c in ads_df.columns]

    geo_col = next((c for c in ads_df.columns if c.upper() == "GEOGRAPHY"), None)
    season_candidates = ["SEASON", "PERIOD_DEFINITION", "TIME_PERIODS"]
    season_col = next((c for c in ads_df.columns if c.upper() in season_candidates), None)

    if geo_col is None or season_col is None:
        st.error("❌ ADS must contain Geography and Season column.")
        st.stop()

    ads_work = pd.DataFrame()
    ads_work["_G"] = ads_df[geo_col].str.upper().str.strip()
    ads_work["_S"] = ads_df[season_col].str.upper().str.strip()

    progress.progress(20)
    status.write("Loading PMF multipliers...")

    # --------------------------------------------------
# 🌍 Geography Normalization Helper
# --------------------------------------------------
    def normalize_geo(name: str):
        """Treat BOSE.COM, BOSE_COM, and BOSE COM as identical."""
        return str(name).strip().upper().replace(".", "").replace("_", "").replace(" ", "")


    # --------------------------------------------------
    # STEP 2 — PMF
    # --------------------------------------------------
    pmf = pd.read_excel(pmf_file, sheet_name="PMF", dtype=str)
    pmf.columns = [c.upper() for c in pmf.columns]

    if "SEASON" not in pmf.columns:
        if "PERIOD MAPPING" in pmf.columns:
            pmf.rename(columns={"PERIOD MAPPING": "SEASON"}, inplace=True)
        else:
            st.error("❌ PMF must contain SEASON.")
            st.stop()

    pmf["GEOGRAPHY"] = pmf["GEOGRAPHY"].str.upper().str.strip()
    pmf["SEASON"] = pmf["SEASON"].str.upper().str.strip()

    ads_pmf_cols = [c for c in ads_df.columns if "_PMF" in c.upper()]
    pmf_vars = [c for c in pmf.columns if "_PMF" in c]
    common = [c for c in ads_pmf_cols if c.upper() in pmf_vars]

    pmf_long = pmf[["GEOGRAPHY", "SEASON"] + common].melt(
        id_vars=["GEOGRAPHY", "SEASON"],
        var_name="VARIABLE",
        value_name="PMF_MULT"
    )
    pmf_long["VARIABLE"] = pmf_long["VARIABLE"].str.upper()
    pmf_long["PMF_MULT"] = pd.to_numeric(pmf_long["PMF_MULT"], errors="coerce")

    pmf_dict = {
       (normalize_geo(g), str(s).strip().upper(), str(v).strip().upper()): m
       for g, s, v, m in pmf_long[["GEOGRAPHY", "SEASON", "VARIABLE", "PMF_MULT"]].itertuples(index=False)
    }


    progress.progress(40)
    status.write("Loading Granular Spec skip logic...")

    # --------------------------------------------------
    # STEP 2.5 — Skip Rules
    # --------------------------------------------------
    gran_xl = pd.ExcelFile(gran_file)
    map_df = pd.read_excel(gran_file, sheet_name="MAP", dtype=str)
    map_df.columns = [c.upper() for c in map_df.columns]

    map_df["GEOGRAPHY"] = map_df["GEOGRAPHY"].str.upper().str.strip()
    map_df["MAP"] = map_df["MAP"].str.upper().str.strip()

    geo2map = map_df.set_index("GEOGRAPHY")["MAP"].to_dict()
    ads_work["_MAP"] = ads_work["_G"].apply(normalize_geo).map({normalize_geo(k): v for k, v in geo2map.items()})


    skip_triples = set()
    import re
    season_pattern = re.compile(r"^S\d\s20\d{2}$")

    for code in map_df["MAP"].unique():
        sheet = str(code)
        if sheet not in gran_xl.sheet_names:
            continue

        gdf = pd.read_excel(gran_file, sheet_name=sheet, dtype=str)
        gdf = gdf.iloc[:, :4]
        gdf.columns = [c.upper() for c in gdf.columns]

        if "VARIABLE" not in gdf.columns or "CONTRIBUTION" not in gdf.columns:
            continue

        gdf["VARIABLE"] = gdf["VARIABLE"].str.upper().str.strip()
        gdf["CONTRIBUTION"] = gdf["CONTRIBUTION"].str.upper().str.strip()

        valid = gdf["CONTRIBUTION"].str.match(season_pattern, na=False)
        gdf_valid = gdf[valid]

        for _, row in gdf_valid.iterrows():
            skip_triples.add((f"{row['VARIABLE']}_PMF", row["CONTRIBUTION"], sheet))

    progress.progress(60)
    status.write("Applying PMF multipliers...")

    # --------------------------------------------------
    # STEP 3 — Apply Multipliers
    # --------------------------------------------------
    result_ads = ads_df.copy()
    skipped_rows = []
    multiplied_rows = []

    G = ads_work["_G"].values
    S = ads_work["_S"].values
    M = ads_work["_MAP"].values

    def get_base_pmf(c):
        name = c.upper()
        i = name.find("_PMF")
        return name if i == -1 else name[: i + 4]

    for col in common:
        col_u = col.upper()
        col_base = get_base_pmf(col_u)

        column_vals = pd.to_numeric(result_ads[col], errors="coerce")

        for i in range(len(result_ads)):

            if (col_base, S[i], M[i]) in skip_triples:
                skipped_rows.append((i, G[i], S[i], M[i], col))
                continue

            mult = pmf_dict.get((normalize_geo(G[i]), S[i], col_u))
            if mult is None or pd.isna(column_vals.iat[i]):
                continue

            updated = column_vals.iat[i] * mult
            result_ads.at[i, col] = updated

            multiplied_rows.append(
                (i, G[i], S[i], M[i], col, column_vals.iat[i], mult, updated)
            )

    progress.progress(90)
    status.write("Preparing logs...")

    skipped_df = pd.DataFrame(skipped_rows, columns=["Row", "Geo", "Season", "MAP", "Variable"])
    multiplied_df = pd.DataFrame(multiplied_rows,
                                 columns=["Row", "Geo", "Season", "MAP", "Variable", "Original", "Multiplier", "Updated"])

    log_output = io.BytesIO()
    with pd.ExcelWriter(log_output, engine="openpyxl") as writer:
        skipped_df.to_excel(writer, sheet_name="Skipped", index=False)
        multiplied_df.to_excel(writer, sheet_name="Multiplied", index=False)

    progress.progress(100)
    status.write("✅ Completed!")

    st.success("✅ PMF Scaling Completed!")

    # --------------------------------------------------
    # ✅ DOWNLOAD SECTION
    # --------------------------------------------------
    with st.expander("📥 Download Outputs", expanded=True):

        st.download_button(
            label="⬇️ Download Scaled ADS CSV",
            data=result_ads.to_csv(index=False).encode(),
            file_name=scaled_ads_filename,
            mime="text/csv"
        )

        st.download_button(
            label="⬇️ Download Logs (Excel)",
            data=log_output.getvalue(),
            file_name=log_filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

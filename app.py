# ============================
# ADS PMF SCALING WEB APP
# ============================

import streamlit as st
import pandas as pd
import numpy as np
import io
import time
import os
from datetime import date
import re

# ---------------------------------------------------------
# 1. PAGE CONFIGURATION
# ---------------------------------------------------------
st.set_page_config(
    page_title="ADS PMF Scaling Tool",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------
# 2. CUSTOM CSS: CENTERED JUGGLING LOADER
# ---------------------------------------------------------
st.markdown("""
<style>
    /* The Overlay (Background) */
    .bose-loader-overlay {
        position: fixed;
        top: 0;
        left: 0;
        width: 100vw;
        height: 100vh;
        background: rgba(255, 255, 255, 0.95);
        z-index: 999999;
        display: flex;
        justify-content: center; 
        align-items: center;
        flex-direction: column;
        backdrop-filter: blur(4px);
    }

    /* Container for the letters */
    .bose-juggler {
        display: flex;
        justify-content: center;
        align-items: flex-end;
        gap: 15px;
        height: 100px;
        margin-bottom: 20px;
    }

    /* Individual Letters */
    .bose-letter {
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        font-weight: 900;
        font-size: 80px; 
        color: #000000;
        line-height: 1;
        animation: juggle 1.4s ease-in-out infinite;
    }

    /* Staggered Delay for the "Wave/Juggle" Effect */
    .bose-letter:nth-child(1) { animation-delay: 0.0s; }
    .bose-letter:nth-child(2) { animation-delay: 0.15s; }
    .bose-letter:nth-child(3) { animation-delay: 0.3s; }
    .bose-letter:nth-child(4) { animation-delay: 0.45s; }

    /* Status Text */
    .bose-status {
        color: #333; 
        font-family: sans-serif;
        font-size: 18px;
        font-weight: 600;
        letter-spacing: 2px;
        text-transform: uppercase;
        animation: fade 1.5s ease-in-out infinite alternate;
    }

    /* Keyframes: The Jump */
    @keyframes juggle {
        0%, 100% { transform: translateY(0); }
        50% { transform: translateY(-40px); }
    }
    
    /* Keyframes: Text pulsing */
    @keyframes fade {
        from { opacity: 0.6; }
        to { opacity: 1; }
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 3. HELPER FUNCTIONS
# ---------------------------------------------------------
def normalize_geo(name: str):
    """Normalizes geography names to handle mismatch (e.g. 'Bose UK' vs 'BOSE_UK')"""
    if pd.isna(name): return ""
    return str(name).strip().upper().replace(".", "").replace("_", "").replace(" ", "")

# ---------------------------------------------------------
# 4. SESSION STATE INITIALIZATION
# ---------------------------------------------------------
if 'processed_data' not in st.session_state:
    st.session_state.processed_data = None
if 'processed_logs' not in st.session_state:
    st.session_state.processed_logs = None
if 'file_signatures' not in st.session_state:
    st.session_state.file_signatures = None

# ---------------------------------------------------------
# 5. MAIN APP LAYOUT
# ---------------------------------------------------------
st.title("📊 ADS PMF Scaling Web Application")
st.write("Upload your ADS, PMF, Granular Spec, and Main Spec files to perform PMF scaling.")

# --- FILE UPLOAD SECTION ---
with st.expander("📁 Upload Required Files", expanded=True):
    ads_file = st.file_uploader("1. Upload ADS File (CSV or XLSX)", type=["csv", "xlsx"])
    pmf_file = st.file_uploader("2. Upload PMF File (XLSX)", type=["xlsx"])
    gran_file = st.file_uploader("3. Upload Granular Spec File (XLSX)", type=["xlsx"])
    main_spec_file = st.file_uploader("4. Upload Main Spec File (XLSX)", type=["xlsx"])

# Check if new files are uploaded to reset state
current_files = [ads_file, pmf_file, gran_file, main_spec_file]
if any(current_files) and current_files != st.session_state.file_signatures:
    st.session_state.processed_data = None
    st.session_state.file_signatures = current_files

# --- MAIN LOGIC BLOCK ---
if all(current_files):

    # 1. READ MAIN SPEC
    try:
        xl = pd.ExcelFile(main_spec_file)
        sheet_name = next((s for s in xl.sheet_names if "model" in s.lower()), xl.sheet_names[0])
        
        # Smart Header Detection
        preview = pd.read_excel(main_spec_file, sheet_name=sheet_name, nrows=50, header=None)
        header_row_idx = None
        for i, row in preview.iterrows():
            cells = [str(x).strip().lower() for x in row.fillna("")]
            if any("variable" in c for c in cells) and any("type" in c for c in cells):
                header_row_idx = i
                break
        
        if header_row_idx is None:
            st.error("❌ Could not auto-detect header row in Main Spec.")
            st.stop()

        ms_df = pd.read_excel(main_spec_file, sheet_name=sheet_name, header=header_row_idx, dtype=str)
        ms_df.columns = [str(c).strip().upper() for c in ms_df.columns]
        
        type_col = next((c for c in ms_df.columns if c in ["TYPE", "TYPES", "VARIABLE TYPE"]), None)
        var_col = next((c for c in ms_df.columns if c in ["VARIABLE", "VARIABLES", "VARIABLE NAME", "VAR NAME"]), None)
        
        if not type_col or not var_col:
            st.error("❌ Main Spec missing 'Type' or 'Variable' columns.")
            st.stop()
            
        available_types = sorted(ms_df[type_col].dropna().unique().tolist())
        var_to_type = dict(zip(ms_df[var_col].str.upper().str.strip(), ms_df[type_col]))

        # --- CONFIGURATION UI ---
        st.divider()
        st.subheader("⚙️ Configuration")
        
        c1, c2 = st.columns([1, 2])
        
        with c1:
            selected_type_category = st.radio("Select Variable Type:", ["All"] + available_types)
        
        with c2:
            st.markdown("##### 🎯 Tolerance Settings")
            st.caption("Multiplication is **SKIPPED** if the PMF multiplier falls strictly between Min and Max.")
            
            tolerance_map = {}
            types_to_configure = available_types if selected_type_category == "All" else [selected_type_category]
            
            with st.container(height=200):
                for t in types_to_configure:
                    cc1, cc2 = st.columns(2)
                    t_min = cc1.number_input(f"Min ({t})", value=0.95, step=0.01, format="%.2f", key=f"min_{t}")
                    t_max = cc2.number_input(f"Max ({t})", value=1.05, step=0.01, format="%.2f", key=f"max_{t}")
                    tolerance_map[t] = (t_min, t_max)
            
            # --- NEW UPPER LIMIT SETTING ---
            st.divider()
            st.markdown("##### 🛑 Upper Limit Threshold")
            st.caption("Multiplication is **SKIPPED** if the PMF multiplier is $\ge$ this value.")
            max_multiplier_limit = st.number_input("Absolute Maximum Multiplier", value=100.0, step=1.0, format="%.2f")

        # --- PROCESS BUTTON ---
        st.divider()
        
        if st.session_state.processed_data is None:
            start_process = st.button("🚀 Start PMF Scaling", type="primary", use_container_width=True)
            
            if start_process:
                # 🌀 SHOW CENTERED JUGGLING LOADER
                loader_placeholder = st.empty()
                loader_placeholder.markdown("""
                <div class="bose-loader-overlay">
                    <div class="bose-juggler">
                        <span class="bose-letter">B</span>
                        <span class="bose-letter">O</span>
                        <span class="bose-letter">S</span>
                        <span class="bose-letter">E</span>
                    </div>
                    <div class="bose-status">Processing Data...</div>
                </div>
                """, unsafe_allow_html=True)

                # Give browser time to render animation
                time.sleep(0.8)

                try:
                    # ==========================================
                    # 🚀 CORE PROCESSING LOGIC
                    # ==========================================
                    
                    # 1. Load ADS
                    if ads_file.name.endswith(".csv"):
                        ads_df = pd.read_csv(ads_file, dtype=str)
                    else:
                        ads_df = pd.read_excel(ads_file, dtype=str)
                    
                    ads_filename = os.path.splitext(ads_file.name)[0]
                    today_str = date.today().isoformat()
                    
                    ads_df.columns = [c.strip() for c in ads_df.columns]
                    geo_col = next((c for c in ads_df.columns if c.upper() == "GEOGRAPHY"), None)
                    season_col = next((c for c in ads_df.columns if c.upper() in ["SEASON", "PERIOD_DEFINITION", "TIME_PERIODS"]), None)

                    if not geo_col or not season_col:
                        loader_placeholder.empty()
                        st.error("❌ ADS missing Geography or Season.")
                        st.stop()

                    ads_work = pd.DataFrame()
                    ads_work["_G"] = ads_df[geo_col].str.upper().str.strip()
                    ads_work["_S"] = ads_df[season_col].str.upper().str.strip()

                    # 2. Load PMF
                    pmf = pd.read_excel(pmf_file, sheet_name="PMF", dtype=str)
                    pmf.columns = [c.upper() for c in pmf.columns]
                    if "PERIOD MAPPING" in pmf.columns: pmf.rename(columns={"PERIOD MAPPING": "SEASON"}, inplace=True)
                    
                    pmf_long = pmf.melt(id_vars=["GEOGRAPHY", "SEASON"], var_name="VARIABLE", value_name="PMF_MULT")
                    pmf_long["PMF_MULT"] = pd.to_numeric(pmf_long["PMF_MULT"], errors="coerce")
                    
                    pmf_dict = {
                        (normalize_geo(g), str(s).strip().upper(), str(v).strip().upper()): m
                        for g, s, v, m in pmf_long[["GEOGRAPHY", "SEASON", "VARIABLE", "PMF_MULT"]].itertuples(index=False)
                    }

                    # 3. Load Granular Skip Rules
                    map_df = pd.read_excel(gran_file, sheet_name="MAP", dtype=str)
                    map_df.columns = [c.upper() for c in map_df.columns]
                    geo2map = dict(zip(map_df["GEOGRAPHY"].str.upper().str.strip(), map_df["MAP"].str.upper().str.strip()))
                    ads_work["_MAP"] = ads_work["_G"].apply(normalize_geo).map({normalize_geo(k): v for k, v in geo2map.items()})

                    skip_triples = set()
                    gran_xl = pd.ExcelFile(gran_file)
                    season_pattern = re.compile(r"^S\d\s20\d{2}$")
                    
                    for code in map_df["MAP"].dropna().unique():
                        sheet_code = str(code)
                        if sheet_code in gran_xl.sheet_names:
                            gdf = pd.read_excel(gran_file, sheet_name=sheet_code, dtype=str).iloc[:, :4]
                            gdf.columns = [c.upper() for c in gdf.columns]
                            if "VARIABLE" in gdf.columns and "CONTRIBUTION" in gdf.columns:
                                gdf = gdf[gdf["CONTRIBUTION"].astype(str).str.match(season_pattern, na=False)]
                                for _, row in gdf.iterrows():
                                    skip_triples.add((f"{str(row['VARIABLE']).strip().upper()}_PMF", str(row["CONTRIBUTION"]).strip().upper(), sheet_code))

                    # 4. Apply Multipliers
                    result_ads = ads_df.copy()
                    skipped_rows = []
                    multiplied_rows = []
                    
                    if selected_type_category == "All":
                        allowed_vars = set(ms_df[var_col].str.upper().str.strip())
                    else:
                        allowed_vars = set(ms_df[ms_df[type_col] == selected_type_category][var_col].str.upper().str.strip())

                    common_vars = [c for c in ads_df.columns if "_PMF" in c.upper()]

                    G_arr = ads_work["_G"].values
                    S_arr = ads_work["_S"].values
                    M_arr = ads_work["_MAP"].values

                    for col in common_vars:
                        col_u = col.upper()
                        col_base = col_u.replace("_PMF", "")

                        if selected_type_category != "All" and col_base not in allowed_vars:
                            continue

                        v_type = var_to_type.get(col_base)
                        t_min, t_max = tolerance_map.get(v_type, (0.95, 1.05))

                        col_values = pd.to_numeric(result_ads[col], errors="coerce")
                        
                        for i in range(len(result_ads)):
                            season = S_arr[i]
                            map_code = M_arr[i]
                            geo = G_arr[i]

                            if (col_u, season, map_code) in skip_triples:
                                skipped_rows.append((i, geo, season, map_code, col, "Granular Spec"))
                                continue
                            
                            mult = pmf_dict.get((normalize_geo(geo), season, col_u))

                            if mult is None or pd.isna(col_values.iat[i]):
                                continue

                            # --- NEW UPPER LIMIT CHECK ---
                            if mult >= max_multiplier_limit:
                                skipped_rows.append((i, geo, season, map_code, col, f"Exceeds Limit ({mult:.3f})"))
                                continue

                            if t_min < mult < t_max:
                                skipped_rows.append((i, geo, season, map_code, col, f"Tolerance ({mult:.3f})"))
                                continue

                            updated = col_values.iat[i] * mult
                            result_ads.at[i, col] = updated
                            multiplied_rows.append((i, geo, season, map_code, col, col_values.iat[i], mult, updated))
                    
                    # 5. Save Results
                    log_output = io.BytesIO()
                    with pd.ExcelWriter(log_output, engine="openpyxl") as writer:
                        pd.DataFrame(skipped_rows, columns=["Row", "Geo", "Season", "MAP", "Variable", "Reason"]).to_excel(writer, sheet_name="Skipped", index=False)
                        pd.DataFrame(multiplied_rows, columns=["Row", "Geo", "Season", "MAP", "Var", "Orig", "Mult", "New"]).to_excel(writer, sheet_name="Multiplied", index=False)
                    
                    st.session_state.processed_data = result_ads.to_csv(index=False).encode()
                    st.session_state.processed_logs = log_output.getvalue()
                    st.session_state.scaled_filename = f"{ads_filename}_Scaled_{selected_type_category}_{today_str}.csv"
                    st.session_state.log_filename = f"{ads_filename}_Logs_{selected_type_category}_{today_str}.xlsx"

                    loader_placeholder.empty()
                    st.rerun()

                except Exception as e:
                    loader_placeholder.empty()
                    st.error(f"An error occurred: {e}")
                    st.stop()

    except Exception as e:
        st.error(f"Error reading Main Spec: {e}")

# --- DOWNLOAD SECTION ---
if st.session_state.processed_data is not None:
    st.success("✅ Processing Complete!")
    
    with st.expander("📥 Download Outputs", expanded=True):
        col_d1, col_d2 = st.columns(2)
        
        with col_d1:
            st.download_button(
                label="⬇️ Download Scaled ADS (CSV)",
                data=st.session_state.processed_data,
                file_name=st.session_state.scaled_filename,
                mime="text/csv",
                use_container_width=True
            )
        
        with col_d2:
            st.download_button(
                label="⬇️ Download Logs (Excel)",
                data=st.session_state.processed_logs,
                file_name=st.session_state.log_filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
    
    if st.button("🔄 Reset and Start Over"):
        st.session_state.processed_data = None
        st.rerun()

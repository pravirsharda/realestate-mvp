# streamlit_gm_dashboard.py
# Streamlit GM Dashboard — auto-score on upload + PDF report generator
import streamlit as st
import pandas as pd
import io
import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import Paragraph, Table, TableStyle, SimpleDocTemplate, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# Optional password gate via Streamlit Secrets
PASSWORD = st.secrets.get("GM_DASHBOARD_PASSWORD", None)
if PASSWORD:
    pw = st.sidebar.text_input("Enter dashboard password", type="password")
    if pw != PASSWORD:
        st.title("Lead Intelligence — Access Restricted")
        st.write("Please enter the password in the left sidebar to continue.")
        st.stop()

st.set_page_config(layout="wide", page_title="GM Dashboard - Lead Intelligence")
st.title("GM Dashboard — Lead Intelligence")
st.markdown("Upload a campaign CSV (raw or pre-scored). The app will auto-score raw uploads, persist the scored CSV, and let you generate a premium PDF report for the GM.")

# ----------------------------
# Scoring functions (MVP logic)
# ----------------------------
def score_recency(days):
    try:
        days = int(days)
    except:
        return 0
    if days <= 1:
        return 20
    if days <= 7:
        return 15
    if days <= 30:
        return 10
    return 0

def score_frequency(n_searches_7d):
    try:
        n = int(n_searches_7d)
    except:
        return 5
    if n >= 10:
        return 20
    if n >= 5:
        return 15
    if n >= 2:
        return 10
    return 5

def score_budget(min_b, max_b):
    try:
        variance = float(max_b) - float(min_b)
    except:
        return 5
    if variance <= 500000:
        return 15
    if variance <= 1000000:
        return 10
    return 5

def score_project_focus(matches):
    try:
        m = int(matches)
    except:
        return 0
    if m >= 3:
        return 15
    if m == 2:
        return 10
    if m == 1:
        return 5
    return 0

def score_cross_platform(platforms_str):
    if pd.isna(platforms_str) or str(platforms_str).strip() == "":
        return 5
    platforms = [p.strip() for p in str(platforms_str).split(",") if p.strip()]
    if len(platforms) >= 3:
        return 20
    if len(platforms) == 2:
        return 15
    return 5

def score_engagement(viewed_mortgage):
    try:
        v = int(viewed_mortgage)
    except:
        return 5
    return 10 if v == 1 else 5

def device_bonus(device_str):
    d = str(device_str).lower()
    bonus = 0
    if "iphone" in d or "ipad" in d or "ios" in d:
        bonus += 3
    if "macbook" in d or "desktop" in d or "windows" in d:
        bonus += 5
    if "android" in d:
        bonus += 1
    return bonus

def compute_score_row(row):
    r = score_recency(row.get("last_seen_days", "")) 
    f = score_frequency(row.get("searches_last_7d", ""))
    b = score_budget(row.get("budget_min", 0), row.get("budget_max", 0))
    p = score_project_focus(row.get("project_keywords_matches", 0))
    c = score_cross_platform(row.get("platforms", ""))
    e = score_engagement(row.get("viewed_mortgage_calc", 0))
    dev = device_bonus(row.get("device", ""))
    raw_total = r + f + b + p + c + e + dev
    score_val = min(round(raw_total), 100)
    breakdown = {"recency": r, "frequency": f, "budget": b, "project_focus": p, "cross_platform": c, "engagement": e, "device_bonus": dev, "raw_total": raw_total}
    return score_val, breakdown

def tag_from_score(s):
    if s >= 80:
        return "Hot 🔥"
    if s >= 60:
        return "Warm"
    return "Cold"

def reasoning_and_action(row, score, breakdown):
    reasons = []
    if breakdown["recency"] >= 15:
        reasons.append("recent activity")
    if breakdown["frequency"] >= 15:
        reasons.append("high frequency of searches")
    if breakdown["project_focus"] >= 10:
        reasons.append("project-specific interest")
    if breakdown["cross_platform"] >= 15:
        reasons.append("cross-platform engagement")
    if breakdown["engagement"] >= 10:
        reasons.append("engaged with mortgage/CTA")
    if breakdown["device_bonus"] >= 3:
        reasons.append("affluent device signal")
    reason_text = ", ".join(reasons) if reasons else "activity recorded"
    action = "Follow up with a personalized message and ROI details."
    if score >= 85:
        action = "Call immediately during buyer's evening hours; highlight payment plan and priority units."
    elif score >= 70:
        action = "Send WhatsApp with project brochure and ROI comparison; follow up with call in 24-48 hrs."
    elif score >= 60:
        action = "Send targeted email / WhatsApp with similar listings and financing options."
    else:
        action = "Add to nurture drip; retarget with video creatives."
    return reason_text, action

# ----------------------------
# PDF Generation (in-memory)
# ----------------------------
def build_pdf_bytes(df, campaign_title="Campaign Intelligence Report"):
    # Uses reportlab to create a polished PDF in memory
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []

    title_style = styles["Title"]
    title_style.textColor = colors.HexColor("#0ea5a4")
    story.append(Paragraph(campaign_title, title_style))
    story.append(Spacer(1, 12))

    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    story.append(Paragraph(f"<b>Generated:</b> {now}", styles["Normal"]))
    story.append(Spacer(1, 12))

    # Summary: top-level counts
    total_leads = len(df)
    hot = int((df['score'] >= 80).sum())
    warm = int(((df['score'] >= 60) & (df['score'] < 80)).sum())
    cold = int((df['score'] < 60).sum())
    summary_text = f"<b>Summary:</b> Total leads: {total_leads} — Hot: {hot} — Warm: {warm} — Cold: {cold}"
    story.append(Paragraph(summary_text, styles["BodyText"]))
    story.append(Spacer(1, 12))

    # Top project/area breakdown
    story.append(Paragraph("<b>Top Projects / Areas</b>", styles["Heading3"]))
    # compute distribution
    dist = {}
    for a in df['areas'].dropna():
        for part in str(a).split(','):
            k = part.strip()
            if not k:
                continue
            dist[k] = dist.get(k, 0) + 1
    dist_rows = [["Project/Area", "Leads"]]
    for k, v in sorted(dist.items(), key=lambda x: x[1], reverse=True):
        dist_rows.append([k, str(v)])
    if len(dist_rows) == 1:
        dist_rows.append(["(no project tags found)", "0"])
    tbl = Table(dist_rows, hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0ea5a4")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("ALIGN", (0,0), (-1,-1), "LEFT"),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,0), 11),
        ("BOTTOMPADDING", (0,0), (-1,0), 8),
        ("BACKGROUND", (0,1), (-1,-1), colors.whitesmoke),
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 12))

    # Add a short Recommendations section
    story.append(Paragraph("<b>Recommendations</b>", styles["Heading3"]))
    recs = [
        "Prioritize outreach to Hot leads first (score >= 80).",
        "For high-performing projects, reallocate ad spend to the creative that produced higher-scoring leads (A/B test results).",
        "Contact buyers during their local evening hours for best response rates."
    ]
    for r in recs:
        story.append(Paragraph("• " + r, styles["BodyText"]))
    story.append(Spacer(1, 12))

    # Add a small top-N leads table (ID, Name, Location, Score, Tag, Next Action)
    story.append(Paragraph("<b>Top leads (by score)</b>", styles["Heading3"]))
    topn = df.sort_values("score", ascending=False).head(15)[["lead_id","name","location","score","tag","next_action"]]
    table_rows = [["ID","Name","Location","Score","Tag","Next Action"]] + topn.fillna("").values.tolist()
    tbl2 = Table(table_rows, colWidths=[50,120,90,40,60,150])
    tbl2.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0ea5a4")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("GRID", (0,0), (-1,-1), 0.3, colors.grey),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    story.append(tbl2)

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes

# ----------------------------
# Upload / Load / Score logic
# ----------------------------
uploaded = st.file_uploader("Upload raw campaign CSV or a pre-scored scored_leads_output.csv (drag & drop)", type=["csv"])
df = pd.DataFrame()

if uploaded is not None:
    try:
        df = pd.read_csv(uploaded)
    except Exception as e:
        st.error(f"Could not read uploaded CSV: {e}")
        st.stop()

    # If the uploaded file already has a 'score' column, assume it's pre-scored
    if 'score' in df.columns:
        st.success("Uploaded file already contains scores — using uploaded scored file.")
    else:
        # Auto-score each row
        st.info("Uploaded file detected as RAW. Scoring leads now...")
        scored_records = []
        for _, row in df.iterrows():
            # ensure keys exist
            r = row.to_dict()
            sc, breakdown = compute_score_row(r)
            tag = tag_from_score(sc)
            reason_text, action_text = reasoning_and_action(r, sc, breakdown)
            r['score'] = sc
            r['tag'] = tag
            r['reasoning'] = reason_text
            r['next_action'] = action_text
            scored_records.append(r)
        df = pd.DataFrame(scored_records)
        st.success("Scoring complete.")

    # Persist the scored CSV to disk (app directory)
    try:
        df.to_csv("scored_leads_output.csv", index=False)
        st.info("Scored leads saved to scored_leads_output.csv in app directory.")
    except Exception as e:
        st.warning(f"Could not save scored CSV to disk: {e}")

else:
    # No upload provided: attempt to load existing scored file in app dir
    try:
        df = pd.read_csv("scored_leads_output.csv")
        st.info("Loaded existing scored_leads_output.csv from app directory.")
    except Exception:
        df = pd.DataFrame()

if df.empty:
    st.warning("No scored leads found. Upload a scored CSV or a raw campaign CSV to start.")
    st.stop()

# Normalize expected columns
expected_cols = ["lead_id","name","location","device","platforms","areas","budget_min","budget_max",
                 "searches_last_7d","searches_last_30d","last_seen_days","viewed_mortgage_calc",
                 "project_keywords_matches","behavior","score","tag","reasoning","next_action"]
for c in expected_cols:
    if c not in df.columns:
        df[c] = ""

# Sidebar: filtering + export selections
st.sidebar.header("Filters & Export")
min_score = int(st.sidebar.slider("Min Score", 0, 100, 60))
all_areas = sorted({a.strip() for ar in df['areas'].dropna() for a in str(ar).split(',') if a.strip()})
area_filter = st.sidebar.multiselect("Areas / Projects", options=all_areas, default=None)
tag_filter = st.sidebar.multiselect("Tags", options=sorted(df['tag'].unique()), default=None)
top_n = int(st.sidebar.selectbox("Top N leads for package/report", options=[10,25,50,100], index=1))
campaign_title = st.sidebar.text_input("Campaign / Report title", value="Off-Plan Campaign Intelligence")

filtered = df[df['score'].astype(int) >= min_score]
if area_filter:
    filtered = filtered[filtered['areas'].apply(lambda x: any(a in str(x) for a in area_filter))]
if tag_filter:
    filtered = filtered[filtered['tag'].isin(tag_filter)]

st.write(f"Showing {len(filtered)} leads (filtered)")

# Main layout: left table, right detail + distribution + actions
left_col, right_col = st.columns([1.2, 1])

with left_col:
    st.subheader("Leads")
    display_df = filtered[['lead_id','name','location','areas','budget_min','budget_max','device','platforms','score','tag']].copy()
    display_df['budget'] = display_df['budget_min'].fillna(0).astype(int).astype(str) + ' - ' + display_df['budget_max'].fillna(0).astype(int).astype(str)
    display_df = display_df.rename(columns={'lead_id':'ID','name':'Name','location':'Location','areas':'Areas','device':'Device','platforms':'Platforms','score':'Score','tag':'Tag'})
    st.dataframe(display_df[['ID','Name','Location','Areas','budget','Device','Platforms','Score','Tag']], height=480)

    # Save scored CSV button (persist current filtered selection)
    csv_bytes = filtered.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Download filtered CSV", data=csv_bytes, file_name="scored_leads_export.csv", mime="text/csv")
    if st.button("💾 Save current scored CSV to app directory (scored_leads_output.csv)"):
        try:
            # overwrite full scored file with filtered or full df? we save the full scored df to keep all leads
            df.to_csv("scored_leads_output.csv", index=False)
            st.success("Saved scored_leads_output.csv to app directory.")
        except Exception as e:
            st.error(f"Could not save to disk: {e}")

with right_col:
    st.subheader("Lead Details & Distribution")
    selected_options = filtered['lead_id'].tolist()
    if selected_options:
        selected = st.selectbox("Select lead to inspect", options=selected_options)
        if selected:
            row = filtered[filtered['lead_id'] == selected].iloc[0]
            st.markdown(f"**{row['name']}** — {row['location']}  \n**Score:** {row['score']} — **{row['tag']}**")
            st.markdown(f"**Device:** {row.get('device','-')}  \n**Platforms:** {row.get('platforms','-')}  \n**Areas:** {row.get('areas','-')}")
            st.markdown(f"**Last Seen (days):** {row.get('last_seen_days','-')}  \n**Frequency (7d):** {row.get('searches_last_7d','-')}")
            st.markdown("**Behavior summary:**")
            beh = row.get('behavior','')
            if pd.notna(beh) and str(beh).strip():
                parts = [p.strip() for p in str(beh).split("|") if p.strip()]
                for p in parts:
                    st.write("- " + p)
            else:
                st.write("- (no behavior details)")
            st.markdown("**AI Reasoning:**")
            st.write(row.get('reasoning','-'))
            st.markdown("**Next Best Action:**")
            st.write(row.get('next_action','-'))
    else:
        st.info("No leads available to select (check filters).")

    st.markdown("---")
    st.markdown("**Suggested Distribution (by Area/Project)**")
    dist = {}
    for a in filtered['areas'].dropna():
        for part in str(a).split(','):
            k = part.strip()
            if not k:
                continue
            dist[k] = dist.get(k,0) + 1
    if dist:
        dist_df = pd.DataFrame([{'Area':k,'Leads':v} for k,v in dist.items()]).sort_values('Leads', ascending=False)
        st.table(dist_df)
    else:
        st.info("No area/project tags found in filtered leads.")

    # ----------------------------
    # PDF generation & download
    # ----------------------------
    st.markdown("---")
    st.markdown("**Generate Premium PDF Report (for GM)**")
    if st.button("📄 Generate PDF report for filtered leads (Top N)"):
        # Build top-N frame for report
        top_frame = filtered.sort_values("score", ascending=False).head(top_n)
        if top_frame.empty:
            st.warning("No leads in the current filtered set to include in report.")
        else:
            try:
                pdf_bytes = build_pdf_bytes(top_frame, campaign_title)
                ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M")
                filename = f"GM_Report_{ts}.pdf"
                st.download_button("⬇️ Download PDF Report", data=pdf_bytes, file_name=filename, mime="application/pdf")
            except Exception as e:
                st.error(f"Could not generate PDF: {e}")

# End of file

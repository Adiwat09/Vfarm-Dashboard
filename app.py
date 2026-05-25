import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import io

st.set_page_config(
    page_title="V Farm — Inventory Dashboard",
    page_icon="🌽",
    layout="wide",
    initial_sidebar_state="expanded"
)

BP_NAME = {
    'CPF01': 'บางบัวทอง', 'CPF02': 'ขอนแก่น', 'CPF03': 'นครราชสีมา',
    'CPF06': 'มหาชัย', 'CPF07': 'ภูเก็ต', 'CPF08': 'สุวรรณภูมิ',
    'CPF11': 'เชียงใหม่', 'CPF12': 'ชลบุรี', 'CPF15': 'นครสวรรค์',
    'CPF32': 'สุราษฎร์', 'CPF33': 'หาดใหญ่'
}

COLORS = ['#378ADD','#1D9E75','#D85A30','#D4537E','#7F77DD',
          '#639922','#BA7517','#E24B4A','#534AB7','#0F6E56','#888780']

@st.cache_data(show_spinner=False)
def load_data(file_bytes):
    df = pd.read_excel(io.BytesIO(file_bytes), sheet_name='Sheet1')
    mask = df['Posting Date'].apply(lambda x: isinstance(x, str) and '.' in str(x) and len(str(x)) == 8)
    data = df[mask].copy()
    data['Date'] = pd.to_datetime(data['Posting Date'], format='%d.%m.%y')
    data['Qty'] = pd.to_numeric(data['Qty'], errors='coerce')
    data['Price'] = pd.to_numeric(data['Price after Disc.'], errors='coerce')

    bp_rows_idx = df[~mask & df['Posting Date'].notna()].index.tolist()
    bp_map = {}
    for i, idx in enumerate(bp_rows_idx):
        bp_code = df.loc[idx, 'Posting Date']
        next_idx = bp_rows_idx[i+1] if i+1 < len(bp_rows_idx) else len(df)
        for j in range(idx+1, next_idx):
            bp_map[j] = bp_code
    data['BP'] = data.index.map(bp_map)
    data['BP_Name'] = data['BP'].map(BP_NAME).fillna(data['BP'])
    data['DocType'] = data['Document'].str[:2]
    data['Month'] = data['Date'].dt.to_period('M')
    data['Week'] = data['Date'].dt.to_period('W')
    data['Qty_abs'] = data['Qty'].abs()
    data['Value'] = data['Qty_abs'] * data['Price']
    return data

def compute_forecast(monthly_series, n=3):
    vals = monthly_series.values
    if len(vals) < n:
        return np.mean(vals)
    return np.mean(vals[-n:])

def detect_cn_spikes(cn_daily, threshold=10):
    if len(cn_daily) == 0:
        return pd.DataFrame()
    mean = cn_daily['qty'].mean()
    std = cn_daily['qty'].std()
    spikes = cn_daily[cn_daily['qty'] > mean + threshold * std].copy()
    spikes['x_normal'] = (spikes['qty'] / mean).round(1)
    return spikes


# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🌽 V Farm Dashboard")
    st.markdown("---")
    uploaded = st.file_uploader(
        "อัปโหลดไฟล์ Excel",
        type=["xlsx"],
        help="ไฟล์ Inventory Posting List by BP"
    )
    if uploaded:
        st.success(f"✅ โหลดแล้ว: {uploaded.name}")

    st.markdown("---")
    st.markdown("**Custom BP Names** (ถ้ามีสาขาใหม่)")
    custom_bp = st.text_area(
        "รูปแบบ: รหัส=ชื่อ (แต่ละบรรทัด)",
        placeholder="CPF99=สาขาใหม่\nCPF98=สาขา2",
        height=100
    )

if not uploaded:
    st.markdown("## 🌽 V Farm — Inventory & Sales Dashboard")
    st.info("👈 กรุณาอัปโหลดไฟล์ **Inventory Posting List by BP** ที่แถบซ้าย เพื่อเริ่มวิเคราะห์")
    st.markdown("""
    **Dashboard นี้วิเคราะห์อัตโนมัติ:**
    - 📅 ยอดส่งรายวัน / รายสัปดาห์ / รายเดือน
    - 🔮 Forecast เดือนถัดไป (3-Month Moving Average)
    - ↩️ วิเคราะห์สินค้าคืน (CN) และตรวจจับ Spike
    - 🏪 เปรียบเทียบยอดแยก BP และ SKU
    """)
    st.stop()

# ─── Load data ────────────────────────────────────────────────────────────────
with st.spinner("กำลังโหลดและประมวลผลข้อมูล..."):
    if custom_bp.strip():
        for line in custom_bp.strip().split('\n'):
            if '=' in line:
                k, v = line.split('=', 1)
                BP_NAME[k.strip()] = v.strip()
    data = load_data(uploaded.getvalue())

in_data = data[data['DocType'] == 'IN'].copy()
cn_data = data[data['DocType'] == 'CN'].copy()

date_min = data['Date'].min().date()
date_max = data['Date'].max().date()
all_bps = sorted(in_data['BP_Name'].dropna().unique())
all_skus = sorted(in_data['Item No.'].dropna().unique())

# ─── Filters ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("---")
    st.markdown("**ตัวกรอง**")
    sel_bp = st.multiselect("เลือก BP (ว่าง = ทั้งหมด)", all_bps, default=[])
    sel_sku = st.multiselect("เลือก SKU (ว่าง = ทั้งหมด)", all_skus, default=[])
    date_range = st.date_input("ช่วงวันที่", value=(date_min, date_max), min_value=date_min, max_value=date_max)

d_start = pd.Timestamp(date_range[0]) if len(date_range) > 0 else pd.Timestamp(date_min)
d_end = pd.Timestamp(date_range[1]) if len(date_range) > 1 else pd.Timestamp(date_max)

def apply_filter(df):
    f = df[(df['Date'] >= d_start) & (df['Date'] <= d_end)]
    if sel_bp:
        f = f[f['BP_Name'].isin(sel_bp)]
    if sel_sku:
        f = f[f['Item No.'].isin(sel_sku)]
    return f

in_f = apply_filter(in_data)
cn_f = apply_filter(cn_data)

# ─── Tabs ─────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 ภาพรวม", "📅 รายวัน/สัปดาห์", "🏪 แยก BP & SKU", "🔮 Forecast", "↩️ สินค้าคืน CN"
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: ภาพรวม
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.markdown("### 📊 ภาพรวมยอดส่งสินค้า")

    total_qty = int(in_f['Qty_abs'].sum())
    total_val = in_f['Value'].sum()
    total_cn_qty = int(cn_f['Qty_abs'].sum())
    return_rate = total_cn_qty / total_qty * 100 if total_qty > 0 else 0
    days = (d_end - d_start).days + 1
    avg_daily = total_qty / days if days > 0 else 0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("ยอดส่งรวม", f"{total_qty:,.0f} ชิ้น")
    c2.metric("มูลค่ารวม", f"฿{total_val:,.0f}")
    c3.metric("เฉลี่ย/วัน", f"{avg_daily:,.0f} ชิ้น")
    c4.metric("สินค้าคืน (CN)", f"{total_cn_qty:,.0f} ชิ้น")
    c5.metric("อัตราคืน", f"{return_rate:.2f}%", delta_color="inverse")

    st.markdown("---")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**ยอดส่งรายเดือน**")
        monthly = in_f.groupby('Month')['Qty_abs'].sum().reset_index()
        monthly['Month_str'] = monthly['Month'].astype(str)
        monthly['MoM'] = monthly['Qty_abs'].pct_change() * 100
        fig = px.bar(monthly, x='Month_str', y='Qty_abs',
                     text=monthly['Qty_abs'].apply(lambda x: f"{x/1000:.0f}K"),
                     color_discrete_sequence=['#378ADD'])
        fig.update_traces(textposition='outside')
        fig.update_layout(xaxis_title='', yaxis_title='ชิ้น', showlegend=False,
                          height=320, margin=dict(t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("**สัดส่วนยอดส่ง แยก SKU**")
        by_sku = in_f.groupby(['Item No.', 'Item Description'])['Qty_abs'].sum().reset_index()
        by_sku['label'] = by_sku['Item Description'].str.replace('V Farm ', '', regex=False).str[:20]
        fig2 = px.pie(by_sku, values='Qty_abs', names='label',
                      color_discrete_sequence=COLORS, hole=0.4)
        fig2.update_layout(height=320, margin=dict(t=10, b=10),
                           legend=dict(font=dict(size=11)))
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("**ยอดส่งรายเดือน แยก BP (Stacked)**")
    monthly_bp = in_f.groupby(['Month', 'BP_Name'])['Qty_abs'].sum().reset_index()
    monthly_bp['Month_str'] = monthly_bp['Month'].astype(str)
    bp_list = monthly_bp['BP_Name'].unique()
    fig3 = px.bar(monthly_bp, x='Month_str', y='Qty_abs', color='BP_Name',
                  color_discrete_sequence=COLORS, barmode='stack')
    fig3.update_layout(xaxis_title='', yaxis_title='ชิ้น', height=360,
                       legend=dict(orientation='h', yanchor='bottom', y=1.02, font=dict(size=11)),
                       margin=dict(t=60, b=10))
    st.plotly_chart(fig3, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: รายวัน/สัปดาห์
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.markdown("### 📅 ยอดส่งรายวัน และรายสัปดาห์")

    daily = in_f.groupby('Date')['Qty_abs'].sum().reset_index()
    daily.columns = ['Date', 'Qty']
    daily['MA7'] = daily['Qty'].rolling(7, min_periods=1).mean()

    cv = daily['Qty'].std() / daily['Qty'].mean() * 100 if daily['Qty'].mean() > 0 else 0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("เฉลี่ย/วัน", f"{daily['Qty'].mean():,.0f} ชิ้น")
    c2.metric("สูงสุด", f"{daily['Qty'].max():,.0f}", daily.loc[daily['Qty'].idxmax(), 'Date'].strftime('%d/%m/%y'))
    c3.metric("ต่ำสุด", f"{daily['Qty'].min():,.0f}", daily.loc[daily['Qty'].idxmin(), 'Date'].strftime('%d/%m/%y'))
    c4.metric("CV (ความผันผวน)", f"{cv:.1f}%")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=daily['Date'], y=daily['Qty'], name='ยอดรายวัน',
                             line=dict(color='#378ADD', width=1.2), opacity=0.6))
    fig.add_trace(go.Scatter(x=daily['Date'], y=daily['MA7'], name='MA 7 วัน',
                             line=dict(color='#D85A30', width=2)))
    fig.update_layout(xaxis_title='', yaxis_title='ชิ้น', height=320,
                      legend=dict(orientation='h', yanchor='bottom', y=1.02),
                      margin=dict(t=40, b=10))
    st.plotly_chart(fig, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**ยอดเฉลี่ยแยกตามวันในสัปดาห์**")
        daily['DOW'] = daily['Date'].dt.day_name()
        dow_order = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
        dow_th = {'Monday':'จันทร์','Tuesday':'อังคาร','Wednesday':'พุธ',
                  'Thursday':'พฤหัส','Friday':'ศุกร์','Saturday':'เสาร์','Sunday':'อาทิตย์'}
        dow_avg = daily.groupby('DOW')['Qty'].mean().reindex(dow_order).reset_index()
        dow_avg['DOW_TH'] = dow_avg['DOW'].map(dow_th)
        fig_dow = px.bar(dow_avg, x='DOW_TH', y='Qty',
                         color_discrete_sequence=['#1D9E75'],
                         text=dow_avg['Qty'].apply(lambda x: f"{x:,.0f}"))
        fig_dow.update_traces(textposition='outside')
        fig_dow.update_layout(xaxis_title='', yaxis_title='ชิ้น', showlegend=False,
                              height=280, margin=dict(t=10, b=10),
                              yaxis=dict(range=[0, dow_avg['Qty'].max()*1.2]))
        st.plotly_chart(fig_dow, use_container_width=True)

    with col2:
        st.markdown("**ยอดรายสัปดาห์**")
        weekly = in_f.groupby('Week')['Qty_abs'].sum().reset_index()
        weekly['Week_str'] = weekly['Week'].astype(str).str[:10]
        avg_wk = weekly['Qty_abs'].mean()
        fig_wk = px.bar(weekly, x='Week_str', y='Qty_abs',
                        color_discrete_sequence=['#378ADD'])
        fig_wk.add_hline(y=avg_wk, line_dash='dash', line_color='#E24B4A',
                         annotation_text=f"เฉลี่ย {avg_wk:,.0f}")
        fig_wk.update_layout(xaxis_title='', yaxis_title='ชิ้น', showlegend=False,
                              height=280, margin=dict(t=10, b=10),
                              xaxis=dict(tickangle=45, tickfont=dict(size=9)))
        st.plotly_chart(fig_wk, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: แยก BP & SKU
# ══════════════════════════════════════════════════════════════════════════════
with tab3:
    st.markdown("### 🏪 วิเคราะห์แยก BP และ SKU")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Top BP — ยอดส่งรวม (ชิ้น)**")
        bp_total = in_f.groupby('BP_Name')['Qty_abs'].sum().sort_values(ascending=True).reset_index()
        bp_total['pct'] = (bp_total['Qty_abs'] / bp_total['Qty_abs'].sum() * 100).round(1)
        fig_bp = px.bar(bp_total, x='Qty_abs', y='BP_Name', orientation='h',
                        text=bp_total['pct'].apply(lambda x: f"{x}%"),
                        color='Qty_abs', color_continuous_scale=['#B5D4F4','#0C447C'])
        fig_bp.update_traces(textposition='outside')
        fig_bp.update_layout(xaxis_title='ชิ้น', yaxis_title='', showlegend=False,
                             coloraxis_showscale=False, height=380, margin=dict(t=10, b=10))
        st.plotly_chart(fig_bp, use_container_width=True)

    with col2:
        st.markdown("**Top SKU — ยอดส่งรวม (ชิ้น)**")
        sku_total = in_f.groupby(['Item No.', 'Item Description'])['Qty_abs'].sum().sort_values(ascending=True).reset_index()
        sku_total['label'] = sku_total['Item Description'].str.replace('V Farm ', '', regex=False).str[:25]
        fig_sku = px.bar(sku_total, x='Qty_abs', y='label', orientation='h',
                         color_discrete_sequence=['#1D9E75'])
        fig_sku.update_layout(xaxis_title='ชิ้น', yaxis_title='', showlegend=False,
                              height=380, margin=dict(t=10, b=10))
        st.plotly_chart(fig_sku, use_container_width=True)

    st.markdown("**Matrix: BP × SKU (ยอดส่ง ชิ้น)**")
    matrix = in_f.groupby(['BP_Name', 'Item No.'])['Qty_abs'].sum().unstack(fill_value=0)
    matrix.columns = [c.replace('V Farm ', '') for c in matrix.columns]
    fig_hm = px.imshow(matrix, text_auto='.0f', aspect='auto',
                       color_continuous_scale='Blues',
                       labels=dict(color='ชิ้น'))
    fig_hm.update_layout(height=420, margin=dict(t=10, b=10),
                         xaxis=dict(tickangle=30, tickfont=dict(size=11)),
                         yaxis=dict(tickfont=dict(size=11)))
    st.plotly_chart(fig_hm, use_container_width=True)

    st.markdown("**Trend รายเดือน แยก SKU**")
    monthly_sku = in_f.groupby(['Month', 'Item Description'])['Qty_abs'].sum().reset_index()
    monthly_sku['Month_str'] = monthly_sku['Month'].astype(str)
    monthly_sku['label'] = monthly_sku['Item Description'].str.replace('V Farm ', '', regex=False)
    fig_ls = px.line(monthly_sku, x='Month_str', y='Qty_abs', color='label',
                     markers=True, color_discrete_sequence=COLORS)
    fig_ls.update_layout(xaxis_title='', yaxis_title='ชิ้น', height=340,
                         legend=dict(orientation='h', yanchor='bottom', y=1.02, font=dict(size=11)),
                         margin=dict(t=60, b=10))
    st.plotly_chart(fig_ls, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4: Forecast
# ══════════════════════════════════════════════════════════════════════════════
with tab4:
    st.markdown("### 🔮 Forecast เดือนถัดไป")
    st.caption("ใช้ 3-Month Moving Average จากเดือนล่าสุด 3 เดือน (ไม่นับเดือนที่ข้อมูลไม่ครบ)")

    all_months = sorted(in_f['Month'].unique())
    complete_months = all_months[:-1] if len(all_months) > 1 else all_months
    in_complete = in_f[in_f['Month'].isin(complete_months)]

    next_month_label = str(all_months[-1].to_timestamp() + pd.offsets.MonthBegin(1))[:7]

    # SKU forecast
    sku_monthly = in_complete.groupby(['Month', 'Item No.', 'Item Description'])['Qty_abs'].sum().reset_index()
    sku_fc_rows = []
    for (sku, desc), grp in sku_monthly.groupby(['Item No.', 'Item Description']):
        grp = grp.sort_values('Month')
        vals = grp['Qty_abs'].values
        fc = compute_forecast(grp.set_index('Month')['Qty_abs'])
        mom = (vals[-1] - vals[-2]) / vals[-2] * 100 if len(vals) >= 2 and vals[-2] > 0 else 0
        trend_4m = (vals[-1] - vals[0]) / vals[0] * 100 if len(vals) >= 2 and vals[0] > 0 else 0
        sku_fc_rows.append({'SKU': sku, 'สินค้า': desc.replace('V Farm ', ''), 'Forecast': int(fc),
                            'MoM %': round(mom, 1), 'Trend 4M %': round(trend_4m, 1)})
    sku_fc_df = pd.DataFrame(sku_fc_rows).sort_values('Forecast', ascending=False)

    def color_trend(val):
        if val > 2: return 'color: green'
        elif val < -5: return 'color: red'
        return ''

    st.markdown(f"**Forecast SKU — {next_month_label}**")
    st.dataframe(
        sku_fc_df.style.map(color_trend, subset=['MoM %', 'Trend 4M %'])
                        .format({'Forecast': '{:,.0f}', 'MoM %': '{:+.1f}%', 'Trend 4M %': '{:+.1f}%'}),
        use_container_width=True, height=320
    )

    # BP forecast
    bp_monthly = in_complete.groupby(['Month', 'BP_Name'])['Qty_abs'].sum().reset_index()
    bp_fc_rows = []
    for bp, grp in bp_monthly.groupby('BP_Name'):
        grp = grp.sort_values('Month')
        vals = grp['Qty_abs'].values
        fc = compute_forecast(grp.set_index('Month')['Qty_abs'])
        mom = (vals[-1] - vals[-2]) / vals[-2] * 100 if len(vals) >= 2 and vals[-2] > 0 else 0
        bp_fc_rows.append({'BP': bp, 'Forecast': int(fc), 'MoM %': round(mom, 1)})
    bp_fc_df = pd.DataFrame(bp_fc_rows).sort_values('Forecast', ascending=False)

    st.markdown(f"**Forecast BP — {next_month_label}**")
    col1, col2 = st.columns([1, 1])
    with col1:
        st.dataframe(
            bp_fc_df.style.map(color_trend, subset=['MoM %'])
                           .format({'Forecast': '{:,.0f}', 'MoM %': '{:+.1f}%'}),
            use_container_width=True, height=430
        )
    with col2:
        fig_fc = px.bar(bp_fc_df.sort_values('Forecast'), x='Forecast', y='BP',
                        orientation='h', text='Forecast',
                        color='Forecast', color_continuous_scale=['#B5D4F4','#0C447C'])
        fig_fc.update_traces(texttemplate='%{text:,.0f}', textposition='outside')
        fig_fc.update_layout(xaxis_title='ชิ้น', yaxis_title='', coloraxis_showscale=False,
                             showlegend=False, height=430, margin=dict(t=10, b=10))
        st.plotly_chart(fig_fc, use_container_width=True)

    # Forecast summary
    total_fc = bp_fc_df['Forecast'].sum()
    st.metric(f"Forecast รวมทั้งหมด — {next_month_label}", f"{total_fc:,.0f} ชิ้น")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5: สินค้าคืน CN
# ══════════════════════════════════════════════════════════════════════════════
with tab5:
    st.markdown("### ↩️ วิเคราะห์สินค้าคืน (Credit Note)")

    total_ret = int(cn_f['Qty_abs'].sum())
    total_ret_val = cn_f['Value'].sum()
    total_in = int(in_f['Qty_abs'].sum())
    ret_rate = total_ret / total_in * 100 if total_in > 0 else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("CN รวม", f"{total_ret:,.0f} ชิ้น")
    c2.metric("มูลค่า CN", f"฿{total_ret_val:,.0f}")
    c3.metric("อัตราคืนรวม", f"{ret_rate:.2f}%")
    c4.metric("จำนวน CN docs", f"{cn_f['Document'].nunique():,}")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**CN แยก BP**")
        cn_bp = cn_f.groupby('BP_Name').agg(qty=('Qty_abs','sum'), val=('Value','sum')).sort_values('qty', ascending=True).reset_index()
        in_bp = in_f.groupby('BP_Name')['Qty_abs'].sum().reset_index()
        cn_bp = cn_bp.merge(in_bp.rename(columns={'Qty_abs':'sent'}), on='BP_Name', how='left')
        cn_bp['rate'] = (cn_bp['qty'] / cn_bp['sent'] * 100).round(2)
        fig_cn = px.bar(cn_bp, x='qty', y='BP_Name', orientation='h',
                        text=cn_bp['rate'].apply(lambda x: f"{x:.2f}%"),
                        color='rate', color_continuous_scale=['#9FE1CB','#A32D2D'])
        fig_cn.update_traces(textposition='outside')
        fig_cn.update_layout(xaxis_title='ชิ้น', yaxis_title='', height=380,
                             coloraxis_colorbar=dict(title='อัตรา%'),
                             margin=dict(t=10, b=10, r=80))
        st.plotly_chart(fig_cn, use_container_width=True)

    with col2:
        st.markdown("**CN แยก SKU**")
        cn_sku = cn_f.groupby(['Item No.', 'Item Description'])['Qty_abs'].sum().sort_values(ascending=True).reset_index()
        cn_sku['label'] = cn_sku['Item Description'].str.replace('V Farm ', '', regex=False).str[:25]
        fig_cns = px.bar(cn_sku, x='Qty_abs', y='label', orientation='h',
                         color_discrete_sequence=['#E24B4A'])
        fig_cns.update_layout(xaxis_title='ชิ้น', yaxis_title='', showlegend=False,
                              height=380, margin=dict(t=10, b=10))
        st.plotly_chart(fig_cns, use_container_width=True)

    st.markdown("**CN รายวัน — ตรวจจับ Spike**")
    cn_daily = cn_f.groupby('Date')['Qty_abs'].sum().reset_index()
    cn_daily.columns = ['Date', 'qty']
    spikes = detect_cn_spikes(cn_daily, threshold=10)

    fig_cn_d = go.Figure()
    fig_cn_d.add_trace(go.Bar(x=cn_daily['Date'], y=cn_daily['qty'],
                              name='CN รายวัน', marker_color='#E24B4A', opacity=0.7))
    if not spikes.empty:
        fig_cn_d.add_trace(go.Scatter(x=spikes['Date'], y=spikes['qty'],
                                      mode='markers', name='⚠️ Spike',
                                      marker=dict(color='#BA7517', size=12, symbol='star')))
    mean_cn = cn_daily['qty'].mean()
    fig_cn_d.add_hline(y=mean_cn, line_dash='dash', line_color='#888780',
                       annotation_text=f"เฉลี่ย {mean_cn:.1f} ชิ้น/วัน")
    fig_cn_d.update_layout(xaxis_title='', yaxis_title='ชิ้น', height=320,
                           legend=dict(orientation='h', yanchor='bottom', y=1.02),
                           margin=dict(t=40, b=10))
    st.plotly_chart(fig_cn_d, use_container_width=True)

    if not spikes.empty:
        st.warning(f"⚠️ พบ CN Spike {len(spikes)} วัน (สูงกว่าค่าเฉลี่ย 10 เท่าขึ้นไป)")
        for _, row in spikes.iterrows():
            bp_label = f" | BP: {sel_bp}" if sel_bp else ""
            st.error(f"🔴 {row['Date'].strftime('%d/%m/%Y')} — CN {row['qty']:,.0f} ชิ้น ({row['x_normal']:.0f}x ของปกติ){bp_label}")

    st.markdown("**CN รายเดือน**")
    cn_monthly = cn_f.groupby(['Month', 'BP_Name'])['Qty_abs'].sum().reset_index()
    cn_monthly['Month_str'] = cn_monthly['Month'].astype(str)
    fig_cnm = px.bar(cn_monthly, x='Month_str', y='Qty_abs', color='BP_Name',
                     barmode='stack', color_discrete_sequence=COLORS)
    fig_cnm.update_layout(xaxis_title='', yaxis_title='ชิ้น', height=300,
                          legend=dict(orientation='h', yanchor='bottom', y=1.02, font=dict(size=11)),
                          margin=dict(t=60, b=10))
    st.plotly_chart(fig_cnm, use_container_width=True)

# ─── Footer ───────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(f"ข้อมูลในไฟล์: {date_min.strftime('%d/%m/%Y')} ถึง {date_max.strftime('%d/%m/%Y')} | IN: {len(in_data):,} rows | CN: {len(cn_data):,} rows")

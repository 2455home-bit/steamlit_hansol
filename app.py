import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from openai import OpenAI
import io
import requests
import zipfile
import xml.etree.ElementTree as ET
import feedparser
import html
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pypdf import PdfReader

st.set_page_config(page_title="국내 주식 대시보드", page_icon="📈", layout="wide")

STOCKS = {
    "삼성전자": "005930.KS",
    "SK하이닉스": "000660.KS",
    "LG에너지솔루션": "373220.KS",
    "삼성바이오로직스": "207940.KS",
    "현대차": "005380.KS",
    "기아": "000270.KS",
    "POSCO홀딩스": "005490.KS",
    "NAVER": "035420.KS",
    "카카오": "035720.KS",
    "셀트리온": "068270.KS",
}

# 종목명 → DART corp_code 매핑 (상장법인 고유번호)
DART_CORP_CODE = {
    "삼성전자":      "00126380",
    "SK하이닉스":    "00164779",
    "LG에너지솔루션": "01426955",
    "삼성바이오로직스": "00788773",
    "현대차":        "00164742",
    "기아":          "00106641",
    "POSCO홀딩스":   "00457518",
    "NAVER":         "00293886",
    "카카오":        "00918444",
    "셀트리온":      "00591613",
}

DART_REPORT_TYPE = {
    "전체": "",
    "정기공시": "A",
    "주요사항보고": "B",
    "발행공시": "C",
    "지분공시": "D",
    "기타공시": "E",
    "외부감사관련": "F",
    "펀드공시": "G",
    "자산유동화": "H",
    "거래소공시": "I",
    "공정위공시": "J",
}

st.title("📈 국내 주식 대시보드")
st.caption("KOSPI 주요 종목 10개 실시간 데이터")

# 사이드바 설정
st.sidebar.header("설정")
period_options = {"1개월": "1mo", "3개월": "3mo", "6개월": "6mo", "1년": "1y", "2년": "2y"}
selected_period_label = st.sidebar.selectbox("조회 기간", list(period_options.keys()), index=2)
selected_period = period_options[selected_period_label]
selected_stocks = st.sidebar.multiselect("종목 선택", list(STOCKS.keys()), default=list(STOCKS.keys()))

st.sidebar.divider()
st.sidebar.header("🤖 AI 챗봇")
api_key = st.sidebar.text_input("OpenAI API Key", type="password", placeholder="sk-...")

st.sidebar.divider()
st.sidebar.header("📢 DART 공시 조회")
dart_api_key = st.sidebar.text_input("DART API Key", type="password", placeholder="DART API Key 입력")

st.sidebar.divider()
st.sidebar.header("📧 이메일 설정")
smtp_sender = st.sidebar.text_input("발신자 이메일", placeholder="example@gmail.com")
smtp_password = st.sidebar.text_input("앱 비밀번호", type="password", placeholder="Gmail 앱 비밀번호 16자리")
smtp_receiver = st.sidebar.text_input("수신자 이메일", placeholder="receiver@example.com")

st.sidebar.divider()
st.sidebar.header("📄 PDF 문서 업로드")
uploaded_pdf = st.sidebar.file_uploader("PDF 파일을 업로드하면 내용 기반으로 질문할 수 있습니다.", type=["pdf"])

# PDF 텍스트를 session_state에 캐싱 (리런마다 재파싱 방지)
if uploaded_pdf is not None:
    file_id = (uploaded_pdf.name, uploaded_pdf.size)
    if st.session_state.get("pdf_file_id") != file_id:
        try:
            reader = PdfReader(io.BytesIO(uploaded_pdf.getvalue()))
            pages = [page.extract_text() or "" for page in reader.pages]
            extracted = "\n".join(pages).strip()
            st.session_state["pdf_text"] = extracted
            st.session_state["pdf_file_id"] = file_id
            st.session_state["pdf_pages"] = len(reader.pages)
            # 새 PDF 업로드 시 대화 초기화
            st.session_state["messages"] = []
        except Exception as e:
            st.sidebar.error(f"PDF 읽기 오류: {e}")
            st.session_state["pdf_text"] = ""
            st.session_state["pdf_file_id"] = None

    pdf_text = st.session_state.get("pdf_text", "")
    if pdf_text:
        st.sidebar.success(f"✅ {st.session_state['pdf_pages']}페이지 로드 완료 ({len(pdf_text):,}자)")
    else:
        st.sidebar.warning("텍스트를 추출할 수 없습니다. (이미지 기반 PDF일 수 있습니다.)")
else:
    # PDF 제거 시 초기화
    if st.session_state.get("pdf_file_id") is not None:
        st.session_state["pdf_text"] = ""
        st.session_state["pdf_file_id"] = None
        st.session_state["messages"] = []
    pdf_text = ""

if not selected_stocks:
    st.warning("최소 1개 이상의 종목을 선택해주세요.")
    st.stop()

# 데이터 수집
@st.cache_data(ttl=300)
def fetch_data(tickers: dict, period: str):
    results = {}
    for name, ticker in tickers.items():
        try:
            data = yf.download(ticker, period=period, progress=False, auto_adjust=True)
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            results[name] = {"history": data}
        except Exception:
            results[name] = None
    return results

with st.spinner("데이터를 불러오는 중..."):
    ticker_map = {k: STOCKS[k] for k in selected_stocks}
    data = fetch_data(ticker_map, selected_period)

# 주식 데이터를 챗봇용 컨텍스트로 변환
def build_stock_context(data: dict, period_label: str) -> str:
    lines = [f"=== 국내 주식 데이터 요약 (조회 기간: {period_label}) ===\n"]
    for name, d in data.items():
        if not d or d["history"].empty:
            lines.append(f"[{name}] 데이터 없음\n")
            continue
        hist = d["history"]
        close_series = hist["Close"]
        current = float(close_series.iloc[-1])
        prev = float(close_series.iloc[-2]) if len(close_series) > 1 else current
        change_pct = (current - prev) / prev * 100
        high = float(hist["High"].max())
        low = float(hist["Low"].min())
        avg_vol = float(hist["Volume"].mean())
        n = len(close_series)

        perf = {}
        for label, days in [("1주", 5), ("1개월", 21), ("3개월", 63), ("6개월", max(1, n - 1))]:
            idx = min(days, n - 1)
            if idx > 0:
                perf[label] = round((close_series.iloc[-1] / close_series.iloc[-idx] - 1) * 100, 2)

        perf_str = " / ".join(f"{k}: {v:+.2f}%" for k, v in perf.items())
        lines.append(
            f"[{name}]\n"
            f"  현재가: {current:,.0f}원 (전일 대비 {change_pct:+.2f}%)\n"
            f"  기간 내 최고: {high:,.0f}원 / 최저: {low:,.0f}원\n"
            f"  평균 거래량: {avg_vol:,.0f}주\n"
            f"  수익률 → {perf_str}\n"
        )
    return "\n".join(lines)

# 현재가 요약 카드
st.subheader("현재가 요약")
cols = st.columns(len(selected_stocks))
for i, name in enumerate(selected_stocks):
    d = data.get(name)
    with cols[i]:
        if d and not d["history"].empty:
            hist = d["history"]
            close = hist["Close"].iloc[-1].item() if hasattr(hist["Close"].iloc[-1], 'item') else float(hist["Close"].iloc[-1])
            prev = (hist["Close"].iloc[-2].item() if hasattr(hist["Close"].iloc[-2], 'item') else float(hist["Close"].iloc[-2])) if len(hist) > 1 else close
            change = close - prev
            pct = change / float(prev) * 100
            color = "🔴" if change < 0 else "🔵" if change == 0 else "🟢"
            st.metric(
                label=f"{color} {name}",
                value=f"{close:,.0f}원",
                delta=f"{change:+,.0f}원 ({pct:+.2f}%)",
            )
        else:
            st.metric(label=name, value="N/A")

st.divider()

# 주가 추이 차트
st.subheader("주가 추이 비교 (정규화)")
fig = go.Figure()
for name in selected_stocks:
    d = data.get(name)
    if d and not d["history"].empty:
        hist = d["history"]
        normalized = hist["Close"] / hist["Close"].iloc[0] * 100
        fig.add_trace(go.Scatter(x=hist.index, y=normalized, name=name, mode="lines"))
fig.update_layout(
    yaxis_title="수익률 지수 (시작=100)",
    xaxis_title="날짜",
    height=400,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    hovermode="x unified",
)
st.plotly_chart(fig, use_container_width=True)

# 거래량 차트
st.subheader("거래량")
vol_fig = go.Figure()
for name in selected_stocks:
    d = data.get(name)
    if d and not d["history"].empty:
        hist = d["history"]
        vol_fig.add_trace(go.Bar(x=hist.index, y=hist["Volume"], name=name, opacity=0.7))
vol_fig.update_layout(
    barmode="group",
    yaxis_title="거래량",
    xaxis_title="날짜",
    height=300,
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
)
st.plotly_chart(vol_fig, use_container_width=True)

# 개별 종목 캔들차트
st.subheader("개별 종목 캔들차트")
selected_one = st.selectbox("종목 선택", selected_stocks)
d = data.get(selected_one)
if d and not d["history"].empty:
    hist = d["history"]
    candle = go.Figure(go.Candlestick(
        x=hist.index,
        open=hist["Open"], high=hist["High"],
        low=hist["Low"], close=hist["Close"],
        name=selected_one,
        increasing_line_color="red",
        decreasing_line_color="blue",
    ))
    candle.update_layout(
        title=f"{selected_one} 캔들차트",
        yaxis_title="주가 (원)",
        xaxis_rangeslider_visible=False,
        height=450,
    )
    st.plotly_chart(candle, use_container_width=True)

# 수익률 히트맵
st.subheader("기간별 수익률")
perf_data = []
for name in selected_stocks:
    d = data.get(name)
    if d and not d["history"].empty:
        hist = d["history"]["Close"]
        row = {"종목": name}
        n = len(hist)
        for label, days in [("1주", 5), ("1개월", 21), ("3개월", 63), ("6개월", max(1, n - 1))]:
            idx = min(days, n - 1)
            row[label] = round((hist.iloc[-1] / hist.iloc[-idx] - 1) * 100, 2) if idx > 0 else None
        perf_data.append(row)

if perf_data:
    perf_df = pd.DataFrame(perf_data).set_index("종목")
    st.dataframe(
        perf_df.style.background_gradient(cmap="RdYlGn", axis=None).format("{:.2f}%", na_rep="-"),
        use_container_width=True,
    )

st.caption(f"마지막 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 데이터: Yahoo Finance (5분 캐시)")

# ── 뉴스 수집 ──────────────────────────────────────────────
st.divider()
st.subheader("📰 종목 관련 뉴스")

STOCK_SEARCH_NAME = {
    "삼성전자": "삼성전자",
    "SK하이닉스": "SK하이닉스",
    "LG에너지솔루션": "LG에너지솔루션",
    "삼성바이오로직스": "삼성바이오로직스",
    "현대차": "현대자동차",
    "기아": "기아자동차",
    "POSCO홀딩스": "POSCO홀딩스",
    "NAVER": "네이버",
    "카카오": "카카오",
    "셀트리온": "셀트리온",
}

@st.cache_data(ttl=300)
def fetch_news(query: str, max_items: int = 10) -> list:
    encoded = requests.utils.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=ko&gl=KR&ceid=KR:ko"
    feed = feedparser.parse(url)
    items = []
    for entry in feed.entries[:max_items]:
        summary = re.sub(r"<[^>]+>", "", html.unescape(entry.get("summary", "")))
        items.append({
            "title": html.unescape(entry.get("title", "")),
            "link": entry.get("link", ""),
            "published": entry.get("published", ""),
            "source": entry.get("source", {}).get("title", ""),
            "summary": summary[:300],
        })
    return items

def build_news_context(news_map: dict) -> str:
    lines = ["=== 종목 관련 최신 뉴스 ===\n"]
    for stock, articles in news_map.items():
        if not articles:
            continue
        lines.append(f"[{stock}]")
        for a in articles[:5]:
            lines.append(f"  - {a['published']} | {a['title']} ({a['source']})")
            if a["summary"]:
                lines.append(f"    요약: {a['summary']}")
    return "\n".join(lines)

news_stock = st.selectbox("뉴스 조회 종목", selected_stocks, key="news_stock")
news_count = st.slider("최대 뉴스 수", 5, 20, 10, key="news_count")

with st.spinner(f"{news_stock} 뉴스 수집 중..."):
    query = STOCK_SEARCH_NAME.get(news_stock, news_stock) + " 주식"
    news_items = fetch_news(query, news_count)

if "collected_news" not in st.session_state:
    st.session_state["collected_news"] = {}

if news_items:
    st.session_state["collected_news"][news_stock] = news_items
    st.success(f"{news_stock} 뉴스 {len(news_items)}건 수집됨")
    for item in news_items:
        with st.expander(f"**{item['published']}** | {item['title']}"):
            st.write(f"- **출처:** {item['source']}")
            if item["summary"]:
                st.write(f"- **요약:** {item['summary']}")
            st.markdown(f"- **[기사 보기]({item['link']})**")
else:
    st.info("수집된 뉴스가 없습니다.")

# ── DART 공시 조회 ─────────────────────────────────────────
st.divider()
st.subheader("📢 DART 공시 정보")

@st.cache_data(ttl=600)
def fetch_dart_disclosures(corp_code: str, api_key: str, report_type: str, bgn_de: str, end_de: str) -> list:
    url = "https://opendart.fss.or.kr/api/list.json"
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bgn_de": bgn_de,
        "end_de": end_de,
        "page_count": 20,
    }
    if report_type:
        params["pblntf_ty"] = report_type
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("status") == "000":
            return data.get("list", [])
        return []
    except Exception:
        return []

if not dart_api_key:
    st.info("왼쪽 사이드바에 DART API Key를 입력하면 공시 정보를 조회할 수 있습니다.")
else:
    col_left, col_right = st.columns([2, 2])
    with col_left:
        dart_stock = st.selectbox("종목 선택", list(DART_CORP_CODE.keys()), key="dart_stock")
        dart_report_type = st.selectbox("공시 유형", list(DART_REPORT_TYPE.keys()), key="dart_type")
    with col_right:
        dart_bgn = st.date_input("조회 시작일", value=datetime(2025, 1, 1), key="dart_bgn")
        dart_end = st.date_input("조회 종료일", value=datetime.today(), key="dart_end")

    if st.button("공시 조회", type="primary"):
        corp_code = DART_CORP_CODE[dart_stock]
        report_type_code = DART_REPORT_TYPE[dart_report_type]
        with st.spinner("DART 공시 정보를 가져오는 중..."):
            disclosures = fetch_dart_disclosures(
                corp_code,
                dart_api_key,
                report_type_code,
                dart_bgn.strftime("%Y%m%d"),
                dart_end.strftime("%Y%m%d"),
            )

        if disclosures:
            df_disc = pd.DataFrame(disclosures)
            col_map = {
                "rcept_dt":      "공시일자",
                "pblntf_ty_nm":  "공시유형",
                "report_nm":     "보고서명",
                "flr_nm":        "제출인",
                "rcept_no":      "접수번호",
            }
            # 실제 응답에 있는 컬럼만 선택
            available = {k: v for k, v in col_map.items() if k in df_disc.columns}
            df_disc = df_disc[list(available.keys())].rename(columns=available)

            if "공시일자" in df_disc.columns:
                df_disc["공시일자"] = pd.to_datetime(df_disc["공시일자"], errors="coerce").dt.strftime("%Y-%m-%d")
            if "접수번호" in df_disc.columns:
                df_disc["DART 링크"] = df_disc["접수번호"].apply(
                    lambda x: f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={x}"
                )

            st.success(f"{dart_stock} 공시 {len(df_disc)}건 조회됨")
            for _, row in df_disc.iterrows():
                date_str  = row.get("공시일자", "")
                type_str  = row.get("공시유형", "")
                report_str = row.get("보고서명", "")
                with st.expander(f"**{date_str}** | {type_str} | {report_str}"):
                    if "제출인" in row:
                        st.write(f"- **제출인:** {row['제출인']}")
                    if "접수번호" in row:
                        st.write(f"- **접수번호:** {row['접수번호']}")
                    if "DART 링크" in row:
                        st.markdown(f"- **[DART에서 보기]({row['DART 링크']})**")
        else:
            st.warning("조회된 공시가 없습니다. 조회 기간이나 공시 유형을 변경해보세요.")

# ── AI 챗봇 ──────────────────────────────────────────────
st.divider()
st.subheader("🤖 AI 주식 챗봇")
if pdf_text:
    st.caption("수집된 주식 데이터 + 업로드된 PDF 문서를 기반으로 GPT-4o-mini가 답변합니다.")
else:
    st.caption("수집된 주식 데이터를 기반으로 GPT-4o-mini가 답변합니다.")

if not api_key:
    st.info("왼쪽 사이드바에 OpenAI API Key를 입력하면 챗봇을 사용할 수 있습니다.")
else:
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # 대화 기록 표시
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    placeholder = "PDF 문서 또는 주식에 대해 질문해보세요." if pdf_text else "주식에 대해 질문해보세요. 예) SK하이닉스 최근 수익률 분석해줘"
    if prompt := st.chat_input(placeholder):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        stock_context = build_stock_context(data, selected_period_label)
        pdf_section = f"\n\n=== 업로드된 PDF 문서 내용 ===\n{pdf_text[:8000]}" if pdf_text else ""
        collected_news = st.session_state.get("collected_news", {})
        news_section = f"\n\n{build_news_context(collected_news)}" if collected_news else ""
        system_prompt = f"""당신은 한국 주식 시장 전문 AI 애널리스트입니다.
아래 실시간 주식 데이터, 최신 뉴스, PDF 문서를 바탕으로 사용자 질문에 한국어로 명확하고 친절하게 답변하세요.
수치를 인용할 때는 구체적인 숫자를 사용하고, 투자 판단은 참고용임을 안내하세요.
뉴스가 제공된 경우 최신 동향을 반영하고, PDF 문서가 제공된 경우 해당 내용도 참고하여 답변하세요.

{stock_context}{news_section}{pdf_section}"""

        with st.chat_message("assistant"):
            with st.spinner("분석 중..."):
                try:
                    client = OpenAI(api_key=api_key)
                    stream = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            *st.session_state.messages,
                        ],
                        stream=True,
                    )
                    response = st.write_stream(stream)
                except Exception as e:
                    response = f"오류가 발생했습니다: {e}"
                    st.error(response)

        st.session_state.messages.append({"role": "assistant", "content": response})

    if st.session_state.get("messages"):
        if st.button("대화 초기화"):
            st.session_state.messages = []
            st.rerun()

# ── 보고서 작성 & 이메일 발송 ──────────────────────────────
st.divider()
st.subheader("📧 AI 보고서 작성 & 이메일 발송")
st.caption("수집된 주식 데이터와 뉴스를 바탕으로 AI가 보고서를 작성하고 이메일로 발송합니다.")

def generate_report(api_key: str, stock_context: str, news_context: str, report_stocks: list) -> str:
    client = OpenAI(api_key=api_key)
    prompt = f"""당신은 한국 주식 시장 전문 AI 애널리스트입니다.
아래 주식 데이터와 최신 뉴스를 바탕으로 {", ".join(report_stocks)} 종목에 대한 투자 분석 보고서를 작성하세요.

보고서 형식:
1. 종합 시장 동향 요약
2. 종목별 현황 분석 (현재가, 수익률, 주요 이슈)
3. 최신 뉴스 동향
4. 투자 시사점 및 유의사항
5. 면책 고지 (본 보고서는 참고용이며 투자 판단의 책임은 본인에게 있음)

작성 기준일: {datetime.now().strftime("%Y년 %m월 %d일")}

{stock_context}

{news_context}
"""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content

def send_email(sender: str, password: str, receiver: str, subject: str, body_html: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = receiver
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, receiver, msg.as_string())

report_stocks = st.multiselect(
    "보고서에 포함할 종목",
    selected_stocks,
    default=selected_stocks[:3] if len(selected_stocks) >= 3 else selected_stocks,
    key="report_stocks",
)

email_ready = smtp_sender and smtp_password and smtp_receiver
ai_ready = bool(api_key)

col_gen, col_send = st.columns([1, 1])

with col_gen:
    if st.button("📝 보고서 생성", type="primary", disabled=not (ai_ready and report_stocks)):
        if not ai_ready:
            st.warning("OpenAI API Key를 사이드바에 입력해주세요.")
        elif not report_stocks:
            st.warning("보고서에 포함할 종목을 선택해주세요.")
        else:
            stock_ctx = build_stock_context(
                {k: v for k, v in data.items() if k in report_stocks}, selected_period_label
            )
            collected_news = st.session_state.get("collected_news", {})
            news_ctx = build_news_context({k: v for k, v in collected_news.items() if k in report_stocks})
            with st.spinner("AI가 보고서를 작성 중입니다..."):
                try:
                    report_md = generate_report(api_key, stock_ctx, news_ctx, report_stocks)
                    st.session_state["generated_report"] = report_md
                    st.success("보고서가 생성되었습니다.")
                except Exception as e:
                    st.error(f"보고서 생성 오류: {e}")

with col_send:
    if st.button("📨 이메일 발송", disabled=not (email_ready and "generated_report" in st.session_state)):
        if not email_ready:
            st.warning("사이드바에서 발신자 이메일, 앱 비밀번호, 수신자 이메일을 모두 입력해주세요.")
        elif "generated_report" not in st.session_state:
            st.warning("먼저 보고서를 생성해주세요.")
        else:
            report_md = st.session_state["generated_report"]
            # 마크다운 → 간단한 HTML 변환
            body_html = f"""
<html><body style="font-family:Arial,sans-serif;max-width:800px;margin:auto;padding:20px;">
<h2 style="color:#1a237e;">📈 AI 주식 분석 보고서</h2>
<p style="color:#666;">작성일: {datetime.now().strftime("%Y년 %m월 %d일 %H:%M")}</p>
<hr/>
<pre style="white-space:pre-wrap;font-family:inherit;line-height:1.7;">{report_md}</pre>
<hr/>
<p style="color:#999;font-size:12px;">본 보고서는 AI가 자동 생성한 참고용 자료이며, 투자 권유가 아닙니다.</p>
</body></html>"""
            subject = f"[AI 주식 보고서] {', '.join(report_stocks)} — {datetime.now().strftime('%Y-%m-%d')}"
            with st.spinner("이메일 발송 중..."):
                try:
                    send_email(smtp_sender, smtp_password, smtp_receiver, subject, body_html)
                    st.success(f"이메일이 {smtp_receiver}으로 발송되었습니다.")
                except smtplib.SMTPAuthenticationError:
                    st.error("인증 오류: Gmail 앱 비밀번호를 확인해주세요. (일반 비밀번호가 아닌 앱 비밀번호 필요)")
                except Exception as e:
                    st.error(f"이메일 발송 오류: {e}")

if "generated_report" in st.session_state:
    st.markdown("---")
    st.markdown("**생성된 보고서 미리보기**")
    st.markdown(st.session_state["generated_report"])

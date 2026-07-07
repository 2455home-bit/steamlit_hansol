import json
import urllib.parse
import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="🎵 음악 추천 서비스", page_icon="🎵", layout="centered")

st.title("🎵 나만의 음악 추천 서비스")
st.write("몇 가지 질문에 답하면 딱 맞는 노래를 추천해드립니다!")

with st.sidebar:
    st.header("⚙️ 설정")
    api_key = st.text_input("OpenAI API Key", type="password", placeholder="sk-...")
    st.caption("API 키는 저장되지 않으며 이 세션에서만 사용됩니다.")

st.divider()
st.subheader("📋 설문 조사")

col1, col2 = st.columns(2)

with col1:
    mood = st.selectbox(
        "1. 지금 기분이 어떤가요?",
        ["행복하고 신나는", "차분하고 편안한", "슬프고 감성적인", "집중하고 싶은", "에너지 넘치는", "로맨틱한"]
    )

    genre = st.multiselect(
        "2. 좋아하는 장르를 선택해주세요 (복수 선택 가능)",
        ["팝(Pop)", "K-Pop", "R&B/소울", "힙합/랩", "재즈", "클래식", "록/메탈", "일렉트로닉/EDM", "인디/어쿠스틱", "발라드"],
        default=["팝(Pop)"]
    )

    tempo = st.select_slider(
        "3. 원하는 템포는?",
        options=["매우 느린", "느린", "보통", "빠른", "매우 빠른"],
        value="보통"
    )

with col2:
    activity = st.selectbox(
        "4. 지금 무엇을 하고 있나요?",
        ["공부/업무 중", "운동 중", "드라이브 중", "휴식 중", "파티/모임", "잠들기 전", "출퇴근 중", "요리/집안일 중"]
    )

    language = st.multiselect(
        "5. 선호하는 노래 언어는?",
        ["한국어", "영어", "일본어", "스페인어", "언어 무관"],
        default=["한국어", "영어"]
    )

    era = st.selectbox(
        "6. 선호하는 음악 시대는?",
        ["최신 (2020년대)", "2010년대", "2000년대", "90년대", "80년대 이전", "시대 무관"]
    )

favorite_artists = st.text_input(
    "7. 좋아하는 아티스트나 노래가 있다면 적어주세요 (선택사항)",
    placeholder="예: BTS, 아이유, Taylor Swift, Adele..."
)

additional = st.text_area(
    "8. 추가로 원하는 음악 스타일이나 요청사항이 있나요? (선택사항)",
    placeholder="예: 가사가 위로가 되는 노래, 피아노가 많이 들어간 곡, 영화 OST 스타일...",
    height=80
)

st.divider()
num_songs = st.slider("추천받을 노래 수", min_value=3, max_value=10, value=5)


def make_youtube_url(title: str, artist: str) -> str:
    query = urllib.parse.quote(f"{title} {artist}")
    return f"https://www.youtube.com/results?search_query={query}"


def fetch_artist_songs(client: OpenAI, artist: str, exclude_titles: list[str]) -> list[dict]:
    exclude_str = ", ".join(f'"{t}"' for t in exclude_titles) if exclude_titles else "없음"
    prompt = f"""{artist}의 대표곡 및 추천곡 5곡을 알려주세요.
이미 추천된 곡({exclude_str})은 제외해주세요.

반드시 아래 JSON 형식으로만 응답하세요:
{{
  "songs": [
    {{
      "title": "곡명",
      "artist": "{artist}",
      "genre": "장르",
      "vibe": "분위기 한 줄 설명"
    }}
  ]
}}"""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "음악 전문가입니다. 요청받은 JSON 형식을 정확히 지켜 응답하세요."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=800,
        response_format={"type": "json_object"}
    )
    data = json.loads(response.choices[0].message.content)
    return data.get("songs", [])


def render_artist_modal(artist: str, songs: list[dict]):
    st.markdown(f"### 🎤 {artist} 추천곡")
    for song in songs:
        title = song.get("title", "")
        yt_url = make_youtube_url(title, artist)
        with st.container(border=True):
            col_info, col_btn = st.columns([4, 1])
            with col_info:
                st.markdown(f"**{title}**")
                st.caption(f"🎼 {song.get('genre', '')}　　✨ {song.get('vibe', '')}")
            with col_btn:
                st.link_button("▶ YouTube", yt_url, use_container_width=True)
    if st.button("✕ 닫기", key="close_artist_panel", use_container_width=True):
        st.session_state.selected_artist = None
        st.session_state.artist_songs = []
        st.rerun()


def render_songs(songs: list, summary: str):
    st.success("🎉 추천 완료!")
    st.subheader("🎧 나를 위한 플레이리스트")

    for i, song in enumerate(songs, 1):
        title = song.get("title", "")
        artist = song.get("artist", "")
        reason = song.get("reason", "")
        genre_info = song.get("genre", "")
        vibe = song.get("vibe", "")
        yt_url = make_youtube_url(title, artist)

        with st.container(border=True):
            col_info, col_artist_btn, col_yt_btn = st.columns([3, 1.3, 1])
            with col_info:
                st.markdown(f"**{i}. {title}**")
                if genre_info:
                    st.caption(f"🎼 {genre_info}　　✨ {vibe}")
                st.write(reason)
            with col_artist_btn:
                if st.button(f"🎤 {artist}", key=f"artist_{i}", use_container_width=True, help=f"{artist}의 다른 곡 보기"):
                    st.session_state.selected_artist = artist
                    st.session_state.artist_songs = []
                    st.session_state.exclude_titles = [s.get("title", "") for s in songs]
                    st.rerun()
            with col_yt_btn:
                st.link_button("▶ YouTube", yt_url, use_container_width=True)

    if summary:
        st.divider()
        st.info(f"🎵 **플레이리스트 무드** \n\n{summary}")


# 세션 상태 초기화
if "selected_artist" not in st.session_state:
    st.session_state.selected_artist = None
if "artist_songs" not in st.session_state:
    st.session_state.artist_songs = []
if "exclude_titles" not in st.session_state:
    st.session_state.exclude_titles = []
if "playlist" not in st.session_state:
    st.session_state.playlist = None
if "playlist_summary" not in st.session_state:
    st.session_state.playlist_summary = ""

if st.button("🎵 노래 추천받기", type="primary", use_container_width=True):
    if not api_key:
        st.error("사이드바에 OpenAI API 키를 입력해주세요.")
    elif not genre:
        st.warning("좋아하는 장르를 하나 이상 선택해주세요.")
    else:
        prompt = f"""당신은 음악 전문가입니다. 사용자의 취향에 맞는 노래를 추천해주세요.

사용자 정보:
- 현재 기분: {mood}
- 좋아하는 장르: {', '.join(genre)}
- 원하는 템포: {tempo}
- 현재 활동: {activity}
- 선호 언어: {', '.join(language)}
- 선호 시대: {era}
{f'- 좋아하는 아티스트/노래: {favorite_artists}' if favorite_artists else ''}
{f'- 추가 요청사항: {additional}' if additional else ''}

위 정보를 바탕으로 {num_songs}곡을 추천해주세요.

반드시 아래 JSON 형식으로만 응답하세요. 마크다운 코드블록(```)을 사용하지 말고 순수 JSON만 반환하세요:
{{
  "songs": [
    {{
      "title": "곡명",
      "artist": "아티스트명",
      "reason": "추천 이유 (2-3문장)",
      "genre": "장르",
      "vibe": "분위기 한 줄 설명"
    }}
  ],
  "summary": "전체 플레이리스트의 공통 테마나 무드 요약 (2-3문장)"
}}"""

        with st.spinner("🎵 당신을 위한 음악을 찾는 중..."):
            try:
                client = OpenAI(api_key=api_key)
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "당신은 다양한 장르에 해박한 음악 전문가입니다. 요청받은 JSON 형식을 정확히 지켜서 응답하세요."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.8,
                    max_tokens=2000,
                    response_format={"type": "json_object"}
                )
                raw = response.choices[0].message.content
                data = json.loads(raw)
                st.session_state.playlist = data.get("songs", [])
                st.session_state.playlist_summary = data.get("summary", "")
                st.session_state.selected_artist = None
                st.session_state.artist_songs = []
                st.rerun()

            except json.JSONDecodeError:
                st.error("❌ 응답 파싱에 실패했습니다. 다시 시도해주세요.")
            except Exception as e:
                error_msg = str(e)
                if "api_key" in error_msg.lower() or "authentication" in error_msg.lower() or "401" in error_msg:
                    st.error("❌ API 키가 올바르지 않습니다. 사이드바에서 API 키를 확인해주세요.")
                elif "rate_limit" in error_msg.lower() or "429" in error_msg:
                    st.error("❌ API 요청 한도를 초과했습니다. 잠시 후 다시 시도해주세요.")
                else:
                    st.error(f"❌ 오류가 발생했습니다: {error_msg}")

# 플레이리스트 표시
if st.session_state.playlist:
    st.divider()
    render_songs(st.session_state.playlist, st.session_state.playlist_summary)

    st.divider()
    with st.expander("📊 내 설문 응답 요약"):
        st.write(f"**기분:** {mood}")
        st.write(f"**장르:** {', '.join(genre)}")
        st.write(f"**템포:** {tempo}")
        st.write(f"**활동:** {activity}")
        st.write(f"**선호 언어:** {', '.join(language)}")
        st.write(f"**선호 시대:** {era}")
        if favorite_artists:
            st.write(f"**좋아하는 아티스트:** {favorite_artists}")

# 아티스트 추가 추천 패널
if st.session_state.selected_artist:
    st.divider()
    artist = st.session_state.selected_artist

    if not st.session_state.artist_songs:
        if not api_key:
            st.error("아티스트 추천을 위해 사이드바에 API 키를 입력해주세요.")
        else:
            with st.spinner(f"🎤 {artist}의 다른 곡을 찾는 중..."):
                try:
                    client = OpenAI(api_key=api_key)
                    st.session_state.artist_songs = fetch_artist_songs(
                        client, artist, st.session_state.exclude_titles
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ 오류가 발생했습니다: {e}")
    else:
        render_artist_modal(artist, st.session_state.artist_songs)

st.divider()
st.caption("🎵 OpenAI gpt-4o-mini 기반 음악 추천 서비스")

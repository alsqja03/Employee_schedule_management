
import html
from pathlib import Path

import streamlit as st
from postgrest.exceptions import APIError

from views.auth import (
    handle_auth_callback,
    get_current_user,
    get_supabase,
    sign_out,
    start_oauth,
)
from views.home.home import render_home

# ==========================================
# 기본 설정
# ==========================================

st.set_page_config(
    page_title="CrewFit · 근무 일정 관리",
    page_icon="📅",
    layout="centered",
    initial_sidebar_state="collapsed",
)

ROOT = Path(__file__).resolve().parent
LOGO_PATH = ROOT / "img" / "crewfit_text_logo.png"
css = (ROOT / "views" / "theme.css").read_text(encoding="utf-8")
st.html(f"<style>{css}</style>")


# Google / Kakao 로그인 후 돌아온 인증 코드 처리
callback_result = handle_auth_callback()

if callback_result:
    if callback_result["success"]:
        st.rerun()
    else:
        st.error(f"로그인에 실패했습니다: {callback_result['error']}")


# ==========================================
# 로그인 상태 확인
# ==========================================

# 로그인 상태 확인
user = get_current_user()

if user:
    try:
        profile = get_supabase().rpc("crewfit_my_profile").execute().data or {}
    except APIError:
        st.error("계정 정보를 불러오지 못했습니다. 잠시 후 새로고침해 주세요.")
        st.stop()
    if not profile.get("deleted"):
        render_home(user, profile)
        st.stop()
    try:
        sign_out()
    except Exception:
        pass
    st.session_state.clear()
    st.session_state["withdrawn_signin"] = True
    st.rerun()

if st.session_state.pop("withdrawal_done", False):
    st.success("CrewFit 회원탈퇴가 완료되었습니다.")
if st.session_state.pop("withdrawn_signin", False):
    st.warning("CrewFit에서 탈퇴한 계정입니다.")


def render_login_button(
    provider: str,
    button_class: str,
    icon: str,
    label: str
):
    try:
        login_url = html.escape(start_oauth(provider), quote=True)
    except Exception:
        st.warning(f"{label} 링크를 준비하지 못했습니다. 페이지를 새로고침해 주세요.")
        return

    st.markdown(
        f"""
        <a class="login-button {button_class}" href="{login_url}" target="_self">
            <span class="button-icon" aria-hidden="true">{icon}</span>
            {label}
        </a>
        """,
        unsafe_allow_html=True,
    )


with st.container(key="crewfit_login"):
    if LOGO_PATH.is_file():
        st.image(str(LOGO_PATH), width=138)
    st.title("CrewFit에 로그인")
    st.caption("가게를 연결하고 이번 주 근무 일정을 확인하세요.")
    render_login_button("google", "google-button", "G", "Google 계정으로 로그인")
    render_login_button("kakao", "kakao-button", "●", "카카오 계정으로 로그인")

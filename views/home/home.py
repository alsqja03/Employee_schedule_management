from pathlib import Path
from urllib.parse import urlsplit

import streamlit as st

from views.auth import sign_out
from views.employee.employee import render_employee_management
from views.mypage.mypage import render_mypage, render_profile_edit, render_withdrawal
from views.store.store import render_store_connection
from views.schedule.schedule import render_schedule


LOGO_PATH = Path(__file__).resolve().parents[2] / "img" / "crewfit_text_logo.png"

MENUS = (
    ("store", "가게 연결", ":material/storefront:"),
    ("schedule", "스케줄 관리", ":material/calendar_month:"),
    ("mypage", "마이페이지", ":material/person:"),
)


def get_user_info(user):
    metadata = getattr(user, "user_metadata", {}) or {}
    name = (
        metadata.get("full_name")
        or metadata.get("name")
        or metadata.get("preferred_username")
        or "사용자"
    )
    email = getattr(user, "email", None) or "이메일 정보 없음"
    avatar = metadata.get("avatar_url") or metadata.get("picture") or metadata.get("photo_url")
    if isinstance(avatar, str):
        try:
            url = urlsplit(avatar)
            if url.scheme == "https" and url.hostname:
                return name, email, avatar
        except ValueError:
            pass
    return name, email, None


def render_home(user, account_profile):
    selected_menu = st.session_state.get("selected_menu")
    with st.container(key="crewfit_home"):
        with st.container(key="crewfit_logo"):
            if LOGO_PATH.is_file():
                st.image(str(LOGO_PATH), width=134)
            else:
                st.title("CrewFit")

        if selected_menu == "mypage":
            st.title("마이페이지")
        elif selected_menu in ("store", "schedule", "employee", "withdraw", "profile_edit"):
            return_to_account = st.session_state.get("account_return", False)
            if st.button("마이페이지로" if return_to_account else "홈으로", icon=":material/arrow_back:", key="home_back"):
                st.session_state.pop("account_return", None)
                st.session_state.pop("employee_store", None)
                if return_to_account:
                    st.session_state["selected_menu"] = "mypage"
                else:
                    st.session_state.pop("selected_menu", None)
                st.rerun()

        name, email, avatar = get_user_info(user)
        with st.container(border=True, key="crewfit_profile"):
            photo, profile, actions = st.columns([1, 5, 2], vertical_alignment="center")
            with photo:
                if avatar:
                    st.image(avatar, width=76 if selected_menu == "mypage" else 58)
                else:
                    st.html('<span class="crewfit-avatar" aria-hidden="true">CF</span>')
            with profile:
                st.text(account_profile.get("name") or name)
                st.caption(email)
            with actions:
                if st.button("로그아웃", key="home_logout", width="stretch"):
                    try:
                        sign_out()
                    finally:
                        st.session_state.clear()
                        st.rerun()

        if selected_menu == "mypage":
            render_mypage()
            return

        if selected_menu == "profile_edit":
            render_profile_edit(account_profile, name)
            return

        if selected_menu == "employee":
            render_employee_management()
            return

        if selected_menu == "withdraw":
            render_withdrawal()
            return

        if selected_menu == "store":
            render_store_connection(account_profile)
            return

        if selected_menu == "schedule":
            render_schedule()
            return

        with st.container(key="crewfit_home_heading"):
            st.title("근무 일정 관리")
            st.divider()
        with st.container(key="crewfit_home_menu"):
            for key, label, icon in MENUS:
                with st.container(key=f"crewfit_card_{key}"):
                    if st.button(label, icon=icon, key=f"menu_{key}", width="stretch"):
                        st.session_state["selected_menu"] = key
                        st.rerun()

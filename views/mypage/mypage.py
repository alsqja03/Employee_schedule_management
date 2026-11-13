from datetime import date, datetime
from zoneinfo import ZoneInfo

import streamlit as st
from postgrest.exceptions import APIError

from views.auth import get_supabase, sign_out


def open_page(page):
    st.session_state["selected_menu"] = page
    st.rerun()


def render_mypage():
    with st.container(key="crewfit_mypage_menu"):
        for label, page in (
            ("내 정보 수정", "profile_edit"),
            ("직원 관리", "employee"),
            ("회원탈퇴", "withdraw"),
        ):
            if st.button(label, width="stretch", key=f"mypage_{page}"):
                st.session_state["account_return"] = True
                open_page(page)

    if st.button("홈으로", icon=":material/arrow_back:", key="mypage_home"):
        st.session_state.pop("selected_menu", None)
        st.rerun()


def render_profile_edit(profile, login_name):
    st.title("내 정보 수정")
    birthday = date.fromisoformat(profile["birth"]) if profile.get("birth") else None
    st.caption("전화번호와 생년월일은 가게를 등록하거나 연결할 때 필요합니다. 직원으로 연결한 가게의 사장님이 직원 관리에서 확인할 수 있습니다.")
    with st.form("edit_profile"):
        name = st.text_input("이름", value=profile.get("name") or login_name[:80], max_chars=80)
        phone = st.text_input("전화번호", value=profile.get("telephone") or "", max_chars=24)
        birth = st.date_input(
            "생년월일", value=birthday, min_value=date(1900, 1, 1),
            max_value=datetime.now(ZoneInfo("Asia/Seoul")).date(), format="YYYY-MM-DD",
        )
        saved = st.form_submit_button("내 정보 저장", type="primary")

    if saved:
        if not name.strip():
            st.warning("이름을 입력해 주세요.")
            return
        if not phone.strip() or not birth:
            st.warning("전화번호와 생년월일을 모두 입력해 주세요.")
            return
        try:
            get_supabase().rpc("crewfit_save_profile", {
                "p_name": name.strip(), "p_phone": phone.strip(),
                "p_birth": birth.isoformat() if birth else None,
            }).execute()
        except APIError:
            st.error("내 정보를 저장하지 못했습니다. 입력 내용을 확인해 주세요.")
        else:
            st.session_state["profile_saved"] = True
            st.rerun()
    if st.session_state.pop("profile_saved", False):
        st.success("내 정보를 저장했습니다.")


def render_withdrawal():
    st.title("회원탈퇴")
    st.warning("탈퇴하면 CrewFit 이용이 종료되고 이름, 전화번호, 생년월일이 삭제됩니다. 사장님 계정이 소유한 가게의 스케줄도 직원 화면에서 이용할 수 없게 됩니다.")
    with st.form("withdraw_account"):
        confirmation = st.checkbox("위 내용을 확인했으며 CrewFit에서 탈퇴합니다.")
        submitted = st.form_submit_button("회원탈퇴", type="primary")
    if not submitted:
        return
    if not confirmation:
        st.warning("탈퇴 확인란을 선택해 주세요.")
        return
    try:
        get_supabase().rpc("crewfit_withdraw").execute()
    except APIError:
        st.error("회원탈퇴를 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.")
        return
    try:
        sign_out()
    except Exception:
        pass
    st.session_state.clear()
    st.session_state["withdrawal_done"] = True
    st.rerun()

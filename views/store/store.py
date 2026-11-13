import re

import streamlit as st
from postgrest.exceptions import APIError

from views.auth import get_supabase


def render_store_connection(profile):
    st.title("가게 연결")
    client = get_supabase()
    try:
        stores = client.rpc("crewfit_my_stores").execute().data or []
    except APIError as error:
        if error.code == "PGRST202":
            st.error("가게 연결 기능을 사용하려면 Supabase에 DB/migrations/store_invites.sql을 적용해 주세요.")
        else:
            st.error("연결된 가게를 불러오지 못했습니다.")
        return

    notice = st.session_state.pop("store_connection_notice", None)
    if notice:
        st.success(notice)

    role = st.radio("이용 구분", ["직원", "사장님"], horizontal=True)
    owned = role == "사장님"
    for store in stores:
        if store["is_owner"] != owned:
            continue
        with st.container(border=True, key=f"crewfit_panel_store_{store['store_id']}"):
            st.text(store["store_name"])
            if owned:
                if store["invite_code"]:
                    st.caption("직원에게 전달할 초대 코드")
                    st.code(store["invite_code"], language=None)
                elif st.button("초대 코드 발급", key=f"issue_invite_{store['store_id']}"):
                    try:
                        code = client.rpc("crewfit_issue_invite", {"p_store_id": store["store_id"]}).execute().data
                    except APIError:
                        st.error("초대 코드를 발급하지 못했습니다.")
                    else:
                        if code:
                            st.rerun()
                        st.error("이 가게의 초대 코드를 발급할 권한을 확인해 주세요.")

    if not (profile.get("telephone") or "").strip() or not profile.get("birth"):
        st.warning("가게를 등록하거나 연결하려면 전화번호와 생년월일을 먼저 저장해 주세요.")
        if st.button("내 정보 수정", key="store_complete_profile"):
            st.session_state["account_return"] = True
            st.session_state["selected_menu"] = "profile_edit"
            st.rerun()
        return

    with st.form("store_registration" if owned else "store_invite", clear_on_submit=True):
        value = st.text_input("가게 이름" if owned else "초대 코드", max_chars=100)
        submitted = st.form_submit_button("가게 등록" if owned else "가게 연결", type="primary")

    if not submitted:
        return
    value = value.strip()
    if not value:
        st.warning("가게 이름을 입력해 주세요." if owned else "초대 코드를 입력해 주세요.")
        return
    if not owned and not re.fullmatch(r"[0-9a-fA-F]{32}", value):
        st.warning("초대 코드 32자리를 확인해 주세요.")
        return

    try:
        if owned:
            client.rpc("crewfit_create_store", {"p_name": value}).execute()
            message = "가게를 등록했습니다."
        else:
            name = client.rpc("crewfit_join_store", {"p_code": value.upper()}).execute().data
            if not name:
                st.error("유효한 초대 코드를 확인해 주세요.")
                return
            message = f"{name} 가게에 연결되었습니다."
    except APIError as error:
        messages = {
            "profile_required": "전화번호와 생년월일을 먼저 저장해 주세요.",
            "already_owner": "이미 이 가게의 사장님으로 등록되어 있습니다.",
            "inactive_profile": "현재 계정은 가게를 연결할 수 없습니다.",
        }
        st.error(messages.get(error.message, "가게 정보를 저장하지 못했습니다. 다시 시도해 주세요."))
        return

    st.session_state["store_connection_notice"] = message
    st.rerun()

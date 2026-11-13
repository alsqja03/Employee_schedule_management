import re

import pandas as pd
import streamlit as st
from postgrest.exceptions import APIError

from views.auth import get_supabase

START_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")


def render_employee_management():
    st.title("직원 관리")
    client = get_supabase()
    selected = st.session_state.get("employee_store")
    if selected is None:
        try:
            stores = client.rpc("crewfit_my_stores").execute().data or []
        except APIError:
            st.error("가게 목록을 불러오지 못했습니다.")
            return
        owned = [store for store in stores if store["is_owner"]]
        if not owned:
            st.info("관리할 가게가 없습니다. 가게 연결에서 사장님으로 가게를 등록해 주세요.")
        for store in owned:
            with st.container(border=True, key=f"crewfit_panel_employee_{store['store_id']}"):
                name, action = st.columns([4, 1], vertical_alignment="center")
                name.subheader(store["store_name"])
                if action.button("직원 관리", key=f"employees_{store['store_id']}"):
                    st.session_state["employee_store"] = store
                    st.rerun()
        return

    if st.button("가게 목록", key="employee_store_back"):
        st.session_state.pop("employee_store", None)
        st.rerun()
    store_id = selected["store_id"]
    try:
        employees = client.rpc("crewfit_store_employees", {"p_store": store_id}).execute().data or []
    except APIError:
        st.error("직원 목록을 불러오지 못했습니다. 가게 관리 권한을 확인해 주세요.")
        return
    if not employees:
        st.info("연결된 직원이 없습니다.")
        return

    with st.container(key="employee_store_heading"):
        st.subheader(selected["store_name"])
        st.caption("직원명과 직책은 이 가게에서만 표시됩니다. 기본 출근시간은 일정 초안에 사용됩니다.")
    rows = [{
        "id": employee["id"], "직원명": employee["name"], "기본 출근시간": employee["start"] or "",
        "직책": employee["position"] or "직원", "전화번호": employee["telephone"] or "",
        "생년월일": employee["birth"] or "",
    } for employee in employees]
    with st.form(f"employee_starts_{store_id}"):
        edited = st.data_editor(
            pd.DataFrame(rows), hide_index=True, width="stretch",
            disabled=["id", "전화번호", "생년월일"],
            column_config={
                "id": None,
                "직원명": st.column_config.TextColumn(max_chars=80),
                "기본 출근시간": st.column_config.TextColumn(max_chars=5),
                "직책": st.column_config.TextColumn(max_chars=40),
            },
        )
        submitted = st.form_submit_button("직원 정보 및 출근시간 저장", type="primary")
    if submitted:
        updates = {}
        for row in edited.to_dict("records"):
            name = (row["직원명"] or "").strip()
            position = (row["직책"] or "").strip()
            start = (row["기본 출근시간"] or "").strip()
            if not name or not position:
                st.warning("직원명과 직책을 입력해 주세요.")
                return
            if start and not START_TIME.fullmatch(start):
                st.warning("출근시간을 HH:MM 형식으로 입력해 주세요.")
                return
            updates[row["id"]] = {
                "name": name,
                "position": position,
                "start": start or None,
            }
        try:
            client.rpc("crewfit_save_employee_settings", {
                "p_store": store_id, "p_employees": updates,
            }).execute()
        except APIError:
            st.error("직원 정보를 저장하지 못했습니다. 입력 내용을 확인해 주세요.")
        else:
            st.session_state[f"employee_saved_{store_id}"] = True
            st.rerun()
    if st.session_state.pop(f"employee_saved_{store_id}", False):
        st.success("기본 출근시간을 저장했습니다.")

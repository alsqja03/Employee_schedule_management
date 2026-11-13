import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from postgrest.exceptions import APIError

from views.auth import get_supabase

DAYS = ("월", "화", "수", "목", "금", "토", "일")
DAY_ENTRY = re.compile(r"([월화수목금토일])(?:요일)?[ :]+(.+)")
ERROR_MESSAGES = {
    "week_published": "이미 확정된 주차입니다. 확정 일정을 확인해 주세요.",
    "invalid_availability": "근무 가능일과 불가능일을 확인해 주세요.",
    "invalid_assignments": "직원별 확정 일정을 확인해 주세요.",
    "store_access_denied": "이 가게의 스케줄에 접근할 수 없습니다.",
    "owner_only": "가게 사장님만 스케줄을 확정할 수 있습니다.",
    "PGRST202": "스케줄 기능을 불러올 수 없습니다. DB 마이그레이션 적용 여부를 확인해 주세요.",
}


def call(client, name, params=None):
    return client.rpc(name, params).execute().data


def show_error(error):
    st.error(ERROR_MESSAGES.get(error.message) or ERROR_MESSAGES.get(error.code)
             or "스케줄을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.")


def render_employee(client, params, week_data, key, dates):
    employee = week_data["employees"][0] if week_data["employees"] else None
    if not employee:
        st.warning("직원으로 연결된 계정을 확인해 주세요.")
        return
    if week_data["published"]:
        st.info("이미 확정된 주차입니다. 스케줄 확인 탭에서 배정 일정을 확인해 주세요.")
        return

    with st.form(f"submit_{key}"):
        available = st.multiselect(
            "근무 가능한 요일", DAYS,
            default=[day for day in DAYS if day in (employee["available"] or [])],
            format_func=lambda day: dates[day],
        )
        unavailable = st.multiselect(
            "근무 불가능한 요일", DAYS,
            default=[day for day in DAYS if day in (employee["unavailable"] or [])],
            format_func=lambda day: dates[day],
        )
        note = st.text_area("특이사항", value=employee["note"] or "", max_chars=500)
        submitted = st.form_submit_button("제출 내용 수정" if employee["submitted"] else "스케줄 제출", type="primary")
    if not submitted:
        return
    if set(available) & set(unavailable):
        st.warning("같은 요일을 가능일과 불가능일에 동시에 선택할 수 없습니다.")
        return
    if not available and not unavailable:
        st.warning("가능하거나 불가능한 요일을 하나 이상 선택해 주세요.")
        return
    try:
        call(client, "crewfit_submit_schedule", {
            **params, "p_available": available, "p_unavailable": unavailable, "p_note": note,
        })
    except APIError as error:
        show_error(error)
    else:
        st.session_state[f"schedule_notice_{key}"] = "근무 가능 일정을 저장했습니다."
        st.rerun()


def draft_rows(employees, assignments, *, generate=False):
    rows = []
    for employee in employees:
        user_id = employee["user_id"]
        row = {"user_id": user_id, "직원": employee["name"], **dict.fromkeys(DAYS, ""), "기존 일정": ""}
        if generate:
            available = set(employee["available"] or []) - set(employee["unavailable"] or [])
            for day in DAYS:
                if day in available:
                    row[day] = employee.get("default_start") or ""
        else:
            assignment = assignments.get(user_id, "")
            parts = assignment.splitlines() if "\n" in assignment else re.split(r",\s*(?=[월화수목금토일](?:요일)?[ :])", assignment)
            entries = [part.strip() for part in parts if part.strip()]
            matches = [DAY_ENTRY.fullmatch(part) for part in entries]
            if all(matches) and len({match[1] for match in matches}) == len(matches):
                for match in matches:
                    row[match[1]] = match[2]
            else:
                row["기존 일정"] = assignment
        rows.append(row)
    return rows


def to_assignments(edited):
    assignments = {}
    for row in edited.to_dict("records"):
        entries = [f"{day} {' '.join(row[day].splitlines()).strip()}" for day in DAYS if isinstance(row[day], str) and row[day].strip()]
        legacy = row.get("기존 일정")
        if isinstance(legacy, str) and legacy.strip():
            entries.append(legacy.strip())
        if entries:
            assignments[row["user_id"]] = "\n".join(entries)
    return assignments


def render_owner(client, params, week_data, key, dates):
    employees = week_data["employees"]
    if not employees:
        st.info("연결된 직원이 없습니다. 직원이 초대 코드로 가게에 연결하면 여기에 표시됩니다.")
        return

    st.subheader("직원별 근무 가능일")
    rows = []
    for employee in employees:
        row = {"직원": employee["name"], "제출": "완료" if employee["submitted"] else "미제출"}
        for day in DAYS:
            availability = "가능" if day in (employee["available"] or []) else ""
            if day in (employee["unavailable"] or []):
                availability = "불가"
            row[dates[day]] = availability or "—"
        row["특이사항"] = employee["note"] or ""
        rows.append(row)
    st.dataframe(rows, hide_index=True, width="stretch")

    st.subheader("주간 근무표")
    if week_data["published"]:
        st.caption("공개된 일정입니다. 수정한 내용은 확정 버튼을 누르면 직원에게 표시됩니다.")
    st.caption("칸을 수정하거나 비울 수 있습니다. 빈칸은 근무 배정이 없는 날입니다.")

    if st.button("기본 출근시간으로 초안 만들기", key=f"generate_{key}"):
        st.session_state[f"draft_{key}"] = draft_rows(employees, week_data["items"], generate=True)
        revision_key = f"draft_revision_{key}"
        st.session_state[revision_key] = st.session_state.get(revision_key, 0) + 1
        missing = [employee["name"] for employee in employees if not employee.get("default_start")]
        if missing:
            st.warning(f"기본 출근시간은 마이페이지의 직원 관리에서 설정할 수 있습니다. 빈칸으로 표시된 미설정 직원 {', '.join(missing)}")

    rows = st.session_state.get(f"draft_{key}")
    if rows is None:
        rows = draft_rows(employees, week_data["items"])
    revision = st.session_state.get(f"draft_revision_{key}", 0)
    columns = {day: st.column_config.TextColumn(dates[day], max_chars=60) for day in DAYS}
    if any(row.get("기존 일정") for row in rows):
        columns["기존 일정"] = st.column_config.TextColumn("기존 일정", max_chars=500)
    else:
        rows = [{key: value for key, value in row.items() if key != "기존 일정"} for row in rows]

    with st.form(f"publish_{key}_{revision}"):
        edited = st.data_editor(
            pd.DataFrame(rows), disabled=["직원", "user_id"], hide_index=True,
            column_config={**columns, "user_id": None}, width="stretch",
            key=f"draft_editor_{key}_{revision}",
        )
        visibility_label = st.radio(
            "직원에게 공개할 일정",
            ["직원 본인 일정만 공개", "가게 전체 직원 일정 공개"],
            index=1 if week_data.get("visibility") == "all" else 0,
            help="전체 공개를 선택하면 직원이 같은 가게 직원들의 확정 일정도 볼 수 있습니다.",
        )
        published = st.form_submit_button("수정 내용 확정" if week_data["published"] else "일정 확정 및 공개", type="primary")
    if not published:
        return

    assignments = to_assignments(edited)
    if not assignments:
        st.warning("한 명 이상의 근무 일정을 입력해 주세요.")
        return
    if any(len(value) > 500 for value in assignments.values()):
        st.warning("직원 한 명의 주간 일정은 500자 이내로 입력해 주세요.")
        return
    try:
        call(client, "crewfit_publish_schedule", {
            **params,
            "p_items": assignments,
            "p_visibility": "all" if visibility_label == "가게 전체 직원 일정 공개" else "self",
        })
    except APIError as error:
        show_error(error)
    else:
        st.session_state.pop(f"draft_{key}", None)
        st.session_state[f"draft_revision_{key}"] = revision + 1
        st.session_state[f"schedule_notice_{key}"] = "확정 일정을 저장했습니다."
        st.rerun()


def render_schedule():
    st.title("스케줄 관리")
    client = get_supabase()
    try:
        stores = call(client, "crewfit_my_stores") or []
    except APIError as error:
        show_error(error)
        return

    if not stores:
        st.info("홈의 가게 연결에서 가게를 먼저 등록하거나 연결해 주세요.")
        return

    registration, confirmation = st.tabs(["스케줄 등록", "스케줄 확인"])
    with registration:
        render_week(client, stores, mode="register")
    with confirmation:
        render_week(client, stores, mode="confirm")


def render_week(client, stores, *, mode):
    by_id = {store["store_id"]: store for store in stores}

    def store_label(store_id):
        store = by_id[store_id]
        role = "사장님" if store["is_owner"] else "직원"
        return f"{store['store_name']} ({role})"

    store_id = st.selectbox("가게 선택", list(by_id), format_func=store_label, key=f"schedule_store_{mode}")
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    selected = st.date_input("주차 선택", value=today, format="YYYY-MM-DD", key=f"schedule_date_{mode}")
    if not selected:
        return
    monday = selected - timedelta(days=selected.weekday())
    sunday = monday + timedelta(days=6)
    st.caption(f"{monday:%Y-%m-%d} (월) ~ {sunday:%Y-%m-%d} (일)")
    dates = {day: f"{day} {(monday + timedelta(days=index)):%m/%d}" for index, day in enumerate(DAYS)}
    params = {"p_store": store_id, "p_week": monday.isoformat()}
    key = f"{store_id}_{monday}"
    notice = st.session_state.pop(f"schedule_notice_{key}", None) if mode == "register" else None
    if notice:
        st.success(notice)
    try:
        week_data = call(client, "crewfit_schedule_week", params)
    except APIError as error:
        show_error(error)
        return
    if mode == "confirm":
        render_confirmed_week(week_data, dates)
    elif week_data["is_owner"]:
        render_owner(client, params, week_data, key, dates)
    else:
        render_employee(client, params, week_data, key, dates)


def render_confirmed_week(week_data, dates):
    if not week_data["published"]:
        st.info("선택한 가게와 주차에 확정된 스케줄이 없습니다.")
        return
    assignments = week_data["items"]
    employees = week_data["employees"]
    if not week_data["is_owner"] and not assignments:
        st.info("이 주차에 배정된 근무가 없습니다.")
        return
    rows = []
    for row in draft_rows(employees, assignments):
        display = {"직원": row["직원"], **{dates[day]: row[day] for day in DAYS}}
        if row["기존 일정"]:
            display["기존 일정"] = row["기존 일정"]
        rows.append(display)
    if rows:
        st.dataframe(pd.DataFrame(rows).fillna(""), hide_index=True, width="stretch")
    else:
        st.info("표시할 직원 일정이 없습니다.")

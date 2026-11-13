
"""
auth.py
Supabase Google / Kakao OAuth 인증 관리
PKCE 검증값 서버 메모리 보관 방식
"""

import os
import time
import secrets
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import streamlit as st

from supabase import create_client
from supabase.client import ClientOptions


# ==========================================
# 1. 환경변수 및 설정
# ==========================================

def get_setting(name: str, default=None):
    try:
        value = st.secrets[name]
        if value:
            return value
    except Exception:
        pass

    return os.getenv(name, default)


def get_redirect_url() -> str:
    return get_setting(
        "APP_URL",
        "https://crew-fit.streamlit.app/"
    )


# ==========================================
# 2. OAuth 서버 저장소
# ==========================================

_FLOW_TTL_SEC = 60 * 60


@st.cache_resource
def _flow_store() -> dict:
    """
    서버 프로세스 메모리에 OAuth 흐름 보관.

    flow_key -> {
        client,
        url,
        created
    }

    클라이언트 객체 자체를 보관하므로
    PKCE code_verifier도 유지된다.
    """
    return {}


def _prune_flows():
    store = _flow_store()
    now = time.time()

    for key, entry in list(store.items()):
        if now - entry["created"] > _FLOW_TTL_SEC:
            store.pop(key, None)


def _build_redirect_url(flow_key: str) -> str:
    base = get_redirect_url()

    parts = urlsplit(base)

    query = dict(parse_qsl(parts.query))
    query["flow"] = flow_key

    return urlunsplit((
        parts.scheme,
        parts.netloc,
        parts.path,
        urlencode(query),
        parts.fragment
    ))


# ==========================================
# 3. Supabase 클라이언트 생성
# ==========================================

def _create_auth_client():

    supabase_url = get_setting("SUPABASE_URL")

    supabase_key = (
        get_setting("SUPABASE_PUBLISHABLE_KEY")
        or get_setting("SUPABASE_ANON_KEY")
        or get_setting("SUPABASE_KEY")
    )

    if not supabase_url or not supabase_key:
        raise ValueError(
            "Supabase URL 또는 API Key가 설정되지 않았습니다."
        )

    options = ClientOptions(
        flow_type="pkce"
    )

    return create_client(
        supabase_url,
        supabase_key,
        options=options
    )


def get_supabase():

    if "_supabase_client" not in st.session_state:
        st.session_state["_supabase_client"] = (
            _create_auth_client()
        )

    return st.session_state["_supabase_client"]


# ==========================================
# 4. Google / Kakao 로그인 요청
# ==========================================

def start_oauth(provider: str) -> str:

    provider = provider.lower()

    if provider not in ["google", "kakao"]:
        raise ValueError(
            "지원하지 않는 로그인 방식입니다."
        )

    _prune_flows()

    # 로그인 요청마다 독립적인 클라이언트 생성
    client = _create_auth_client()

    # 고유한 인증 흐름 ID 생성
    flow_key = secrets.token_urlsafe(24)

    redirect_url = _build_redirect_url(flow_key)

    response = client.auth.sign_in_with_oauth({
        "provider": provider,
        "options": {
            "redirect_to": redirect_url
        }
    })

    if not response.url:
        raise RuntimeError(
            "로그인 URL 생성에 실패했습니다."
        )

    # 중요:
    # PKCE 검증값을 가지고 있는 클라이언트 객체를
    # 서버 메모리에 그대로 보관한다.
    _flow_store()[flow_key] = {
        "client": client,
        "url": response.url,
        "created": time.time(),
        "provider": provider
    }

    return response.url


# ==========================================
# 5. OAuth 콜백 처리
# ==========================================

def handle_auth_callback():

    error = st.query_params.get("error")

    if error:
        description = st.query_params.get(
            "error_description", error
        )

        st.query_params.clear()

        return {
            "success": False,
            "error": description
        }

    code = st.query_params.get("code")
    flow_key = st.query_params.get("flow")

    if not code:
        return None

    # 인증 코드와 flow_key를 먼저 확보한 후
    # URL에서 파라미터 제거
    st.query_params.clear()

    if not flow_key:
        return {
            "success": False,
            "error": (
                "OAuth 흐름 ID가 없습니다. "
                "로그인을 다시 시도해 주세요."
            )
        }

    # 동일한 OAuth 요청의 클라이언트 가져오기
    entry = _flow_store().pop(flow_key, None)

    if not entry:
        return {
            "success": False,
            "error": (
                "로그인 흐름 정보를 찾지 못했습니다. "
                "로그인을 다시 시도해 주세요."
            )
        }

    if time.time() - entry["created"] > _FLOW_TTL_SEC:
        return {
            "success": False,
            "error": "로그인 요청이 만료되었습니다."
        }

    # OAuth 시작 시 사용한 바로 그 클라이언트
    supabase = entry["client"]

    try:
        response = supabase.auth.exchange_code_for_session({
            "auth_code": code
        })

        if not response.session or not response.user:
            raise RuntimeError(
                "인증 세션을 생성하지 못했습니다."
            )

        # 인증된 동일한 클라이언트를 세션에 저장
        st.session_state["_supabase_client"] = supabase

        st.session_state["_supabase_access_token"] = (
            response.session.access_token
        )

        st.session_state["_supabase_refresh_token"] = (
            response.session.refresh_token
        )

        return {
            "success": True,
            "user": response.user
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ==========================================
# 6. 로그인 사용자 확인
# ==========================================

def get_current_user():

    try:
        supabase = get_supabase()
        session = supabase.auth.get_session()

        if session and session.user:
            return session.user

        return None

    except Exception:
        return None


def is_authenticated() -> bool:
    return get_current_user() is not None


# ==========================================
# 7. 로그아웃
# ==========================================

def sign_out():

    try:
        if "_supabase_client" in st.session_state:
            supabase = st.session_state["_supabase_client"]
            supabase.auth.sign_out()

    finally:
        st.session_state.pop("_supabase_client", None)
        st.session_state.pop(
            "_supabase_access_token", None
        )
        st.session_state.pop(
            "_supabase_refresh_token", None
        )

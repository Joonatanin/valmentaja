import os
import re
import sqlite3
from datetime import date
from typing import Dict

import google.generativeai as genai
import streamlit as st


DB_FILE = "coach_data.db"
DEFAULT_PROFILE = {
    "name": "",
    "pr_results": {
        "Squat": 133.0,
        "RDL": 140.0,
    },
    "weekly_schedule": "",
}

EXERCISE_TO_PR_KEY = {
    "squat": "Squat",
    "back squat": "Squat",
    "front squat": "Squat",
    "rdl": "RDL",
    "romanian deadlift": "RDL",
    "deadlift": "RDL",
    "maastaveto": "RDL",
    "kyykky": "Squat",
}

SYSTEM_INSTRUCTION = (
    "Olet ammattitaitoinen hybridivalmentaja. Vastaa lyhyesti ja kannustavasti kysymyksiin "
    "kuntosaliharjoittelusta, juoksusta ja joukkueurheilun yhdistämisestä."
)
PRIMARY_MODEL = "gemini-1.5-flash-latest"


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                name TEXT NOT NULL DEFAULT '',
                squat REAL NOT NULL DEFAULT 133.0,
                rdl REAL NOT NULL DEFAULT 140.0,
                weekly_schedule TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS training_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                training_date TEXT NOT NULL,
                training_type TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                rpe INTEGER NOT NULL,
                notes TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO profile (id, name, squat, rdl, weekly_schedule)
            VALUES (1, ?, ?, ?, ?)
            """,
            (
                DEFAULT_PROFILE["name"],
                DEFAULT_PROFILE["pr_results"]["Squat"],
                DEFAULT_PROFILE["pr_results"]["RDL"],
                DEFAULT_PROFILE["weekly_schedule"],
            ),
        )


def load_profile_data() -> Dict:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT name, squat, rdl, weekly_schedule FROM profile WHERE id = 1"
        ).fetchone()
    if not row:
        return DEFAULT_PROFILE.copy()
    return {
        "name": row["name"],
        "pr_results": {
            "Squat": float(row["squat"]),
            "RDL": float(row["rdl"]),
        },
        "weekly_schedule": row["weekly_schedule"],
    }


def save_profile_data(data: Dict) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO profile (id, name, squat, rdl, weekly_schedule)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                squat = excluded.squat,
                rdl = excluded.rdl,
                weekly_schedule = excluded.weekly_schedule
            """,
            (
                data.get("name", ""),
                float(data.get("pr_results", {}).get("Squat", 0)),
                float(data.get("pr_results", {}).get("RDL", 0)),
                data.get("weekly_schedule", ""),
            ),
        )


def load_training_log() -> list[Dict]:
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, training_date, training_type, duration_minutes, rpe, notes
            FROM training_log
            ORDER BY training_date DESC, id DESC
            """
        ).fetchall()
    return [
        {
            "id": row["id"],
            "Päivämäärä": row["training_date"],
            "Treenityyppi": row["training_type"],
            "Kesto (min)": row["duration_minutes"],
            "RPE": row["rpe"],
            "Muistiinpanot": row["notes"],
        }
        for row in rows
    ]


def add_training_log_entry(entry: Dict) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO training_log (training_date, training_type, duration_minutes, rpe, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                entry["Päivämäärä"],
                entry["Treenityyppi"],
                entry["Kesto (min)"],
                entry["RPE"],
                entry["Muistiinpanot"],
            ),
        )


def delete_training_log_entry(entry_id: int) -> None:
    with get_db_connection() as conn:
        conn.execute("DELETE FROM training_log WHERE id = ?", (entry_id,))


def init_state() -> None:
    init_db()
    if "profile_data" not in st.session_state:
        st.session_state.profile_data = load_profile_data()
    if "ai_plan" not in st.session_state:
        st.session_state.ai_plan = ""
    if "training_log" not in st.session_state:
        st.session_state.training_log = load_training_log()
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []
    if "gemini_api_key" not in st.session_state:
        st.session_state.gemini_api_key = ""


def resolve_api_key() -> str:
    secrets_key = st.secrets.get("GEMINI_API_KEY", "").strip() if hasattr(st, "secrets") else ""
    session_key = st.session_state.get("gemini_api_key", "").strip()
    env_key = os.getenv("GEMINI_API_KEY", "").strip()
    return secrets_key or session_key or env_key


def apply_theme() -> None:
    st.set_page_config(
        page_title="Hybridivalmentaja",
        page_icon="🏋️",
        layout="wide",
    )
    st.markdown(
        """
        <style>
        .stApp {
            background: linear-gradient(160deg, #0c1118 0%, #0f1720 55%, #1b2635 100%);
            color: #e8edf2;
        }
        [data-testid="stSidebar"] {
            background: #111822;
            border-right: 1px solid rgba(148, 163, 184, 0.2);
        }
        .card {
            background: rgba(17, 24, 34, 0.86);
            border: 1px solid rgba(148, 163, 184, 0.22);
            border-radius: 16px;
            padding: 1rem 1.1rem;
            margin-bottom: 1rem;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.22);
        }
        .title {
            font-size: 2rem;
            font-weight: 700;
            letter-spacing: 0.3px;
            margin-bottom: 0.3rem;
        }
        .subtitle {
            color: #a9bacb;
            margin-bottom: 1rem;
        }
        .stButton > button {
            background: linear-gradient(90deg, #00b894, #0984e3);
            color: #ffffff;
            border: 0;
            border-radius: 10px;
            font-weight: 600;
        }
        .stButton > button:hover {
            filter: brightness(1.08);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def calculate_recommendation(exercise_name: str, percentage: float, pr_data: Dict) -> str:
    key = EXERCISE_TO_PR_KEY.get(exercise_name.strip().lower())
    if not key:
        return f"{exercise_name}: Ei tunnettu PR-pohjaista liikettä."
    max_weight = float(pr_data.get(key, 0))
    recommended = max_weight * (percentage / 100.0)
    return f"{exercise_name}: {recommended:.1f} kg ({percentage:.0f}% {key}-maksimista)"


def build_gemini_prompt(profile: Dict) -> str:
    name = profile.get("name", "").strip() or "Urheilija"
    pr = profile.get("pr_results", {})
    schedule = profile.get("weekly_schedule", "")
    return f"""
Laadi suomeksi moderni, käytännöllinen ja palautumisen huomioiva 7 päivän hybridiharjoitusohjelma.

Urheilija: {name}
PR-tulokset:
- Squat: {pr.get("Squat", 0)} kg
- RDL: {pr.get("RDL", 0)} kg

Viikon joukkueurheilun aikataulu:
{schedule}

Vaatimukset:
1) Suunnittele salitreenit ja lenkit niin, että futis- ja lätkäkuormitus huomioidaan.
2) Priorisoi suorituskykyä ja palautumista.
3) Kerro päivän tavoite, treenin sisältö, kesto ja teho.
4) Lisää lyhyt perustelu miksi tämä jako toimii.
5) Vastaa selkeästi markdown-muodossa.
""".strip()


def resolve_gemini_model_candidates() -> list[str]:
    preferred = [
        PRIMARY_MODEL,
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
    ]
    try:
        available = []
        for model in genai.list_models():
            methods = getattr(model, "supported_generation_methods", []) or []
            if "generateContent" in methods:
                available.append(getattr(model, "name", ""))

        if not available:
            return ["gemini-2.0-flash"]

        # Model names can come as "models/gemini-2.0-flash"; normalize for compare.
        normalized_map = {
            name.split("/", 1)[-1]: name
            for name in available
            if "gemini" in name
        }

        ordered_candidates = []
        for wanted in preferred:
            if wanted in normalized_map:
                ordered_candidates.append(normalized_map[wanted])

        # Final fallback: first available Gemini model that supports generateContent.
        for full_name in available:
            if "gemini" in full_name and full_name not in ordered_candidates:
                ordered_candidates.append(full_name)
        if ordered_candidates:
            return ordered_candidates
    except Exception:
        # Last-resort fallback if model listing fails.
        return ["gemini-2.0-flash"]

    return ["gemini-2.0-flash"]


def generate_ai_plan() -> None:
    profile = st.session_state.profile_data
    api_key = resolve_api_key()

    if not api_key:
        st.error("Lisää Gemini API-avain sivupalkkiin tai ympäristömuuttujaan GEMINI_API_KEY.")
        return
    if not profile.get("weekly_schedule", "").strip():
        st.error("Lisää ensin viikon aikataulu.")
        return

    genai.configure(api_key=api_key)
    prompt = build_gemini_prompt(profile)

    with st.spinner("Rakennetaan optimaalista viikkoa..."):
        candidates = resolve_gemini_model_candidates()
        last_error = ""
        for idx, selected_model in enumerate(candidates):
            try:
                model = genai.GenerativeModel(selected_model)
                response = model.generate_content(prompt)
                response_text = getattr(response, "text", "") or ""
                if not response_text.strip():
                    last_error = "Gemini ei palauttanut tekstiä."
                    continue
                st.session_state.ai_plan = response_text
                st.caption(f"Kaytetty malli: {selected_model}")
                return
            except Exception as exc:
                err = str(exc)
                last_error = err
                quota_hit = "429" in err or "quota" in err.lower() or "rate limit" in err.lower()
                has_next_model = idx < len(candidates) - 1
                if quota_hit and has_next_model:
                    continue
                if quota_hit:
                    retry_seconds = None
                    retry_match = re.search(r"Please retry in ([0-9.]+)s", err)
                    if retry_match:
                        retry_seconds = int(float(retry_match.group(1)) + 1)
                    else:
                        retry_match = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", err)
                        if retry_match:
                            retry_seconds = int(retry_match.group(1))
                    st.session_state.ai_plan = ""
                    if retry_seconds is not None:
                        st.error(
                            f"Ilmaisen tason pyyntoraja tayttyi. Odota noin {retry_seconds} s ja yrita uudelleen."
                        )
                    else:
                        st.error("Ilmaisen tason pyyntoraja tayttyi. Odota hetki ja yrita uudelleen.")
                    return
                if not has_next_model:
                    break

        st.session_state.ai_plan = ""
        if last_error:
            st.error(f"AI-suunnitelman luonti epaonnistui: {last_error}")
        else:
            st.error("AI-suunnitelman luonti epaonnistui tuntemattomasta syysta.")


def render_weekly_plan_tab() -> None:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Profiili & PR-tulokset")
    data = st.session_state.profile_data
    col_a, col_b, col_c = st.columns([1.4, 1, 1])
    with col_a:
        data["name"] = st.text_input("Nimi", value=data.get("name", ""), key="profile_name")
    with col_b:
        data["pr_results"]["Squat"] = st.number_input(
            "Squat (kg)",
            min_value=0.0,
            value=float(data["pr_results"].get("Squat", 0)),
            step=1.0,
            key="profile_squat",
        )
    with col_c:
        data["pr_results"]["RDL"] = st.number_input(
            "RDL (kg)",
            min_value=0.0,
            value=float(data["pr_results"].get("RDL", 0)),
            step=1.0,
            key="profile_rdl",
        )
    if st.button("Tallenna profiili", key="save_profile_tab"):
        save_profile_data(data)
        st.success("Profiili tallennettu.")
    st.markdown("</div>", unsafe_allow_html=True)

    col1, col2 = st.columns([1.2, 1], gap="large")
    with col1:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Viikkoaikataulu")
        current_schedule = st.session_state.profile_data.get("weekly_schedule", "")
        schedule_text = st.text_area(
            "Syötä futis- ja lätkätreenit sekä pelit vapaasti",
            value=current_schedule,
            height=220,
            placeholder="Esim.\nMa: futistreeni 18:00\nTi: lätkätreeni 20:00\nLa: futispeli 15:00",
            key="weekly_schedule_input",
        )
        st.session_state.profile_data["weekly_schedule"] = schedule_text
        if st.button("Tallenna aikataulu", key="save_schedule_tab"):
            save_profile_data(st.session_state.profile_data)
            st.success("Aikataulu tallennettu.")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("AI-suunnittelija")
        st.write("Luo viikkokohtainen sali- ja lenkkisuunnitelma PR-tulostesi ja joukkuekuormituksen mukaan.")
        if st.button("Luo viikon suunnitelma Gemini AI:lla", key="generate_week_plan"):
            generate_ai_plan()
        if st.session_state.ai_plan:
            st.markdown("### AI:n ehdotus")
            st.markdown(st.session_state.ai_plan)
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Hevy-integraatio (painosuositukset)")
        st.caption("Syötä liikkeet pilkulla erotettuna, esim: Squat, RDL, Deadlift")
        exercises = st.text_input("Liikkeet", key="hevy_exercises")
        percentage = st.slider("Kuormitus (% maksimista)", min_value=50, max_value=95, value=70, step=5, key="hevy_pct")

        if st.button("Laske suositellut painot", key="hevy_calc"):
            if not exercises.strip():
                st.warning("Syötä vähintään yksi liike.")
            else:
                st.markdown("### Suositukset")
                for raw in [x.strip() for x in exercises.split(",") if x.strip()]:
                    st.write(calculate_recommendation(raw, float(percentage), st.session_state.profile_data["pr_results"]))
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Tallennetut PR:t")
        pr = st.session_state.profile_data["pr_results"]
        st.metric("Squat", f"{pr.get('Squat', 0):.0f} kg")
        st.metric("RDL", f"{pr.get('RDL', 0):.0f} kg")
        st.markdown("</div>", unsafe_allow_html=True)


def render_training_log_tab() -> None:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Treeniloki")
    col1, col2 = st.columns(2)
    with col1:
        training_date = st.date_input("Päivämäärä", value=date.today(), key="log_date")
        training_type = st.selectbox(
            "Treenityyppi",
            ["Kuntosali", "Juoksu", "Jääkiekko", "Jalkapallo", "Muu"],
            key="log_type",
        )
        duration_minutes = st.number_input("Kesto minuutteina", min_value=1, max_value=600, value=60, step=5, key="log_duration")
    with col2:
        rpe = st.slider("Fiilis / RPE (1-10)", min_value=1, max_value=10, value=6, key="log_rpe")
        notes = st.text_area("Muistiinpanot", height=120, placeholder="Esim. Lenkin vauhti 5:30/km", key="log_notes")

    if st.button("Tallenna treeni", key="save_training_log"):
        new_entry = {
            "Päivämäärä": training_date.isoformat(),
            "Treenityyppi": training_type,
            "Kesto (min)": int(duration_minutes),
            "RPE": int(rpe),
            "Muistiinpanot": notes.strip(),
        }
        add_training_log_entry(new_entry)
        st.session_state.training_log = load_training_log()
        st.success("Treeni tallennettu lokiin.")
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Tallennetut treenit")
    if st.session_state.training_log:
        display_rows = []
        for row in st.session_state.training_log:
            display_rows.append({k: v for k, v in row.items() if k != "id"})
        st.dataframe(display_rows, use_container_width=True)
        st.markdown("### Poista treeni")
        delete_index = st.selectbox(
            "Valitse poistettava treeni",
            options=list(range(len(st.session_state.training_log))),
            format_func=lambda i: (
                f"{st.session_state.training_log[i]['Päivämäärä']} - "
                f"{st.session_state.training_log[i]['Treenityyppi']} "
                f"({st.session_state.training_log[i]['Kesto (min)']} min)"
            ),
            key="delete_log_index",
        )
        if st.button("Poista valittu treeni", key="delete_training_log"):
            selected_entry = st.session_state.training_log[delete_index]
            delete_training_log_entry(int(selected_entry["id"]))
            st.session_state.training_log = load_training_log()
            st.success("Treeni poistettu.")
            st.rerun()
    else:
        st.info("Ei vielä tallennettuja treenejä.")
    st.markdown("</div>", unsafe_allow_html=True)


def generate_chat_reply(user_message: str) -> str:
    api_key = resolve_api_key()
    if not api_key:
        return "Lisää Gemini API-avain sivupalkkiin tai ympäristömuuttujaan GEMINI_API_KEY."

    genai.configure(api_key=api_key)
    history = []
    for msg in st.session_state.chat_messages:
        role = "user" if msg["role"] == "user" else "model"
        history.append({"role": role, "parts": [msg["content"]]})

    candidates = resolve_gemini_model_candidates()
    last_error = ""
    for selected_model in candidates:
        try:
            model = genai.GenerativeModel(selected_model, system_instruction=SYSTEM_INSTRUCTION)
            chat = model.start_chat(history=history)
            response = chat.send_message(user_message)
            text = getattr(response, "text", "") or ""
            if text.strip():
                return text
            last_error = f"Malli {selected_model} ei palauttanut tekstiä."
        except Exception as exc:
            last_error = str(exc)
            continue

    return f"AI-valmentaja ei vastannut: {last_error or 'Tuntematon virhe'}"


def render_ai_coach_tab() -> None:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("AI-Valmentaja")
    st.caption("Kysy lyhyitä kysymyksiä salista, juoksusta ja joukkueurheilun yhdistämisestä.")
    st.markdown("</div>", unsafe_allow_html=True)

    for msg in st.session_state.chat_messages:
        with st.chat_message("user" if msg["role"] == "user" else "assistant"):
            st.markdown(msg["content"])

    user_prompt = st.chat_input("Kysy AI-valmentajalta...")
    if user_prompt:
        st.session_state.chat_messages.append({"role": "user", "content": user_prompt})
        with st.chat_message("user"):
            st.markdown(user_prompt)

        with st.chat_message("assistant"):
            with st.spinner("AI-valmentaja miettii..."):
                answer = generate_chat_reply(user_prompt)
                st.markdown(answer)
        st.session_state.chat_messages.append({"role": "assistant", "content": answer})


def main() -> None:
    apply_theme()
    init_state()
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Gemini API")
    entered_api_key = st.sidebar.text_input(
        "API-avain",
        type="password",
        value=st.session_state.get("gemini_api_key", ""),
        help="Luetaan ensisijaisesti Streamlit-secretsista (GEMINI_API_KEY)."
    )
    if entered_api_key != st.session_state.get("gemini_api_key", ""):
        st.session_state.gemini_api_key = entered_api_key

    if st.secrets.get("GEMINI_API_KEY", ""):
        st.sidebar.success("GEMINI_API_KEY loytyi Streamlit-secretsista.")

    st.markdown('<div class="title">Hybridivalmentaja</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Yhdistä joukkueurheilu, sali ja juoksu fiksuksi viikoksi.</div>',
        unsafe_allow_html=True,
    )

    tab_weekly, tab_log, tab_chat = st.tabs(["Viikkosuunnitelma", "Treeniloki", "AI-Valmentaja"])
    with tab_weekly:
        render_weekly_plan_tab()
    with tab_log:
        render_training_log_tab()
    with tab_chat:
        render_ai_coach_tab()


if __name__ == "__main__":
    main()
